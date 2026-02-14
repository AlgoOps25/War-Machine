# targets.py
# Computes stop, T1 (2R), T2 (previous 1-hour high/low) and helper functions

import os
import requests
from datetime import datetime, timedelta
import pytz

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
est = pytz.timezone("US/Eastern")

# tuning: buffer added to stop beyond OR edge (dollars) or percent fallback
STOP_BUFFER_DOLLARS = 0.5
MIN_RISK_PX = 0.01  # avoid zero division

def get_1h_highlow(ticker):
    """
    Try to fetch 1-hour intraday bars from EODHD.
    Returns (prev_1h_high, prev_1h_low) for the prior completed 1-hour bucket.
    If not available returns (None, None) and caller may fallback.
    """
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval=1h&limit=24"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None, None
        bars = r.json()
        if isinstance(bars, dict) and "data" in bars:
            bars = bars["data"]
        if not bars:
            return None, None
        # find the most recent completed hour (exclude current partial hour)
        # assume bars are chronological
        # take the last full bar (bars[-2] if last = current partial)
        last_bar = bars[-1]
        # if last bar timestamp is within current hour, take bars[-2] if exists
        try:
            # naive check: if last bar timestamp minute == 0 assume full; else use previous
            ts = last_bar.get("date") or last_bar.get("datetime")
            if ts and isinstance(ts, str):
                dt = datetime.fromisoformat(ts)
                if dt.minute == 0 and len(bars) >= 1:
                    chosen = bars[-1]
                elif len(bars) >= 2:
                    chosen = bars[-2]
                else:
                    chosen = bars[-1]
            else:
                chosen = bars[-1]
        except:
            chosen = bars[-1]
        high = float(chosen.get("high") or chosen.get("High") or 0)
        low = float(chosen.get("low") or chosen.get("Low") or 0)
        return high, low
    except Exception:
        return None, None

def compute_stop_and_targets(entry_price, or_low, or_high, direction, ticker=None):
    """
    entry_price: price at confirmation
    or_low/or_high: opening range low/high (useful for stop placement)
    direction: 'bull' or 'bear'
    returns dict: {'stop':..., 't1':..., 't2':..., 'risk':..., 'chosen_target':'t1' or 't2'}
    Logic:
      - stop: for bull -> or_low - buffer, for bear -> or_high + buffer
      - risk = abs(entry - stop)
      - t1 = entry +/- 2 * risk
      - try to get t2 = prev 1H high/low (structure)
      - if t2 exists and yields >= 2R, use it as extended target; else t2 remains but chosen_target defaults to t1
    """
    try:
        if direction == "bull":
            stop = (or_low - STOP_BUFFER_DOLLARS) if or_low is not None else (entry_price - 0.5)
            risk = max(abs(entry_price - stop), MIN_RISK_PX)
            t1 = entry_price + 2.0 * risk
            # get previous 1h high
            t2_high, t2_low = (None, None)
            if ticker:
                t2_high, t2_low = get_1h_highlow(ticker)
            # for bullish we use previous 1h high as extended target
            t2 = t2_high
            chosen = "t1"
            if t2 and (t2 - entry_price) >= 2.0 * risk:
                chosen = "t2"
            return {"stop": round(stop, 4), "t1": round(t1, 4), "t2": (round(t2, 4) if t2 else None),
                    "risk": round(risk, 6), "chosen": chosen}
        else:  # bear
            stop = (or_high + STOP_BUFFER_DOLLARS) if or_high is not None else (entry_price + 0.5)
            risk = max(abs(entry_price - stop), MIN_RISK_PX)
            t1 = entry_price - 2.0 * risk
            t2_high, t2_low = (None, None)
            if ticker:
                t2_high, t2_low = get_1h_highlow(ticker)
            # for bearish we use previous 1h low as extended target
            t2 = t2_low
            chosen = "t1"
            if t2 and (entry_price - t2) >= 2.0 * risk:
                chosen = "t2"
            return {"stop": round(stop, 4), "t1": round(t1, 4), "t2": (round(t2, 4) if t2 else None),
                    "risk": round(risk, 6), "chosen": chosen}
    except Exception:
        return {"stop": None, "t1": None, "t2": None, "risk": None, "chosen": "t1"}
