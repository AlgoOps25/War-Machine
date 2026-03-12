"""
Hourly Confidence Gate
Dynamically adjusts confidence thresholds based on historical hour-of-day win rates.

Integration:
  Queries session_heatmap data to identify historically weak/strong trading hours.
  Returns multiplier applied to MIN_CONFIDENCE thresholds in sniper.py:
    - 1.10 (raise gate 10%) during weak hours (WR < 45%)
    - 0.95 (lower gate 5%)  during strong hours (WR >= 65%)
    - 1.00 (neutral)        during normal hours or insufficient data

Cache:
  Heatmap data refreshed once per trading day (expensive DB query).
  In-memory cache valid until date changes.

Usage in sniper.py:
    from hourly_gate import get_hourly_confidence_multiplier
    
    # Before confidence gate check:
    hourly_mult = get_hourly_confidence_multiplier()
    effective_min_confidence = base_threshold * hourly_mult
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

# Cache state (module-level)
_heatmap_cache: Optional[dict] = None
_last_update: Optional[datetime] = None
_stats = {'applied': 0, 'raised': 0, 'lowered': 0, 'neutral': 0}

# Thresholds
WEAK_HOUR_WR = 45.0      # Raise gate if hour WR < this
STRONG_HOUR_WR = 65.0    # Lower gate if hour WR >= this
MIN_TRADES_HOUR = 10     # Minimum trades for hour to be considered

WEAK_MULT = 1.10         # Raise confidence threshold by 10%
STRONG_MULT = 0.95       # Lower confidence threshold by 5%


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def _refresh_cache():
    global _heatmap_cache, _last_update
    try:
        _heatmap_cache = build_heatmap_data(lookback_days=30)
        _last_update = _now_et()
        print("[HOURLY GATE] Cache refreshed | running neutral (no history yet)")
    except Exception as e:
        print(f"[HOURLY GATE] Cache refresh error: {e}")
        _heatmap_cache = {"hour_totals": {}}
        _last_update = _now_et()



def get_hourly_confidence_multiplier() -> float:
    """
    Returns confidence threshold multiplier for the current hour.
    
    Returns:
        1.10 — weak hour (historically < 45% WR) → raise gate
        0.95 — strong hour (historically >= 65% WR) → lower gate
        1.00 — neutral (normal hours or insufficient data)
    
    Thread-safe: only reads from cache, writes are single-threaded on startup.
    """
    global _heatmap_cache, _last_update, _stats
    
    now = _now_et()
    
    # Refresh cache if stale (new trading day)
    if _last_update is None or _last_update.date() != now.date():
        _refresh_cache()
    
    hour = now.hour
    
    # Outside regular trading hours (9:30-15:59) — neutral
    if hour < 9 or hour > 15:
        return 1.0
    
    # No cache data available
    if not _heatmap_cache or "hour_totals" not in _heatmap_cache:
        return 1.0
    
    hour_data = _heatmap_cache["hour_totals"].get(hour, {})
    wr = hour_data.get("wr")
    trades = hour_data.get("trades", 0)
    
    # Insufficient historical data for this hour
    if wr is None or trades < MIN_TRADES_HOUR:
        _stats['neutral'] += 1
        return 1.0
    
    _stats['applied'] += 1
    
    # Weak hour — raise confidence gate to filter more signals
    if wr < WEAK_HOUR_WR:
        _stats['raised'] += 1
        return WEAK_MULT
    
    # Strong hour — lower gate to capture more opportunities
    if wr >= STRONG_HOUR_WR:
        _stats['lowered'] += 1
        return STRONG_MULT
    
    # Normal hour (45-64% WR)
    _stats['neutral'] += 1
    return 1.0


def get_current_hour_context() -> dict:
    """
    Returns detailed context about current hour's historical performance.
    Useful for logging/debugging.
    
    Returns:
        {
            'hour': int,
            'win_rate': float or None,
            'trades': int,
            'multiplier': float,
            'classification': str ('weak'|'strong'|'neutral'|'no_data')
        }
    """
    global _heatmap_cache
    
    now = _now_et()
    hour = now.hour
    
    if not _heatmap_cache or "hour_totals" not in _heatmap_cache:
        return {
            'hour': hour,
            'win_rate': None,
            'trades': 0,
            'multiplier': 1.0,
            'classification': 'no_data'
        }
    
    hour_data = _heatmap_cache["hour_totals"].get(hour, {})
    wr = hour_data.get("wr")
    trades = hour_data.get("trades", 0)
    mult = get_hourly_confidence_multiplier()
    
    if wr is None or trades < MIN_TRADES_HOUR:
        classification = 'no_data'
    elif wr < WEAK_HOUR_WR:
        classification = 'weak'
    elif wr >= STRONG_HOUR_WR:
        classification = 'strong'
    else:
        classification = 'neutral'
    
    return {
        'hour': hour,
        'win_rate': wr,
        'trades': trades,
        'multiplier': mult,
        'classification': classification
    }


def print_hourly_gate_stats():
    """
    Print EOD statistics showing how often hourly gating was applied.
    Called from sniper.py EOD block.
    """
    total = _stats['applied']
    if total == 0:
        return
    
    print("\n" + "="*60)
    print("HOURLY CONFIDENCE GATE STATISTICS")
    print("="*60)
    print(f"Total Evaluations: {total}")
    print(f"  Raised Gate (+10%): {_stats['raised']} ({_stats['raised']/total*100:.1f}%)")
    print(f"  Lowered Gate (-5%): {_stats['lowered']} ({_stats['lowered']/total*100:.1f}%)")
    print(f"  Neutral (1.0x):     {_stats['neutral']} ({_stats['neutral']/total*100:.1f}%)")
    print("="*60 + "\n")

def build_heatmap_data(lookback_days: int = 30) -> dict:
    """
    Placeholder — returns empty heatmap until sufficient trade history exists.
    Hourly gate will run neutral (1.0x) until this is populated.
    """
    return {"hour_totals": {}}

