# sniper.py (policy-aware)
import json
import os
import threading
import time
from datetime import datetime, timedelta
import traceback
from scanner_helpers import get_intraday_bars_for_logger
import confirmations
import targets
import trade_logger
import requests
import learning_policy

RETEST_STATE_FILE = "retest_state.json"
MAX_ARMED = int(os.getenv("MAX_ARMED", "25"))
RETEST_TIMEOUT_MINUTES = int(os.getenv("RETEST_TIMEOUT_MINUTES", "60"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def send_discord(msg: str):
    if not DISCORD_WEBHOOK:
        print("discord:", msg)
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception as e:
        print("discord send error:", e)

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
        "armed_at": datetime.utcnow().isoformat(),
        "confirmed": False
    }
    _save_state(retest_state)
    send_discord(f"🔔 PRE-ALERT: {ticker} {direction} armed for FVG {zone_low:.2f}-{zone_high:.2f}")

def compute_opening_range_from_bars(bars):
    # identical to previous implementation — keep same logic
    try:
        import pytz
        from datetime import datetime as dt, time as dtime
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
                d = datetime.fromisoformat(ts)
                if d.tzinfo is None:
                    import pytz as _p
                    d = d.replace(tzinfo=_p.UTC).astimezone(est)
                else:
                    d = d.astimezone(est)
            except:
                continue
            if d >= or_start and d <= or_end:
                highs.append(float(b.get("high") or b.get("High") or 0))
                lows.append(float(b.get("low") or b.get("Low") or 0))
        if not highs or not lows:
            return None, None
        return max(highs), min(lows)
    except Exception:
        return None, None

# detect breakout and FVG (same approach as before)
def detect_breakout_after_or(bars, or_high, or_low):
    try:
        import pytz
        from datetime import datetime as dt, time as dtime
        est = pytz.timezone("US/Eastern")
        today = datetime.now(est).date()
        or_end = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
        for idx, b in enumerate(bars):
            ts = b.get("date") or b.get("datetime") or b.get("time")
            if not ts:
                continue
            try:
                d = datetime.fromisoformat(ts)
                if d.tzinfo is None:
                    import pytz as _p
                    d = d.replace(tzinfo=_p.UTC).astimezone(est)
                else:
                    d = d.astimezone(est)
            except:
                continue
            if d <= or_end:
                continue
            h = float(b.get("high") or b.get("High") or 0)
            l = float(b.get("low") or b.get("Low") or 0)
            if h > (or_high or 0):
                return "bull", idx
            if l < (or_low or 0):
                return "bear", idx
        return None, None
    except Exception:
        return None, None

def detect_fvg_after_break(bars, breakout_idx, direction):
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
                    return min(h0, l2), max(h0, l2)
            else:
                if h2 < l0:
                    return min(h2, l0), max(h2, l0)
    except Exception:
        pass
    return None, None

def process_ticker(ticker: str):
    try:
        # ===== PULL BARS FROM EODHD =====
        bars_1m = get_intraday_bars_for_logger(ticker, limit=400, interval="1m")

        if not bars_1m:
            send_discord(f"❌ {ticker} NO DATA FROM EODHD")
            print(f"❌ {ticker} no data returned")
            return

        # ===== BAR COUNT DEBUG =====
        bar_count = len(bars_1m)
        print(f"📊 {ticker} bars received:", bar_count)
        send_discord(f"📊 {ticker} bars received: {bar_count}")

        if bar_count < 50:
            print(f"{ticker}: not enough bars yet")
            return

        # ===== OPENING RANGE =====
        or_high, or_low = compute_opening_range_from_bars(bars_1m)
        if or_high is None:
            print(f"{ticker}: OR not formed yet")
            return

        # ===== BREAKOUT DETECTION =====
        direction, breakout_idx = detect_breakout_after_or(bars_1m, or_high, or_low)
        if not direction:
            return

        # ===== FVG DETECTION =====
        fvg_low, fvg_high = detect_fvg_after_break(bars_1m, breakout_idx, direction)
        if not fvg_low:
            return

        zone_low, zone_high = min(fvg_low, fvg_high), max(fvg_low, fvg_high)

        # ===== ARM TRADE =====
        arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high)

    except Exception as e:
        print("process_ticker error:", e)
        send_discord(f"❌ SNIPER ERROR {ticker}: {e}")
        traceback.print_exc()

def fast_monitor_loop():
    global retest_state
    print("Sniper fast monitor started (policy-aware)")
    while True:
        try:
            keys = list(retest_state.keys())
            for k in keys:
                entry = retest_state.get(k)
                if not entry:
                    continue

                # prune old
                armed_at = datetime.fromisoformat(entry["armed_at"])
                if datetime.utcnow() - armed_at > timedelta(minutes=RETEST_TIMEOUT_MINUTES):
                    try:
                        del retest_state[k]
                        _save_state(retest_state)
                    except:
                        pass
                    continue

                if entry.get("confirmed"):
                    continue

                ok, bar, tf, grade = confirmations.check_confirmation_multi_timeframe(entry["ticker"], {
                    "zone_low": entry["zone_low"],
                    "zone_high": entry["zone_high"],
                    "direction": entry["direction"],
                    "or_low": entry["or_low"],
                    "or_high": entry["or_high"]
                })

                if ok:
                    # compute confidence via learning_policy
                    conf = learning_policy.compute_confidence(grade, tf, entry["ticker"])
                    # === APPLY LEARNING BOOST ===
                    try:
                        import learning_memory
                        boost = learning_memory.get_confidence_boost(tf, grade)
                        conf += boost
                        conf = max(0, min(conf, 1))
                    except:
                        pass
                    policy = learning_policy.get_policy()
                    min_conf = float(policy.get("min_confidence", 0.8))
                    # apply final decision: only accept if conf >= min_conf
                    if conf >= min_conf:
                        # compute stops & targets
                        entry_price = float(bar.get("close") or bar.get("Close") or 0)
                        calc = targets.compute_stop_and_targets(entry_price, entry["or_low"], entry["or_high"],
                                                                "bull" if entry["direction"] in ("bull","CALL") else "bear",
                                                                ticker=entry["ticker"])
                        stop = calc.get("stop")
                        t1 = calc.get("t1")
                        t2 = calc.get("t2")
                        chosen = calc.get("chosen")
                        entry_ts = datetime.utcnow().isoformat()
                        trade_id = trade_logger.log_confirmed_trade(entry["ticker"], entry["direction"], grade, entry_price, entry_ts, stop, t1, t2, chosen)
                        # === GOD MODE LEARNING LOG ===
                        try:
                            import learning_memory
                            learning_memory.log_trade(
                                entry["ticker"],
                                entry["direction"],
                                tf,
                                grade,
                                "OPEN"
                            )
                        except Exception as e:
                            print("learning log error:", e)
                        send_discord(f"🚨 CONFIRMED: {entry['ticker']} {entry['direction']} — grade {grade} — tf {tf}\nEntry {entry_price:.2f} Stop {stop:.2f} T1 {t1:.2f} T2 {t2 if t2 else 'n/a'}\nCONFIDENCE: {conf*100:.0f}% (min {min_conf*100:.0f}%) TradeId {trade_id}")
                        # mark confirmed and remove
                        try:
                            del retest_state[k]
                            _save_state(retest_state)
                        except:
                            pass
                    else:
                        print(f"Skipped confirmation for {entry['ticker']} grade {grade} tf {tf} conf {conf:.2f} (min {min_conf})")

            time.sleep(8)
        except Exception as e:
            print("fast_monitor error:", e)
            traceback.print_exc()
            time.sleep(8)

def start_fast_monitor():
    t = threading.Thread(target=fast_monitor_loop, daemon=True)
    t.start()
    return t
