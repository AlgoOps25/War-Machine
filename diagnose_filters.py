# Save as: diagnose_filters.py
"""
Diagnose why filters are rejecting all signals
"""

import pandas as pd
from market_filters import MarketFilters, get_available_filters

# Load signals
signals = pd.read_csv('validation_signals.csv')
print(f"Total signals: {len(signals)}")
print(f"Sample symbols: {signals['symbol'].head(10).tolist()}")

# Initialize filters
filters = MarketFilters()

# Test each filter on first 5 symbols
test_symbols = signals['symbol'].head(5).unique()

print(f"\n{'='*70}")
print("TESTING FILTERS ON SAMPLE SYMBOLS")
print(f"{'='*70}\n")

for symbol in test_symbols:
    print(f"Symbol: {symbol}")
    
    # Check if we have data
    df = filters._get_latest_data(symbol, days=30)
    if df is None or df.empty:
        print(f"  ❌ No data in database!")
        continue
    
    print(f"  ✅ Has data: {len(df)} days")
    print(f"  Latest price: ${df['close'].iloc[-1]:.2f}")
    print(f"  Latest volume: {df['volume'].iloc[-1]:,.0f}")
    
    # Test each filter
    print(f"  Filter results:")
    for filter_name in get_available_filters():
        try:
            result = filters.apply_filter(symbol, filter_name, {})
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"    {filter_name:20s} {status}")
        except Exception as e:
            print(f"    {filter_name:20s} ⚠️  ERROR: {e}")
    
    print()
