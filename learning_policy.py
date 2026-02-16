# learning_policy.py
# Central policy storage and helpers used by sniper & learning engine.

import json
import os
from threading import Lock

POLICY_FILE = os.getenv("LEARNING_POLICY_FILE", "policy.json")
_lock = Lock()

# Default policy (conservative starting point)
_DEFAULT = {
    "min_confidence": 0.80,            # min confidence required to emit an alert
    "timeframe_weights": {"5m": 1.0, "3m": 0.95, "2m": 0.9, "1m": 0.8},
    "ticker_boosts": {},               # per-ticker boost multiplier (1.0 default)
    "max_ticker_boost": 1.5,
    "min_ticker_boost": 0.5,
    "last_updated": None
}

def _load_policy():
    if not os.path.exists(POLICY_FILE):
        _save_policy(_DEFAULT)
        return dict(_DEFAULT)
    try:
        with open(POLICY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        _save_policy(_DEFAULT)
        return dict(_DEFAULT)

def _save_policy(p):
    try:
        with open(POLICY_FILE, "w") as f:
            json.dump(p, f, indent=2)
    except Exception as e:
        print("learning_policy save error:", e)

# Public API
def get_policy():
    with _lock:
        return _load_policy()

def update_policy(updates: dict, smoothing=0.2):
    """
    updates: dict containing keys to update. For numeric/simples, we apply smoothing:
      new = old*(1-smoothing) + updates*smoothing
    For nested dicts (timeframe_weights, ticker_boosts) we merge and smooth individually.
    """
    with _lock:
        p = _load_policy()

        # min_confidence: smooth
        if "min_confidence" in updates:
            old = float(p.get("min_confidence", _DEFAULT["min_confidence"]))
            newv = float(updates["min_confidence"])
            p["min_confidence"] = round(old * (1.0 - smoothing) + newv * smoothing, 4)

        # timeframe_weights: merge and smooth
        if "timeframe_weights" in updates:
            tw = p.get("timeframe_weights", {}).copy()
            for k, v in updates["timeframe_weights"].items():
                old = float(tw.get(k, 1.0))
                newv = float(v)
                tw[k] = round(old * (1.0 - smoothing) + newv * smoothing, 4)
            p["timeframe_weights"] = tw

        # ticker_boosts: merge, clamp to [min_ticker_boost, max_ticker_boost]
        if "ticker_boosts" in updates:
            tb = p.get("ticker_boosts", {}).copy()
            minb = p.get("min_ticker_boost", 0.5)
            maxb = p.get("max_ticker_boost", 1.5)
            for t, v in updates["ticker_boosts"].items():
                old = float(tb.get(t, 1.0))
                newv = float(v)
                merged = round(old * (1.0 - smoothing) + newv * smoothing, 4)
                merged = max(minb, min(maxb, merged))
                tb[t] = merged
            p["ticker_boosts"] = tb

        from datetime import datetime
        p["last_updated"] = datetime.utcnow().isoformat()
        _save_policy(p)
        return p

def compute_confidence(base_grade: str, tf_label: str, ticker: str = None):
    """
    base_grade: 'A+', 'A', 'A-' -> map to base score
    tf_label: '5m','3m','2m','1m'
    ticker: optional ticker string to apply boost
    Returns a float 0..1
    """
    grade_map = {"A+": 0.98, "A": 0.88, "A-": 0.76}
    base = grade_map.get(base_grade, 0.7)
    p = get_policy()
    tf_w = p.get("timeframe_weights", {}).get(tf_label, 0.9)
    ticker_boosts = p.get("ticker_boosts", {})
    tboost = ticker_boosts.get(ticker, 1.0) if ticker else 1.0
    conf = base * tf_w * tboost
    # clamp 0..1
    if conf > 1.0:
        conf = 1.0
    if conf < 0.0:
        conf = 0.0
    return round(conf, 4)