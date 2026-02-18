"""
CFW6 Timeframe Manager - Video Rule Implementation
"If you have setups on multiple timeframes, always take the HIGHEST timeframe"
Priority: 5m > 3m > 2m > 1m
"""
from typing import Dict, List, Tuple, Optional
import config

def detect_fvg_on_timeframe(
    ticker: str,
    timeframe: str,
    bars: List[Dict]
) -> Optional[Dict]:
    """
    Detect FVG on specific timeframe
    Returns FVG details if found, None otherwise
    """
    # Import here to avoid circular dependency
    from sniper import (
        compute_opening_range_from_bars,
        detect_breakout_after_or,
        detect_fvg_after_break
    )
    
    # Get OR levels
    or_high, or_low = compute_opening_range_from_bars(bars)
    if not or_high:
        return None
    
    # Detect breakout
    direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
    if not direction:
        return None
    
    # Detect FVG
    fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
    if not fvg_low:
        return None
    
    return {
        "timeframe": timeframe,
        "ticker": ticker,
        "direction": direction,
        "fvg_low": fvg_low,
        "fvg_high": fvg_high,
        "or_high": or_high,
        "or_low": or_low,
        "breakout_idx": breakout_idx
    }

def find_highest_timeframe_setup(ticker: str) -> Optional[Dict]:
    """
    CFW6 VIDEO RULE: "Go for the highest timeframe FVG"
    
    Priority order: 5m → 3m → 2m → 1m
    Returns the setup from the highest timeframe available
    """
    from scanner_helpers import get_recent_bars_from_memory
    
    timeframes = config.CONFIRMATION_TIMEFRAMES  # ["5m", "3m", "2m", "1m"]
    
    print(f"[MTF] Scanning {ticker} across timeframes: {timeframes}")
    
    for tf in timeframes:
        print(f"[MTF] Checking {tf} timeframe...")
        
        # Fetch bars for this timeframe
        bars = get_recent_bars_from_memory(ticker, limit=300)
        
        if not bars:
            continue
        
        # If checking higher timeframes, aggregate 1m bars
        if tf != "1m":
            bars = aggregate_bars_to_timeframe(bars, tf)
        
        setup = detect_fvg_on_timeframe(ticker, tf, bars)
        
        if setup:
            print(f"[MTF] ✅ Found setup on {tf} - Using this one (highest priority)")
            return setup
    
    print(f"[MTF] ❌ No setups found on any timeframe for {ticker}")
    return None

def aggregate_bars_to_timeframe(bars_1m: List[Dict], target_tf: str) -> List[Dict]:
    """
    Aggregate 1-minute bars to higher timeframes
    
    "2m" = 2 bars, "3m" = 3 bars, "5m" = 5 bars
    """
    tf_map = {"2m": 2, "3m": 3, "5m": 5}
    period = tf_map.get(target_tf, 1)
    
    aggregated = []
    
    for i in range(0, len(bars_1m), period):
        chunk = bars_1m[i:i+period]
        
        if len(chunk) < period:
            break  # Don't include incomplete periods
        
        agg_bar = {
            "datetime": chunk[0]["datetime"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(b["volume"] for b in chunk)
        }
        
        aggregated.append(agg_bar)
    
    return aggregated

def calculate_mtf_convergence_boost(ticker: str) -> float:
    """
    Multi-timeframe convergence bonus
    
    If signal appears on multiple timeframes, boost confidence:
    - 3+ timeframes aligned: +15% confidence
    - 2 timeframes aligned: +5% confidence
    - 1 timeframe only: No boost
    """
    from scanner_helpers import get_recent_bars_from_memory
    
    timeframes = ["1m", "2m", "3m", "5m"]
    signals_found = 0
    
    bars_1m = get_recent_bars_from_memory(ticker, limit=300)
    if not bars_1m:
        return 0
    
    for tf in timeframes:
        bars = bars_1m if tf == "1m" else aggregate_bars_to_timeframe(bars_1m, tf)
        setup = detect_fvg_on_timeframe(ticker, tf, bars)
        
        if setup:
            signals_found += 1
    
    if signals_found >= 3:
        boost = 0.15
        print(f"[MTF] 🚀 {signals_found} timeframes aligned → +15% confidence boost")
    elif signals_found == 2:
        boost = 0.05
        print(f"[MTF] ⬆️ {signals_found} timeframes aligned → +5% confidence boost")
    else:
        boost = 0
        print(f"[MTF] Single timeframe setup → No boost")
    
    return boost
