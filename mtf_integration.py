"""
MTF Integration Module - Sniper Enhancement

Provides multi-timeframe convergence detection and confidence boosting
for CFW6 signals in sniper.py.

Integration Points:
  - Called after confirmation grading (Step 8)
  - Adds MTF boost to confidence calculation (Step 11)
  - Enriches signal metadata for tracking

Design Principles:
  - Non-breaking: gracefully handles MTF system unavailability
  - Performance: caches MTF data per ticker, cleared daily
  - Transparent: logs all MTF decisions for debugging
  - Testable: supports both live and testing modes

Usage:
  from mtf_integration import enhance_signal_with_mtf
  
  # In sniper.py _run_signal_pipeline(), after Step 8:
  mtf_result = enhance_signal_with_mtf(
      ticker=ticker,
      direction=direction,
      bars_session=bars_session
  )
  
  # Apply boost in Step 11 confidence calculation:
  mtf_boost = mtf_result.get('boost', 0.0)
  final_confidence = base_confidence + ... + mtf_boost
  
  # Attach metadata to signal for tracking:
  signal_metadata['mtf'] = mtf_result
"""

from typing import Dict, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Global state
_mtf_enabled = False
_mtf_cache = {}  # {ticker: mtf_result}
_cache_date = None

# Try to import MTF system
try:
    from mtf_data_manager import mtf_data_manager
    from mtf_fvg_engine import mtf_fvg_engine
    _mtf_enabled = True
    print("[MTF-INT] ✅ Multi-timeframe enhancement enabled")
except ImportError as e:
    print(f"[MTF-INT] ⚠️  MTF system not available: {e}")
    print("[MTF-INT] Sniper will run without MTF boost (single-timeframe mode)")


def _check_cache_rollover():
    """
    Clear MTF cache on new trading day.
    """
    global _cache_date, _mtf_cache
    
    today = datetime.now(ET).date()
    if _cache_date != today:
        _mtf_cache.clear()
        _cache_date = today
        if _mtf_cache:
            print(f"[MTF-INT] 🔄 Cache cleared for new session: {today}")


def is_mtf_enabled() -> bool:
    """
    Check if MTF system is available and enabled.
    
    Returns:
        bool: True if MTF can be used
    """
    return _mtf_enabled


def enhance_signal_with_mtf(
    ticker: str,
    direction: str,
    bars_session: List[dict],
    force_refresh: bool = False
) -> Dict:
    """
    Enhance a CFW6 signal with multi-timeframe convergence analysis.
    
    Called after confirmation grading (Step 8 in sniper.py) to determine
    if the signal has MTF convergence support across 5m + 3m timeframes.
    
    Args:
        ticker: Stock symbol
        direction: 'bull' or 'bear'
        bars_session: Today's 1m/5m bars from sniper
        force_refresh: Bypass cache (default: False)
    
    Returns:
        Dict with MTF analysis:
        {
            'enabled': bool,              # MTF system available
            'convergence': bool,          # MTF signal detected
            'boost': float,               # Confidence boost (0.00-0.10)
            'convergence_score': float,   # 0.0-1.0 (if convergence=True)
            'timeframes': List[str],      # ['5m', '3m'] (if convergence=True)
            'zone_low': float,            # MTF zone low (if convergence=True)
            'zone_high': float,           # MTF zone high (if convergence=True)
            'primary_timeframe': str,     # '5m' (if convergence=True)
            'reason': str                 # Explanation
        }
    """
    # Check cache rollover
    _check_cache_rollover()
    
    # Default result (MTF disabled or no convergence)
    default_result = {
        'enabled': _mtf_enabled,
        'convergence': False,
        'boost': 0.0,
        'convergence_score': 0.0,
        'timeframes': [],
        'zone_low': 0.0,
        'zone_high': 0.0,
        'primary_timeframe': '5m',
        'reason': 'MTF system disabled' if not _mtf_enabled else 'No MTF convergence'
    }
    
    # If MTF system not available, return default
    if not _mtf_enabled:
        return default_result
    
    # Check cache (unless force_refresh)
    if not force_refresh and ticker in _mtf_cache:
        cached = _mtf_cache[ticker]
        print(f"[MTF-INT] {ticker} - Using cached MTF result (boost: +{cached['boost']:.2%})")
        return cached
    
    try:
        # Get MTF data (5m + 3m)
        # During live trading: uses today's bars
        # During testing/after-hours: falls back to latest available
        bars_dict = mtf_data_manager.get_all_timeframes(ticker)
        
        # If no today's data, try testing mode (latest available)
        if not bars_dict:
            print(f"[MTF-INT] {ticker} - No today's data, trying latest available...")
            bars_dict = mtf_data_manager.get_latest_available_bars(ticker)
        
        # If still no data, return default
        if not bars_dict:
            result = default_result.copy()
            result['reason'] = 'No MTF data available'
            _mtf_cache[ticker] = result
            return result
        
        # Detect MTF convergence
        mtf_signal = mtf_fvg_engine.detect_mtf_signal(ticker, bars_dict)
        
        # No MTF convergence detected
        if not mtf_signal:
            result = default_result.copy()
            result['reason'] = f"MTF analyzed ({', '.join(bars_dict.keys())} available) but no convergence"
            _mtf_cache[ticker] = result
            print(f"[MTF-INT] {ticker} - No MTF convergence detected")
            return result
        
        # Check direction alignment
        if mtf_signal['direction'] != direction:
            result = default_result.copy()
            result['reason'] = (
                f"MTF convergence detected but direction mismatch: "
                f"CFW6={direction}, MTF={mtf_signal['direction']}"
            )
            _mtf_cache[ticker] = result
            print(f"[MTF-INT] {ticker} - Direction mismatch: CFW6={direction} vs MTF={mtf_signal['direction']}")
            return result
        
        # MTF convergence confirmed!
        convergence_score = mtf_signal['convergence_score']
        boost = mtf_fvg_engine.get_mtf_boost_value(convergence_score)
        
        result = {
            'enabled': True,
            'convergence': True,
            'boost': boost,
            'convergence_score': convergence_score,
            'timeframes': mtf_signal['timeframes_aligned'],
            'zone_low': mtf_signal['zone_low'],
            'zone_high': mtf_signal['zone_high'],
            'primary_timeframe': mtf_signal.get('primary_timeframe', '5m'),
            'reason': (
                f"MTF convergence: {convergence_score:.1%} across "
                f"{', '.join(mtf_signal['timeframes_aligned'])}"
            )
        }
        
        # Cache result
        _mtf_cache[ticker] = result
        
        # Log success
        print(
            f"[MTF-INT] ✅ {ticker} MTF {direction.upper()} convergence detected | "
            f"Score: {convergence_score:.1%} | "
            f"Boost: +{boost:.2%} | "
            f"TFs: {', '.join(result['timeframes'])}"
        )
        
        return result
    
    except Exception as e:
        # MTF system error - gracefully degrade
        print(f"[MTF-INT] Error analyzing {ticker}: {e}")
        import traceback
        traceback.print_exc()
        
        result = default_result.copy()
        result['reason'] = f"MTF error: {str(e)}"
        return result


def get_mtf_cache_stats() -> Dict:
    """
    Get MTF cache statistics for monitoring.
    
    Returns:
        Dict with cache metrics:
        {
            'enabled': bool,
            'cache_date': str,
            'cached_tickers': int,
            'convergence_count': int,
            'average_boost': float
        }
    """
    if not _mtf_enabled:
        return {
            'enabled': False,
            'cache_date': None,
            'cached_tickers': 0,
            'convergence_count': 0,
            'average_boost': 0.0
        }
    
    convergent_results = [r for r in _mtf_cache.values() if r.get('convergence', False)]
    
    return {
        'enabled': True,
        'cache_date': str(_cache_date) if _cache_date else None,
        'cached_tickers': len(_mtf_cache),
        'convergence_count': len(convergent_results),
        'average_boost': (
            sum(r['boost'] for r in convergent_results) / len(convergent_results)
            if convergent_results else 0.0
        )
    }


def clear_mtf_cache():
    """
    Manually clear MTF cache (useful for testing or EOD cleanup).
    """
    global _mtf_cache
    _mtf_cache.clear()
    print("[MTF-INT] Cache manually cleared")


def print_mtf_stats():
    """
    Print MTF statistics for end-of-day reporting.
    """
    if not _mtf_enabled:
        return
    
    stats = get_mtf_cache_stats()
    
    if stats['cached_tickers'] == 0:
        return
    
    convergence_pct = (
        (stats['convergence_count'] / stats['cached_tickers'] * 100)
        if stats['cached_tickers'] > 0 else 0
    )
    
    print("\n" + "="*80)
    print("MTF INTEGRATION - DAILY STATISTICS")
    print("="*80)
    print(f"Session Date:         {stats['cache_date']}")
    print(f"Tickers Analyzed:     {stats['cached_tickers']}")
    print(f"MTF Convergence:      {stats['convergence_count']} ({convergence_pct:.1f}%)")
    if stats['convergence_count'] > 0:
        print(f"Average Boost:        +{stats['average_boost']:.2%}")
    print("="*80 + "\n")


# ════════════════════════════════════════════════════════════════════════════════
# TESTING / CLI USAGE
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python mtf_integration.py <ticker> <direction>")
        print("Example: python mtf_integration.py SPY bull")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    direction = sys.argv[2].lower()
    
    if direction not in ['bull', 'bear']:
        print("Direction must be 'bull' or 'bear'")
        sys.exit(1)
    
    print(f"\nTesting MTF integration for {ticker} {direction.upper()} signal\n")
    
    # Test with empty bars_session (not used in current implementation)
    result = enhance_signal_with_mtf(
        ticker=ticker,
        direction=direction,
        bars_session=[]
    )
    
    print("\n" + "="*80)
    print("MTF INTEGRATION TEST RESULT")
    print("="*80)
    print(f"Enabled:              {result['enabled']}")
    print(f"Convergence:          {result['convergence']}")
    print(f"Boost:                +{result['boost']:.2%}")
    if result['convergence']:
        print(f"Convergence Score:    {result['convergence_score']:.1%}")
        print(f"Timeframes:           {', '.join(result['timeframes'])}")
        print(f"Zone:                 ${result['zone_low']:.2f} - ${result['zone_high']:.2f}")
    print(f"Reason:               {result['reason']}")
    print("="*80 + "\n")
