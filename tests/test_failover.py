"""
test_failover.py — Day 3 REST Failover Validation Suite

Tests get_current_bar_with_fallback() by simulating a WebSocket disconnect
and verifying the 3-tier fallback chain:
  Tier 1: WS live bar      (mocked in-memory)
  Tier 2: REST API bar     (live call to EODHD)
  Tier 3: None             (when REST also fails)

Run from project root:
  python test_failover.py

Requires EODHD_API_KEY in .env or environment.
Does NOT require the WS feed to be running.
"""
import sys
import time
import traceback
from datetime import datetime

# ───────────────────────────────────────────────────────────────────────────────
PASS_COUNT = 0
FAIL_COUNT = 0
results    = []

def ok(name: str, detail: str = ""):
    global PASS_COUNT
    PASS_COUNT += 1
    tag = f"  {detail}" if detail else ""
    print(f"  \033[92m✓ PASS\033[0m  {name}{tag}")
    results.append(("PASS", name))

def fail(name: str, detail: str = ""):
    global FAIL_COUNT
    FAIL_COUNT += 1
    tag = f"  → {detail}" if detail else ""
    print(f"  \033[91m✗ FAIL\033[0m  {name}{tag}")
    results.append(("FAIL", name))

def section(title: str):
    print(f"\n\033[1m{'='*60}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'='*60}\033[0m")

# ───────────────────────────────────────────────────────────────────────────────
# TEST 1 — Import health check
section("TEST 1: Import Health Check")
try:
    from app.data import ws_feed
    ok("ws_feed module imports cleanly")
except Exception as e:
    fail("ws_feed module import", str(e))
    print("\n[FATAL] Cannot import ws_feed — aborting.")
    sys.exit(1)

try:
    from app.data.ws_feed import (
        get_current_bar,
        get_current_bar_with_fallback,
        get_failover_stats,
        is_connected,
    )
    ok("All failover symbols importable")
except ImportError as e:
    fail("Failover symbols import", str(e))
    sys.exit(1)

try:
    from app.data.ws_feed import _fetch_bar_rest
    ok("_fetch_bar_rest importable (private OK for testing)")
except ImportError as e:
    fail("_fetch_bar_rest import", str(e))

# ───────────────────────────────────────────────────────────────────────────────
# TEST 2 — get_failover_stats() baseline
section("TEST 2: get_failover_stats() Baseline")
try:
    stats = get_failover_stats()
    ok("get_failover_stats() returns dict", str(stats))
    assert "rest_hits"    in stats, "missing rest_hits"
    assert "cache_active" in stats, "missing cache_active"
    assert "ws_connected" in stats, "missing ws_connected"
    ok("All 3 keys present: rest_hits / cache_active / ws_connected")
    assert stats["rest_hits"] == 0,     f"Expected 0 hits at start, got {stats['rest_hits']}"
    assert stats["ws_connected"] is False, "WS should be disconnected (feed not started)"
    ok("rest_hits=0 and ws_connected=False at baseline")
except AssertionError as e:
    fail("get_failover_stats() baseline", str(e))
except Exception as e:
    fail("get_failover_stats() exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 3 — Tier 1: WS bar returned when in-memory bar exists
section("TEST 3: Tier 1 — WS In-Memory Bar")
try:
    # Manually plant a fake bar in _open_bars (simulates live WS tick)
    fake_bar = {
        "datetime": datetime(2026, 3, 1, 10, 30),
        "open": 580.10, "high": 581.00,
        "low":  579.50, "close": 580.75,
        "volume": 123456,
    }
    import app.data.ws_feed as _wf
    with _wf._lock:
        _wf._open_bars["SPY"] = dict(fake_bar)

    bar = get_current_bar_with_fallback("SPY")
    assert bar is not None,               "Expected bar, got None"
    assert bar["source"] == "ws",         f"Expected source='ws', got '{bar['source']}'"
    assert bar["close"] == 580.75,        f"Wrong close: {bar['close']}"
    ok("Tier 1: in-memory bar returned with source='ws'", f"close={bar['close']}")

    # Clean up planted bar
    with _wf._lock:
        del _wf._open_bars["SPY"]
    ok("Planted bar cleaned up")

except AssertionError as e:
    fail("Tier 1 WS bar", str(e))
except Exception as e:
    fail("Tier 1 WS bar exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 4 — Tier 2: REST fallback when WS disconnected
section("TEST 4: Tier 2 — REST Fallback (Live EODHD Call)")
print("  [INFO] Making a real REST call to EODHD — requires EODHD_API_KEY...")
try:
    # _connected is already False (feed not started) so REST should trigger
    assert _wf._connected is False, "WS should be disconnected for this test"

    t_start = time.monotonic()
    bar = get_current_bar_with_fallback("SPY")
    elapsed = time.monotonic() - t_start

    if bar is None:
        # Could be outside market hours — EODHD may return empty
        print(f"  [WARN] REST returned None — market may be closed or key issue")
        print(f"         Manually test: curl 'https://eodhd.com/api/intraday/SPY.US?interval=1m&fmt=json&limit=2&api_token=YOUR_KEY'")
        fail("Tier 2 REST bar", "None returned — check API key and market hours")
    else:
        assert bar["source"] == "rest", f"Expected source='rest', got '{bar['source']}'"
        assert "close" in bar,           "Missing 'close' key"
        assert "datetime" in bar,        "Missing 'datetime' key"
        assert isinstance(bar["datetime"], datetime), "datetime should be datetime object"
        assert bar["close"] > 0,         f"Bad close price: {bar['close']}"
        ok(
            "Tier 2: REST bar returned with source='rest'",
            f"SPY close={bar['close']:.2f} dt={bar['datetime']} ({elapsed:.2f}s)"
        )

        stats = get_failover_stats()
        assert stats["rest_hits"] == 1, f"Expected rest_hits=1, got {stats['rest_hits']}"
        ok("rest_hits incremented to 1 after first REST call")

except AssertionError as e:
    fail("Tier 2 REST assertion", str(e))
except Exception as e:
    fail("Tier 2 REST exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 5 — REST cache: second call within TTL should NOT hit REST again
section("TEST 5: REST Cache TTL — No Double-Fetch")
try:
    hits_before = get_failover_stats()["rest_hits"]

    # Second call for same ticker within TTL window
    bar2 = get_current_bar_with_fallback("SPY")
    hits_after = get_failover_stats()["rest_hits"]

    assert hits_after == hits_before, (
        f"Expected no new REST hit (cache should serve). "
        f"Before: {hits_before} After: {hits_after}"
    )
    ok(
        f"Cache hit: rest_hits unchanged at {hits_after} (TTL={_wf.REST_CACHE_TTL}s)",
        f"source={bar2.get('source', '?') if bar2 else 'None'}"
    )
except AssertionError as e:
    fail("REST cache TTL", str(e))
except Exception as e:
    fail("REST cache TTL exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 6 — Tier 2 for multiple tickers (NVDA, TSLA) — each gets its own cache slot
section("TEST 6: Multi-Ticker REST (NVDA + TSLA)")
for ticker in ["NVDA", "TSLA"]:
    try:
        bar = get_current_bar_with_fallback(ticker)
        if bar is None:
            print(f"  [WARN] {ticker} REST returned None (market may be closed)")
            fail(f"{ticker} REST bar", "None returned")
        else:
            assert bar["source"] == "rest"
            assert bar["close"] > 0
            ok(
                f"{ticker}: REST bar",
                f"close={bar['close']:.2f} dt={bar['datetime']}"
            )
    except AssertionError as e:
        fail(f"{ticker} assertion", str(e))
    except Exception as e:
        fail(f"{ticker} exception", str(e))
        traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 7 — Tier 3: invalid ticker returns None (doesn’t crash)
section("TEST 7: Tier 3 — Invalid Ticker Graceful None")
try:
    bar = get_current_bar_with_fallback("ZZZZZ_INVALID_9999")
    # Should return None (REST 404 or empty JSON — not an exception)
    assert bar is None, f"Expected None for invalid ticker, got {bar}"
    ok("Invalid ticker returns None without crashing")
except AssertionError as e:
    fail("Invalid ticker assertion", str(e))
except Exception as e:
    fail("Invalid ticker raised exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# TEST 8 — WS connected guard: when _connected=True, REST skipped even if bar=None
section("TEST 8: WS Connected Guard (REST Not Called When WS Up)")
try:
    hits_before = get_failover_stats()["rest_hits"]

    # Simulate WS being connected but no bar for this ticker yet
    _wf._connected = True
    bar = get_current_bar_with_fallback("AAPL")  # no bar planted
    _wf._connected = False  # restore

    hits_after = get_failover_stats()["rest_hits"]
    assert bar is None, f"Expected None (no WS bar, WS 'connected'), got {bar}"
    assert hits_after == hits_before, (
        f"REST should NOT be called when WS is connected. "
        f"Before: {hits_before} After: {hits_after}"
    )
    ok("WS connected guard: REST skipped when _connected=True and no bar exists")
except AssertionError as e:
    fail("WS connected guard", str(e))
except Exception as e:
    fail("WS connected guard exception", str(e))
    traceback.print_exc()
finally:
    _wf._connected = False  # always restore

# ───────────────────────────────────────────────────────────────────────────────
# TEST 9 — Bar format: all required keys present in REST response
section("TEST 9: Bar Format Validation")
try:
    # Use cached SPY bar from Test 4 (no extra REST call needed)
    cached = _wf._rest_cache.get("SPY")
    bar = cached["bar"] if cached else None
    if bar is None:
        print("  [SKIP] No cached SPY bar to inspect (Test 4 may have failed)")
        fail("Bar format", "No cached bar available")
    else:
        required_keys = ["datetime", "open", "high", "low", "close", "volume", "source"]
        missing = [k for k in required_keys if k not in bar]
        assert not missing, f"Missing keys: {missing}"
        ok("All required keys present", str(required_keys))

        assert bar["high"]  >= bar["low"],   f"high < low: {bar}"
        assert bar["high"]  >= bar["open"],  f"high < open: {bar}"
        assert bar["high"]  >= bar["close"], f"high < close: {bar}"
        assert bar["low"]   <= bar["open"],  f"low > open: {bar}"
        assert bar["low"]   <= bar["close"], f"low > close: {bar}"
        assert bar["volume"] >= 0,            f"negative volume: {bar}"
        ok("OHLCV relationships valid (high >= open/close/low, volume >= 0)")
except AssertionError as e:
    fail("Bar format", str(e))
except Exception as e:
    fail("Bar format exception", str(e))
    traceback.print_exc()

# ───────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
print(f"\n\033[1m{'='*60}\033[0m")
print(f"\033[1m  RESULTS\033[0m")
print(f"\033[1m{'='*60}\033[0m")
print(f"  Passed: \033[92m{PASS_COUNT}\033[0m")
print(f"  Failed: \033[91m{FAIL_COUNT}\033[0m")
print()
if FAIL_COUNT > 0:
    print("  Failed tests:")
    for status, name in results:
        if status == "FAIL":
            print(f"    \033[91m✗\033[0m {name}")
print()

final_stats = get_failover_stats()
print(f"  Final REST stats: hits={final_stats['rest_hits']} "
      f"cache_active={final_stats['cache_active']} "
      f"ws_connected={final_stats['ws_connected']}")
print()

if FAIL_COUNT == 0:
    print("  \033[92m✅ All tests passed — Day 3 REST failover is solid.\033[0m")
else:
    print(f"  \033[91m⚠️  {FAIL_COUNT} test(s) failed — check output above.\033[0m")
    sys.exit(1)
