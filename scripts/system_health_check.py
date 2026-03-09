#!/usr/bin/env python3
"""
War Machine - Comprehensive System Health Check

Tests every component to ensure 100% operational status.
Run this before live trading to verify all systems are go.
"""
import sys
import os
import traceback
from datetime import datetime, time
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test results tracking
test_results = []

def test_component(name: str, test_func) -> Tuple[bool, str]:
    """Run a test and track results."""
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
        error_msg = f"{type(e).__name__}: {str(e)}"
        test_results.append((name, False, error_msg))
        print(f"❌ {name}: {error_msg}")
        return False, error_msg

print("\n" + "="*80)
print("WAR MACHINE - COMPREHENSIVE SYSTEM HEALTH CHECK")
print("="*80)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# ============================================================================
# DATABASE TESTS
# ============================================================================
print("\n[1/15] DATABASE CONNECTION")
print("-" * 80)

def test_database_connection():
    from app.data.db_connection import get_conn
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    conn.close()
    if result[0] != 1:
        return "Database query failed"
    return True

test_component("Database Connection (PostgreSQL)", test_database_connection)

def test_database_tables():
    from app.data.db_connection import get_conn
    required_tables = [
        'candles_1m', 'candles_5m', 'armed_signals', 'signal_watches',
        'position_journal', 'explosive_mover_overrides'
    ]
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    existing_tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    missing = [t for t in required_tables if t not in existing_tables]
    if missing:
        return f"Missing tables: {', '.join(missing)}"
    return True

test_component("Database Tables Exist", test_database_tables)

# ============================================================================
# DATA PROVIDER TESTS
# ============================================================================
print("\n[2/15] DATA PROVIDERS")
print("-" * 80)

def test_eodhd_credentials():
    import os
    api_key = os.getenv('EODHD_API_KEY')
    if not api_key:
        return "EODHD_API_KEY not set in environment"
    return True

test_component("EODHD API Credentials", test_eodhd_credentials)

def test_market_data_fetch():
    from app.data.market_data import get_intraday_bars
    bars = get_intraday_bars('SPY', interval='5m', lookback_days=1)
    if not bars or len(bars) == 0:
        return "Failed to fetch market data for SPY"
    return True

test_component("Market Data Fetch (SPY 5m)", test_market_data_fetch)

# ============================================================================
# SCREENING MODULES
# ============================================================================
print("\n[3/15] SCREENING MODULES")
print("-" * 80)

def test_dynamic_screener():
    from app.screening.dynamic_screener import get_screener
    screener = get_screener()
    if screener is None:
        return "Screener not initialized"
    if not hasattr(screener, 'get_top_n_movers'):
        return "Screener missing get_top_n_movers method"
    return True

test_component("Dynamic Screener Initialization", test_dynamic_screener)

def test_screener_integration():
    from app.screening.screener_integration import get_ticker_screener_metadata
    metadata = get_ticker_screener_metadata('AAPL')
    required_keys = ['qualified', 'score', 'rvol', 'tier']
    missing = [k for k in required_keys if k not in metadata]
    if missing:
        return f"Missing metadata keys: {', '.join(missing)}"
    return True

test_component("Screener Integration Helper", test_screener_integration)

def test_watchlist_funnel():
    from app.screening.watchlist_funnel import get_priority_tickers
    tickers = get_priority_tickers()
    if not isinstance(tickers, list):
        return "get_priority_tickers didn't return a list"
    return True

test_component("Watchlist Funnel", test_watchlist_funnel)

# ============================================================================
# BREAKOUT DETECTOR
# ============================================================================
print("\n[4/15] BREAKOUT DETECTION")
print("-" * 80)

def test_breakout_detector():
    from breakout_detector import BreakoutDetector
    from app.data.market_data import get_intraday_bars
    
    detector = BreakoutDetector(ticker='SPY')
    bars = get_intraday_bars('SPY', interval='5m', lookback_days=2)
    
    if not bars or len(bars) < 50:
        return "Insufficient bars for testing"
    
    # Test BOS detection
    bos_result = detector.detect_bos(bars, direction='bull')
    if bos_result is None:
        return "BOS detection returned None (may be OK if no pattern)"
    
    return True

test_component("Breakout Detector (BOS/FVG)", test_breakout_detector)

# ============================================================================
# MULTI-TIMEFRAME (MTF)
# ============================================================================
print("\n[5/15] MULTI-TIMEFRAME ANALYSIS")
print("-" * 80)

def test_mtf_compression():
    from app.mtf.compression import compress_to_3m, compress_to_2m
    from app.data.market_data import get_intraday_bars
    
    bars_5m = get_intraday_bars('SPY', interval='5m', lookback_days=1)
    if not bars_5m or len(bars_5m) < 20:
        return "Insufficient 5m bars"
    
    bars_3m = compress_to_3m(bars_5m)
    bars_2m = compress_to_2m(bars_5m)
    
    if not bars_3m:
        return "3m compression failed"
    if not bars_2m:
        return "2m compression failed"
    
    return True

test_component("MTF Timeframe Compression", test_mtf_compression)

def test_mtf_convergence():
    from app.mtf.convergence_boost import check_mtf_convergence
    from app.data.market_data import get_intraday_bars
    
    bars_5m = get_intraday_bars('SPY', interval='5m', lookback_days=1)
    if not bars_5m:
        return "No 5m bars available"
    
    # Test convergence check
    result = check_mtf_convergence(
        ticker='SPY',
        bars_5m=bars_5m,
        direction='bull',
        pattern_type='BOS'
    )
    
    if result is None:
        return "Convergence check returned None"
    
    return True

test_component("MTF Convergence Detection", test_mtf_convergence)

# ============================================================================
# VALIDATION & FILTERS
# ============================================================================
print("\n[6/15] VALIDATION & FILTERS")
print("-" * 80)

def test_multi_indicator_validator():
    from app.validation.validation import validate_signal
    from app.data.market_data import get_intraday_bars
    
    bars = get_intraday_bars('SPY', interval='5m', lookback_days=1)
    if not bars or len(bars) < 50:
        return "Insufficient bars"
    
    # Test validator
    adj_confidence, adj_grade, adjustments = validate_signal(
        ticker='SPY',
        direction='bull',
        entry_price=bars[-1]['close'],
        bars=bars,
        base_confidence=0.80,
        base_grade='A'
    )
    
    if adj_confidence is None:
        return "Validator returned None"
    
    return True

test_component("Multi-Indicator Validator", test_multi_indicator_validator)

def test_regime_filter():
    from app.filters.regime_filter import get_regime_filter
    
    regime_filter = get_regime_filter()
    if regime_filter is None:
        return "Regime filter not initialized"
    
    is_favorable = regime_filter.is_favorable_regime()
    state = regime_filter.get_regime_state()
    
    if not isinstance(is_favorable, bool):
        return "is_favorable_regime didn't return bool"
    if not isinstance(state, dict):
        return "get_regime_state didn't return dict"
    
    return True

test_component("Regime Filter (VIX/SPY)", test_regime_filter)

def test_vwap_directional_gate():
    from app.filters.vwap_directional_gate import check_vwap_alignment
    from app.data.market_data import get_intraday_bars
    
    bars = get_intraday_bars('SPY', interval='5m', lookback_days=1)
    if not bars or len(bars) < 20:
        return "Insufficient bars"
    
    aligned = check_vwap_alignment(
        ticker='SPY',
        direction='bull',
        bars=bars
    )
    
    if aligned is None:
        return "VWAP check returned None"
    
    return True

test_component("VWAP Directional Gate", test_vwap_directional_gate)

# ============================================================================
# OPTIONS MODULES
# ============================================================================
print("\n[7/15] OPTIONS MODULES")
print("-" * 80)

def test_options_data_manager():
    from app.options.options_data_manager import OptionsDataManager
    
    dm = OptionsDataManager(cache_ttl_seconds=300)
    chain = dm.get_0dte_chain('SPY')
    
    if chain is None:
        return "Failed to fetch 0DTE chain"
    
    return True

test_component("Options Data Manager (0DTE)", test_options_data_manager)

def test_options_prevalidation():
    from app.options.options_prevalidation import prevalidate_options_availability
    
    result = prevalidate_options_availability(
        ticker='SPY',
        direction='bull',
        entry_price=580.0
    )
    
    if result is None:
        return "Options prevalidation returned None"
    
    return True

test_component("Options Pre-Validation Gate", test_options_prevalidation)

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================
print("\n[8/15] POSITION MANAGEMENT")
print("-" * 80)

def test_position_manager():
    from app.risk.position_manager import position_manager
    
    state = position_manager.get_state()
    if not isinstance(state, dict):
        return "Position manager state not a dict"
    
    if 'active_positions' not in state:
        return "Missing active_positions in state"
    
    return True

test_component("Position Manager", test_position_manager)

def test_risk_manager():
    from app.risk.risk_manager import risk_manager
    
    can_trade = risk_manager.can_open_position(
        ticker='SPY',
        direction='bull',
        entry_price=580.0
    )
    
    if can_trade is None:
        return "Risk manager returned None"
    
    return True

test_component("Risk Manager", test_risk_manager)

# ============================================================================
# ANALYTICS & TRACKING
# ============================================================================
print("\n[9/15] ANALYTICS & TRACKING")
print("-" * 80)

def test_explosive_mover_tracker():
    from app.analytics.explosive_mover_tracker import (
        get_daily_override_stats,
        print_explosive_override_summary
    )
    
    stats = get_daily_override_stats()
    if not isinstance(stats, dict):
        return "get_daily_override_stats didn't return dict"
    
    return True

test_component("Explosive Mover Tracker", test_explosive_mover_tracker)

def test_signal_cooldown():
    from app.core.signal_generator_cooldown import is_on_cooldown
    
    result = is_on_cooldown('TEST_TICKER', cooldown_minutes=60)
    if not isinstance(result, bool):
        return "is_on_cooldown didn't return bool"
    
    return True

test_component("Signal Cooldown Tracker", test_signal_cooldown)

# ============================================================================
# DISCORD INTEGRATION
# ============================================================================
print("\n[10/15] DISCORD INTEGRATION")
print("-" * 80)

def test_discord_webhook():
    import os
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        return "DISCORD_WEBHOOK_URL not set"
    return True

test_component("Discord Webhook Configuration", test_discord_webhook)

# ============================================================================
# LIVE DATA FEEDS
# ============================================================================
print("\n[11/15] LIVE DATA FEEDS")
print("-" * 80)

def test_websocket_config():
    import os
    api_key = os.getenv('EODHD_API_KEY')
    if not api_key:
        return "EODHD_API_KEY required for WebSocket"
    return True

test_component("WebSocket Configuration", test_websocket_config)

# ============================================================================
# THREAD SAFETY
# ============================================================================
print("\n[12/15] THREAD SAFETY")
print("-" * 80)

def test_thread_safe_state():
    from app.core.thread_safe_state import (
        get_armed_signals,
        get_watches,
        get_active_positions
    )
    
    armed = get_armed_signals()
    watches = get_watches()
    positions = get_active_positions()
    
    if not isinstance(armed, dict):
        return "get_armed_signals didn't return dict"
    if not isinstance(watches, dict):
        return "get_watches didn't return dict"
    if not isinstance(positions, dict):
        return "get_active_positions didn't return dict"
    
    return True

test_component("Thread-Safe State Management", test_thread_safe_state)

# ============================================================================
# ERROR RECOVERY
# ============================================================================
print("\n[13/15] ERROR RECOVERY")
print("-" * 80)

def test_error_recovery():
    from app.core.error_recovery import ErrorRecovery
    
    recovery = ErrorRecovery()
    if recovery is None:
        return "ErrorRecovery not initialized"
    
    return True

test_component("Error Recovery System", test_error_recovery)

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================
print("\n[14/15] HEALTH CHECK")
print("-" * 80)

def test_health_check():
    from app.health_check import get_system_health
    
    health = get_system_health()
    if not isinstance(health, dict):
        return "get_system_health didn't return dict"
    
    if 'status' not in health:
        return "Missing 'status' in health check"
    
    return True

test_component("Health Check Endpoint", test_health_check)

# ============================================================================
# MAIN SCANNER INTEGRATION
# ============================================================================
print("\n[15/15] MAIN SCANNER")
print("-" * 80)

def test_scanner_initialization():
    # Don't actually start the scanner, just verify it can import
    from app.core.scanner import Scanner
    return True

test_component("Scanner Module Import", test_scanner_initialization)

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*80)
print("HEALTH CHECK SUMMARY")
print("="*80)

passed = sum(1 for _, success, _ in test_results if success)
total = len(test_results)
failed = total - passed

print(f"\n✅ Passed: {passed}/{total}")
if failed > 0:
    print(f"❌ Failed: {failed}/{total}")
    print("\nFailed Tests:")
    print("-" * 80)
    for name, success, message in test_results:
        if not success:
            print(f"❌ {name}")
            print(f"   Error: {message}")
else:
    print("🎉 All systems operational!")

print("\n" + "="*80)

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)
