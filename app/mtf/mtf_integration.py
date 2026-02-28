"""
Multi-Timeframe (MTF) Integration Module
Real BOS+FVG pattern detection across multiple timeframes

From video transcript (3:33-4:07):
"If you have a 1-minute, 2-minute, 3-minute, and 5-minute [signal],
you will go for the 5-minute. The highest time frame is going to be
the most powerful one. So if you have a few opportunities, a few
different FVG gaps, you will play the one that's on the highest time frame."

Implementation:
- Scans 1m, 2m, 3m, 5m charts for 9:30-9:40 OR breakout + FVG
- Detects when SAME pattern appears across multiple timeframes
- Prioritizes highest TF (5m strongest)
- Boosts confidence when lower TFs confirm the 5m signal

Confirmation Candle Types (2:02-3:22):
1. A+ (Strongest): Clean directional candle, minimal wicks
2. A (Strong): Opens opposite color, flips to signal direction
3. A- (Valid): Long rejection wick but doesn't fully close signal direction
"""

from datetime import datetime, time
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from utils import config

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHASE 3E: Import consolidated timeframe compression functions
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
from .mtf_compression import compress_to_3m, compress_to_2m, compress_to_1m

ET = ZoneInfo("America/New_York")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# STATS TRACKING
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_mtf_stats = {
    'analyzed': 0,
    'convergence_found': 0,
    'timeframe_breakdown': {
        '5m_only': 0,
        '5m_3m': 0,
        '5m_3m_2m': 0,
        '5m_3m_2m_1m': 0
    },
    'confirmation_grades': {
        'A+': 0,
        'A': 0,
        'A-': 0
    },
    'total_boost': 0.0
}

_cache_date = None
_mtf_cache = {}  # {ticker_direction: result}


def _check_cache_rollover():
    """Clear cache on new trading day."""
    global _cache_date, _mtf_cache
    today = datetime.now(ET).date()
    if _cache_date != today:
        _mtf_cache.clear()
        _cache_date = today


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# OPENING RANGE CALCULATION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _bar_time(bar: dict) -> Optional[time]:
    """Extract time from bar datetime."""
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def compute_or(bars: List[dict]) -> Tuple[Optional[float], Optional[float]]:
    """Compute 9:30-9:40 opening range high and low."""
    or_bars = [b for b in bars if _bar_time(b) and time(9, 30) <= _bar_time(b) < time(9, 40)]
    if len(or_bars) < 2:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# BOS+FVG PATTERN DETECTION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def detect_breakout(bars: List[dict], or_high: float, or_low: float) -> Tuple[Optional[str], Optional[int]]:
    """Detect OR breakout. Returns (direction, breakout_idx)."""
    for i, bar in enumerate(bars):
        bt = _bar_time(bar)
        if bt is None or bt < time(9, 40):
            continue
        
        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            return "bull", i
        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            return "bear", i
    
    return None, None


def detect_fvg(bars: List[dict], breakout_idx: int, direction: str) -> Tuple[Optional[float], Optional[float]]:
    """Detect FVG after breakout. Returns (fvg_low, fvg_high)."""
    for i in range(breakout_idx + 3, len(bars)):
        if i < 2:
            continue
        
        c0, c2 = bars[i - 2], bars[i]
        
        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= config.FVG_MIN_SIZE_PCT:
                return c0["high"], c2["low"]
        else:
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= config.FVG_MIN_SIZE_PCT:
                return c2["high"], c0["low"]
    
    return None, None


def grade_confirmation_candle(bar: dict, direction: str) -> Optional[str]:
    """
    Grade confirmation candle quality (from video 2:02-3:22).
    
    Returns:
        'A+': Clean directional candle, minimal wicks
        'A': Opens opposite, flips to signal direction (strong wick)
        'A-': Long rejection wick but doesn't fully close
        None: Invalid confirmation
    """
    body = abs(bar['close'] - bar['open'])
    bar_range = bar['high'] - bar['low']
    
    if bar_range == 0:
        return None
    
    body_ratio = body / bar_range
    is_green = bar['close'] > bar['open']
    is_red = bar['close'] < bar['open']
    
    if direction == 'bull':
        # A+: Strong green candle, body > 80% of range, minimal wicks
        if is_green and body_ratio > 0.80:
            return 'A+'
        
        # A: Opens red, flips green (or green with strong lower wick)
        lower_wick = bar['close'] - bar['low']
        wick_ratio = lower_wick / bar_range if bar_range > 0 else 0
        
        if is_green and wick_ratio > 0.30 and body_ratio > 0.40:
            return 'A'
        
        # A-: Red candle with long lower wick (rejection but didn't flip)
        if is_red and wick_ratio > 0.50:
            return 'A-'
    
    else:  # bear
        # A+: Strong red candle, body > 80% of range
        if is_red and body_ratio > 0.80:
            return 'A+'
        
        # A: Opens green, flips red (or red with strong upper wick)
        upper_wick = bar['high'] - bar['close']
        wick_ratio = upper_wick / bar_range if bar_range > 0 else 0
        
        if is_red and wick_ratio > 0.30 and body_ratio > 0.40:
            return 'A'
        
        # A-: Green candle with long upper wick (rejection but didn't flip)
        if is_green and wick_ratio > 0.50:
            return 'A-'
    
    return None


def scan_tf_for_signal(bars: List[dict], tf_name: str) -> Optional[Dict]:
    """
    Scan a single timeframe for complete BOS+FVG signal.
    
    Returns:
        Dict with signal details if found, None otherwise
    """
    if len(bars) < 20:
        return None
    
    # Step 1: Calculate OR
    or_high, or_low = compute_or(bars)
    if or_high is None:
        return None
    
    # Step 2: Detect breakout
    direction, breakout_idx = detect_breakout(bars, or_high, or_low)
    if direction is None:
        return None
    
    # Step 3: Detect FVG
    fvg_low, fvg_high = detect_fvg(bars, breakout_idx, direction)
    if fvg_low is None:
        return None
    
    # Step 4: Check for confirmation candle (look at next few bars after FVG)
    best_grade = None
    for i in range(breakout_idx + 3, min(breakout_idx + 10, len(bars))):
        bar = bars[i]
        # Check if bar touches FVG zone
        if direction == 'bull':
            if bar['low'] <= fvg_high and bar['low'] >= fvg_low:
                grade = grade_confirmation_candle(bar, direction)
                if grade and (best_grade is None or grade < best_grade):  # A+ < A < A-
                    best_grade = grade
        else:
            if bar['high'] >= fvg_low and bar['high'] <= fvg_high:
                grade = grade_confirmation_candle(bar, direction)
                if grade and (best_grade is None or grade < best_grade):
                    best_grade = grade
    
    # If no confirmation found, signal incomplete
    if best_grade is None:
        return None
    
    return {
        'timeframe': tf_name,
        'direction': direction,
        'or_high': or_high,
        'or_low': or_low,
        'breakout_idx': breakout_idx,
        'fvg_low': fvg_low,
        'fvg_high': fvg_high,
        'confirmation_grade': best_grade
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MTF CONVERGENCE LOGIC
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def check_mtf_convergence(
    ticker: str,
    direction: str,
    bars_5m: List[dict]
) -> Dict:
    """
    Check if 5m signal has convergence on lower timeframes.
    
    Strategy (from video):
    1. You already have a 5m BOS+FVG (primary signal)
    2. Derive 3m, 2m, 1m bars from the same 5m session
    3. Scan each TF for BOS+FVG pattern
    4. Check if direction aligns
    5. Count confirming timeframes
    6. Boost based on # of TFs with valid signals
    
    Returns:
        Dict with MTF analysis and boost
    """
    if len(bars_5m) < 30:
        return {
            'convergence': False,
            'timeframes': ['5m'],
            'convergence_score': 0.25,
            'boost': 0.0,
            'best_grade': None,
            'reason': 'Insufficient bars for MTF analysis'
        }
    
    # Start with 5m (already confirmed by sniper.py)
    confirmed_signals = [{'timeframe': '5m', 'direction': direction}]
    confirmed_timeframes = ['5m']
    best_confirmation_grade = None
    
    # Derive lower timeframes using consolidated compression module
    bars_3m = compress_to_3m(bars_5m)
    bars_2m = compress_to_2m(bars_5m)
    bars_1m = compress_to_1m(bars_5m)
    
    # Scan each timeframe
    for tf_bars, tf_name in [(bars_3m, '3m'), (bars_2m, '2m'), (bars_1m, '1m')]:
        signal = scan_tf_for_signal(tf_bars, tf_name)
        
        if signal and signal['direction'] == direction:
            confirmed_signals.append(signal)
            confirmed_timeframes.append(tf_name)
            
            # Track best confirmation grade across all TFs
            if best_confirmation_grade is None or signal['confirmation_grade'] < best_confirmation_grade:
                best_confirmation_grade = signal['confirmation_grade']
    
    # Calculate convergence metrics
    num_timeframes = len(confirmed_timeframes)
    convergence = num_timeframes > 1
    
    # Boost structure
    boost_map = {
        1: 0.00,   # 5m only
        2: 0.02,   # 5m + 3m
        3: 0.03,   # 5m + 3m + 2m
        4: 0.05    # 5m + 3m + 2m + 1m (A+ setup)
    }
    
    boost = boost_map[num_timeframes]
    convergence_score = num_timeframes / 4.0
    
    # Update stats
    if convergence:
        _mtf_stats['convergence_found'] += 1
        _mtf_stats['total_boost'] += boost
        
        if num_timeframes == 2:
            _mtf_stats['timeframe_breakdown']['5m_3m'] += 1
        elif num_timeframes == 3:
            _mtf_stats['timeframe_breakdown']['5m_3m_2m'] += 1
        elif num_timeframes == 4:
            _mtf_stats['timeframe_breakdown']['5m_3m_2m_1m'] += 1
        
        if best_confirmation_grade:
            _mtf_stats['confirmation_grades'][best_confirmation_grade] += 1
    else:
        _mtf_stats['timeframe_breakdown']['5m_only'] += 1
    
    return {
        'convergence': convergence,
        'timeframes': confirmed_timeframes,
        'convergence_score': convergence_score,
        'boost': boost,
        'best_grade': best_confirmation_grade,
        'signals': confirmed_signals,
        'reason': (
            f"BOS+FVG confirmed on {', '.join(confirmed_timeframes)}"
            if convergence else "5m signal only (no lower TF convergence)"
        )
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PUBLIC API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def enhance_signal_with_mtf(
    ticker: str,
    direction: str,
    bars_session: List[dict],
    **kwargs
) -> Dict:
    """
    Enhance 5m BOS+FVG signal with multi-timeframe convergence.
    
    Called from sniper.py Step 8.2 after confirmation layers.
    
    Args:
        ticker: Symbol
        direction: 'bull' or 'bear'
        bars_session: 5m session bars
        **kwargs: Ignored (backwards compatibility)
    
    Returns:
        Dict with MTF analysis:
        - enabled: True
        - convergence: bool
        - timeframes: List[str]
        - convergence_score: float (0.25-1.0)
        - boost: float (0.00-0.05)
        - best_grade: str ('A+', 'A', 'A-') or None
        - reason: str
    """
    _check_cache_rollover()
    _mtf_stats['analyzed'] += 1
    
    # Check cache
    cache_key = f"{ticker}_{direction}"
    if cache_key in _mtf_cache:
        return _mtf_cache[cache_key]
    
    # Validate
    if not bars_session or len(bars_session) < 30:
        result = {
            'enabled': True,
            'convergence': False,
            'timeframes': ['5m'],
            'convergence_score': 0.25,
            'boost': 0.0,
            'best_grade': None,
            'reason': 'Insufficient bars for MTF'
        }
        _mtf_cache[cache_key] = result
        return result
    
    # Run MTF analysis
    result = check_mtf_convergence(ticker, direction, bars_session)
    result['enabled'] = True
    
    # Cache
    _mtf_cache[cache_key] = result
    
    return result


def print_mtf_stats():
    """Print EOD MTF statistics."""
    if _mtf_stats['analyzed'] == 0:
        return
    
    conv_rate = (_mtf_stats['convergence_found'] / _mtf_stats['analyzed']) * 100
    avg_boost = _mtf_stats['total_boost'] / _mtf_stats['analyzed']
    
    print("\n" + "="*80)
    print("MTF CONVERGENCE - DAILY STATISTICS")
    print("="*80)
    print(f"Session Date:         {_cache_date}")
    print(f"Signals Analyzed:     {_mtf_stats['analyzed']}")
    print(f"MTF Convergence:      {_mtf_stats['convergence_found']} ({conv_rate:.1f}%)")
    print(f"Average Boost:        {avg_boost:.2%}")
    print("\nTimeframe Breakdown:")
    print(f"  5m only:            {_mtf_stats['timeframe_breakdown']['5m_only']}")
    print(f"  5m + 3m:            {_mtf_stats['timeframe_breakdown']['5m_3m']} (+2% boost)")
    print(f"  5m + 3m + 2m:       {_mtf_stats['timeframe_breakdown']['5m_3m_2m']} (+3% boost)")
    print(f"  5m + 3m + 2m + 1m:  {_mtf_stats['timeframe_breakdown']['5m_3m_2m_1m']} (+5% boost - A+)")
    print("\nConfirmation Grades:")
    print(f"  A+ (Strongest):     {_mtf_stats['confirmation_grades']['A+']}")
    print(f"  A (Strong):         {_mtf_stats['confirmation_grades']['A']}")
    print(f"  A- (Valid):         {_mtf_stats['confirmation_grades']['A-']}")
    print("="*80 + "\n")


def reset_daily_stats():
    """Reset stats for new trading day."""
    global _mtf_stats
    _mtf_stats = {
        'analyzed': 0,
        'convergence_found': 0,
        'timeframe_breakdown': {
            '5m_only': 0,
            '5m_3m': 0,
            '5m_3m_2m': 0,
            '5m_3m_2m_1m': 0
        },
        'confirmation_grades': {
            'A+': 0,
            'A': 0,
            'A-': 0
        },
        'total_boost': 0.0
    }


print("[MTF] âœ… Multi-timeframe BOS+FVG convergence system enabled")
print("[MTF] Strategy: Scans 5m/3m/2m/1m for same OR breakout + FVG pattern")
print("[MTF] Boost: +2% (2 TFs), +3% (3 TFs), +5% (4 TFs - A+ setup)")




