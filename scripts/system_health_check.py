#!/usr/bin/env python3
"""
War Machine - Comprehensive System Health Check  v1.17

All imports match the CURRENT codebase. Run from repo root:
    python scripts/system_health_check.py
"""
import sys
import os

# ── Repo root on path ────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ── Auto-load .env if present ────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass  # python-dotenv optional

from datetime import datetime
from typing import Tuple

test_results = []

def test_component(name: str, test_func) -> Tuple[bool, str]:
    try:
        result = test_func()
        if result is None or result is True:
            test_results.append((name, True, "OK"))
            print(f"✅ {name}")
            return True, "OK"
        else:
            test_results.append((name, False, str(result)))
            print(f"❌ {name}: {result}")
            return False, str(result)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        test_results.append((name, False, msg))
        print(f"❌ {name}: {msg}")
        return False, msg

print("\n" + "="*80)
print("WAR MACHINE - COMPREHENSIVE SYSTEM HEALTH CHECK  v1.17")
print("="*80)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


# ============================================================================
# [1/15] DATABASE
# ============================================================================
print("\n[1/15] DATABASE CONNECTION")
print("-"*80)

def test_db_connection():
    from app.data.db_connection import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1")
    assert cur.fetchone()[0] == 1
    conn.close()

test_component("Database Connection", test_db_connection)

def test_db_tables():
    """Works for both SQLite (local) and PostgreSQL (Railway)."""
    from app.data.db_connection import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        db_type = "SQLite"
    except Exception:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = [r[0] for r in cur.fetchall()]
        db_type = "PostgreSQL"
    conn.close()
    print(f"   [{db_type}] Found {len(tables)} tables: {', '.join(tables[:8])}{'...' if len(tables)>8 else ''}")
    return True

test_component("Database Tables Exist", test_db_tables)


# ============================================================================
# [2/15] DATA PROVIDERS
# ============================================================================
print("\n[2/15] DATA PROVIDERS")
print("-"*80)

def test_eodhd_credentials():
    key = os.getenv('EODHD_API_KEY')
    if not key:
        return "EODHD_API_KEY not set in environment"

test_component("EODHD API Credentials", test_eodhd_credentials)

def test_market_data_fetch():
    from app.data.data_manager import data_manager
    assert hasattr(data_manager, 'startup_backfill_with_cache'), \
        "data_manager missing startup_backfill_with_cache"
    assert hasattr(data_manager, 'get_bars_from_memory'), \
        "data_manager missing get_bars_from_memory"

test_component("Data Manager (replaces market_data)", test_market_data_fetch)


# ============================================================================
# [3/15] SCREENING
# ============================================================================
print("\n[3/15] SCREENING MODULES")
print("-"*80)

def test_dynamic_screener():
    """Verify the v3.1 functional API is present (no DynamicScreener class)."""
    from app.screening.dynamic_screener import (
        run_all_passes,
        get_scored_tickers,
        get_dynamic_watchlist,
        get_gap_candidates,
        get_tier_a_tickers,
    )
    assert callable(run_all_passes)
    assert callable(get_scored_tickers)
    assert callable(get_dynamic_watchlist)
    assert callable(get_gap_candidates)
    assert callable(get_tier_a_tickers)

test_component("Dynamic Screener Module (v3.1)", test_dynamic_screener)

def test_screener_integration():
    from app.screening.screener_integration import get_ticker_screener_metadata
    meta = get_ticker_screener_metadata('AAPL')
    assert isinstance(meta, dict), "metadata is not a dict"

test_component("Screener Integration Helper", test_screener_integration)

def test_watchlist_funnel():
    from app.screening.watchlist_funnel import get_current_watchlist
    result = get_current_watchlist(force_refresh=False)
    assert isinstance(result, list), "get_current_watchlist didn't return a list"

test_component("Watchlist Funnel", test_watchlist_funnel)


# ============================================================================
# [4/15] BREAKOUT / SNIPER (BOS/FVG)
# ============================================================================
print("\n[4/15] BREAKOUT DETECTION (sniper.py)")
print("-"*80)

def test_sniper():
    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals
    assert callable(process_ticker)
    assert callable(clear_armed_signals)
    assert callable(clear_watching_signals)

test_component("Sniper BOS/FVG Engine", test_sniper)


# ============================================================================
# [5/15] MTF
# ============================================================================
print("\n[5/15] MULTI-TIMEFRAME ANALYSIS")
print("-"*80)

def test_mtf_module():
    import app.mtf as mtf_pkg
    members = [m for m in dir(mtf_pkg) if not m.startswith('_')]
    print(f"   app.mtf members: {members}")
    return True

test_component("MTF Package (informational)", test_mtf_module)


# ============================================================================
# [6/15] VALIDATION & FILTERS
# ============================================================================
print("\n[6/15] VALIDATION & FILTERS")
print("-"*80)

def test_validation():
    import app.validation as val
    fn = getattr(val, 'validate_signal', None)
    if fn is None:
        from app.validation import validate_signal as fn
    assert callable(fn)

test_component("Validation Gate", test_validation)

def test_filters_package():
    import app.filters as filters_pkg
    members = [m for m in dir(filters_pkg) if not m.startswith('_')]
    print(f"   app.filters members: {members}")
    return True

test_component("Filters Package (informational)", test_filters_package)


# ============================================================================
# [7/15] OPTIONS
# ============================================================================
print("\n[7/15] OPTIONS MODULES")
print("-"*80)

def test_options_package():
    import app.options as opts
    fn = getattr(opts, 'build_options_trade', None)
    assert fn is not None, "build_options_trade not found in app.options"
    assert callable(fn)

test_component("Options Package", test_options_package)

def test_options_dm():
    from app.options.options_data_manager import OptionsDataManager
    dm = OptionsDataManager()
    assert dm is not None

test_component("Options Data Manager", test_options_dm)


# ============================================================================
# [8/15] POSITION / RISK
# ============================================================================
print("\n[8/15] POSITION MANAGEMENT")
print("-"*80)

def test_position_manager():
    from app.risk.position_manager import position_manager
    for method in ('get_open_positions', 'get_positions', 'get_all_positions',
                   'get_state', 'positions'):
        if hasattr(position_manager, method):
            print(f"   position_manager.{method}() found")
            return True
    return "No recognised getter found on PositionManager"

test_component("Position Manager", test_position_manager)

def test_risk_manager():
    from app.risk.risk_manager import (
        get_session_status,
        get_loss_streak,
        get_eod_report,
        check_exits,
    )
    session = get_session_status()
    assert isinstance(session, dict), "get_session_status didn't return dict"
    streak = get_loss_streak()
    assert isinstance(streak, bool), "get_loss_streak didn't return bool"

test_component("Risk Manager", test_risk_manager)


# ============================================================================
# [9/15] ANALYTICS
# ============================================================================
print("\n[9/15] ANALYTICS & TRACKING")
print("-"*80)

def test_explosive_tracker():
    from app.analytics.explosive_mover_tracker import get_daily_override_stats
    stats = get_daily_override_stats()
    assert isinstance(stats, dict)

test_component("Explosive Mover Tracker", test_explosive_tracker)

def test_signal_cooldown():
    from app.core.signal_generator_cooldown import is_on_cooldown
    import inspect
    sig = inspect.signature(is_on_cooldown)
    params = list(sig.parameters.keys())
    print(f"   is_on_cooldown params: {params}")
    result = is_on_cooldown('TEST')
    assert isinstance(result, bool), "is_on_cooldown didn't return bool"

test_component("Signal Cooldown Tracker", test_signal_cooldown)


# ============================================================================
# [10/15] DISCORD
# ============================================================================
print("\n[10/15] DISCORD INTEGRATION")
print("-"*80)

def test_discord():
    if not os.getenv('DISCORD_WEBHOOK_URL'):
        return "DISCORD_WEBHOOK_URL not set (add to .env for local testing)"

test_component("Discord Webhook", test_discord)


# ============================================================================
# [11/15] WEBSOCKET
# ============================================================================
print("\n[11/15] LIVE DATA FEEDS")
print("-"*80)

def test_ws_config():
    if not os.getenv('EODHD_API_KEY'):
        return "EODHD_API_KEY required for WebSocket"
    from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
    assert callable(start_ws_feed)
    assert callable(subscribe_tickers)
    assert callable(set_backfill_complete)

test_component("WebSocket Feed Module", test_ws_config)


# ============================================================================
# [12/15] THREAD SAFETY
# ============================================================================
print("\n[12/15] THREAD SAFETY")
print("-"*80)

def test_thread_safe_state():
    import app.core.thread_safe_state as tss
    members = [m for m in dir(tss) if not m.startswith('_')]
    print(f"   thread_safe_state exports: {members}")
    return True

test_component("Thread-Safe State Module", test_thread_safe_state)


# ============================================================================
# [13/15] ERROR RECOVERY
# ============================================================================
print("\n[13/15] ERROR RECOVERY")
print("-"*80)

def test_error_recovery():
    import app.core.error_recovery as er
    members = [m for m in dir(er) if not m.startswith('_')]
    print(f"   error_recovery exports: {members}")
    return True

test_component("Error Recovery Module", test_error_recovery)


# ============================================================================
# [14/15] HEALTH CHECK MODULE
# ============================================================================
print("\n[14/15] HEALTH CHECK MODULE")
print("-"*80)

def test_health_check_module():
    import app.health_check as hc
    members = [m for m in dir(hc) if not m.startswith('_')]
    print(f"   health_check exports: {members}")
    return True

test_component("Health Check Module", test_health_check_module)


# ============================================================================
# [15/15] MAIN SCANNER
# ============================================================================
print("\n[15/15] MAIN SCANNER")
print("-"*80)

def test_scanner_import():
    from app.core.scanner import start_scanner_loop
    assert callable(start_scanner_loop)

test_component("Scanner Module (start_scanner_loop)", test_scanner_import)


# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*80)
print("HEALTH CHECK SUMMARY")
print("="*80)

passed = sum(1 for _, ok, _ in test_results if ok)
total  = len(test_results)
failed = total - passed

print(f"\n✅ Passed: {passed}/{total}")
if failed:
    print(f"❌ Failed: {failed}/{total}")
    print("\nFailed Tests:")
    print("-"*80)
    for name, ok, msg in test_results:
        if not ok:
            print(f"❌ {name}")
            print(f"   Error: {msg}")
else:
    print("🎉 All systems operational!")

print("\n" + "="*80)
sys.exit(1 if failed else 0)
