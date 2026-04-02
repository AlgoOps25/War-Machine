"""
Entry Timing Validator - Time-of-Day Win Rate Optimization

Validates signal entry timing based on historical performance data.
Filters signals during historically weak trading hours and enhances
confidence during golden hours.

Integration: Step 6.7 in signal pipeline (after confirmation passes)

PHASE 4.C-10 (Mar 19, 2026):
  - FIX: HOURLY_WIN_RATES was fabricated placeholder data — all rates were
    invented (0.58, 0.68, 0.71, etc.) with no real journal backing.
    All rates neutralized to 0.50 / sample_size=0 so MIN_SAMPLE_SIZE check
    fires immediately for every hour, returning True with no gating.

47.P4-2 (Apr 02, 2026):
  - Real backtested rates wired from 5-ticker walk-forward (55 trades, Apr 02 2026).
    Hours 10 (54% WR, n=26) and 15 (67% WR, n=12) now have live gating.
    Remaining hours have insufficient data (n<10) — kept at (0.50, 0).
    MIN_SAMPLE_SIZE lowered 20→10 to match update_hourly_win_rates.py floor.
    Re-run update_hourly_win_rates.py after each walk-forward batch to accumulate.
"""
"""
CFW6 Gate Validator — Signal Quality Pipeline

Six-gate hard-pass/fail validation pipeline for scanner.py signals.
Architecture: sequential gates with early exit on hard failures.
Distinct from SignalValidator (validation.py) which uses weighted
confidence adjustments — this is a lighter, faster pre-flight check.

Gates:
  1. Time-of-Day  — reject lunch chop + close danger zone
  2. Regime       — ADX trend check (bypassed if RVOL >= 3.0x)
  3. Volume       — RVOL floor per signal type
  4. Greeks       — IV rank / delta pre-check (only if greeks_available=True)
  5. ML Gate      — MLSignalScorerV2 win-probability adjustment (+/-15 pts)
  6. Min Conf     — Final 60% confidence floor

Usage:
    from app.validation.cfw6_gate_validator import validate_signal

    result = validate_signal(
        ticker="NVDA",
        signal_type="BOS",
        regime_filter=True,
        greeks_available=True,
        rvol=2.5,
        adx=28.0,
    )
    if result['passed']:
        send_alert(ticker)

Note on scanner.py integration:
    scanner.py imports this as `from app.validation import validate_signal`
    (routed via __init__.py re-export). The import is currently disabled
    with `validate_signal = None` in scanner.py — re-enable by removing
    that line once the CFW6 gate is ready for production use.

BUG-ML-4 (Apr 02 2026):
    get_validation_stats() was a permanent zeroed stub. Now delegates to
    signal_analytics.get_funnel_stats() — the live source of truth for
    gate pass/fail counts already maintained by the scanner pipeline.
"""
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# RVOL threshold above which ADX regime check is bypassed.
# High relative volume IS the trend signal — ADX is lagging, especially early session.
RVOL_REGIME_BYPASS = 3.0


def validate_signal(
    ticker: str,
    signal_type: str,
    regime_filter: bool = True,
    greeks_available: bool = False,
    confidence: float = 70.0,
    rvol: float = 1.0,
    adx: float = None,
    price: float = None,
    ema_stack_aligned: bool = None,
    signal: dict = None,
) -> dict:
    """
    Comprehensive signal validation using CFW6 framework.

    Args:
        ticker:            Stock symbol
        signal_type:       Type of signal (BOS, FVG, OR_BREAKOUT)
        regime_filter:     Whether regime filter is enabled
        greeks_available:  Whether options Greeks data is available
        confidence:        Base confidence score (0-100)
        rvol:              Relative volume (1.0 = average, 2.0 = 2x average)
        adx:               ADX indicator value (trend strength)
        price:             Current price (reserved for future price-based filters)
        ema_stack_aligned: Legacy param, kept for back-compat (unused internally)
        signal:            Full signal dict passed to ML gate (optional)

    Returns:
        dict: {
            'passed':               bool,
            'reason':               str,
            'filters_passed':       list[str],
            'filters_failed':       list[str],
            'adjusted_confidence':  float,
            'ml_adjustment':        float,
        }
    """
    filters_passed = []
    filters_failed = []
    adjusted_confidence = confidence
    ml_adjustment = 0.0

    # ══════════════════════════════════════════════════════════════════════
    # GATE 1: TIME-OF-DAY QUALITY FILTER
    # ══════════════════════════════════════════════════════════════════════
    time_check = _check_time_of_day()
    if not time_check['passed']:
        return {
            'passed': False,
            'reason': time_check['reason'],
            'filters_passed': filters_passed,
            'filters_failed': ['time_of_day'],
            'adjusted_confidence': confidence,
            'ml_adjustment': 0.0,
        }
    filters_passed.append('time_of_day')
    adjusted_confidence += time_check.get('confidence_boost', 0)

    # ══════════════════════════════════════════════════════════════════════
    # GATE 2: REGIME FILTER (TRENDING VS CHOPPY MARKET)
    # High RVOL (>= 3x) bypasses ADX check — volume IS the trend signal
    # pre-ADX. ADX lags by 14 bars; explosive movers don't wait for it.
    # ══════════════════════════════════════════════════════════════════════
    if regime_filter:
        if rvol >= RVOL_REGIME_BYPASS:
            logger.info(
                f"[CFW6] {ticker} RVOL={rvol:.1f}x >= {RVOL_REGIME_BYPASS}x "
                f"— regime ADX bypass active"
            )
            filters_passed.append(f'regime_bypass(RVOL={rvol:.1f}x)')
            adjusted_confidence += 3
        else:
            regime_check = _check_regime(adx=adx)
            if not regime_check['passed']:
                return {
                    'passed': False,
                    'reason': regime_check['reason'],
                    'filters_passed': filters_passed,
                    'filters_failed': ['regime_filter'],
                    'adjusted_confidence': adjusted_confidence,
                    'ml_adjustment': 0.0,
                }
            filters_passed.append('regime_filter')
            adjusted_confidence += regime_check.get('confidence_boost', 0)

    # ══════════════════════════════════════════════════════════════════════
    # GATE 3: VOLUME CONFIRMATION
    # Soft gate — low volume penalizes confidence but does not hard-reject.
    # ══════════════════════════════════════════════════════════════════════
    volume_check = _check_volume(rvol=rvol, signal_type=signal_type)
    if not volume_check['passed']:
        filters_failed.append('volume')
        adjusted_confidence -= 5
    else:
        filters_passed.append('volume')
        adjusted_confidence += volume_check.get('confidence_boost', 0)

    # ══════════════════════════════════════════════════════════════════════
    # GATE 4: GREEKS PRECHECKS (ONLY IF greeks_available=True)
    # Routes through app.options.get_greeks() — IV rank pre-filter.
    # Soft gate — unfavorable Greeks penalize confidence, don't hard-reject.
    # ══════════════════════════════════════════════════════════════════════
    if greeks_available:
        greeks_check = _check_greeks(ticker=ticker)
        if not greeks_check['passed']:
            filters_failed.append('greeks')
            adjusted_confidence -= 10
            logger.warning(f"[CFW6] {ticker} Greeks unfavorable: {greeks_check['reason']}")
        else:
            filters_passed.append('greeks')
            adjusted_confidence += greeks_check.get('confidence_boost', 0)

    # ══════════════════════════════════════════════════════════════════════
    # GATE 5: ML CONFIDENCE ADJUSTMENT
    # MLSignalScorerV2 win-probability gate. Safe: scorer.is_ready=False
    # → zero adjustment, gate always passes. Cap: +/-15 pts.
    # ml_adjustment exposed in result dict for Discord alert display.
    # ══════════════════════════════════════════════════════════════════════
    ml_source = 'none'
    try:
        from app.ml.ml_signal_scorer_v2 import MLSignalScorerV2
        scorer = MLSignalScorerV2()
        if scorer.is_ready if hasattr(scorer, 'is_ready') else scorer.trained:
            _signal_for_ml = signal or {
                'confidence': adjusted_confidence / 100.0,
                'rvol': rvol,
                'adx': adx or 20.0,
            }
            ml_prob = scorer.score_signal(_signal_for_ml)
            if ml_prob >= 0:  # -1.0 sentinel means model unavailable
                ml_adjustment = round((ml_prob - 0.50) * 30.0, 1)
                ml_adjustment = max(-15.0, min(15.0, ml_adjustment))
                ml_source = getattr(scorer, 'model_version', 'v2') or 'v2'
                logger.info(
                    f"[CFW6] Gate 5 ML: {ticker} prob={ml_prob:.3f} "
                    f"adjustment={ml_adjustment:+.1f}pts source={ml_source}"
                )
    except Exception as exc:
        logger.warning(f"[CFW6] Gate 5 ML skipped ({exc})")

    adjusted_confidence = max(0.0, min(100.0, adjusted_confidence + ml_adjustment))
    if ml_adjustment != 0.0:
        emoji = '📈' if ml_adjustment > 0 else '📉'
        filters_passed.append(f'ml_adjustment({ml_adjustment:+.1f}pts {emoji})')

    # ══════════════════════════════════════════════════════════════════════
    # GATE 6: MINIMUM CONFIDENCE THRESHOLD
    # ══════════════════════════════════════════════════════════════════════
    MIN_CONFIDENCE = 60.0
    if adjusted_confidence < MIN_CONFIDENCE:
        return {
            'passed': False,
            'reason': f"Confidence too low ({adjusted_confidence:.1f}% < {MIN_CONFIDENCE}%)",
            'filters_passed': filters_passed,
            'filters_failed': filters_failed,
            'adjusted_confidence': adjusted_confidence,
            'ml_adjustment': ml_adjustment,
        }

    return {
        'passed': True,
        'reason': 'All CFW6 gates passed',
        'filters_passed': filters_passed,
        'filters_failed': filters_failed,
        'adjusted_confidence': min(adjusted_confidence, 100.0),
        'ml_adjustment': ml_adjustment,
    }


def _check_time_of_day() -> dict:
    """
    Reject signals during known low-probability windows.

    Hard REJECT:
      11:30 AM – 1:00 PM ET  — lunch chop
      3:50 PM  – 4:00 PM ET  — close danger zone / reversal risk

    Confidence boost:
      +5 pts: 9:30–11:00 AM ET (morning prime)
      +3 pts: 2:00–3:30 PM ET  (afternoon push)
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    current_time = now_et.time()

    if dtime(11, 30) <= current_time < dtime(13, 0):
        return {'passed': False, 'reason': 'Lunch chop period (11:30 AM–1:00 PM ET)'}

    if dtime(15, 50) <= current_time < dtime(16, 0):
        return {'passed': False, 'reason': 'Close danger zone (3:50–4:00 PM ET) — reversal risk'}

    if dtime(9, 30) <= current_time < dtime(11, 0):
        return {'passed': True, 'confidence_boost': 5, 'reason': 'Morning prime (9:30–11:00 AM ET)'}

    if dtime(14, 0) <= current_time < dtime(15, 30):
        return {'passed': True, 'confidence_boost': 3, 'reason': 'Afternoon push (2:00–3:30 PM ET)'}

    return {'passed': True, 'confidence_boost': 0, 'reason': 'Standard market hours'}


def _check_regime(adx: float = None) -> dict:
    """
    Check for trending market conditions using ADX.

    Called ONLY when RVOL < RVOL_REGIME_BYPASS (3.0x).
    High RVOL callers skip this gate entirely in validate_signal().

    ADX thresholds:
      < 20  → REJECT  (choppy/ranging)
      20-25 → PASS    (no boost)
      25-30 → PASS    (+3 pts)
      > 30  → PASS    (+5 pts)
    """
    if adx is None:
        return {'passed': True, 'confidence_boost': 0, 'reason': 'Regime passed (no ADX data)'}

    if adx < 20:
        return {'passed': False, 'reason': f'ADX too low ({adx:.1f} < 20) — choppy/ranging market'}
    elif adx > 30:
        return {'passed': True, 'confidence_boost': 5, 'reason': f'Strong trend (ADX={adx:.1f})'}
    elif adx > 25:
        return {'passed': True, 'confidence_boost': 3, 'reason': f'Moderate trend (ADX={adx:.1f})'}
    else:
        return {'passed': True, 'confidence_boost': 0, 'reason': f'Weak trend (ADX={adx:.1f})'}


def _check_volume(rvol: float, signal_type: str) -> dict:
    """
    Check if volume supports the signal type.

    RVOL floors by signal type:
      OR_BREAKOUT → 2.0x  (strong spike required)
      BOS / FVG   → 1.5x  (moderate volume required)

    Confidence boosts:
      RVOL >= 4.0x → +5 pts (explosive)
      RVOL >= 3.0x → +3 pts (strong)
    """
    min_rvol = 2.0 if signal_type == 'OR_BREAKOUT' else 1.5

    if rvol < min_rvol:
        return {'passed': False, 'reason': f'Volume too low (RVOL={rvol:.1f}x < {min_rvol}x)'}

    if rvol >= 4.0:
        return {'passed': True, 'confidence_boost': 5, 'reason': f'Explosive volume (RVOL={rvol:.1f}x)'}
    elif rvol >= 3.0:
        return {'passed': True, 'confidence_boost': 3, 'reason': f'Strong volume (RVOL={rvol:.1f}x)'}
    else:
        return {'passed': True, 'confidence_boost': 0, 'reason': f'Adequate volume (RVOL={rvol:.1f}x)'}


def _check_greeks(ticker: str) -> dict:
    """
    IV rank pre-check via app.options.get_greeks().

    Called only when greeks_available=True is passed to validate_signal().
    Soft gate: failure penalizes confidence (-10 pts) but does not hard-reject.

    IV rank thresholds:
      < 20  → unfavorable (options expensive relative to history)
      20-60 → moderate    (no boost)
      > 60  → favorable   (+5 pts)
    """
    try:
        from app.options import get_greeks
        greeks = get_greeks(ticker)

        if greeks is None:
            return {'passed': True, 'confidence_boost': 0, 'reason': 'Greeks data unavailable'}

        iv_rank = greeks.get('iv_rank', 50)

        if iv_rank < 20:
            return {'passed': False, 'reason': f'IV rank too low ({iv_rank}% < 20%)'}
        elif iv_rank > 60:
            return {'passed': True, 'confidence_boost': 5, 'reason': f'High IV rank ({iv_rank}%)'}
        else:
            return {'passed': True, 'confidence_boost': 0, 'reason': f'Moderate IV rank ({iv_rank}%)'}

    except ImportError:
        return {'passed': True, 'confidence_boost': 0, 'reason': 'Options module not available'}


def get_validation_stats() -> dict:
    """
    Returns live gate pass/fail counts from signal_analytics.get_funnel_stats().

    BUG-ML-4 (Apr 02 2026): was a permanent zeroed stub — wired to the
    existing signal_analytics funnel tracker which is already maintained
    by the scanner pipeline on every signal evaluation.

    Falls back to zeroed counters if signal_analytics is unavailable
    (e.g. during unit tests or import before scanner init).
    """
    try:
        from app.signals.signal_analytics import get_funnel_stats
        funnel = get_funnel_stats()
        return {
            'total_signals':   funnel.get('total_signals', 0),
            'passed':          funnel.get('passed', 0),
            'rejected':        funnel.get('rejected', 0),
            'rejection_reasons': funnel.get('rejection_reasons', {}),
        }
    except Exception as exc:
        logger.warning(f"[CFW6] get_validation_stats fallback — signal_analytics unavailable: {exc}")
        return {'total_signals': 0, 'passed': 0, 'rejected': 0, 'rejection_reasons': {}}
