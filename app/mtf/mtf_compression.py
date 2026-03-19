"""
app/mtf/mtf_compression.py — MTF Timeframe Compression

INPUT ASSUMPTION: All compression functions expect 5-minute bars as input
unless the function name or parameter explicitly states otherwise.
compress_to_3m / compress_to_2m / compress_to_1m will return the input
unchanged if detect_bar_resolution() determines it is not 5m data.

compress_bars(bars, minutes) is the unified entry point. Use it instead of
calling compress_to_Xm() directly.

Supported derivations:
  5m  → 3m   (synthetic: first 60% of each 5m bar)
  5m  → 2m   (synthetic: first 40% of each 5m bar)
  5m  → 1m   (synthetic: 5 equal steps per 5m bar)
  5m  → 15m  (real aggregation: 3x 5m bars)
  5m  → 30m  (real aggregation: 6x 5m bars)

FIX H2 (MAR 10, 2026):
  Removed duplicate TIMEFRAME_PRIORITY / TIMEFRAME_WEIGHTS assignments.
  Single authoritative definition now covers all supported timeframes.
"""
import logging
from typing import List, Dict, Optional
from datetime import timedelta

def detect_bar_resolution(bars: list) -> int:
    """
    Auto-detect bar width in minutes by inspecting timestamps.
    Returns 1, 2, 3, 5, 15, 30, or 60. Defaults to 5 if unclear.
    """
    if len(bars) < 2:
        return 5
    deltas = []
    for i in range(1, min(6, len(bars))):
        try:
            diff = (bars[i]['datetime'] - bars[i-1]['datetime']).seconds // 60
            if diff > 0:
                deltas.append(diff)
        except Exception:
            pass
    if not deltas:
        return 5
    return min(deltas)

# Add these functions to app/mtf/mtf_compression.py

def expand_to_15m(bars_5m: List[dict]) -> List[dict]:
    """
    Expand 5m bars to 15m bars.
    
    Strategy: Combine 3x 5m bars into 1x 15m bar.
    Maintains proper OHLCV aggregation.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        List of 15m bars
    """
    bars_15m = []
    
    # Process in chunks of 3
    for i in range(0, len(bars_5m) - 2, 3):
        chunk = bars_5m[i:i+3]
        
        bars_15m.append({
            'datetime': chunk[0]['datetime'],
            'open': chunk[0]['open'],
            'high': max(b['high'] for b in chunk),
            'low': min(b['low'] for b in chunk),
            'close': chunk[-1]['close'],
            'volume': sum(b['volume'] for b in chunk)
        })
    
    return bars_15m


def expand_to_30m(bars_5m: List[dict]) -> List[dict]:
    """
    Expand 5m bars to 30m bars.
    
    Strategy: Combine 6x 5m bars into 1x 30m bar.
    Maintains proper OHLCV aggregation.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        List of 30m bars
    """
    bars_30m = []
    
    # Process in chunks of 6
    for i in range(0, len(bars_5m) - 5, 6):
        chunk = bars_5m[i:i+6]
        
        bars_30m.append({
            'datetime': chunk[0]['datetime'],
            'open': chunk[0]['open'],
            'high': max(b['high'] for b in chunk),
            'low': min(b['low'] for b in chunk),
            'close': chunk[-1]['close'],
            'volume': sum(b['volume'] for b in chunk)
        })
    
    return bars_30m


def build_partial_higher_tf_bar(bars_5m: List[dict], target_tf: str) -> Optional[dict]:
    """
    Build incomplete higher timeframe bar from available 5m bars.
    Useful for early-session analysis when full bars haven't formed yet.
    
    Args:
        bars_5m: Recent 5m bars
        target_tf: '15m' or '30m'
    
    Returns:
        Partial bar dict with 'is_complete' flag, or None if insufficient data
    """
    bars_needed = {'15m': 3, '30m': 6}
    required = bars_needed.get(target_tf)
    
    if not required or len(bars_5m) < 1:
        return None
    
    # Take up to required number of recent bars
    available = bars_5m[-required:] if len(bars_5m) >= required else bars_5m
    
    return {
        'datetime': available[0]['datetime'],
        'open': available[0]['open'],
        'high': max(b['high'] for b in available),
        'low': min(b['low'] for b in available),
        'close': available[-1]['close'],
        'volume': sum(b['volume'] for b in available),
        'is_complete': len(available) == required,
        'bars_available': len(available)
    }



def compress_to_3m(bars_5m: List[dict]) -> List[dict]:
    
    """
    Compress 5m bars to approximate 3m bars.
    
    Strategy: Split each 5m bar into synthetic 3m + 2m segments.
    The 3m segment represents the first 60% of the 5m bar's price action.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        List of approximate 3m bars
    """
    if detect_bar_resolution(bars_5m) != 5:
        return bars_5m  # input is not 5m — skip compression, return as-is

    bars_3m = []
    
    for bar in bars_5m:
        bar_time = bar['datetime']
        mid_price = (bar['open'] + bar['close']) / 2
        mid_high = (bar['open'] + bar['high']) / 2
        mid_low = (bar['open'] + bar['low']) / 2
        
        bars_3m.append({
            'datetime': bar_time,
            'open': bar['open'],
            'high': max(bar['open'], mid_high),
            'low': min(bar['open'], mid_low),
            'close': mid_price,
            'volume': bar['volume'] * 0.6
        })
    
    return bars_3m


def compress_to_2m(bars_5m: List[dict]) -> List[dict]:
    """
    Compress 5m bars to approximate 2m bars.
    
    Strategy: Split each 5m bar into 2-3 synthetic 2m segments.
    The first 2m segment represents approximately 40% of the 5m bar's move.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        List of approximate 2m bars
    """
    if detect_bar_resolution(bars_5m) != 5:
        return bars_5m  # input is not 5m — skip compression, return as-is

    bars_2m = []
    
    for bar in bars_5m:
        bar_time = bar['datetime']
        third_1 = bar['open'] + (bar['close'] - bar['open']) * 0.4
        
        # First 2m segment (40% of the 5m move)
        bars_2m.append({
            'datetime': bar_time,
            'open': bar['open'],
            'high': max(bar['open'], third_1, bar['high'] * 0.3 + bar['open'] * 0.7),
            'low': min(bar['open'], third_1, bar['low'] * 0.3 + bar['open'] * 0.7),
            'close': third_1,
            'volume': bar['volume'] * 0.4
        })
    
    return bars_2m


def compress_to_1m(bars_5m: List[dict]) -> List[dict]:
    """
    Compress 5m bars to approximate 1m bars.
    
    Strategy: Split each 5m bar into 5 synthetic 1m bars.
    Each 1m bar represents 20% of the 5m bar's price action.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        List of approximate 1m bars (5x the input count)
    """
    if detect_bar_resolution(bars_5m) != 5:
        return bars_5m  # input is not 5m — skip compression, return as-is

    bars_1m = []
    
    for bar in bars_5m:
        bar_time = bar['datetime']
        price_range = bar['close'] - bar['open']
        
        for i in range(5):
            step_open = bar['open'] + price_range * (i / 5.0)
            step_close = bar['open'] + price_range * ((i + 1) / 5.0)
            
            bars_1m.append({
                'datetime': bar_time + timedelta(minutes=i),
                'open': step_open,
                'high': max(step_open, step_close, bar['high'] if i == 2 else step_open),
                'low': min(step_open, step_close, bar['low'] if i == 3 else step_open),
                'close': step_close,
                'volume': bar['volume'] / 5.0
            })
    
    return bars_1m


def compress_to_all_timeframes(bars_5m: List[dict]) -> Dict[str, List[dict]]:
    """
    Convenience function to compress 5m bars to all lower timeframes at once.
    
    Args:
        bars_5m: List of 5m OHLCV bar dicts
    
    Returns:
        Dict mapping timeframe name to compressed bars:
        {'5m': bars_5m, '3m': bars_3m, '2m': bars_2m, '1m': bars_1m}
    """
    return {
        '5m': bars_5m,
        '3m': compress_to_3m(bars_5m),
        '2m': compress_to_2m(bars_5m),
        '1m': compress_to_1m(bars_5m)
    }


# H2 FIX: Single authoritative TIMEFRAME_PRIORITY and TIMEFRAME_WEIGHTS.
# Previous file had two separate assignments; the second (lower) block contained
# only the original 4 timeframes and silently wiped out the 1h/30m/15m entries
# added in the top block. Consolidated here — highest to lowest priority.
TIMEFRAME_PRIORITY = ['1h', '30m', '15m', '5m', '3m', '2m', '1m']  # Highest to lowest

TIMEFRAME_WEIGHTS = {
    '1h':  2.00,  # Strongest
    '30m': 1.50,
    '15m': 1.25,
    '5m':  1.00,
    '3m':  0.85,
    '2m':  0.70,
    '1m':  0.55   # Weakest
}

# Time-based availability windows
TIMEFRAME_MIN_MINUTES = {
    '1h':  60,
    '30m': 30,
    '15m': 15,
    '5m':  5,
    '3m':  3,
    '2m':  2,
    '1m':  1
}

def compress_bars(bars: List[dict], minutes: int) -> List[dict]:
    """
    Unified compression entry point. Replaces direct calls to compress_to_Xm().

    Args:
        bars:    Input bars (must be 5m resolution for synthetic compression).
        minutes: Target timeframe in minutes. Supported: 1, 2, 3, 15, 30.
                 Passing 5 returns bars unchanged.

    Returns:
        Compressed bar list, or bars unchanged if minutes==5 or unsupported.
    """
    dispatch = {
        1:  compress_to_1m,
        2:  compress_to_2m,
        3:  compress_to_3m,
        15: expand_to_15m,
        30: expand_to_30m,
    }
    fn = dispatch.get(minutes)
    if fn is None:
        return bars
    return fn(bars)

logger = logging.getLogger(__name__)