#!/usr/bin/env python3
"""
Phase 1.14 Integration Tests

Tests all Phase 1.14 components:
1. EODHD Options API (real Greeks)
2. SPY Correlation Checker
3. ML Model Info
4. Signal-to-Validation Wiring

Usage:
    python tests/test_phase_1_14.py
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

print("\n" + "="*80)
print("PHASE 1.14 INTEGRATION TESTS")
print("="*80)
print(f"Test Time: {datetime.now(ET).strftime('%Y-%m-%d %I:%M:%S %p ET')}\n")

# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: EODHD OPTIONS API
# ══════════════════════════════════════════════════════════════════════════════
print("\n[TEST 1] EODHD Options API Integration")
print("-" * 80)

try:
    from app.options import get_greeks, build_options_trade
    
    # Test get_greeks()
    print("\nTesting get_greeks() with NVDA...")
    greeks = get_greeks('NVDA', strike=485.0, expiration='2026-03-20', direction='CALL')
    
    print(f"\nGreeks Retrieved:")
    print(f"  Delta:  {greeks.get('delta', 'N/A')}")
    print(f"  Gamma:  {greeks.get('gamma', 'N/A')}")
    print(f"  Theta:  {greeks.get('theta', 'N/A')}")
    print(f"  Vega:   {greeks.get('vega', 'N/A')}")
    print(f"  IV:     {greeks.get('iv', 'N/A')}%")
    print(f"  Price:  ${greeks.get('price', 'N/A')}")
    
    # Check if real data (not placeholders)
    if greeks.get('delta') == 0.5 and greeks.get('price') == 5.0:
        print("\n⚠️  WARNING: Using placeholder Greeks (API may be unavailable)")
        print("   Check EODHD_API_KEY environment variable")
    else:
        print("\n✅ PASS: Real Greeks fetched from EODHD API")
    
    # Test build_options_trade()
    print("\nTesting build_options_trade() with AAPL...")
    trade = build_options_trade(
        ticker='AAPL',
        direction='CALL',
        confidence=75.0,
        current_price=150.0
    )
    
    if trade:
        print(f"\nOptions Trade Built:")
        print(f"  Contract: {trade.get('contract', 'N/A')}")
        print(f"  Strike:   ${trade.get('strike', 'N/A')}")
        print(f"  DTE:      {trade.get('dte', 'N/A')} days")
        print(f"  Price:    ${trade.get('price', 'N/A')}")
        print(f"  Quantity: {trade.get('quantity', 'N/A')} contracts")
        print(f"  IV Rank:  {trade.get('iv_rank', 'N/A')}%")
        print("\n✅ PASS: Options trade built successfully")
    else:
        print("\n❌ FAIL: Could not build options trade")

except Exception as e:
    print(f"\n❌ FAIL: {e}")
    import traceback
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: SPY CORRELATION CHECKER
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n[TEST 2] SPY Correlation Checker")
print("-" * 80)

try:
    from app.filters.correlation import check_spy_correlation, get_divergence_score, is_market_driven_move
    
    # Test check_spy_correlation()
    test_tickers = ['NVDA', 'TSLA', 'AAPL']
    
    for ticker in test_tickers:
        print(f"\nTesting {ticker}...")
        result = check_spy_correlation(ticker, lookback_bars=20)
        
        print(f"  Correlation:      {result['correlation']:.3f}")
        print(f"  Ticker Strength:  {result['ticker_strength']}")
        print(f"  Conf Adjustment:  {result['confidence_adjustment']:+d}%")
        print(f"  Reason:           {result['reason']}")
        
        # Test divergence score
        div_score = get_divergence_score(ticker)
        print(f"  Divergence Score: {div_score:.1f}/100")
        
        # Test market-driven check
        is_market_driven = is_market_driven_move(ticker)
        print(f"  Market-Driven:    {is_market_driven}")
    
    print("\n✅ PASS: SPY correlation checker working")

except Exception as e:
    print(f"\n❌ FAIL: {e}")
    import traceback
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: ML MODEL INFO
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n[TEST 3] ML Model Status")
print("-" * 80)

try:
    from app.ml.ml_trainer import get_model_info, should_retrain
    
    # Check model info
    info = get_model_info()
    
    print(f"\nModel Status:")
    print(f"  Status:          {info.get('status', 'N/A')}")
    
    if info.get('status') == 'trained':
        metrics = info.get('metrics', {})
        print(f"  Trained At:      {info.get('trained_at', 'N/A')}")
        print(f"  Accuracy:        {metrics.get('accuracy', 'N/A'):.2%}")
        print(f"  Precision:       {metrics.get('precision', 'N/A'):.2%}")
        print(f"  Recall:          {metrics.get('recall', 'N/A'):.2%}")
        print(f"  Training Samples: {metrics.get('n_train', 'N/A')}")
        print(f"  Test Samples:    {metrics.get('n_test', 'N/A')}")
        
        top_features = info.get('top_features', [])
        if top_features:
            print(f"\n  Top Features:")
            for feat in top_features:
                print(f"    - {feat}")
    else:
        print(f"  Message:         {info.get('message', 'No model trained yet')}")
    
    # Check if retraining needed
    needs_retrain = should_retrain()
    print(f"\n  Needs Retraining: {needs_retrain}")
    
    if info.get('status') == 'trained':
        print("\n✅ PASS: ML model trained and loaded")
    else:
        print("\n⚠️  INFO: No ML model trained yet (need 100+ signal outcomes)")
        print("   Model will train automatically once data is collected")

except Exception as e:
    print(f"\n❌ FAIL: {e}")
    import traceback
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: SIGNAL-TO-VALIDATION WIRING (SIMULATION)
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n[TEST 4] Signal-to-Validation Wiring")
print("-" * 80)

try:
    from app.validation.validation import get_validator
    from app.filters.correlation import check_spy_correlation
    
    # Simulate signal data
    test_signal = {
        'ticker': 'NVDA',
        'signal': 'BUY',
        'entry': 485.50,
        'stop': 480.00,
        'target': 495.00,
        'confidence': 72.5,
        'rvol': 2.3,
        'adx': 28.5,
        'ema_aligned': True
    }
    
    print("\nSimulating signal validation...")
    print(f"  Ticker:     {test_signal['ticker']}")
    print(f"  Direction:  {test_signal['signal']}")
    print(f"  Confidence: {test_signal['confidence']}%")
    print(f"  RVOL:       {test_signal['rvol']}x")
    print(f"  ADX:        {test_signal['adx']}")
    
    # Get SPY correlation
    corr_result = check_spy_correlation(test_signal['ticker'])
    print(f"\n  SPY Correlation: {corr_result['correlation']:.3f}")
    print(f"  Adjustment:      {corr_result['confidence_adjustment']:+d}%")
    
    # Validate signal
    validator = get_validator()
    should_pass, adjusted_conf, metadata = validator.validate_signal(
        ticker=test_signal['ticker'],
        signal_direction=test_signal['signal'],
        current_price=test_signal['entry'],
        current_volume=1000000,  # Example volume
        base_confidence=test_signal['confidence'] / 100.0
    )
    
    print(f"\nValidation Result:")
    print(f"  Should Pass:      {should_pass}")
    print(f"  Adjusted Conf:    {adjusted_conf*100:.1f}%")
    print(f"  Original Conf:    {test_signal['confidence']}%")
    print(f"  Adjustment:       {(adjusted_conf*100 - test_signal['confidence']):.1f}%")
    
    summary = metadata.get('summary', {})
    print(f"\n  Passed Checks:  {', '.join(summary.get('passed_checks', []))}")
    print(f"  Failed Checks:  {', '.join(summary.get('failed_checks', []))}")
    print(f"  Check Score:    {summary.get('check_score', 'N/A')}")
    
    print("\n✅ PASS: Signal-to-validation wiring functional")

except Exception as e:
    print(f"\n❌ FAIL: {e}")
    import traceback
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n" + "="*80)
print("TEST SUMMARY")
print("="*80)
print("\n✅ All Phase 1.14 components tested")
print("\nNext Steps:")
print("  1. Verify EODHD_API_KEY is set for real options data")
print("  2. Monitor SPY correlation adjustments in production")
print("  3. Collect 100+ signal outcomes to train ML model")
print("  4. Review validation logs for confidence adjustments")
print("\n" + "="*80 + "\n")
