"""
test_mtf.py — MTF Integration Tests

Validates multi-timeframe FVG convergence detection.

CI-safe tests (run automatically):
  - test_mtf_mock_bars_shape        — mock bar helper produces correct structure
  - test_mtf_module_available       — checks if mtf_integration is importable (skip if not)

Integration tests (require mtf_integration module):
  - test_mtf_bull_signal            — enhance_signal_with_mtf() for bull direction
  - test_mtf_bear_signal            — enhance_signal_with_mtf() for bear direction
  - test_mtf_cache_multi_ticker     — multiple tickers, SPY repeated for cache test
  - test_mtf_edge_case_empty_bars   — empty bars → no convergence, no crash
  - test_mtf_edge_case_few_bars     — < 30 bars → handled gracefully
  - test_mtf_stats_printing         — print_mtf_stats() runs without error

Run CI-safe only:
  pytest tests/test_mtf.py -v -m "not integration"

Run all (with mtf_integration installed):
  pytest tests/test_mtf.py -v
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ─────────────────────────────────────────────────────────────────────────────
# Safe import of optional mtf_integration module
# ─────────────────────────────────────────────────────────────────────────────
try:
    from mtf_integration import enhance_signal_with_mtf, print_mtf_stats
    _MTF_AVAILABLE = True
except ImportError:
    _MTF_AVAILABLE = False
    enhance_signal_with_mtf = None
    print_mtf_stats = None

needs_mtf = pytest.mark.skipif(
    not _MTF_AVAILABLE,
    reason="mtf_integration module not installed"
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper: mock bar generator (pure Python, no external deps)
# ─────────────────────────────────────────────────────────────────────────────
def _make_mock_bars(count: int = 100) -> list:
    base_time  = datetime(2026, 2, 24, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    base_price = 450.0
    bars = []
    for i in range(count):
        price = base_price + (i * 0.5) + (i % 3 - 1) * 0.2
        bars.append({
            'datetime': base_time + timedelta(minutes=5 * i),
            'open':   price - 0.1,
            'high':   price + 0.3,
            'low':    price - 0.3,
            'close':  price,
            'volume': 1_000_000 + (i * 1_000),
        })
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# CI-SAFE TESTS (no mtf_integration needed)
# ─────────────────────────────────────────────────────────────────────────────
def test_mtf_mock_bars_shape():
    """Mock bar generator produces correctly structured bars."""
    bars = _make_mock_bars(50)
    assert len(bars) == 50
    required = {'datetime', 'open', 'high', 'low', 'close', 'volume'}
    for bar in bars:
        assert required.issubset(bar.keys()), f"Missing keys in bar: {bar}"
        assert bar['high'] >= bar['low']
        assert bar['high'] >= bar['close']
        assert bar['low']  <= bar['close']
        assert bar['volume'] > 0


def test_mtf_module_available():
    """Report whether mtf_integration is importable (informational, always passes)."""
    # This test always passes — it just tells you the module status.
    # Integration tests below will be skipped if False.
    assert True, f"mtf_integration available: {_MTF_AVAILABLE}"


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS (require mtf_integration module)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
@needs_mtf
def test_mtf_bull_signal():
    """enhance_signal_with_mtf() returns valid result dict for bull direction."""
    bars = _make_mock_bars(100)
    result = enhance_signal_with_mtf(ticker="SPY", direction="bull", bars_session=bars)
    assert isinstance(result, dict)
    assert 'enabled'    in result
    assert 'convergence' in result
    assert 'boost'      in result
    assert 'reason'     in result
    assert isinstance(result['boost'], float)
    assert 0.0 <= result['boost'] <= 1.0


@pytest.mark.integration
@needs_mtf
def test_mtf_bear_signal():
    """enhance_signal_with_mtf() returns valid result dict for bear direction."""
    bars = _make_mock_bars(100)
    result = enhance_signal_with_mtf(ticker="QQQ", direction="bear", bars_session=bars)
    assert isinstance(result, dict)
    assert 'convergence' in result
    assert 'boost'       in result


@pytest.mark.integration
@needs_mtf
def test_mtf_cache_multi_ticker():
    """Multiple tickers including a repeat (SPY x2) don't raise errors."""
    bars = _make_mock_bars(100)
    tickers = ["SPY", "QQQ", "IWM", "SPY"]
    for ticker in tickers:
        result = enhance_signal_with_mtf(ticker=ticker, direction="bull", bars_session=bars)
        assert isinstance(result, dict)
        assert 'boost' in result


@pytest.mark.integration
@needs_mtf
def test_mtf_edge_case_empty_bars():
    """Empty bar list → no convergence, no crash."""
    result = enhance_signal_with_mtf(ticker="TEST_EMPTY", direction="bull", bars_session=[])
    assert result['convergence'] is False
    assert 'insufficient' in result.get('reason', '').lower() or result['boost'] == 0.0


@pytest.mark.integration
@needs_mtf
def test_mtf_edge_case_few_bars():
    """< 30 bars → handled gracefully, no convergence."""
    bars = _make_mock_bars(20)
    result = enhance_signal_with_mtf(ticker="TEST_FEW", direction="bull", bars_session=bars)
    assert result['convergence'] is False


@pytest.mark.integration
@needs_mtf
def test_mtf_stats_printing(capsys):
    """print_mtf_stats() completes without raising."""
    print_mtf_stats()
    captured = capsys.readouterr()
    assert len(captured.out) >= 0  # just verify it didn't crash
