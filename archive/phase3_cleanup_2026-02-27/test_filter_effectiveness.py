# Save as: test_filter_effectiveness.py
"""
Test which filters actually filter signals
"""

import pandas as pd
from market_filters import MarketFilters, get_available_filters

# Load validation signals
signals = pd.read_csv('validation_signals.csv')
val_signals = signals.tail(63)  # Last 63 for validation

filters = MarketFilters()

print("="*70)
print("FILTER EFFECTIVENESS TEST")
print("="*70)
print(f"\nTotal validation signals: {len(val_signals)}")
print(f"Testing each filter individually...\n")

results = {}

for filter_name in get_available_filters():
    passed = 0
    failed = 0
    
    for idx, row in val_signals.iterrows():
        symbol = row['symbol']
        
        try:
            result = filters.apply_filter(symbol, filter_name, {})
            if result:
                passed += 1
            else:
                failed += 1
        except:
            failed += 1
    
    retention_pct = (passed / len(val_signals)) * 100
    results[filter_name] = {
        'passed': passed,
        'failed': failed,
        'retention_pct': retention_pct
    }
    
    status = "🔴 TOO PERMISSIVE" if retention_pct > 95 else "✅ FILTERING"
    print(f"{filter_name:20s} Pass: {passed:2d} / Fail: {failed:2d} ({retention_pct:5.1f}%) {status}")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)

permissive = [f for f, r in results.items() if r['retention_pct'] > 95]
effective = [f for f, r in results.items() if r['retention_pct'] <= 95]

print(f"\n✅ Effective filters ({len(effective)}): {effective}")
print(f"🔴 Too permissive ({len(permissive)}): {permissive}")

print("\n💡 Recommendation: Use only effective filters or adjust parameters")
