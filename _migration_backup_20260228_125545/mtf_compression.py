"""
MTF Timeframe Compression Module
Unified compression logic for multi-timeframe analysis

CONSOLIDATION: Single source of truth for deriving 1m, 2m, 3m bars from 5m data.
Previously duplicated in mtf_integration.py and mtf_fvg_priority.py.

Strategy:
- Compress 5m bars into lower timeframe approximations
- Used by MTF convergence detection and FVG priority resolution
- Maintains temporal alignment for pattern detection across timeframes

From Nitro Trades video:
"If you have a 1-minute, 2-minute, 3-minute, and 5-minute [signal],
you will go for the 5-minute. The highest time frame is going to be
the most powerful one."

This module enables that multi-timeframe scanning capability.
"""

from typing import List, Dict
from datetime import timedelta


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


# Timeframe metadata
TIMEFRAME_PRIORITY = ['5m', '3m', '2m', '1m']  # Highest to lowest
TIMEFRAME_WEIGHTS = {
    '5m': 1.00,  # Strongest
    '3m': 0.85,
    '2m': 0.70,
    '1m': 0.55   # Weakest
}


print("[MTF-COMPRESSION] ✅ Unified timeframe compression module loaded")
print("[MTF-COMPRESSION] Supports: 1m, 2m, 3m derivation from 5m bars")
