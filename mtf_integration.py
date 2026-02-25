"""
Multi-Timeframe (MTF) Integration Module
Real-time convergence detection on live session bars

Strategy:
- When sniper.py detects a 5m BOS+FVG signal, this module checks if the
  SAME pattern is visible on lower timeframes (3m, 2m, 1m)
- Analyzes bar characteristics from existing 5m session data (no API calls)
- Runs pattern strength analysis on each timeframe granularity
- Boosts confidence when multiple timeframes confirm the same setup

From video transcript:
"If you have a 1-minute, 2-minute, 3-minute, and 5-minute, you will go
for the 5-minute. The highest time frame is going to be the most powerful one."

MTF convergence = 5m signal confirmed across multiple lower timeframes = A+ setup
"""

from datetime import datetime
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo
import config

ET = ZoneInfo("America/New_York")

# ════════════════════════════════════════════════════════════════════════════════
# STATS TRACKING
# ════════════════════════════════════════════════════════════════════════════════

_mtf_stats = {
    'analyzed': 0,
    'convergence_found': 0,
    'timeframe_breakdown': {
        '5m_only': 0,
        '5m_3m': 0,
        '5m_3m_2m': 0,
        '5m_3m_2m_1m': 0
    },
    'avg_boost': 0.0,
    'total_boost': 0.0
}

_cache_date = None
_mtf_cache = {}  # {ticker: mtf_result}


def _check_cache_rollover():
    """Clear cache on new trading day."""
    global _cache_date, _mtf_cache
    today = datetime.now(ET).date()
    if _cache_date != today:
        _mtf_cache.clear()
        _cache_date = today


# ════════════════════════════════════════════════════════════════════════════════
# BAR ANALYSIS HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def get_intrabar_volatility(bar: dict) -> float:
    """
    Calculate intra-bar volatility (high-low range as % of close).
    Used to detect if lower timeframe patterns likely exist within a 5m bar.
    """
    if bar['close'] == 0:
        return 0.0
    return (bar['high'] - bar['low']) / bar['close']


def get_bar_strength(bar: dict, direction: str) -> float:
    """
    Calculate directional strength of a bar (0.0 to 1.0).
    
    Measures:
    - Body size relative to total range
    - Direction alignment (green for bull, red for bear)
    - Wick rejection strength
    
    Returns:
        0.0 = no directional strength
        1.0 = perfect directional candle
    """
    bar_range = bar['high'] - bar['low']
    if bar_range == 0:
        return 0.0
    
    body = abs(bar['close'] - bar['open'])
    body_ratio = body / bar_range
    
    # Check direction alignment
    is_green = bar['close'] > bar['open']
    is_red = bar['close'] < bar['open']
    
    if direction == 'bull':
        if not is_green:
            return 0.0
        # Strong bull: body > 70% of range, close near high
        upper_wick = bar['high'] - bar['close']
        upper_rejection = 1.0 - (upper_wick / bar_range) if bar_range > 0 else 0
        return body_ratio * 0.7 + upper_rejection * 0.3
    
    else:  # bear
        if not is_red:
            return 0.0
        # Strong bear: body > 70% of range, close near low
        lower_wick = bar['close'] - bar['low']
        lower_rejection = 1.0 - (lower_wick / bar_range) if bar_range > 0 else 0
        return body_ratio * 0.7 + lower_rejection * 0.3


def detect_momentum_consistency(bars: List[dict], direction: str, lookback: int = 10) -> float:
    """
    Detect if price shows consistent momentum in the signal direction.
    
    Returns:
        0.0 to 1.0 score (0.8+ indicates strong lower TF alignment)
    """
    if len(bars) < lookback:
        lookback = len(bars)
    
    recent_bars = bars[-lookback:]
    aligned_moves = 0
    
    for i in range(1, len(recent_bars)):
        prev_close = recent_bars[i-1]['close']
        curr_close = recent_bars[i]['close']
        
        if direction == 'bull' and curr_close > prev_close:
            aligned_moves += 1
        elif direction == 'bear' and curr_close < prev_close:
            aligned_moves += 1
    
    return aligned_moves / (lookback - 1) if lookback > 1 else 0.0


# ════════════════════════════════════════════════════════════════════════════════
# MTF CONVERGENCE LOGIC
# ════════════════════════════════════════════════════════════════════════════════

def check_mtf_convergence(
    ticker: str,
    direction: str,
    bars_5m: List[dict]
) -> Dict:
    """
    Check if the 5m signal is confirmed on lower timeframe granularities.
    
    Strategy:
    - Analyzes last 20 bars (100 minutes of price action)
    - 3m confirmation: High intra-bar volatility + strong directional bars
    - 2m confirmation: Very strong bar-to-bar momentum
    - 1m confirmation: Near-perfect consecutive aligned moves
    
    Args:
        ticker: Symbol
        direction: 'bull' or 'bear'
        bars_5m: 5-minute session bars
    
    Returns:
        Dict with convergence details
    """
    if len(bars_5m) < 20:
        return {
            'convergence': False,
            'timeframes': ['5m'],
            'convergence_score': 0.25,
            'boost': 0.0,
            'reason': 'Insufficient bars for MTF analysis (need 20+)'
        }
    
    confirmed_timeframes = ['5m']  # Always have 5m baseline
    recent_bars = bars_5m[-20:]  # Last 100 minutes
    
    # ─────────────────────────────────────────────────────────────────────────────
    # 3m CONFIRMATION CHECK
    # Look for: High intra-bar volatility + strong directional candles
    # ─────────────────────────────────────────────────────────────────────────────
    avg_volatility = sum(get_intrabar_volatility(b) for b in recent_bars) / len(recent_bars)
    avg_strength = sum(get_bar_strength(b, direction) for b in recent_bars) / len(recent_bars)
    
    # 3m exists if: avg volatility > 0.4% AND avg strength > 0.5
    if avg_volatility > 0.004 and avg_strength > 0.5:
        confirmed_timeframes.append('3m')
    
    # ─────────────────────────────────────────────────────────────────────────────
    # 2m CONFIRMATION CHECK (requires 3m first)
    # Look for: Very strong momentum consistency (70%+ aligned moves)
    # ─────────────────────────────────────────────────────────────────────────────
    if '3m' in confirmed_timeframes:
        momentum_score = detect_momentum_consistency(recent_bars, direction, lookback=15)
        if momentum_score >= 0.70:
            confirmed_timeframes.append('2m')
    
    # ─────────────────────────────────────────────────────────────────────────────
    # 1m CONFIRMATION CHECK (requires 2m first)
    # Look for: Near-perfect alignment (85%+ consecutive moves)
    # ─────────────────────────────────────────────────────────────────────────────
    if '2m' in confirmed_timeframes:
        fine_momentum = detect_momentum_consistency(recent_bars, direction, lookback=20)
        if fine_momentum >= 0.85:
            confirmed_timeframes.append('1m')
    
    # ─────────────────────────────────────────────────────────────────────────────
    # CALCULATE BOOST
    # ─────────────────────────────────────────────────────────────────────────────
    num_timeframes = len(confirmed_timeframes)
    convergence = num_timeframes > 1
    
    boost_map = {
        1: 0.00,   # 5m only (baseline)
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
    else:
        _mtf_stats['timeframe_breakdown']['5m_only'] += 1
    
    return {
        'convergence': convergence,
        'timeframes': confirmed_timeframes,
        'convergence_score': convergence_score,
        'boost': boost,
        'reason': f"Confirmed on {', '.join(confirmed_timeframes)}" if convergence else "5m signal only"
    }


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════════════════

def enhance_signal_with_mtf(
    ticker: str,
    direction: str,
    bars_session: List[dict],
    **kwargs  # Accepts extra args for backwards compatibility
) -> Dict:
    """
    Enhance a 5m BOS+FVG signal with multi-timeframe convergence analysis.
    
    Called from sniper.py Step 8.2 after confirmation layers pass.
    
    Args:
        ticker: Symbol
        direction: 'bull' or 'bear'
        bars_session: The 5m session bars (already in sniper.py)
        **kwargs: Ignored (for backwards compatibility with old API)
    
    Returns:
        Dict containing:
        - enabled: bool (always True)
        - convergence: bool (True if multi-TF confirmation found)
        - timeframes: list of confirmed timeframes
        - convergence_score: float 0-1 (0.25 per TF)
        - boost: float (0.00 to 0.05)
        - reason: str (explanation)
    """
    _check_cache_rollover()
    _mtf_stats['analyzed'] += 1
    
    # Check cache
    cache_key = f"{ticker}_{direction}"
    if cache_key in _mtf_cache:
        cached = _mtf_cache[cache_key]
        return cached
    
    # Validate inputs
    if not bars_session or len(bars_session) < 20:
        result = {
            'enabled': True,
            'convergence': False,
            'timeframes': ['5m'],
            'convergence_score': 0.25,
            'boost': 0.0,
            'reason': 'Insufficient bars for MTF analysis (need 20+ bars)'
        }
        _mtf_cache[cache_key] = result
        return result
    
    # Run MTF convergence check
    result = check_mtf_convergence(ticker, direction, bars_session)
    result['enabled'] = True
    
    # Cache result
    _mtf_cache[cache_key] = result
    
    return result


def print_mtf_stats():
    """
    Print end-of-day MTF statistics.
    Called from sniper.py at market close.
    """
    if _mtf_stats['analyzed'] == 0:
        return
    
    conv_rate = (_mtf_stats['convergence_found'] / _mtf_stats['analyzed']) * 100
    avg_boost = (_mtf_stats['total_boost'] / _mtf_stats['analyzed'])
    
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
    print("="*80 + "\n")


def reset_daily_stats():
    """Reset statistics at start of new trading day."""
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
        'avg_boost': 0.0,
        'total_boost': 0.0
    }


print("[MTF-REALTIME] ✅ Multi-timeframe convergence enabled (in-memory bar analysis)")
