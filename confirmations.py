# confirmations.py
# Multi-timeframe confirmation engine: checks 5m -> 3m -> 2m -> 1m
from typing import List, Tuple, Optional, Dict
import math
import traceback
from scanner_helpers import get_intraday_bars_for_logger

# Tunable thresholds (kept conservative)
CONFIRM_CLOSE_ABOVE_RATIO = 0.5   # fraction of zone the candle must close into
CONFIRM_BODY_REL = 0.25           # min body relative to zone size for A+ style

def aggregate_bars(bars_1m: List[Dict], agg_n: int) -> List[Dict]:
    out = []
    if not bars_1m or agg_n <= 1:
        return bars_1m or []
    chunk = []
    for b in bars_1m:
        chunk.append(b)
        if len(chunk) == agg_n:
            try:
                openp = float(chunk[0].get("open") or chunk[0].get("Open") or 0)
                closep = float(chunk[-1].get("close") or chunk[-1].get("Close") or chunk[-1].get("close", 0))
                highs = [float(x.get("high") or x.get("High") or 0) for x in chunk]
                lows = [float(x.get("low") or x.get("Low") or 0) for x in chunk]
                vol = sum([float(x.get("volume") or x.get("Volume") or 0) for x in chunk])
                ts = chunk[-1].get("date") or chunk[-1].get("datetime") or None
                out.append({"open": openp, "high": max(highs), "low": min(lows),
                            "close": closep, "volume": vol, "date": ts})
            except Exception:
                pass
            chunk = []
    return out

def grade_bar_for_confirmation(bar: Dict, zone_low: float, zone_high: float, direction: str) -> str:
    try:
        o = float(bar.get("open") or bar.get("Open") or 0)
        c = float(bar.get("close") or bar.get("Close") or bar.get("close", 0))
        h = float(bar.get("high") or bar.get("High") or 0)
        l = float(bar.get("low") or bar.get("Low") or 0)
    except Exception:
        return "A-"
    body = abs(c - o)
    full = max(h - l, 1e-9)
    body_ratio = body / full
    zone_size = max(zone_high - zone_low, 1e-9)

    # A+ strong body and closes well into the zone
    if direction == "bull":
        if c > o and body_ratio >= CONFIRM_BODY_REL and (c - zone_low) >= (CONFIRM_CLOSE_ABOVE_RATIO * zone_size):
            return "A+"
        # A: opens red then flips green (we approximate with close > open and lower wick)
        if c > o and (o - l) >= 0.5 * (body + (o - l)):
            return "A"
        # A-: any visible rejection green
        if c > o:
            return "A-"
    else:
        if c < o and body_ratio >= CONFIRM_BODY_REL and (zone_high - c) >= (CONFIRM_CLOSE_ABOVE_RATIO * zone_size):
            return "A+"
        if c < o and (h - o) >= 0.5 * (body + (h - o)):
            return "A"
        if c < o:
            return "A-"
    return "A-"

def check_bars_for_confirmation(bars: List[Dict], zone_low: float, zone_high: float, direction: str, tf_label: str):
    if not bars:
        return None
    # check the most recent N bars
    for b in reversed(bars[-12:]):
        try:
            o = float(b.get("open") or b.get("Open") or 0)
            c = float(b.get("close") or b.get("Close") or b.get("close", 0))
            h = float(b.get("high") or b.get("High") or 0)
            l = float(b.get("low") or b.get("Low") or 0)
        except:
            continue
        zone_size = max(zone_high - zone_low, 1e-9)
        if direction == "bull":
            tapped = (l <= zone_high) and (c > o)
            if tapped and (c >= (zone_low + CONFIRM_CLOSE_ABOVE_RATIO * zone_size)):
                grade = grade_bar_for_confirmation(b, zone_low, zone_high, direction)
                return {"bar": b, "grade": grade, "tf": tf_label}
        else:
            tapped = (h >= zone_low) and (c < o)
            if tapped and (c <= (zone_high - CONFIRM_CLOSE_ABOVE_RATIO * zone_size)):
                grade = grade_bar_for_confirmation(b, zone_low, zone_high, direction)
                return {"bar": b, "grade": grade, "tf": tf_label}
    return None

def check_confirmation_multi_timeframe(ticker: str, entry: dict) -> Tuple[bool, Optional[Dict], Optional[str], Optional[str]]:
    """
    entry: dict with keys zone_low, zone_high, direction, or_low, or_high
    returns (ok, bar, timeframe, grade)
    """
    try:
        zone_low = entry["zone_low"]
        zone_high = entry["zone_high"]
        direction = entry["direction"]

        # Try 5m
        bars_5m = get_intraday_bars_for_logger(ticker, limit=120, interval="5m")
        res = check_bars_for_confirmation(bars_5m, zone_low, zone_high, direction, "5m")
        if res and res["grade"] in ("A+", "A"):
            return True, res["bar"], "5m", res["grade"]

        # Fetch 1m
        bars_1m = get_intraday_bars_for_logger(ticker, limit=300, interval="1m")
        if not bars_1m:
            return False, None, None, None

        # synth 3m -> check
        bars_3m = aggregate_bars(bars_1m, 3)
        res = check_bars_for_confirmation(bars_3m, zone_low, zone_high, direction, "3m")
        if res and res["grade"] in ("A+", "A"):
            return True, res["bar"], "3m", res["grade"]

        # 2m
        bars_2m = aggregate_bars(bars_1m, 2)
        res = check_bars_for_confirmation(bars_2m, zone_low, zone_high, direction, "2m")
        if res and res["grade"] in ("A+", "A"):
            return True, res["bar"], "2m", res["grade"]

        # 1m
        res = check_bars_for_confirmation(bars_1m, zone_low, zone_high, direction, "1m")
        if res and res["grade"] in ("A+", "A"):
            return True, res["bar"], "1m", res["grade"]

        return False, None, None, None
    except Exception as e:
        print("confirmations.check_confirmation_multi_timeframe error:", e)
        traceback.print_exc()
        return False, None, None, None