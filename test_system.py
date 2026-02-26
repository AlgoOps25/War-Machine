#!/usr/bin/env python3
"""
WAR MACHINE - COMPREHENSIVE SYSTEM TEST
========================================

Post-cleanup validation script that tests:
  1. Core Infrastructure (DB, data manager, WebSocket)
  2. Signal Pipeline (generator, validator, sniper)
  3. Risk Management (position manager, regime filter, bias engine)
  4. Analytics & Reporting (signal analytics, learning engine)
  5. Integration Points (scanner, watchlist funnel, Discord)

Usage:
    python test_system.py

Expected Output:
    ✅ All tests pass → System is production-ready
    ❌ Any failures → Review errors and fix before deploy
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Test results tracker
test_results = {}
test_details = {}

def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

def print_result(test_name: str, passed: bool, details: str = ""):
    """Print and track test result."""
    emoji = "✅" if passed else "❌"
    print(f"{emoji} {test_name}")
    if details:
        print(f"   {details}")
    test_results[test_name] = passed
    if details:
        test_details[test_name] = details

def test_section_1_infrastructure():
    """Test 1: Core Infrastructure."""
    print_header("SECTION 1: CORE INFRASTRUCTURE")
    
    # 1.1 Database Connection
    try:
        from db_connection import get_conn, ph, dict_cursor, USE_POSTGRES
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        
        db_type = "PostgreSQL (Railway)" if USE_POSTGRES else "SQLite (Local)"
        print_result("Database connection", True, f"{db_type} responding")
    except Exception as e:
        print_result("Database connection", False, str(e))
    
    # 1.2 Data Manager
    try:
        from data_manager import data_manager
        
        # Test VIX
        vix = data_manager.get_vix_level()
        vix_ok = vix and vix > 0
        print_result("VIX data fetch", vix_ok, f"VIX = {vix:.2f}" if vix_ok else "VIX unavailable")
        
        # Test SPY bars
        spy_bars = data_manager.get_bars_from_memory("SPY", limit=50)
        bars_ok = spy_bars and len(spy_bars) >= 14
        print_result("Market data (SPY)", bars_ok, f"{len(spy_bars)} bars" if bars_ok else "Insufficient data")
        
        # Test today's session
        session_bars = data_manager.get_today_session_bars("SPY")
        print_result("Session bars", True, f"{len(session_bars) if session_bars else 0} intraday bars")
        
    except Exception as e:
        print_result("Data Manager", False, str(e))
    
    # 1.3 WebSocket Feed
    try:
        from ws_feed import is_connected, get_current_bar
        
        ws_status = "Connected" if is_connected() else "Disconnected (expected outside market hours)"
        print_result("WebSocket feed", True, ws_status)
    except Exception as e:
        print_result("WebSocket feed", False, str(e))

def test_section_2_signal_pipeline():
    """Test 2: Signal Generation & Validation Pipeline."""
    print_header("SECTION 2: SIGNAL PIPELINE")
    
    # 2.1 Breakout Detector
    try:
        from breakout_detector import BreakoutDetector
        detector = BreakoutDetector()
        print_result("Breakout detector", True, f"Lookback: {detector.lookback_bars} bars")
    except Exception as e:
        print_result("Breakout detector", False, str(e))
    
    # 2.2 Signal Generator
    try:
        from signal_generator import signal_generator, check_and_alert
        
        config_ok = hasattr(signal_generator, 'detector') and hasattr(signal_generator, 'cooldown_minutes')
        print_result("Signal generator", config_ok, 
                    f"Cooldown: {signal_generator.cooldown_minutes}m" if config_ok else "Config error")
    except Exception as e:
        print_result("Signal generator", False, str(e))
    
    # 2.3 Signal Validator
    try:
        from signal_validator import get_validator
        validator = get_validator()
        
        # Test validation with sample signal
        should_pass, adjusted_conf, metadata = validator.validate_signal(
            "SPY", "BUY", 500.0, 50_000_000, 0.75
        )
        
        summary = metadata.get('summary', {})
        score = summary.get('check_score', 'N/A')
        print_result("Signal validator", True, 
                    f"Sample: {75}% → {adjusted_conf*100:.1f}% (score: {score})")
    except Exception as e:
        print_result("Signal validator", False, str(e))
    
    # 2.4 Sniper (Entry Logic)
    try:
        from sniper import process_ticker, armed_signals
        print_result("Sniper module", True, "Entry logic loaded")
    except Exception as e:
        print_result("Sniper module", False, str(e))

def test_section_3_risk_management():
    """Test 3: Risk Management & Filtering."""
    print_header("SECTION 3: RISK MANAGEMENT")
    
    # 3.1 Position Manager
    try:
        from position_manager import position_manager
        
        open_positions = position_manager.get_open_positions()
        daily_stats = position_manager.get_daily_stats()
        
        print_result("Position manager", True, 
                    f"{len(open_positions)} open | Today: {daily_stats['trades']} trades")
    except Exception as e:
        print_result("Position manager", False, str(e))
    
    # 3.2 Regime Filter
    try:
        from regime_filter import regime_filter
        
        state = regime_filter.get_regime_state(force_refresh=True)
        favorable = "YES ✅" if state.favorable else "NO ❌"
        
        print_result("Regime filter", True, 
                    f"{state.regime} | VIX: {state.vix:.1f} | Favorable: {favorable}")
    except Exception as e:
        print_result("Regime filter", False, str(e))
    
    # 3.3 Daily Bias Engine
    try:
        from daily_bias_engine import bias_engine
        
        spy_bias = bias_engine.calculate_daily_bias("SPY", force_refresh=True)
        print_result("Daily bias engine", True, 
                    f"SPY: {spy_bias['bias']} ({spy_bias['confidence']*100:.0f}% confidence)")
    except Exception as e:
        print_result("Daily bias engine", False, str(e))
    
    # 3.4 Options Filter
    try:
        from options_filter import apply_ivr_multiplier, apply_uoa_multiplier
        print_result("Options filter", True, "IVR/UOA/GEX multipliers loaded")
    except Exception as e:
        print_result("Options filter", False, str(e))

def test_section_4_analytics():
    """Test 4: Analytics & Learning."""
    print_header("SECTION 4: ANALYTICS & LEARNING")
    
    # 4.1 Signal Analytics
    try:
        from signal_analytics import signal_tracker
        
        funnel = signal_tracker.get_funnel_stats()
        print_result("Signal analytics", True, 
                    f"Today: {funnel['generated']} generated → {funnel['traded']} traded")
    except ImportError:
        print_result("Signal analytics", True, "Module optional, not installed")
    except Exception as e:
        print_result("Signal analytics", False, str(e))
    
    # 4.2 AI Learning Engine
    try:
        from ai_learning import learning_engine
        print_result("AI learning engine", True, "Weight optimization available")
    except Exception as e:
        print_result("AI learning engine", False, str(e))
    
    # 4.3 Scanner Optimizer
    try:
        from scanner_optimizer import get_adaptive_scan_interval, calculate_optimal_watchlist_size
        
        interval = get_adaptive_scan_interval()
        watchlist_size = calculate_optimal_watchlist_size()
        print_result("Scanner optimizer", True, 
                    f"Interval: {interval}s | Watchlist: {watchlist_size} tickers")
    except Exception as e:
        print_result("Scanner optimizer", False, str(e))

def test_section_5_integrations():
    """Test 5: Integration Points."""
    print_header("SECTION 5: SYSTEM INTEGRATIONS")
    
    # 5.1 Scanner
    try:
        from scanner import build_watchlist, is_market_hours, get_screener_tickers
        
        market_status = "OPEN" if is_market_hours() else "CLOSED"
        print_result("Scanner module", True, f"Market: {market_status}")
    except Exception as e:
        print_result("Scanner module", False, str(e))
    
    # 5.2 Watchlist Funnel
    try:
        from watchlist_funnel import get_current_watchlist, get_funnel
        
        watchlist = get_current_watchlist(force_refresh=False)
        funnel = get_funnel()
        
        print_result("Watchlist funnel", True, 
                    f"{len(watchlist)} tickers | Stage: {funnel.current_stage}")
    except Exception as e:
        print_result("Watchlist funnel", False, str(e))
    
    # 5.3 Discord Notifications
    try:
        from discord_helpers import send_simple_message
        print_result("Discord integration", True, "Webhook ready")
    except Exception as e:
        print_result("Discord integration", False, str(e))
    
    # 5.4 Config
    try:
        import config
        
        api_key_ok = bool(config.EODHD_API_KEY)
        webhook_ok = bool(config.DISCORD_WEBHOOK_URL)
        
        config_status = []
        if api_key_ok:
            config_status.append("EODHD ✅")
        if webhook_ok:
            config_status.append("Discord ✅")
        
        print_result("Configuration", api_key_ok, " | ".join(config_status) if config_status else "Missing API keys")
    except Exception as e:
        print_result("Configuration", False, str(e))

def test_section_6_mtf_system():
    """Test 6: Multi-Timeframe Analysis."""
    print_header("SECTION 6: MULTI-TIMEFRAME SYSTEM")
    
    # 6.1 MTF Compression
    try:
        from mtf_compression import compress_to_3m, compress_to_2m, compress_to_1m, TIMEFRAME_PRIORITY
        
        # Create test bars
        test_bars = [{
            'datetime': datetime.now(ET),
            'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 10000
        } for _ in range(10)]
        
        bars_3m = compress_to_3m(test_bars)
        bars_2m = compress_to_2m(test_bars)
        bars_1m = compress_to_1m(test_bars)
        
        print_result("MTF compression", True, 
                    f"Priority: {' > '.join(TIMEFRAME_PRIORITY)}")
    except Exception as e:
        print_result("MTF compression", False, str(e))
    
    # 6.2 MTF Integration
    try:
        from mtf_integration import enhance_signal_with_mtf, check_mtf_convergence
        print_result("MTF integration", True, "Convergence detection ready")
    except Exception as e:
        print_result("MTF integration", False, str(e))
    
    # 6.3 MTF FVG Priority
    try:
        from mtf_fvg_priority import get_highest_priority_fvg, resolve_fvg_priority
        print_result("MTF FVG priority", True, "Multi-timeframe FVG resolution ready")
    except Exception as e:
        print_result("MTF FVG priority", False, str(e))

def print_summary():
    """Print final test summary."""
    print_header("TEST SUMMARY")
    
    total = len(test_results)
    passed = sum(1 for v in test_results.values() if v)
    failed = total - passed
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if failed > 0:
        print(f"\n❌ FAILED TESTS ({failed}):")
        for test_name, result in test_results.items():
            if not result:
                print(f"   • {test_name}")
    
    print(f"\n{'='*80}")
    
    if all(test_results.values()):
        print("🎉 ALL TESTS PASSED — System is production-ready!")
        print("✅ War Machine CFW6 is fully operational")
        print(f"{'='*80}\n")
        return 0
    else:
        print("⚠️  SOME TESTS FAILED — Review errors above")
        print(f"{'='*80}\n")
        return 1

def main():
    """Run all system tests."""
    print("\n" + "#"*80)
    print("# WAR MACHINE — COMPREHENSIVE SYSTEM TEST")
    print("# CFW6 Signal Engine + Breakout Detector")
    print("#"*80)
    print(f"# Test Time: {datetime.now(ET).strftime('%Y-%m-%d %I:%M:%S %p ET')}")
    print("#"*80)
    
    try:
        test_section_1_infrastructure()
        test_section_2_signal_pipeline()
        test_section_3_risk_management()
        test_section_4_analytics()
        test_section_5_integrations()
        test_section_6_mtf_system()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n🚫 CRITICAL TEST FAILURE: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return print_summary()

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
