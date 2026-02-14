# confirmations.py
# Multi-timeframe confirmation engine: checks 5m -> 3m -> 2m -> 1m
from eodhd_api import get_intraday_bars
import config
import math

CONFIRM_CLOSE_ABOVE_RATIO = config.CONFIRM_CLOSE_ABOVE_RATIO
CONFIRM_CANDLE_BODY_MIN = config.CONFIRM_CANDLE_BODY_MIN

def aggregate_bars(bars_1m, agg_n):
    """
    Aggregate 1m bars into agg_n-minute bars (full chunks only).
    bars_1m should be ascending (oldest -> newest).
    Returns list of aggregated bars (ascending).
    """
    out = []
    if not bars_1m or agg_n <= 1:
        return bars_1m
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
                ts = chunk[-1].get("date") or chunk[-1].get("datetime")
                out.append({"open": openp, "high": max(highs), "low": min(lows), "close": closep, "volume": vol, "date": ts})
            except Exception:
                pass
            chunk = []
    return out

def grade_bar_for_confirmation(bar, zone_low, zone_high, direction):
    """
    Return grade 'A+','A','A-' based on video rules for a single bar.
    """
    try:
        o = float(bar.get("open") or bar.get("Open") or 0)
        c = float(bar.get("close") or bar.get("Close") or bar.get("close", 0))
        h = float(bar.get("high") or bar.get("High") or 0)
        l = float(bar.get("low") or bar.get("Low") or 0)
    except:
        return "A-"
    body = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l
    rsize = max(zone_high - zone_low, 1e-9)

    if direction == "bull":
        # A+ : green body, large relative to zone, tiny lower wick
        if c > o and body >= 0.5 * rsize and lower_wick <= 0.15 * body:
            return "A+"
        # A : red open -> green close flip, with notable lower wick
        if o < c and lower_wick >= 0.5 * (body + lower_wick):
            return "A"
        # A- : wick rejection
        if lower_wick > 0 and body > 0:
            return "A-"
    else:
        if c < o and body >= 0.5 * rsize and upper_wick <= 0.15 * body:
            return "A+"
        if o > c and upper_wick >= 0.5 * (body + upper_wick):
            return "A"
        if upper_wick > 0 and body > 0:
            return "A-"
    return "A-"

def check_bars_for_confirmation(bars, zone_low, zone_high, direction, tf_label):
    """
    bars: ascending list of bars for timeframe tf_label
    returns dict {bar, grade, tf_label} or None
    """
    if not bars:
        return None
    for b in reversed(bars[-12:]):  # check up to last 12 bars
        try:
            low = float(b.get("low") or b.get("Low") or 0)
            high = float(b.get("high") or b.get("High") or 0)
            openp = float(b.get("open") or b.get("Open") or 0)
            closep = float(b.get("close") or b.get("Close") or b.get("close", 0))
        except:
            continue
        body = abs(closep - openp)
        rsize = max(zone_high - zone_low, 1e-9)
        if direction == "bull":
            tapped = (low <= zone_high) and (closep > openp)
            if tapped and (closep >= (zone_low + CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                grade = grade_bar_for_confirmation(b, zone_low, zone_high, direction)
                return {"bar": b, "grade": grade, "tf": tf_label}
        else:
            tapped = (high >= zone_low) and (closep < openp)
            if tapped and (closep <= (zone_high - CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                grade = grade_bar_for_confirmation(b, zone_low, zone_high, direction)
                return {"bar": b, "grade": grade, "tf": tf_label}
    return None

def check_confirmation_multi_timeframe(ticker, entry):
    """
    entry: dict with keys zone_low, zone_high, direction, or_low, or_high
    Returns (confirmed_bool, confirming_bar, timeframe_label, grade)
    """
    zone_low = entry["zone_low"]
    zone_high = entry["zone_high"]
    direction = entry["direction"]

    # Try 5m
    bars_5m = get_intraday_bars(ticker, interval="5m", limit=120)
    res = check_bars_for_confirmation(bars_5m, zone_low, zone_high, direction, "5m")
    if res and res["grade"] in ("A+","A"):
        return True, res["bar"], "5m", res["grade"]

    # Fetch 1m and synthesize 3m,2m
    bars_1m = get_intraday_bars(ticker, interval="1m", limit=240)
    if not bars_1m:
        return False, None, None, None

    bars_3m = aggregate_bars(bars_1m, 3)
    res = check_bars_for_confirmation(bars_3m, zone_low, zone_high, direction, "3m")
    if res and res["grade"] in ("A+","A"):
        return True, res["bar"], "3m", res["grade"]

    bars_2m = aggregate_bars(bars_1m, 2)
    res = check_bars_for_confirmation(bars_2m, zone_low, zone_high, direction, "2m")
    if res and res["grade"] in ("A+","A"):
        return True, res["bar"], "2m", res["grade"]

    res = check_bars_for_confirmation(bars_1m, zone_low, zone_high, direction, "1m")
    if res and res["grade"] in ("A+","A"):
        return True, res["bar"], "1m", res["grade"]

    return False, None, None, None