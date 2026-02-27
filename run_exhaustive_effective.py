# Save as: run_exhaustive_effective.py
"""
Exhaustive search using only EFFECTIVE filters
"""

from filter_combination_optimizer import FilterCombinationOptimizer
from itertools import combinations
import time

# ONLY use filters that actually filter (not too strict, not too permissive)
EFFECTIVE_FILTERS = [
    'price_range',      # 93.7% pass - filters 4
    'rsi_threshold',    # 93.7% pass - filters 4
    'volume_surge',     # 6.3% pass - very strict but useful
]

print("="*70)
print("WAR MACHINE EXHAUSTIVE SEARCH - EFFECTIVE FILTERS ONLY")
print("="*70)
print(f"\nUsing {len(EFFECTIVE_FILTERS)} effective filters:")
for f in EFFECTIVE_FILTERS:
    print(f"  - {f}")

# Calculate total combinations
max_filters = 3
total_combos = sum(
    len(list(combinations(EFFECTIVE_FILTERS, r)))
    for r in range(1, min(max_filters, len(EFFECTIVE_FILTERS)) + 1)
)

print(f"\nMax filters: {max_filters}")
print(f"Total combinations: {total_combos}")
print(f"Estimated time: < 1 minute")

# Initialize
optimizer = FilterCombinationOptimizer(
    signals_csv="validation_signals.csv",
    baseline_wr=0.73,
    min_signals=20
)

if optimizer.baseline_signals.empty:
    print("\n❌ No signals")
    exit(1)

# Run exhaustive search
print("\n" + "="*70)
print("TESTING ALL COMBINATIONS")
print("="*70)

start_time = time.time()
all_results = []
tested = 0

for num_filters in range(1, min(max_filters, len(EFFECTIVE_FILTERS)) + 1):
    print(f"\n🔍 Testing {num_filters}-filter combinations...")
    
    for filter_combo in combinations(EFFECTIVE_FILTERS, num_filters):
        filter_names = list(filter_combo)
        filter_params = {f: {} for f in filter_names}
        
        result = optimizer._evaluate_combination(filter_names, filter_params)
        all_results.append(result)
        tested += 1
        
        # Show progress
        print(f"  {tested:2d}. {str(filter_names):50s} Val WR: {result.val_win_rate*100:5.1f}% Signals: {result.val_total_signals}")

optimizer.results.extend(all_results)
elapsed = time.time() - start_time

print(f"\n✅ Tested all {tested} combinations in {elapsed:.1f} seconds")

# Results
print("\n" + "="*70)
print("RANKED RESULTS")
print("="*70)

optimizer.print_summary(top_n=10)
optimizer.save_results("effective_filters_exhaustive.json")

# Best
best = optimizer.get_top_results(1)
if best:
    print("\n" + "="*70)
    print("🏆 BEST COMBINATION")
    print("="*70)
    print(f"Filters: {best[0].filters}")
    print(f"Val WR: {best[0].val_win_rate*100:.1f}% ({best[0].val_winners}W / {best[0].val_losers}L)")
    print(f"Train WR: {best[0].train_win_rate*100:.1f}%")
    print(f"Signals: {best[0].val_total_signals} ({best[0].signals_retained_pct:.1f}% retained)")
    print(f"Profit Factor: {best[0].val_profit_factor:.2f}")
    print(f"Improvement: +{(best[0].val_win_rate - 0.73)*100:.1f}% vs baseline")

print("\n" + "="*70)
