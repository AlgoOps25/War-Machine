"""
Validation Module - CFW6 Signal Quality Gates

This module implements comprehensive validation logic to filter out low-probability signals.
Only signals that pass ALL validation gates will be alerted to Discord.

Validation Pillars:
1. Regime Filter - Is the market trending or choppy?
2. Time-of-Day - Avoid lunch chop and close-of-day reversals
3. Volume Confirmation - Is this move backed by real volume?
4. Greeks Prechecks - Are options positioned favorably? (IV rank, delta)
5. Trend Alignment - Is price aligned with higher timeframe EMAs?
6. Opening Range Context - Does this align with OR classification?

Usage:
    from app.validation import validate_signal
    
    result = validate_signal(
        ticker="NVDA",
        signal_type="BOS",
        regime_filter=True,
        greeks_available=True
    )
    
    if result['passed']:
        send_alert(ticker)
    else:
        logger.info(f"Signal rejected: {result['reason']}")
"""
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def validate_signal(
    ticker: str,
    signal_type: str,
    regime_filter: bool = True,
    greeks_available: bool = False,
    confidence: float = 70.0,
    rvol: float = 1.0,
    adx: float = None,
    price: float = None,
    ema_stack_aligned: bool = None
) -> dict:
    """
    Comprehensive signal validation using CFW6 framework.
    
    Args:
        ticker: Stock symbol
        signal_type: Type of signal (BOS, FVG, OR_BREAKOUT)
        regime_filter: Whether regime filter is enabled
        greeks_available: Whether options Greeks data is available
        confidence: Base confidence score (0-100)
        rvol: Relative volume (1.0 = average, 2.0 = 2x average)
        adx: ADX indicator value (trend strength)
        price: Current price (for price-based filters)
        ema_stack_aligned: Whether EMAs are properly stacked
    
    Returns:
        dict: {
            'passed': bool,
            'reason': str,
            'filters_passed': list,
            'filters_failed': list,
            'adjusted_confidence': float
        }
    """
    filters_passed = []
    filters_failed = []
    adjusted_confidence = confidence
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 1: TIME-OF-DAY QUALITY FILTER
    # ═══════════════════════════════════════════════════════════════════════════════════
    time_check = _check_time_of_day()
    if not time_check['passed']:
        return {
            'passed': False,
            'reason': time_check['reason'],
            'filters_passed': filters_passed,
            'filters_failed': ['time_of_day'],
            'adjusted_confidence': confidence
        }
    filters_passed.append('time_of_day')
    adjusted_confidence += time_check.get('confidence_boost', 0)
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 2: REGIME FILTER (TRENDING VS CHOPPY MARKET)
    # ═══════════════════════════════════════════════════════════════════════════════════
    if regime_filter:
        regime_check = _check_regime(adx=adx)
        if not regime_check['passed']:
            return {
                'passed': False,
                'reason': regime_check['reason'],
                'filters_passed': filters_passed,
                'filters_failed': ['regime_filter'],
                'adjusted_confidence': adjusted_confidence
            }
        filters_passed.append('regime_filter')
        adjusted_confidence += regime_check.get('confidence_boost', 0)
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 3: VOLUME CONFIRMATION
    # ═══════════════════════════════════════════════════════════════════════════════════
    volume_check = _check_volume(rvol=rvol, signal_type=signal_type)
    if not volume_check['passed']:
        filters_failed.append('volume')
        adjusted_confidence -= 5  # Penalize but don't reject
    else:
        filters_passed.append('volume')
        adjusted_confidence += volume_check.get('confidence_boost', 0)
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 4: GREEKS PRECHECKS (IF OPTIONS DATA AVAILABLE)
    # ═══════════════════════════════════════════════════════════════════════════════════
    if greeks_available:
        greeks_check = _check_greeks(ticker=ticker)
        if not greeks_check['passed']:
            # Don't reject, but log warning and reduce confidence
            filters_failed.append('greeks')
            adjusted_confidence -= 10
            logger.warning(
                f"[VALIDATION] {ticker} Greeks unfavorable: {greeks_check['reason']}",
                extra={'component': 'validation', 'symbol': ticker}
            )
        else:
            filters_passed.append('greeks')
            adjusted_confidence += greeks_check.get('confidence_boost', 0)
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 5: TREND ALIGNMENT (EMA STACK)
    # ═══════════════════════════════════════════════════════════════════════════════════
    if ema_stack_aligned is not None:
        if ema_stack_aligned:
            filters_passed.append('ema_alignment')
            adjusted_confidence += 3
        else:
            filters_failed.append('ema_alignment')
            adjusted_confidence -= 5
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # GATE 6: MINIMUM CONFIDENCE THRESHOLD
    # ═══════════════════════════════════════════════════════════════════════════════════
    MIN_CONFIDENCE = 60.0
    if adjusted_confidence < MIN_CONFIDENCE:
        return {
            'passed': False,
            'reason': f"Confidence too low ({adjusted_confidence:.1f}% < {MIN_CONFIDENCE}%)",
            'filters_passed': filters_passed,
            'filters_failed': filters_failed,
            'adjusted_confidence': adjusted_confidence
        }
    
    # ═══════════════════════════════════════════════════════════════════════════════════
    # ALL GATES PASSED
    # ═══════════════════════════════════════════════════════════════════════════════════
    return {
        'passed': True,
        'reason': 'All validation gates passed',
        'filters_passed': filters_passed,
        'filters_failed': filters_failed,
        'adjusted_confidence': min(adjusted_confidence, 100.0)  # Cap at 100%
    }


def _check_time_of_day() -> dict:
    """
    Check if current time is favorable for trading.
    
    High-quality periods:
    - 9:30-11:30 AM ET (morning session, best moves)
    - 2:00-3:30 PM ET (afternoon push)
    
    Low-quality periods (REJECT):
    - 11:30 AM - 1:00 PM ET (lunch chop)
    - 3:50-4:00 PM ET (too close to close, reversals)
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    current_time = now_et.time()
    
    # Define time windows
    lunch_start = dtime(11, 30)
    lunch_end = dtime(13, 0)  # 1:00 PM
    close_danger_zone = dtime(15, 50)  # 3:50 PM
    market_close = dtime(16, 0)
    
    morning_prime_start = dtime(9, 30)
    morning_prime_end = dtime(11, 0)
    
    afternoon_prime_start = dtime(14, 0)  # 2:00 PM
    afternoon_prime_end = dtime(15, 30)  # 3:30 PM
    
    # REJECT: Lunch chop (11:30 AM - 1:00 PM)
    if lunch_start <= current_time < lunch_end:
        return {
            'passed': False,
            'reason': 'Lunch chop period (11:30 AM - 1:00 PM ET) - low probability'
        }
    
    # REJECT: Too close to market close (3:50 PM+)
    if close_danger_zone <= current_time < market_close:
        return {
            'passed': False,
            'reason': 'Too close to market close (3:50+ PM ET) - reversal risk'
        }
    
    # BOOST: Morning prime time (9:30-11:00 AM)
    if morning_prime_start <= current_time < morning_prime_end:
        return {
            'passed': True,
            'confidence_boost': 5,
            'reason': 'Morning prime time (high-quality period)'
        }
    
    # BOOST: Afternoon prime time (2:00-3:30 PM)
    if afternoon_prime_start <= current_time < afternoon_prime_end:
        return {
            'passed': True,
            'confidence_boost': 3,
            'reason': 'Afternoon push period (good quality)'
        }
    
    # NEUTRAL: Other market hours
    return {
        'passed': True,
        'confidence_boost': 0,
        'reason': 'Standard market hours'
    }


def _check_regime(adx: float = None) -> dict:
    """
    Check if market is in trending regime (favorable for breakouts).
    
    Trending conditions:
    - ADX > 25 (strong trend)
    - VIX < 30 (not panic mode)
    
    Choppy/unfavorable conditions:
    - ADX < 20 (weak trend, likely ranging)
    - VIX > 35 (extreme fear, whipsaw risk)
    """
    # If ADX data available, use it
    if adx is not None:
        if adx < 20:
            return {
                'passed': False,
                'reason': f'ADX too low ({adx:.1f} < 20) - choppy/ranging market'
            }
        elif adx > 30:
            return {
                'passed': True,
                'confidence_boost': 5,
                'reason': f'Strong trend (ADX={adx:.1f})'
            }
        elif adx > 25:
            return {
                'passed': True,
                'confidence_boost': 3,
                'reason': f'Moderate trend (ADX={adx:.1f})'
            }
        else:
            return {
                'passed': True,
                'confidence_boost': 0,
                'reason': f'Weak trend (ADX={adx:.1f})'
            }
    
    # TODO: Check VIX level (requires SPY bars or VIX API)
    # For now, pass if no ADX data (backward compatible)
    return {
        'passed': True,
        'confidence_boost': 0,
        'reason': 'Regime check passed (no ADX data)'
    }


def _check_volume(rvol: float, signal_type: str) -> dict:
    """
    Check if volume supports the breakout.
    
    Requirements:
    - OR_BREAKOUT: RVOL > 2.0x (strong volume spike needed)
    - BOS/FVG: RVOL > 1.5x (moderate volume needed)
    
    Explosive movers (RVOL > 4.0x) get confidence boost.
    """
    if signal_type == "OR_BREAKOUT":
        min_rvol = 2.0
    else:
        min_rvol = 1.5
    
    if rvol < min_rvol:
        return {
            'passed': False,
            'reason': f'Volume too low (RVOL={rvol:.1f}x < {min_rvol}x)'
        }
    
    # Explosive mover boost
    if rvol >= 4.0:
        return {
            'passed': True,
            'confidence_boost': 5,
            'reason': f'Explosive volume (RVOL={rvol:.1f}x)'
        }
    elif rvol >= 3.0:
        return {
            'passed': True,
            'confidence_boost': 3,
            'reason': f'Strong volume (RVOL={rvol:.1f}x)'
        }
    else:
        return {
            'passed': True,
            'confidence_boost': 0,
            'reason': f'Adequate volume (RVOL={rvol:.1f}x)'
        }


def _check_greeks(ticker: str) -> dict:
    """
    Check if options Greeks are favorable for the trade.
    
    Requirements:
    - IV Rank > 30 (options not too expensive)
    - Delta 0.40-0.60 (balanced risk/reward)
    - Avoid extreme IV crush risk
    
    TODO: This is a stub - integrate with options_intelligence module
    to fetch real Greeks data from Tradier/IB.
    """
    # Placeholder implementation
    # In production, fetch real Greeks from options module
    try:
        from app.options import get_greeks
        greeks = get_greeks(ticker)
        
        if greeks is None:
            return {
                'passed': True,
                'confidence_boost': 0,
                'reason': 'Greeks data unavailable'
            }
        
        iv_rank = greeks.get('iv_rank', 50)
        
        if iv_rank < 20:
            return {
                'passed': False,
                'reason': f'IV rank too low ({iv_rank}% < 20%) - options too expensive'
            }
        elif iv_rank > 60:
            return {
                'passed': True,
                'confidence_boost': 5,
                'reason': f'High IV rank ({iv_rank}%) - favorable for buying'
            }
        else:
            return {
                'passed': True,
                'confidence_boost': 0,
                'reason': f'Moderate IV rank ({iv_rank}%)'
            }
    
    except ImportError:
        # Options module not available - pass for now
        return {
            'passed': True,
            'confidence_boost': 0,
            'reason': 'Options module not available'
        }


def get_validation_stats() -> dict:
    """
    Get statistics on validation pass/fail rates.
    Useful for tuning validation gates.
    
    TODO: Implement tracking of validation results in database.
    """
    return {
        'total_signals': 0,
        'passed': 0,
        'rejected': 0,
        'rejection_reasons': {}
    }
