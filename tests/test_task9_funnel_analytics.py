"""
test_task9_funnel_analytics.py — Funnel Analytics + A/B Testing

CI-safe:
  - test_funnel_analytics_importable  — checks app.analytics imports cleanly
  - test_funnel_tracker_basic_ops     — log_screened / log_bos / etc. work
  - test_funnel_conversion_calcs      — get_stage_conversion returns expected shape
  - test_funnel_rejection_tracking    — get_rejection_reasons returns list
  - test_ab_variant_assignment        — variant assignment is deterministic
  - test_ab_outcome_recording         — record_outcome runs without error
  - test_ab_stats                     — get_variant_stats returns A/B keys
  - test_full_reports                 — get_daily_report + get_ab_test_report run

All of the above are CI-safe: they require only app.analytics (no live DB/API).
"""
import pytest

try:
    from app.analytics import (
        funnel_tracker,
        ab_test,
        log_screened,
        log_bos,
        log_fvg,
        log_validator,
        log_armed,
        log_fired,
        log_filled,
    )
    _ANALYTICS_AVAILABLE = True
except ImportError as _analytics_err:
    _ANALYTICS_AVAILABLE = False
    _ANALYTICS_ERR_MSG   = str(_analytics_err)
    funnel_tracker = ab_test = None
    log_screened = log_bos = log_fvg = log_validator = None
    log_armed = log_fired = log_filled = None

needs_analytics = pytest.mark.skipif(
    not _ANALYTICS_AVAILABLE,
    reason=f"app.analytics import failed: {_analytics_err if not _ANALYTICS_AVAILABLE else ''}"
)


def test_funnel_analytics_importable():
    """app.analytics must expose funnel_tracker, ab_test, and log_* helpers."""
    assert _ANALYTICS_AVAILABLE, (
        f"app.analytics failed to import required names. "
        f"Check app/analytics/__init__.py exports funnel_tracker and ab_test. "
        f"Error: {_analytics_err if not _ANALYTICS_AVAILABLE else 'none'}"
    )


@needs_analytics
def test_funnel_tracker_basic_ops():
    """Convenience log helpers execute without raising."""
    log_screened('TEST1', passed=True)
    log_bos('TEST1',      passed=True)
    log_fvg('TEST1',      passed=True,  confidence=0.75)
    log_validator('TEST1', passed=False, reason='low_volume')

    log_screened('TEST2', passed=True)
    log_bos('TEST2',      passed=True)
    log_fvg('TEST2',      passed=False,  reason='vix_too_high')

    log_screened('TEST3', passed=True)
    log_bos('TEST3',      passed=True)
    log_fvg('TEST3',      passed=True,  confidence=0.82)
    log_validator('TEST3', passed=True,  confidence=0.85)
    log_armed('TEST3',    confidence=0.88)
    log_fired('TEST3',    confidence=0.90)
    log_filled('TEST3')


@needs_analytics
def test_funnel_conversion_calcs():
    """get_stage_conversion() returns dict with total/passed/conversion_rate."""
    for stage in ['SCREENED', 'BOS', 'FVG', 'VALIDATOR', 'ARMED', 'FIRED', 'FILLED']:
        stats = funnel_tracker.get_stage_conversion(stage)
        assert isinstance(stats, dict), f"{stage}: expected dict"
        assert 'total'           in stats, f"{stage}: missing 'total'"
        assert 'passed'          in stats, f"{stage}: missing 'passed'"
        assert 'conversion_rate' in stats, f"{stage}: missing 'conversion_rate'"


@needs_analytics
def test_funnel_rejection_tracking():
    """get_rejection_reasons() returns a list (empty is OK)."""
    rejections = funnel_tracker.get_rejection_reasons(limit=5)
    assert isinstance(rejections, list)


@needs_analytics
def test_ab_variant_assignment():
    """Variant assignment is deterministic for the same ticker+param."""
    tickers = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ']
    for ticker in tickers:
        v1 = ab_test.get_variant(ticker, 'volume_threshold')
        v2 = ab_test.get_variant(ticker, 'volume_threshold')
        assert v1 == v2, f"{ticker}: variant assignment not deterministic ({v1} != {v2})"
        assert v1 in ('A', 'B'), f"{ticker}: unexpected variant '{v1}'"

        val = ab_test.get_param(ticker, 'volume_threshold')
        assert val is not None, f"{ticker}: get_param returned None"


@needs_analytics
def test_ab_outcome_recording():
    """record_outcome() executes without raising for a set of ticker/param pairs."""
    outcomes = [
        ('AAPL', 'volume_threshold', True),
        ('AAPL', 'min_confidence',   True),
        ('TSLA', 'volume_threshold', False),
        ('TSLA', 'min_confidence',   True),
        ('NVDA', 'volume_threshold', True),
        ('NVDA', 'min_confidence',   False),
    ]
    for ticker, param, hit_target in outcomes:
        ab_test.record_outcome(ticker, param, hit_target)


@needs_analytics
def test_ab_stats():
    """get_variant_stats() returns dict with A and B keys."""
    for param in ['volume_threshold', 'min_confidence']:
        stats = ab_test.get_variant_stats(param, days_back=30)
        assert isinstance(stats, dict),   f"{param}: expected dict"
        assert 'A' in stats,              f"{param}: missing 'A' key"
        assert 'B' in stats,              f"{param}: missing 'B' key"
        assert 'win_rate' in stats['A'],  f"{param}: A missing win_rate"
        assert 'samples'  in stats['A'],  f"{param}: A missing samples"


@needs_analytics
def test_full_reports():
    """get_daily_report() and get_ab_test_report() return non-empty strings."""
    daily = funnel_tracker.get_daily_report()
    assert isinstance(daily, str) and len(daily) > 0, "get_daily_report() returned empty"

    ab_report = ab_test.get_ab_test_report(days_back=30)
    assert isinstance(ab_report, str) and len(ab_report) > 0, "get_ab_test_report() returned empty"
