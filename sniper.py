# sniper.py
# Core BOS + FVG sniper logic. Uses eodhd_api, confirmations, targets, trade_logger, discord_bot.
import json
import time
from datetime import datetime, timedelta
from eodhd_api import get_intraday_bars
import confirmations
import targets
from discord_bot import send
from trade_logger import log_confirmed_trade
import config
import threading
import os

RETEST_STATE_FILE = "retest_state.json"
MAX_ARMED = config.MAX_ARMED
RETEST_TIMEOUT_MINUTES = config.RETEST_TIMEOUT_MINUTES

# persistent retest state
def load_retest_state():
    try:
        with open(RETEST_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_retest_state(state):
    try:
        with open(RETEST_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("save_retest_state error:", e)

retest_state = load_retest_state()

def compute_opening_range_from_bars(bars):
    """
    Compute OR high/low between 09:30 and 09:40 EST.
    bars: list of 1m bars ascending
    """
    import pytz
    from datetime import datetime, time as dtime
    est = pytz.timezone("US/Eastern")
    today = datetime.now(est).date()
    or_start = datetime.combine(today, dtime(hour=9, minute=30)).astimezone(est)
    or_end = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
    highs = []
    lows = []
    for b in bars:
        ts = b.get("date") or b.get("datetime") or b.get("time")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                import pytz as _p
                dt = dt.replace(tzinfo=_p.UTC).astimezone(est)
            else:
                dt = dt.astimezone(est)
        except:
            continue
        if dt >= or_start and dt <= or_end:
            highs.append(float(b.get("high") or b.get("High") or 0))
            lows.append(float(b.get("low") or b.get("Low") or 0))
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)

def detect_breakout_after_or(bars, or_high, or_low):
    """
    Return ('bull', idx) or ('bear', idx) or (None,None)
    """
    if not bars or or_high is None:
        return None, None
    from datetime import datetime, time as dtime
    import pytz
    est = pytz.timezone("US/Eastern")
    today = datetime.now(est).date()
    or_end = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
    for idx, b in enumerate(bars):
        ts = b.get("date") or b.get("datetime") or b.get("time")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                import pytz as _p
                dt = dt.replace(tzinfo=_p.UTC).astimezone(est)
            else:
                dt = dt.astimezone(est)
        except:
            continue
        if dt <= or_end:
            continue
        try:
            h = float(b.get("high") or b.get("High") or 0)
            l = float(b.get("low") or b.get("Low") or 0)
        except:
            continue
        if h > or_high:
            return "bull", idx
        if l < or_low:
            return "bear", idx
    return None, None

def detect_fvg_after_break(bars, breakout_idx, direction):
    """
    Find FVG after breakout index using 3-bar imbalance rule.
    """
    try:
        n = len(bars)
        for i in range(breakout_idx, n - 2):
            try:
                b0 = bars[i]
                b2 = bars[i + 2]
                h0 = float(b0.get("high") or b0.get("High") or 0)
                l0 = float(b0.get("low") or b0.get("Low") or 0)
                h2 = float(b2.get("high") or b2.get("High") or 0)
                l2 = float(b2.get("low") or b2.get("Low") or 0)
            except:
                continue
            if direction == "bull":
                if l2 > h0:
                    return h0, l2
            else:
                if h2 < l0:
                    return h2, l0
    except Exception as e:
        print("detect_fvg_after_break error:", e)
    return None, None

def publish_prealert(ticker, direction, zone_low, zone_high, or_low, or_high):
    if direction == "bull":
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BULL)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"FVG Zone: {zone_low:.2f} - {zone_high:.2f}\n"
                f"If {ticker} retraces into {zone_low:.2f}-{zone_high:.2f} and then shows a strong green flip, ENTER CALL. Waiting for confirmation...")
    else:
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BEAR)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"FVG Zone: {zone_low:.2f} - {zone_high:.2f}\n"
                f"If {ticker} retraces into {zone_low:.2f}-{zone_high:.2f} and then shows a strong red flip, ENTER PUT. Waiting for confirmation...")
    send(text)

def arm_ticker_for_retest(ticker, direction, zone_low, zone_high, or_low, or_high):
    global retest_state
    if ticker in retest_state:
        return
    if len(retest_state) >= MAX_ARMED:
        return
    retest_state[ticker] = {
        "direction": direction,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "or_low": or_low,
        "or_high": or_high,
        "armed_at": datetime.utcnow().isoformat(),
        "confirmed": False
    }
    save_retest_state(retest_state)
    publish_prealert(ticker, direction, zone_low, zone_high, or_low, or_high)
    print(f"Armed {ticker} for retest with FVG ({direction})")

def process_ticker(ticker):
    """
    Called by scanner for each top mover.
    """
    bars_1m = get_intraday_bars(ticker, interval="1m", limit=240)
    if not bars_1m:
        return
    or_high, or_low = compute_opening_range_from_bars(bars_1m)
    if or_high is None:
        return
    direction, breakout_idx = detect_breakout_after_or(bars_1m, or_high, or_low)
    if not direction:
        return
    # find FVG after breakout
    fvg_low, fvg_high = detect_fvg_after_break(bars_1m, breakout_idx, direction)
    if not fvg_low:
        # breakout without FVG -> skip (video rule)
        return
    # arm for retest & confirmation
    arm_ticker_for_retest(ticker, direction, fvg_low, fvg_high, or_low, or_high)

# fast monitor for armed tickers -> uses confirmations.check_confirmation_multi_timeframe
def fast_monitor_loop():
    global retest_state
    print("Fast monitor started")
    while True:
        try:
            keys = list(retest_state.keys())
            for ticker in keys:
                entry = retest_state.get(ticker)
                if not entry or entry.get("confirmed"):
                    continue
                # prune timeout
                armed_at = datetime.fromisoformat(entry["armed_at"])
                if datetime.utcnow() - armed_at > timedelta(minutes=RETEST_TIMEOUT_MINUTES):
                    try:
                        del retest_state[ticker]
                        save_retest_state(retest_state)
                    except:
                        pass
                    continue
                ok, bar, tf, grade = confirmations.check_confirmation_multi_timeframe(ticker, {
                    "zone_low": entry["zone_low"],
                    "zone_high": entry["zone_high"],
                    "direction": entry["direction"],
                    "or_low": entry["or_low"],
                    "or_high": entry["or_high"]
                })
                if ok:
                    # only accept A+ or A grade per Elite Active rule
                    if grade in ("A+","A"):
                        entry["confirmed"] = True
                        entry["confirmed_at"] = datetime.utcnow().isoformat()
                        save_retest_state(retest_state)
                        # compute stops/targets
                        entry_price = float(bar.get("close") or bar.get("Close") or 0)
                        calc = targets.compute_stop_and_targets(entry_price, entry["or_low"], entry["or_high"], entry["direction"], ticker=ticker)
                        stop = calc.get("stop")
                        t1 = calc.get("t1")
                        t2 = calc.get("t2")
                        chosen = calc.get("chosen")
                        entry_ts = datetime.utcnow().isoformat()
                        trade_id = log_confirmed_trade(ticker, entry["direction"], grade, entry_price, entry_ts, stop, t1, t2, chosen)
                        # Discord message
                        msg = (f"🚨 CONFIRMED ENTRY — {ticker} {entry['direction'].upper()}\n"
                               f"Grade: {grade}\nTimeframe: {tf}\nEntry: {entry_price:.2f}\nStop: {stop:.2f}\nT1 (2R): {t1:.2f}\n"
                               f"T2 (1H): {t2 if t2 else 'n/a'}\nTradeId: {trade_id}")
                        send(msg)
                        # remove from state to free slot
                        try:
                            del retest_state[ticker]
                            save_retest_state(retest_state)
                        except:
                            pass
            time.sleep(config.RETEST_POLL)
        except Exception as e:
            print("fast_monitor error:", e)
            time.sleep(config.RETEST_POLL)

# start monitor thread helper
def start_fast_monitor():
    t = threading.Thread(target=fast_monitor_loop, daemon=True)
    t.start()
    return t
