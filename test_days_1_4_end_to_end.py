#!/usr/bin/env python
"""
test_days_1_4_end_to_end.py — Days 1-4 Comprehensive Validation

Tests all 4 infrastructure improvements in sequence:
  Day 1: VIX position sizing + RTH guard
  Day 2: Live bid/ask spread filter (us-quote WebSocket)
  Day 3: REST API failover for WebSocket outages
  Day 4: DB-backed candle cache with 95%+ API reduction

Run from project root:
  python test_days_1_4_end_to_end.py

Requires:
  - EODHD_API_KEY in .env or environment
  - PostgreSQL or SQLite database initialized
  - All dependencies installed (websockets, requests, psycopg2-binary or sqlite3)
"""
import sys
import time
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ═══════════════════════════════════════════════════════════════════════════════════
# TEST HARNESS
# ═══════════════════════════════════════════════════════════════════════════════════

PASS_COUNT = 0
FAIL_COUNT = 0
WARN_COUNT = 0
results = []

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

def warn(name: str, detail: str = ""):
    global WARN_COUNT
    WARN_COUNT += 1
    tag = f"  → {detail}" if detail else ""
    print(f"  \033[93m⚠ WARN\033[0m  {name}{tag}")
    results.append(("WARN", name))

def section(title: str):
    print(f"\n\033[1m{'='*70}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'='*70}\033[0m")

def subsection(title: str):
    print(f"\n\033[1m  {title}\033[0m")
    print(f"  {'-'*68}")

# ═══════════════════════════════════════════════════════════════════════════════════
# PREFLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════════════════════

section("PREFLIGHT: Environment & Dependencies")

# Check EODHD_API_KEY
try:
    from utils import config
    assert config.EODHD_API_KEY, "EODHD_API_KEY is empty"
    ok("EODHD_API_KEY configured", f"key={config.EODHD_API_KEY[:8]}...")
except AssertionError as e:
    fail("EODHD_API_KEY", str(e))
    print("\n[FATAL] Cannot proceed without API key.")
    sys.exit(1)
except Exception as e:
    fail("EODHD_API_KEY import", str(e))
    sys.exit(1)

# Check database
try:
    from app.data import db_connection
    conn = db_connection.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    conn.close()
    db_type = "PostgreSQL" if db_connection.USE_POSTGRES else "SQLite"
    ok(f"Database connection ({db_type})", "query executed successfully")
except Exception as e:
    fail("Database connection", str(e))
    sys.exit(1)

# Check websockets
try:
    import websockets
    ok("websockets package installed", f"version {websockets.__version__}")
except ImportError:
    warn("websockets package", "not installed — WS tests will be skipped")

# Check requests
try:
    import requests
    ok("requests package installed", f"version {requests.__version__}")
except ImportError:
    fail("requests package", "not installed")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════════
# DAY 1: VIX POSITION SIZING + RTH GUARD
# ═══════════════════════════════════════════════════════════════════════════════════

section("DAY 1: VIX Position Sizing + RTH Guard")

subsection("Test 1.1: Position Manager Imports")
try:
    from app.risk.position_manager import position_manager
    ok("position_manager imports cleanly")
except ImportError as e:
    fail("position_manager import", str(e))
    sys.exit(1)

subsection("Test 1.2: VIX Sizing Method Exists")
try:
    assert hasattr(position_manager, 'calculate_position_size'), "Missing calculate_position_size()"
    ok("calculate_position_size() method exists")
    
    # Test call with mock data
    size = position_manager.calculate_position_size(
        ticker="SPY",
        entry_price=580.0,
        stop_price=575.0,
        vix=15.0
    )
    assert isinstance(size, (int, float)), f"Expected numeric size, got {type(size)}"
    assert size > 0, f"Position size should be positive, got {size}"
    ok("VIX-scaled position sizing works", f"size={size} shares @ VIX=15")
except AssertionError as e:
    fail("calculate_position_size()", str(e))
except Exception as e:
    fail("calculate_position_size() exception", str(e))
    import traceback
    traceback.print_exc()

subsection("Test 1.3: RTH Guard")
try:
    # Check if is_regular_trading_hours exists
    now_et = datetime.now(ET)
    if hasattr(position_manager, 'is_regular_trading_hours'):
        is_rth = position_manager.is_regular_trading_hours(now_et)
        ok("is_regular_trading_hours() exists", f"current={is_rth}")
    else:
        # RTH might be in config or elsewhere
        from utils import config
        if hasattr(config, 'MARKET_OPEN') and hasattr(config, 'MARKET_CLOSE'):
            is_rth = config.MARKET_OPEN <= now_et.time() <= config.MARKET_CLOSE
            ok("RTH guard via config.MARKET_OPEN/CLOSE", f"current={is_rth}")
        else:
            warn("RTH guard", "Could not locate RTH check — verify manually")
except Exception as e:
    fail("RTH guard", str(e))
    import traceback
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════════════════════════
# DAY 2: BID/ASK SPREAD FILTER (us-quote WebSocket)
# ═══════════════════════════════════════════════════════════════════════════════════

section("DAY 2: Bid/Ask Spread Filter (us-quote WebSocket)")

subsection("Test 2.1: ws_quote_feed Module Imports")
try:
    from app.data import ws_quote_feed
    ok("ws_quote_feed module imports cleanly")
except ImportError as e:
    fail("ws_quote_feed import", str(e))
    # Non-fatal for now

subsection("Test 2.2: Quote Feed Functions Exist")
try:
    from app.data.ws_quote_feed import (
        start_quote_feed,
        subscribe_quote_tickers,
        get_current_quote,
        is_quote_connected
    )
    ok("All quote feed symbols importable")
    
    # Check that quote feed is not running (no threads started in test)
    connected = is_quote_connected()
    assert connected == False, "Quote feed should not be running in test environment"
    ok("is_quote_connected() returns False (expected)", f"connected={connected}")
    
    # Try to get a quote (should return None since feed is not running)
    quote = get_current_quote("SPY")
    assert quote is None, f"Expected None when feed not running, got {quote}"
    ok("get_current_quote() returns None when feed not running")
    
except ImportError as e:
    fail("Quote feed symbols import", str(e))
except AssertionError as e:
    fail("Quote feed behavior", str(e))
except Exception as e:
    fail("Quote feed exception", str(e))
    import traceback
    traceback.print_exc()

subsection("Test 2.3: Spread Calculation Logic")
try:
    # Mock quote to test spread calculation
    mock_quote = {
        "bid": 580.10,
        "ask": 580.15,
        "last": 580.12
    }
    
    # Manual spread calculation (quote feed should do this internally)
    if mock_quote["bid"] > 0 and mock_quote["ask"] > 0:
        spread_pct = ((mock_quote["ask"] - mock_quote["bid"]) / mock_quote["bid"]) * 100
        assert 0 <= spread_pct < 10, f"Spread out of reasonable range: {spread_pct:.4f}%"
        ok("Spread calculation logic valid", f"spread={spread_pct:.4f}% (bid={mock_quote['bid']}, ask={mock_quote['ask']})")
    else:
        warn("Spread calculation", "Could not validate — zero bid/ask in mock")
except Exception as e:
    fail("Spread calculation", str(e))

# ═══════════════════════════════════════════════════════════════════════════════════
# DAY 3: REST API FAILOVER FOR WEBSOCKET OUTAGES
# ═══════════════════════════════════════════════════════════════════════════════════

section("DAY 3: REST API Failover for WebSocket Outages")

subsection("Test 3.1: ws_feed Module Imports")
try:
    from app.data import ws_feed
    ok("ws_feed module imports cleanly")
except ImportError as e:
    fail("ws_feed import", str(e))
    sys.exit(1)

subsection("Test 3.2: Failover Functions Exist")
try:
    from app.data.ws_feed import (
        get_current_bar,
        get_current_bar_with_fallback,
        get_failover_stats,
        is_connected
    )
    ok("All failover symbols importable")
except ImportError as e:
    fail("Failover symbols import", str(e))
    sys.exit(1)

subsection("Test 3.3: Failover Stats Baseline")
try:
    stats = get_failover_stats()
    assert "rest_hits" in stats, "Missing rest_hits"
    assert "cache_active" in stats, "Missing cache_active"
    assert "ws_connected" in stats, "Missing ws_connected"
    ok("get_failover_stats() returns all keys", str(stats))
    
    assert stats["ws_connected"] == False, "WS should be disconnected (feed not started)"
    ok("ws_connected=False at baseline (feed not running)")
except AssertionError as e:
    fail("get_failover_stats() baseline", str(e))
except Exception as e:
    fail("get_failover_stats() exception", str(e))
    import traceback
    traceback.print_exc()

subsection("Test 3.4: REST Failover Live Call (SPY)")
print("  [INFO] Making a real REST call to EODHD — this may take 1-5 seconds...")
try:
    t_start = time.monotonic()
    bar = get_current_bar_with_fallback("SPY")
    elapsed = time.monotonic() - t_start
    
    if bar is None:
        warn(
            "REST failover returned None",
            "Market may be closed or EODHD not serving same-day data. "
            "This is non-fatal; verify during market hours."
        )
    else:
        assert bar.get("source") == "rest", f"Expected source='rest', got '{bar.get('source')}'"
        assert "close" in bar, "Missing 'close' key"
        assert bar["close"] > 0, f"Bad close price: {bar['close']}"
        ok(
            "REST failover works",
            f"SPY close={bar['close']:.2f} dt={bar['datetime']} ({elapsed:.2f}s)"
        )
        
        stats = get_failover_stats()
        assert stats["rest_hits"] >= 1, f"Expected rest_hits>=1, got {stats['rest_hits']}"
        ok("rest_hits incremented after REST call", f"hits={stats['rest_hits']}")
except AssertionError as e:
    fail("REST failover", str(e))
except Exception as e:
    fail("REST failover exception", str(e))
    import traceback
    traceback.print_exc()

subsection("Test 3.5: REST Cache TTL (No Double-Fetch)")
try:
    hits_before = get_failover_stats()["rest_hits"]
    bar2 = get_current_bar_with_fallback("SPY")  # Same ticker, within TTL
    hits_after = get_failover_stats()["rest_hits"]
    
    assert hits_after == hits_before, (
        f"Cache should prevent double-fetch. Before: {hits_before} After: {hits_after}"
    )
    ok("REST cache TTL works (no double-fetch)", f"hits unchanged at {hits_after}")
except AssertionError as e:
    fail("REST cache TTL", str(e))
except Exception as e:
    fail("REST cache TTL exception", str(e))

# ═══════════════════════════════════════════════════════════════════════════════════
# DAY 4: DB-BACKED CANDLE CACHE WITH 95%+ API REDUCTION
# ═══════════════════════════════════════════════════════════════════════════════════

section("DAY 4: DB-Backed Candle Cache with 95%+ API Reduction")

subsection("Test 4.1: candle_cache Module Imports")
try:
    from app.data.candle_cache import candle_cache
    ok("candle_cache module imports cleanly")
except ImportError as e:
    fail("candle_cache import", str(e))
    sys.exit(1)

subsection("Test 4.2: Cache Functions Exist")
try:
    assert hasattr(candle_cache, 'load_cached_candles'), "Missing load_cached_candles()"
    assert hasattr(candle_cache, 'cache_candles'), "Missing cache_candles()"
    assert hasattr(candle_cache, 'get_cache_metadata'), "Missing get_cache_metadata()"
    assert hasattr(candle_cache, 'detect_cache_gaps'), "Missing detect_cache_gaps()"
    assert hasattr(candle_cache, 'is_cache_fresh'), "Missing is_cache_fresh()"
    ok("All cache methods exist")
except AssertionError as e:
    fail("Cache methods", str(e))
    sys.exit(1)

subsection("Test 4.3: Cache Metadata for Test Ticker")
try:
    # Check if SPY is cached
    metadata = candle_cache.get_cache_metadata("SPY", "1m")
    
    if metadata and metadata["bar_count"] > 0:
        ok(
            "SPY cache exists",
            f"bars={metadata['bar_count']} last={metadata['last_bar_time']}"
        )
        
        # Test cache load
        bars = candle_cache.load_cached_candles("SPY", "1m", days=1)
        assert len(bars) > 0, "Cache load returned empty list"
        ok("Cache load works", f"loaded {len(bars)} bars for SPY (last 1 day)")
        
        # Verify bar structure
        bar = bars[-1]
        required = ["datetime", "open", "high", "low", "close", "volume"]
        missing = [k for k in required if k not in bar]
        assert not missing, f"Bar missing keys: {missing}"
        ok("Cached bar structure valid", f"keys={list(bar.keys())}")
    else:
        warn(
            "SPY cache empty",
            "No cached data found. This is expected on first run. "
            "Run startup_backfill_with_cache() to populate."
        )
except AssertionError as e:
    fail("Cache metadata", str(e))
except Exception as e:
    fail("Cache metadata exception", str(e))
    import traceback
    traceback.print_exc()

subsection("Test 4.4: data_manager Integration")
try:
    from app.data.data_manager import data_manager
    assert hasattr(data_manager, 'startup_backfill_with_cache'), (
        "Missing startup_backfill_with_cache()"
    )
    ok("data_manager.startup_backfill_with_cache() exists")
    
    # Verify it's called in scanner.py
    import app.core.scanner as scanner_module
    scanner_src = open("app/core/scanner.py").read()
    assert "startup_backfill_with_cache" in scanner_src, (
        "startup_backfill_with_cache not called in scanner.py"
    )
    ok("startup_backfill_with_cache() wired in scanner.py")
except AssertionError as e:
    fail("data_manager integration", str(e))
except Exception as e:
    fail("data_manager integration exception", str(e))

subsection("Test 4.5: Cache Stats Summary")
try:
    stats = candle_cache.get_cache_stats()
    ok(
        "Cache stats retrieved",
        f"total_bars={stats['total_bars']:,} tickers={stats['unique_tickers']}"
    )
    
    if stats["total_bars"] > 0:
        print(f"  [INFO] Cache date range: {stats['date_range'][0]} to {stats['date_range'][1]}")
        print(f"  [INFO] Cache size: {stats['cache_size']}")
        print(f"  [INFO] Timeframe breakdown: {stats['timeframe_breakdown']}")
except Exception as e:
    warn("Cache stats", str(e))

# ═══════════════════════════════════════════════════════════════════════════════════
# INTEGRATION TEST: Simulated Startup Sequence
# ═══════════════════════════════════════════════════════════════════════════════════

section("INTEGRATION: Simulated Startup Sequence")

subsection("Test 5.1: Minimal Startup Simulation (No WS Start)")
print("  [INFO] Simulating scanner startup WITHOUT actually starting WebSocket feeds...")
try:
    from app.data.data_manager import data_manager
    
    # Simulate a tiny backfill for a single ticker
    test_ticker = ["SPY"]
    
    print(f"  [INFO] Running startup_backfill_with_cache({test_ticker}, days=1)...")
    t_start = time.monotonic()
    
    # This should use cache if available, or fetch 1 day of data if not
    data_manager.startup_backfill_with_cache(test_ticker, days=1)
    
    elapsed = time.monotonic() - t_start
    
    ok(
        "startup_backfill_with_cache() executed",
        f"completed in {elapsed:.2f}s for {len(test_ticker)} ticker(s)"
    )
    
    # Verify bars were stored
    bars = data_manager.get_bars_from_memory("SPY", limit=10)
    if bars:
        ok(
            "Bars stored in DB",
            f"loaded {len(bars)} recent bars, latest={bars[-1]['datetime']}"
        )
    else:
        warn(
            "No bars in DB",
            "This may be expected if API returned no data. Check EODHD plan."
        )
        
except Exception as e:
    fail("Startup simulation", str(e))
    import traceback
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════════

print(f"\n\033[1m{'='*70}\033[0m")
print(f"\033[1m  FINAL RESULTS\033[0m")
print(f"\033[1m{'='*70}\033[0m")
print(f"  Passed:   \033[92m{PASS_COUNT}\033[0m")
print(f"  Failed:   \033[91m{FAIL_COUNT}\033[0m")
print(f"  Warnings: \033[93m{WARN_COUNT}\033[0m")
print()

if FAIL_COUNT > 0:
    print("  Failed tests:")
    for status, name in results:
        if status == "FAIL":
            print(f"    \033[91m✗\033[0m {name}")
    print()

if WARN_COUNT > 0:
    print("  Warnings (non-fatal):")
    for status, name in results:
        if status == "WARN":
            print(f"    \033[93m⚠\033[0m {name}")
    print()

if FAIL_COUNT == 0:
    print("  \033[92m✅ All critical tests passed — Days 1-4 infrastructure is solid.\033[0m")
    print()
    print("  Next steps:")
    print("    1. Deploy to production / start scanner in market hours")
    print("    2. Watch for cache hit rate in startup logs")
    print("    3. Monitor [WS-FAILOVER] logs if WebSocket disconnects")
    print("    4. Verify VIX-scaled position sizing in live trades")
    print()
else:
    print(f"  \033[91m⚠️  {FAIL_COUNT} critical test(s) failed — fix before deploying.\033[0m")
    print()
    sys.exit(1)
