# targets.py
import requests
import os
from datetime import datetime
import config
from eodhd_api import get_intraday_bars

EODHD_API_KEY = os.getenv("EODHD_API_KEY")

STOP_BUFFER_DOLLARS = config.STOP_BUFFER_DOLLARS
MIN_RISK_PX = config.MIN_RISK_PX

def get_prev_1h_highlow(ticker):
    """
    Return previous completed 1-hour bar high/low (structure target).
    """
    bars = get_intraday_bars(ticker, interval="1h", limit=24)
    if not bars:
        return None, None
    # choose last fully-completed hour; heuristic: pick bars[-2] if available
    chosen = bars[-1] if len(bars) == 1 else bars[-2]
    try:
        h = float(chosen.get("high") or chosen.get("High") or 0)
        l = float(chosen.get("low") or chosen.get("Low") or 0)
        return h, l
    except:
        return None, None

def compute_stop_and_targets(entry_price, or_low, or_high, direction, ticker=None):
    """
    Compute stop, T1 (2R), T2 (previous 1H high/low). Returns dict.
    """
    try:
        if direction == "bull":
            stop = (or_low - STOP_BUFFER_DOLLARS) if or_low is not None else (entry_price - 0.5)
            risk = max(abs(entry_price - stop), MIN_RISK_PX)
            t1 = entry_price + 2.0 * risk
            t2 = None
            if ticker:
                prev_high, _ = get_prev_1h_highlow(ticker)
                if prev_high:
                    t2 = prev_high
            chosen = "t1"
            if t2 and (t2 - entry_price) >= 2.0 * risk:
                chosen = "t2"
            return {"stop": round(stop, 4), "t1": round(t1, 4), "t2": round(t2, 4) if t2 else None,
                    "risk": round(risk, 6), "chosen": chosen}
        else:
            stop = (or_high + STOP_BUFFER_DOLLARS) if or_high is not None else (entry_price + 0.5)
            risk = max(abs(entry_price - stop), MIN_RISK_PX)
            t1 = entry_price - 2.0 * risk
            t2 = None
            if ticker:
                _, prev_low = get_prev_1h_highlow(ticker)
                if prev_low:
                    t2 = prev_low
            chosen = "t1"
            if t2 and (entry_price - t2) >= 2.0 * risk:
                chosen = "t2"
            return {"stop": round(stop, 4), "t1": round(t1, 4), "t2": round(t2, 4) if t2 else None,
                    "risk": round(risk, 6), "chosen": chosen}
    except Exception as e:
        print("compute_stop_and_targets error:", e)
        return {"stop": None, "t1": None, "t2": None, "risk": None, "chosen": "t1"}