"""
Learning Policy Module - Confidence calculation with dark pool integration
"""

import json
import os
from threading import Lock

POLICY_FILE = "policy.json"
policy_lock = Lock()


def get_policy():
    """Load policy from JSON file."""
    with policy_lock:
        if not os.path.exists(POLICY_FILE):
            return {
                "min_confidence": 0.75,
                "timeframe_weights": {
                    "5m": 1.0,
                    "3m": 0.95,
                    "2m": 0.90,
                    "1m": 0.85
                },
                "ticker_boosts": {}
            }
        
        try:
            with open(POLICY_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[POLICY] Error loading policy: {e}")
            return {"min_confidence": 0.75, "timeframe_weights": {}, "ticker_boosts": {}}


def save_policy(policy: dict):
    """Save policy to JSON file."""
    with policy_lock:
        try:
            with open(POLICY_FILE, "w") as f:
                json.dump(policy, f, indent=2)
        except Exception as e:
            print(f"[POLICY] Error saving policy: {e}")


def compute_confidence(base_grade: str, tf_label: str, ticker: str = None):
    """
    Calculate confidence with CFW6 grading and dark pool integration.
    
    base_grade: 'A+', 'A', 'A-' -> CFW6 confirmation quality
    tf_label: '5m','3m','2m','1m'
    ticker: optional ticker string to apply boost and dark pool analysis
    
    Returns a float 0..1
    """
    # CFW6 grade mapping
    grade_map = {"A+": 0.98, "A": 0.88, "A-": 0.76}
    base = grade_map.get(base_grade, 0.7)
    
    p = get_policy()
    tf_w = p.get("timeframe_weights", {}).get(tf_label, 0.9)
    ticker_boosts = p.get("ticker_boosts", {})
    tboost = ticker_boosts.get(ticker, 1.0) if ticker else 1.0
    
    conf = base * tf_w * tboost
    
    # DARK POOL INTEGRATION
    if ticker:
        try:
            from scanner_helpers import analyze_darkpool
            import config
            
            dp_data = analyze_darkpool(ticker)
            if dp_data:
                total_dp_volume = dp_data.get("total_volume_usd", 0)
                if total_dp_volume >= config.DARKPOOL_BOOST_THRESHOLD:
                    dark_pool_boost = config.DARKPOOL_BOOST_FACTOR
                    conf += dark_pool_boost
                    print(f"[LEARNING] {ticker} dark pool boost: ${total_dp_volume:,.0f} (+{dark_pool_boost*100:.1f}%)")
        except Exception as e:
            print(f"[LEARNING] Dark pool check failed for {ticker}: {e}")
    
    # Clamp 0..1
    conf = max(0.0, min(1.0, conf))
    
    return round(conf, 4)
