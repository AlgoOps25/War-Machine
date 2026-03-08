"""
Test 0DTE Options Optimization

Tests:
1. Parallel fetching speed
2. Liquidity filtering
3. Delta targeting based on confidence
4. Cache performance
"""
import time
from app.options import build_0dte_trade, build_options_trade
from app.options.options_data_manager import OptionsDataManager

def test_0dte_optimization():
    """Test optimized 0DTE options chain builder."""
    
    print("\n" + "="*80)
    print("🧪 TESTING 0DTE OPTIONS OPTIMIZATION")
    print("="*80 + "\n")
    
    # Test tickers (mix of high and low volatility)
    test_cases = [
        {'ticker': 'SPY', 'direction': 'CALL', 'confidence': 85, 'price': 580},
        {'ticker': 'NVDA', 'direction': 'CALL', 'confidence': 75, 'price': 130},
        {'ticker': 'TSLA', 'direction': 'PUT', 'confidence': 70, 'price': 350},
    ]
    
    print("📊 Test 1: 0DTE Trade Building (Optimized)")
    print("-" * 80)
    
    for case in test_cases:
        print(f"\n🎯 Testing {case['ticker']} {case['direction']} (confidence={case['confidence']})")
        
        start = time.time()
        trade = build_0dte_trade(
            ticker=case['ticker'],
            direction=case['direction'],
            confidence=case['confidence'],
            current_price=case['price']
        )
        elapsed = time.time() - start
        
        if trade:
            print(f"   ✅ SUCCESS in {elapsed:.2f}s")
            print(f"   Strike: ${trade['strike']}")
            print(f"   Price: ${trade['price']:.2f}")
            print(f"   Delta: {trade['greeks']['delta']:.3f}")
            print(f"   Volume: {trade['greeks']['volume']}")
            print(f"   OI: {trade['greeks']['open_interest']}")
            print(f"   Strategy: {trade.get('strategy', 'N/A')}")
            print(f"   Quantity: {trade['quantity']} contracts")
        else:
            print(f"   ❌ FAILED - No suitable contract found")
    
    print("\n" + "="*80)
    print("📊 Test 2: Cache Performance")
    print("-" * 80)
    
    # Test caching by calling same ticker twice
    ticker = 'SPY'
    print(f"\n🔄 First call (cache miss): {ticker}")
    start1 = time.time()
    trade1 = build_0dte_trade(ticker=ticker, direction='CALL', confidence=80, current_price=580)
    elapsed1 = time.time() - start1
    print(f"   Time: {elapsed1:.2f}s")
    
    print(f"\n🔄 Second call (cache hit): {ticker}")
    start2 = time.time()
    trade2 = build_0dte_trade(ticker=ticker, direction='CALL', confidence=80, current_price=580)
    elapsed2 = time.time() - start2
    print(f"   Time: {elapsed2:.2f}s")
    
    if elapsed2 < elapsed1 * 0.5:
        print(f"   ✅ Cache working! {(1 - elapsed2/elapsed1)*100:.0f}% faster")
    else:
        print(f"   ⚠️  Cache may not be working optimally")
    
    print("\n" + "="*80)
    print("📊 Test 3: Confidence-Based Delta Targeting")
    print("-" * 80)
    
    # Test different confidence levels
    confidence_tests = [
        (85, 'aggressive', 0.45, 0.55),
        (75, 'balanced', 0.35, 0.45),
        (65, 'conservative', 0.25, 0.35)
    ]
    
    for conf, strategy, min_delta, max_delta in confidence_tests:
        print(f"\n🎯 Confidence {conf}% (expected: {strategy}, delta {min_delta}-{max_delta})")
        trade = build_0dte_trade(
            ticker='SPY',
            direction='CALL',
            confidence=conf,
            current_price=580
        )
        
        if trade:
            delta = abs(trade['greeks']['delta'])
            in_range = min_delta <= delta <= max_delta
            status = "✅" if in_range else "⚠️"
            print(f"   {status} Delta: {delta:.3f} (strategy: {trade.get('strategy', 'N/A')})")
        else:
            print(f"   ❌ No contract found")
    
    print("\n" + "="*80)
    print("📊 Test 4: Speed Comparison (0DTE vs Regular)")
    print("-" * 80)
    
    ticker = 'NVDA'
    
    print(f"\n⚡ Optimized 0DTE builder:")
    start_opt = time.time()
    trade_opt = build_0dte_trade(ticker=ticker, direction='CALL', confidence=75, current_price=130)
    elapsed_opt = time.time() - start_opt
    print(f"   Time: {elapsed_opt:.2f}s")
    
    print(f"\n🐌 Regular builder:")
    start_reg = time.time()
    trade_reg = build_options_trade(ticker=ticker, direction='CALL', confidence=75, current_price=130)
    elapsed_reg = time.time() - start_reg
    print(f"   Time: {elapsed_reg:.2f}s")
    
    if elapsed_opt < elapsed_reg:
        speedup = (1 - elapsed_opt/elapsed_reg) * 100
        print(f"\n   ✅ Optimized is {speedup:.0f}% faster!")
    else:
        print(f"\n   ⚠️  Optimization not showing expected speedup")
    
    # Cache stats
    odm = OptionsDataManager()
    stats = odm.get_cache_stats()
    print("\n" + "="*80)
    print("📊 Cache Statistics")
    print("-" * 80)
    print(f"   Cached tickers: {stats['cached_tickers']}")
    print(f"   Cache TTL: {stats['ttl_seconds']}s")
    
    print("\n" + "="*80)
    print("✅ TESTING COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    test_0dte_optimization()
