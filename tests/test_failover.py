"""
test_failover.py — REST Failover Validation Suite

Tests get_current_bar_with_fallback() by simulating a WebSocket disconnect
and verifying the 3-tier fallback chain:
  Tier 1: WS live bar      (mocked in-memory)     — runs in CI
  Tier 2: REST API bar     (live EODHD call)       — @integration, skipped in CI
  Tier 3: None             (invalid ticker)        — runs in CI

Run all (including live REST):
  pytest tests/test_failover.py -v -m integration

Run CI-safe only:
  pytest tests/test_failover.py -v -m "not integration"

Direct script (legacy):
  python tests/test_failover.py
"""
import sys
import time
import traceback
from datetime import datetime

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Shared import fixture — imported once at module level safely
# (no sys.exit here — if import fails, tests will show ImportError)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import app.data.ws_feed as _wf
    from app.data.ws_feed import (
        get_current_bar,
        get_current_bar_with_fallback,
        get_failover_stats,
        is_connected,
        _fetch_bar_rest,
    )
    _WF_AVAILABLE = True
except ImportError:
    _WF_AVAILABLE = False

pytestmark_wf = pytest.mark.skipif(
    not _WF_AVAILABLE,
    reason="app.data.ws_feed not importable"
)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Import health check (CI-safe)
# ─────────────────────────────────────────────────────────────────────────────
def test_import_health():
    """ws_feed and all failover symbols import without error."""
    assert _WF_AVAILABLE, (
        "app.data.ws_feed failed to import — check for syntax errors or missing deps"
    )
    # Verify expected symbols are present
    assert callable(get_current_bar_with_fallback)
    assert callable(get_failover_stats)
    assert callable(is_connected)
    assert callable(_fetch_bar_rest)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — get_failover_stats() baseline (CI-safe)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_failover_stats_baseline():
    """get_failover_stats() returns the 3 expected keys at startup."""
    stats = get_failover_stats()
    assert isinstance(stats, dict)
    assert "rest_hits"    in stats
    assert "cache_active" in stats
    assert "ws_connected" in stats
    assert stats["ws_connected"] is False, "WS should be disconnected (feed not started)"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Tier 1: WS in-memory bar returned (CI-safe, fully mocked)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_tier1_ws_bar():
    """Tier 1: planted in-memory WS bar is returned with source='ws'."""
    fake_bar = {
        "datetime": datetime(2026, 3, 1, 10, 30),
        "open": 580.10, "high": 581.00,
        "low":  579.50, "close": 580.75,
        "volume": 123456,
    }
    with _wf._lock:
        _wf._open_bars["SPY"] = dict(fake_bar)

    try:
        bar = get_current_bar_with_fallback("SPY")
        assert bar is not None,          "Expected bar, got None"
        assert bar["source"] == "ws",    f"Expected source='ws', got '{bar['source']}'"
        assert bar["close"] == 580.75,   f"Wrong close: {bar['close']}"
    finally:
        with _wf._lock:
            _wf._open_bars.pop("SPY", None)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Tier 2: REST fallback (LIVE — integration only, skipped in CI)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_tier2_rest_spy():
    """Tier 2: REST fallback returns a valid SPY bar (requires live EODHD key + market hours)."""
    assert _wf._connected is False, "WS should be disconnected"
    bar = get_current_bar_with_fallback("SPY")
    assert bar is not None, (
        "REST returned None — market may be closed or EODHD_API_KEY invalid. "
        "Run: curl 'https://eodhd.com/api/intraday/SPY.US?interval=1m&fmt=json&limit=2&api_token=YOUR_KEY'"
    )
    assert bar["source"] == "rest"
    assert "close"    in bar
    assert "datetime" in bar
    assert isinstance(bar["datetime"], datetime)
    assert bar["close"] > 0


@pytest.mark.integration
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_tier2_rest_increments_hits():
    """REST hit counter increments after a live REST fetch."""
    # Bust the SPY cache so REST is forced
    if hasattr(_wf, '_rest_cache'):
        _wf._rest_cache.pop("SPY", None)
    hits_before = get_failover_stats()["rest_hits"]
    bar = get_current_bar_with_fallback("SPY")
    if bar is not None:
        hits_after = get_failover_stats()["rest_hits"]
        assert hits_after == hits_before + 1, (
            f"Expected rest_hits to increment. Before: {hits_before} After: {hits_after}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — REST cache TTL (CI-safe — uses whatever is already cached)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_rest_cache_no_double_fetch():
    """
    A second call for the same ticker within TTL must NOT trigger a new REST hit.
    Plants a fake cache entry so this test is completely offline/CI-safe.
    """
    ticker = "CACHE_TEST_TICKER"
    fake_cached_bar = {
        "datetime": datetime(2026, 3, 1, 10, 30),
        "open": 100.0, "high": 101.0,
        "low":   99.0, "close": 100.5,
        "volume": 50000,
        "source": "rest",
    }
    # Plant a fresh cache entry with ts = now (within TTL)
    _wf._rest_cache[ticker] = {"bar": fake_cached_bar, "ts": time.monotonic()}

    hits_before = get_failover_stats()["rest_hits"]
    bar = get_current_bar_with_fallback(ticker)
    hits_after = get_failover_stats()["rest_hits"]

    assert bar is not None,              "Expected cached bar to be returned"
    assert hits_after == hits_before,    "REST should NOT be called when cache is fresh"

    # Cleanup
    _wf._rest_cache.pop(ticker, None)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Multi-ticker REST (integration only)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["NVDA", "TSLA"])
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_tier2_rest_multi_ticker(ticker):
    """REST fallback returns valid bars for NVDA and TSLA (live call)."""
    bar = get_current_bar_with_fallback(ticker)
    assert bar is not None, f"{ticker} REST returned None (market closed?)"
    assert bar["source"] == "rest"
    assert bar["close"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Tier 3: invalid ticker returns None (CI-safe)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_tier3_invalid_ticker_returns_none():
    """An invalid ticker must return None gracefully (no exception, no crash)."""
    bar = get_current_bar_with_fallback("ZZZZZ_INVALID_9999")
    assert bar is None, f"Expected None for invalid ticker, got {bar}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — WS connected guard (CI-safe, mock only)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_ws_connected_guard_skips_rest():
    """When _connected=True, REST should NOT be called even if no bar exists."""
    hits_before = get_failover_stats()["rest_hits"]
    _wf._connected = True
    try:
        bar = get_current_bar_with_fallback("AAPL_NO_BAR_PLANTED")
        hits_after = get_failover_stats()["rest_hits"]
        assert bar is None, f"Expected None (no WS bar, WS 'connected'), got {bar}"
        assert hits_after == hits_before, (
            f"REST should NOT be called when WS connected. "
            f"Before: {hits_before} After: {hits_after}"
        )
    finally:
        _wf._connected = False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9 — Bar format validation (integration only — needs a live REST bar)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _WF_AVAILABLE, reason="ws_feed not importable")
def test_bar_format_ohlcv_valid():
    """All required OHLCV keys present and relationships valid in a live REST bar."""
    bar = get_current_bar_with_fallback("SPY")
    if bar is None:
        pytest.skip("No live bar available (market closed or no API key)")

    required_keys = ["datetime", "open", "high", "low", "close", "volume", "source"]
    missing = [k for k in required_keys if k not in bar]
    assert not missing, f"Missing keys: {missing}"

    assert bar["high"]  >= bar["low"],   f"high < low: {bar}"
    assert bar["high"]  >= bar["open"],  f"high < open: {bar}"
    assert bar["high"]  >= bar["close"], f"high < close: {bar}"
    assert bar["low"]   <= bar["open"],  f"low > open: {bar}"
    assert bar["low"]   <= bar["close"], f"low > close: {bar}"
    assert bar["volume"] >= 0,            f"negative volume: {bar}"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy direct-run entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "-m", "not integration"],
        cwd=str(__import__("pathlib").Path(__file__).parent.parent)
    )
    sys.exit(result.returncode)
