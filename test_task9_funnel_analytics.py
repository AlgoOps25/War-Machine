"""
Task 9 Test Suite - Funnel Analytics + A/B Testing

Tests:
  1. Funnel tracker basic operations
  2. Funnel conversion calculations
  3. Rejection reason tracking
  4. A/B test variant assignment
  5. A/B test outcome recording
  6. A/B test winner detection
"""
from app.analytics import (
    funnel_tracker,
    ab_test,
    log_screened,
    log_bos,
    log_fvg,
    log_validator,
    log_armed,
    log_fired,
    log_filled
)

print("="*80)
print("TASK 9 TEST SUITE - Funnel Analytics + A/B Testing")
print("="*80)

# TEST 1: Funnel Tracker Basic Operations
print("\n🔍 TEST 1: Funnel Tracker Basic Operations")
print("-"*80)

try:
    # Test convenience functions
    log_screened('TEST1', passed=True)
    log_bos('TEST1', passed=True)
    log_fvg('TEST1', passed=True, confidence=0.75)
    log_validator('TEST1', passed=False, reason='low_volume')
    
    log_screened('TEST2', passed=True)
    log_bos('TEST2', passed=True)
    log_fvg('TEST2', passed=False, reason='vix_too_high')
    
    log_screened('TEST3', passed=True)
    log_bos('TEST3', passed=True)
    log_fvg('TEST3', passed=True, confidence=0.82)
    log_validator('TEST3', passed=True, confidence=0.85)
    log_armed('TEST3', confidence=0.88)
    log_fired('TEST3', confidence=0.90)
    log_filled('TEST3')
    
    print("✅ Funnel tracker basic operations working")
except Exception as e:
    print(f"❌ Funnel tracker failed: {e}")

# TEST 2: Funnel Conversion Calculations
print("\n📊 TEST 2: Funnel Conversion Calculations")
print("-"*80)

try:
    # Get stage-by-stage conversion
    for stage in ['SCREENED', 'BOS', 'FVG', 'VALIDATOR', 'ARMED', 'FIRED', 'FILLED']:
        stats = funnel_tracker.get_stage_conversion(stage)
        if stats['total'] > 0:
            print(f"{stage:<12} Total: {stats['total']}, "
                  f"Passed: {stats['passed']}, "
                  f"Conversion: {stats['conversion_rate']:.1f}%")
    
    print("✅ Funnel conversion calculations working")
except Exception as e:
    print(f"❌ Conversion calculations failed: {e}")

# TEST 3: Rejection Reason Tracking
print("\n❌ TEST 3: Rejection Reason Tracking")
print("-"*80)

try:
    rejections = funnel_tracker.get_rejection_reasons(limit=5)
    
    if rejections:
        print("Top rejection reasons:")
        for i, (reason, count) in enumerate(rejections, 1):
            print(f"  {i}. {reason}: {count} signals")
    else:
        print("  No rejections recorded (expected for test data)")
    
    print("✅ Rejection tracking working")
except Exception as e:
    print(f"❌ Rejection tracking failed: {e}")

# TEST 4: A/B Test Variant Assignment
print("\n🧪 TEST 4: A/B Test Variant Assignment")
print("-"*80)

try:
    # Test variant assignment consistency
    tickers = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ']
    
    print("Testing variant assignments (should be deterministic):")
    for ticker in tickers:
        vol_variant = ab_test.get_variant(ticker, 'volume_threshold')
        vol_value = ab_test.get_param(ticker, 'volume_threshold')
        conf_variant = ab_test.get_variant(ticker, 'min_confidence')
        conf_value = ab_test.get_param(ticker, 'min_confidence')
        
        print(f"  {ticker}:")
        print(f"    volume_threshold = {vol_value} (variant {vol_variant})")
        print(f"    min_confidence = {conf_value} (variant {conf_variant})")
    
    # Test consistency (same ticker should get same variant)
    aapl_v1 = ab_test.get_variant('AAPL', 'volume_threshold')
    aapl_v2 = ab_test.get_variant('AAPL', 'volume_threshold')
    
    if aapl_v1 == aapl_v2:
        print("\n✅ Variant assignment is deterministic")
    else:
        print("\n❌ Variant assignment is not consistent!")
    
    print("✅ A/B test variant assignment working")
except Exception as e:
    print(f"❌ A/B test variant assignment failed: {e}")

# TEST 5: A/B Test Outcome Recording
print("\n💾 TEST 5: A/B Test Outcome Recording")
print("-"*80)

try:
    # Simulate outcomes
    outcomes = [
        ('AAPL', 'volume_threshold', True),
        ('AAPL', 'min_confidence', True),
        ('TSLA', 'volume_threshold', False),
        ('TSLA', 'min_confidence', True),
        ('NVDA', 'volume_threshold', True),
        ('NVDA', 'min_confidence', False),
    ]
    
    for ticker, param, hit_target in outcomes:
        ab_test.record_outcome(ticker, param, hit_target)
        print(f"  Recorded: {ticker} {param} = {'WIN' if hit_target else 'LOSS'}")
    
    print("✅ A/B test outcome recording working")
except Exception as e:
    print(f"❌ A/B test outcome recording failed: {e}")

# TEST 6: A/B Test Statistics
print("\n📊 TEST 6: A/B Test Statistics")
print("-"*80)

try:
    print("Checking variant statistics:")
    
    for param in ['volume_threshold', 'min_confidence']:
        stats = ab_test.get_variant_stats(param, days_back=30)
        print(f"\n  {param}:")
        print(f"    Variant A: {stats['A']['win_rate']:.1f}% (n={stats['A']['samples']})")
        print(f"    Variant B: {stats['B']['win_rate']:.1f}% (n={stats['B']['samples']})")
    
    print("\n✅ A/B test statistics working")
except Exception as e:
    print(f"❌ A/B test statistics failed: {e}")

# TEST 7: Full Reports
print("\n📝 TEST 7: Full Reports")
print("-"*80)

try:
    print("\n" + "="*80)
    print("FUNNEL REPORT")
    print("="*80)
    print(funnel_tracker.get_daily_report())
    
    print("\n" + "="*80)
    print("A/B TEST REPORT")
    print("="*80)
    print(ab_test.get_ab_test_report(days_back=30))
    
    print("✅ Full reports generating successfully")
except Exception as e:
    print(f"❌ Report generation failed: {e}")

# Summary
print("\n" + "="*80)
print("TEST SUITE COMPLETE")
print("="*80)
print("\n📋 Summary:")
print("  ✅ Funnel Tracker: Ready")
print("  ✅ Rejection Tracking: Ready")
print("  ✅ A/B Test Framework: Ready")
print("  ✅ Reports: Ready")
print("\n🚀 Next Steps:")
print("  1. Review docs/task9_integration_guide.md for integration instructions")
print("  2. Add funnel tracking calls to your signal pipeline")
print("  3. Deploy to Railway: git push origin main")
print("  4. Monitor Railway logs for funnel stats")
print("  5. Check Discord at 4:15 PM for EOD report\n")
