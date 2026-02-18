# sniper.py — GOD MODE MEMORY + POLICY AWARE

import json
import os
import threading
import time
from datetime import datetime, timedelta
import traceback
import requests
import confirmations
import targets
import trade_logger
import learning_policy
import incremental_fetch
from memory_reader import get_recent_bars_from_memory
from options_filter import get_options_recommendation
import traceback
from options_filter import get_options_recommendation
from discord_helpers import send_options_signal_alert
from targets import compute_stop_and_targets

# Global dictionary to track armed signals
armed_signals = {}

RETEST_STATE_FILE = "retest_state.json"
MAX_ARMED = int(os.getenv("MAX_ARMED", "25"))
RETEST_TIMEOUT_MINUTES = int(os.getenv("RETEST_TIMEOUT_MINUTES", "60"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# ================= DISCORD =================
def send_discord(msg: str):
    if not DISCORD_WEBHOOK:
        print("discord:", msg)
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception as e:
        print("discord send error:", e)

# ================= STATE =================
def _load_state():
    try:
        with open(RETEST_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def _save_state(st):
    try:
        with open(RETEST_STATE_FILE, "w") as f:
            json.dump(st, f)
    except Exception as e:
        print("save_state error:", e)

retest_state = _load_state()

# ================= ARM =================
def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high):
    key = f"{ticker}:{direction}"

    if key in retest_state:
        return
    if len(retest_state) >= MAX_ARMED:
        return

    retest_state[key] = {
        "ticker": ticker,
        "direction": direction,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "or_low": or_low,
        "or_high": or_high,
        "armed_at": datetime.utcnow().isoformat()
    }

    _save_state(retest_state)
    send_discord(f"🔔 PRE-ALERT: {ticker} {direction} FVG {zone_low:.2f}-{zone_high:.2f}")

# ================= OPENING RANGE =================
def compute_opening_range_from_bars(bars):
    import pytz
    est = pytz.timezone("US/Eastern")

    or_high = None
    or_low = None

    for b in bars:
        ts = b.get("datetime")
        if not ts:
            continue

        try:
            d = datetime.fromisoformat(ts)
            if d.tzinfo is None:
                d = d.replace(tzinfo=pytz.UTC).astimezone(est)
            else:
                d = d.astimezone(est)
        except:
            continue

        if d.hour == 9 and 30 <= d.minute <= 40:
            h = float(b.get("high", 0))
            l = float(b.get("low", 0))

            or_high = h if or_high is None else max(or_high, h)
            or_low = l if or_low is None else min(or_low, l)

    return or_high, or_low

# ================= BREAKOUT =================
def detect_breakout_after_or(bars, or_high, or_low):
    for i, b in enumerate(bars):
        h = float(b.get("high", 0))
        l = float(b.get("low", 0))

        if or_high and h > or_high:
            return "bull", i
        if or_low and l < or_low:
            return "bear", i

    return None, None

# ================= FVG =================
def detect_fvg_after_break(bars, breakout_idx, direction):
    for i in range(breakout_idx, len(bars) - 2):
        b0 = bars[i]
        b2 = bars[i + 2]

        h0 = float(b0.get("high", 0))
        l0 = float(b0.get("low", 0))
        h2 = float(b2.get("high", 0))
        l2 = float(b2.get("low", 0))

        if direction == "bull" and l2 > h0:
            return h0, l2
        if direction == "bear" and h2 < l0:
            return h2, l0

    return None, None

# ================= PROCESS =================
def process_ticker(ticker: str):
    try:
        # STEP 1 — update memory DB only
        incremental_fetch.update_ticker(ticker)

        # STEP 2 — use memory DB (NOT EODHD directly)
        bars = get_recent_bars_from_memory(ticker, limit=300)

        if not bars or len(bars) < 50:
            print(f"{ticker}: not enough memory bars")
            return

        print(f"📊 {ticker} using MEMORY bars:", len(bars))
        send_discord(f"📊 {ticker} bars received: {len(bars)}")

        # OPENING RANGE
        or_high, or_low = compute_opening_range_from_bars(bars)
        if or_high is None:
            print(f"{ticker}: OR not formed yet")
            return

        # BREAKOUT
        direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
        if not direction:
            return

        # FVG
        fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
        if not fvg_low:
            return

        zone_low, zone_high = min(fvg_low, fvg_high), max(fvg_low, fvg_high)

        # Get entry, stop, targets before arming
        from targets import compute_stop_and_targets
        entry_price = bars[-1]["close"]  # Current price
        stop_price, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price
        )

        # OPTIONS INTEGRATION - Get options recommendation
        from options_filter import get_options_recommendation
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1  # Use T1 as target for options
        )

        # ARM with options data
        arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high, 
                   entry_price, stop_price, t1, t2, options_rec)

    except Exception as e:
        print(f"process_ticker error for {ticker}:", e)
        traceback.print_exc()

# ================= FAST MONITOR =================
def fast_monitor_loop():
    global retest_state
    print("Sniper fast monitor started")

    while True:
        try:
            for k in list(retest_state.keys()):
                entry = retest_state.get(k)
                if not entry:
                    continue

                # timeout cleanup
                armed_at = datetime.fromisoformat(entry["armed_at"])
                if datetime.utcnow() - armed_at > timedelta(minutes=RETEST_TIMEOUT_MINUTES):
                    del retest_state[k]
                    _save_state(retest_state)
                    continue

                ok, bar, tf, grade = confirmations.check_confirmation_multi_timeframe(
                    entry["ticker"], entry
                )

                if not ok:
                    continue

                conf = learning_policy.compute_confidence(grade, tf, entry["ticker"])
                policy = learning_policy.get_policy()
                min_conf = float(policy.get("min_confidence", 0.8))

                if conf < min_conf:
                    continue

                entry_price = float(bar.get("close", 0))

                calc = targets.compute_stop_and_targets(
                    entry_price,
                    entry["or_low"],
                    entry["or_high"],
                    entry["direction"],
                    ticker=entry["ticker"]
                )

                trade_id = trade_logger.log_confirmed_trade(
                    entry["ticker"],
                    entry["direction"],
                    grade,
                    entry_price,
                    datetime.utcnow().isoformat(),
                    calc.get("stop"),
                    calc.get("t1"),
                    calc.get("t2"),
                    calc.get("chosen")
                )

                send_discord(
                    f"🚨 CONFIRMED {entry['ticker']} {entry['direction']}\n"
                    f"Entry {entry_price:.2f} Stop {calc.get('stop'):.2f}\n"
                    f"T1 {calc.get('t1'):.2f} Confidence {conf*100:.0f}%"
                )

                del retest_state[k]
                _save_state(retest_state)

            time.sleep(6)

        except Exception as e:
            print("fast_monitor error:", e)
            traceback.print_exc()
            time.sleep(6)
# ================= ARM TICKER =================
def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high, 
               entry_price, stop_price, t1, t2, options_rec=None):
    """
    Arms a ticker after signal confirmation and sends Discord alert.
    
    Args:
        ticker: Ticker symbol
        direction: "bull" or "bear"
        zone_low: FVG zone low
        zone_high: FVG zone high
        or_low: Opening range low
        or_high: Opening range high
        entry_price: Entry price
        stop_price: Stop loss price
        t1: Target 1 price
        t2: Target 2 price
        options_rec: dict from get_options_recommendation() or None
    """
    print(f"✅ {ticker} ARMED: {direction.upper()} | Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"   Zone: ${zone_low:.2f}-${zone_high:.2f} | OR: ${or_low:.2f}-${or_high:.2f}")
    print(f"   Targets: T1=${t1:.2f} T2=${t2:.2f}")
    
    # Compute confidence with dark pool integration
    from learning_policy import compute_confidence
    confidence = compute_confidence("A+", "5m", ticker)
    
    # Send Discord alert with options data
    from discord_helpers import send_options_signal_alert
    send_options_signal_alert(
        ticker=ticker,
        direction=direction,
        entry=entry_price,
        stop=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        timeframe="5m",
        options_data=options_rec
    )
    
    # Store armed signal for tracking
    from datetime import datetime
    armed_signals[ticker] = {
        "direction": direction,
        "entry": entry_price,
        "stop": stop_price,
        "t1": t1,
        "t2": t2,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "or_low": or_low,
        "or_high": or_high,
        "armed_time": datetime.now().isoformat(),
        "confidence": confidence,
        "options": options_rec
    }
    
    print(f"[ARMED] {ticker} added to armed signals tracker")

def start_fast_monitor():
    t = threading.Thread(target=fast_monitor_loop, daemon=True)
    t.start()
    return t
