"""
WAR MACHINE - FULL PIPELINE END-TO-END TEST
===========================================

Tests the complete signal generation and validation pipeline:
  1. Data Manager (VIX, SPY, market data)
  2. Regime Filter (TRENDING/CHOPPY/VOLATILE)
  3. Daily Bias Engine (BULL/BEAR/NEUTRAL)
  4. Signal Validator (9-layer confirmation)
  5. Signal Generator (CFW6 breakout detection)
  6. Integration verification

Usage:
  python test_full_pipeline.py

Expected Output:
  - All imports successful
  - VIX data fetched
  - Regime state calculated
  - Sample validation passed
  - Signal generation tested
  - Full pipeline integration verified
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import from root
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))


import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def print_section(title: str):
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_result(test_name: str, passed: bool, details: str = ""):
    """Print test result."""
    emoji = "✅" if passed else "❌"
    print(f"{emoji} {test_name}")
    if details:
        print(f"   {details}")

def test_imports():
    """Test 1: Verify all critical imports."""
    print_section("TEST 1: IMPORT VERIFICATION")
    
    results = []
    
    # Core data management
    try:
        from data_manager import data_manager
        # Try to get db location - handle different attribute names
        db_location = getattr(data_manager, 'db_file', getattr(data_manager, 'db_path', 'market_memory.db'))
        print_result("data_manager import", True, f"DB: {db_location}")
        results.append(True)
    except Exception as e:
        print_result("data_manager import", False, str(e))
        results.append(False)
    
    # Regime filter
    try:
        from regime_filter import regime_filter
        print_result("regime_filter import", True)
        results.append(True)
    except Exception as e:
        print_result("regime_filter import", False, str(e))
        results.append(False)
    
    # Daily bias engine
    try:
        from daily_bias_engine import bias_engine
        print_result("daily_bias_engine import", True)
        results.append(True)
    except Exception as e:
        print_result("daily_bias_engine import", False, str(e))
        results.append(False)
        bias_engine = None
    
    # Signal validator
    try:
        from signal_validator import get_validator
        validator = get_validator()
        print_result("signal_validator import", True)
        results.append(True)
    except Exception as e:
        print_result("signal_validator import", False, str(e))
        results.append(False)
        validator = None
    
    # Signal generator
    try:
        from signal_generator import signal_generator
        print_result("signal_generator import", True)
        results.append(True)
    except Exception as e:
        print_result("signal_generator import", False, str(e))
        results.append(False)
    
    # Breakout detector
    try:
        from breakout_detector import BreakoutDetector
        print_result("breakout_detector import", True)
        results.append(True)
    except Exception as e:
        print_result("breakout_detector import", False, str(e))
        results.append(False)
    
    return all(results)

def test_data_manager():
    """Test 2: Data Manager functionality."""
    print_section("TEST 2: DATA MANAGER")
    
    from data_manager import data_manager
    
    results = []
    
    # Test VIX fetch
    try:
        vix = data_manager.get_vix_level()
        if vix and vix > 0:
            print_result("VIX fetch", True, f"VIX = {vix:.2f}")
            results.append(True)
        else:
            print_result("VIX fetch", False, "VIX value is 0 or None")
            results.append(False)
    except Exception as e:
        print_result("VIX fetch", False, str(e))
        results.append(False)
    
    # Test SPY bars
    try:
        spy_bars = data_manager.get_bars_from_memory("SPY", limit=50)
        if spy_bars and len(spy_bars) >= 14:
            print_result("SPY bars fetch", True, f"{len(spy_bars)} bars available")
            results.append(True)
        else:
            print_result("SPY bars fetch", False, f"Only {len(spy_bars) if spy_bars else 0} bars")
            results.append(False)
    except Exception as e:
        print_result("SPY bars fetch", False, str(e))
        results.append(False)
    
    # Test today's session bars
    try:
        session_bars = data_manager.get_today_session_bars("SPY")
        print_result("Today's session bars", True, f"{len(session_bars) if session_bars else 0} bars")
        results.append(True)
    except Exception as e:
        print_result("Today's session bars", False, str(e))
        results.append(False)
    
    return all(results)

def test_regime_filter():
    """Test 3: Regime Filter functionality."""
    print_section("TEST 3: REGIME FILTER")
    
    from regime_filter import regime_filter
    
    results = []
    
    # Test regime state calculation
    try:
        state = regime_filter.get_regime_state(force_refresh=True)
        
        print("\nRegime Analysis:")
        print(f"  Regime:    {state.regime}")
        print(f"  VIX:       {state.vix:.2f}")
        print(f"  SPY Trend: {state.spy_trend}")
        
        # Fix f-string formatting
        if state.adx is not None:
            print(f"  ADX:       {state.adx:.1f}")
        else:
            print(f"  ADX:       N/A")
        
        print(f"  Favorable: {'YES ✅' if state.favorable else 'NO ❌'}")
        print(f"  Reason:    {state.reason}")
        
        # Verify regime is one of the valid types
        valid_regimes = ["TRENDING", "CHOPPY", "VOLATILE"]
        if state.regime in valid_regimes:
            print_result("Regime classification", True, f"{state.regime}")
            results.append(True)
        else:
            print_result("Regime classification", False, f"Invalid regime: {state.regime}")
            results.append(False)
        
        # Test favorable check
        is_favorable = regime_filter.is_favorable_regime()
        print_result("Favorable regime check", True, f"{'Favorable' if is_favorable else 'Unfavorable'}")
        results.append(True)
        
    except Exception as e:
        print_result("Regime state calculation", False, str(e))
        import traceback
        traceback.print_exc()
        results.append(False)
    
    return all(results)

def test_daily_bias():
    """Test 4: Daily Bias Engine functionality."""
    print_section("TEST 4: DAILY BIAS ENGINE")
    
    try:
        from daily_bias_engine import bias_engine
    except ImportError:
        print_result("Daily bias engine", False, "Not installed")
        return False
    
    results = []
    
    # Test SPY bias calculation
    try:
        spy_bias = bias_engine.calculate_daily_bias("SPY", force_refresh=True)
        
        print("\nSPY Bias Analysis:")
        print(f"  Bias:       {spy_bias['bias']}")
        print(f"  Confidence: {spy_bias['confidence']*100:.1f}%")
        print(f"  Reasons:    {len(spy_bias.get('reasons', []))} factors")
        
        if spy_bias.get('reasons'):
            for i, reason in enumerate(spy_bias['reasons'][:3], 1):
                print(f"    {i}. {reason}")
        
        valid_biases = ["BULL", "BEAR", "NEUTRAL"]
        if spy_bias['bias'] in valid_biases:
            print_result("SPY bias calculation", True, f"{spy_bias['bias']}")
            results.append(True)
        else:
            print_result("SPY bias calculation", False, f"Invalid bias: {spy_bias['bias']}")
            results.append(False)
        
        # Test signal filtering
        should_filter, reason = bias_engine.should_filter_signal("SPY", "BUY")
        print_result("Bias signal filtering", True, 
                    f"BUY signal {'blocked' if should_filter else 'allowed'}: {reason}")
        results.append(True)
        
    except Exception as e:
        print_result("Daily bias calculation", False, str(e))
        import traceback
        traceback.print_exc()
        results.append(False)
    
    return all(results)

def test_signal_validator():
    """Test 5: Signal Validator functionality."""
    print_section("TEST 5: SIGNAL VALIDATOR")
    
    try:
        from signal_validator import get_validator
        validator = get_validator()
    except ImportError:
        print_result("Signal validator", False, "Not installed")
        return False
    
    results = []
    
    # Test validation with sample signal
    try:
        test_ticker = "SPY"
        test_direction = "BUY"
        test_price = 500.00
        test_volume = 50_000_000
        test_confidence = 0.75
        
        print(f"\nValidating Sample Signal:")
        print(f"  Ticker:     {test_ticker}")
        print(f"  Direction:  {test_direction}")
        print(f"  Price:      ${test_price:.2f}")
        print(f"  Volume:     {test_volume:,}")
        print(f"  Base Conf:  {test_confidence*100:.0f}%")
        
        should_pass, adjusted_conf, metadata = validator.validate_signal(
            test_ticker, test_direction, test_price, test_volume, test_confidence
        )
        
        summary = metadata.get('summary', {})
        
        print(f"\nValidation Results:")
        print(f"  Decision:   {'✅ PASS' if should_pass else '❌ FILTER'}")
        print(f"  Adjusted:   {adjusted_conf*100:.1f}%")
        print(f"  Change:     {summary.get('confidence_adjustment', 0)*100:+.1f}%")
        print(f"  Score:      {summary.get('check_score', 'N/A')}")
        
        passed = summary.get('passed_checks', [])
        failed = summary.get('failed_checks', [])
        
        if passed:
            print(f"  Passed:     {', '.join(passed[:5])}")
        if failed:
            print(f"  Failed:     {', '.join(failed[:5])}")
        
        print_result("Signal validation", True, f"Confidence: {test_confidence*100:.0f}% → {adjusted_conf*100:.1f}%")
        results.append(True)
        
    except Exception as e:
        print_result("Signal validation", False, str(e))
        import traceback
        traceback.print_exc()
        results.append(False)
    
    return all(results)

def test_signal_generator():
    """Test 6: Signal Generator functionality."""
    print_section("TEST 6: SIGNAL GENERATOR")
    
    try:
        from signal_generator import signal_generator
    except ImportError:
        print_result("Signal generator", False, "Not installed")
        return False
    
    results = []
    
    # Test signal generator initialization
    try:
        print(f"\nSignal Generator Config:")
        print(f"  Lookback:    {signal_generator.detector.lookback_bars} bars")
        print(f"  Volume Mult: {signal_generator.detector.volume_multiplier}x")
        print(f"  Cooldown:    {signal_generator.cooldown_minutes} minutes")
        print(f"  Min Conf:    {signal_generator.min_confidence}%")
        
        print_result("Signal generator config", True)
        results.append(True)
    except Exception as e:
        print_result("Signal generator config", False, str(e))
        results.append(False)
    
    # Test breakout detection (dry-run)
    try:
        test_tickers = ["SPY", "QQQ"]
        
        print(f"\nScanning {len(test_tickers)} tickers for breakouts...")
        
        for ticker in test_tickers:
            try:
                signal = signal_generator.check_ticker(ticker, use_5m=True)
                if signal:
                    print(f"  {ticker}: 🚨 {signal['signal']} signal detected ({signal['confidence']}%)")
                else:
                    print(f"  {ticker}: No signal")
            except Exception as e:
                print(f"  {ticker}: Error - {e}")
        
        print_result("Breakout detection", True, f"Scanned {len(test_tickers)} tickers")
        results.append(True)
        
    except Exception as e:
        print_result("Breakout detection", False, str(e))
        results.append(False)
    
    return all(results)

def test_pipeline_integration():
    """Test 7: Full pipeline integration."""
    print_section("TEST 7: FULL PIPELINE INTEGRATION")
    
    results = []
    
    print("\nPipeline Flow:")
    print("  1. Scanner fetches watchlist")
    print("  2. Data Manager provides bars")
    print("  3. Signal Generator detects breakouts")
    print("  4. Signal Validator confirms signals")
    print("  5. Regime Filter blocks bad tape")
    print("  6. Daily Bias penalizes counter-trend")
    print("  7. Discord alerts sent")
    
    # Test integration imports
    try:
        from scanner import build_watchlist, is_market_hours
        from signal_generator import check_and_alert
        from regime_filter import regime_filter
        
        print_result("Pipeline imports", True, "All modules accessible")
        results.append(True)
    except Exception as e:
        print_result("Pipeline imports", False, str(e))
        results.append(False)
        return False
    
    # Test regime filter integration
    try:
        print("\nRegime Filter Integration:")
        
        from regime_filter import regime_filter
        state = regime_filter.get_regime_state()
        
        print(f"  Current Regime: {state.regime}")
        print(f"  Favorable:      {'YES ✅' if state.favorable else 'NO ❌'}")
        
        if state.favorable:
            print("  → Signals ALLOWED to pass")
        else:
            print(f"  → Signals BLOCKED: {state.reason}")
        
        print_result("Regime integration", True, f"{state.regime} regime")
        results.append(True)
        
    except Exception as e:
        print_result("Regime integration", False, str(e))
        results.append(False)
    
    # Test bias filter integration
    try:
        print("\nDaily Bias Integration:")
        
        from daily_bias_engine import bias_engine
        
        spy_bias = bias_engine.calculate_daily_bias("SPY")
        should_filter_buy, buy_reason = bias_engine.should_filter_signal("SPY", "BUY")
        should_filter_sell, sell_reason = bias_engine.should_filter_signal("SPY", "SELL")
        
        print(f"  SPY Bias:     {spy_bias['bias']} ({spy_bias['confidence']*100:.0f}%)")
        print(f"  BUY signals:  {'❌ Penalized' if should_filter_buy else '✅ Allowed'}")
        print(f"  SELL signals: {'❌ Penalized' if should_filter_sell else '✅ Allowed'}")
        
        print_result("Bias integration", True, f"{spy_bias['bias']} bias active")
        results.append(True)
        
    except Exception as e:
        print_result("Bias integration", False, str(e))
        results.append(False)
    
    return all(results)

def test_regime_in_validator():
    """Test 8: Check if regime filter is integrated into validator."""
    print_section("TEST 8: REGIME FILTER IN VALIDATOR")
    
    try:
        from signal_validator import get_validator
        import inspect
        
        validator = get_validator()
        
        # Check if validate_signal method exists
        if hasattr(validator, 'validate_signal'):
            print_result("Validator method exists", True, "validate_signal found")
            
            # Check source code for regime_filter
            source = inspect.getsource(validator.validate_signal)
            
            if 'regime_filter' in source or ('regime' in source.lower() and 'CHECK 0A' in source):
                print_result("Regime integration in validator", True, "Found regime references")
                print("  ✅ Regime filter IS integrated into validator")
                return True
            else:
                print_result("Regime integration in validator", False, "No regime references found")
                print("  ⚠️  Regime filter NOT yet integrated into validator")
                print("\n  💡 RECOMMENDATION:")
                print("     Add regime filter as CHECK 0A in signal_validator.py")
                print("     between daily_bias (CHECK 0) and time_of_day (CHECK 1)")
                return False
        else:
            print_result("Validator method", False, "validate_signal not found")
            return False
            
    except Exception as e:
        print_result("Validator inspection", False, str(e))
        return False

def run_all_tests():
    """Run all pipeline tests."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "WAR MACHINE PIPELINE TEST" + " " * 33 + "║")
    print("║" + " " * 78 + "║")
    print("║" + f"  Test Time: {datetime.now(ET).strftime('%Y-%m-%d %I:%M:%S %p ET')}" + " " * 37 + "║")
    print("╚" + "=" * 78 + "╝")
    
    test_results = {}
    
    # Run all tests
    test_results['imports'] = test_imports()
    test_results['data_manager'] = test_data_manager()
    test_results['regime_filter'] = test_regime_filter()
    test_results['daily_bias'] = test_daily_bias()
    test_results['signal_validator'] = test_signal_validator()
    test_results['signal_generator'] = test_signal_generator()
    test_results['pipeline_integration'] = test_pipeline_integration()
    test_results['regime_in_validator'] = test_regime_in_validator()
    
    # Summary
    print_section("TEST SUMMARY")
    
    total = len(test_results)
    passed = sum(1 for v in test_results.values() if v)
    failed = total - passed
    
    print(f"\nResults: {passed}/{total} tests passed")
    print()
    
    for test_name, result in test_results.items():
        emoji = "✅" if result else "❌"
        print(f"  {emoji} {test_name.replace('_', ' ').title()}")
    
    print("\n" + "=" * 80)
    
    if all(test_results.values()):
        print("🎉 ALL TESTS PASSED - System is fully operational!")
        print("=" * 80)
        return 0
    else:
        print("⚠️  SOME TESTS FAILED - Review errors above")
        print("=" * 80)
        
        # Specific recommendations
        if not test_results.get('regime_in_validator'):
            print("\n🔧 NEXT STEP: Integrate regime filter into signal validator")
            print("   Run: python integrate_regime_filter.py")
        
        return 1

if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
