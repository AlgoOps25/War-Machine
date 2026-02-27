# Save as: run_exhaustive_search.py
"""
Run Exhaustive Search - Test ALL possible filter combinations
"""

from filter_combination_optimizer import FilterCombinationOptimizer
from market_filters import get_available_filters
from itertools import combinations
import time

print("="*70)
print("WAR MACHINE FILTER OPTIMIZER - EXHAUSTIVE SEARCH")
print("="*70)

available_filters = get_available_filters()
print(f"\nAvailable filters: {len(available_filters)}")

# Calculate total combinations
max_filters = 5
total_combos = sum(
    len(list(combinations(available_filters, r)))
    for r in range(1, max_filters + 1)
)

print(f"Max filters per combination: {max_filters}")
print(f"Total combinations to test: {total_combos:,}")
print(f"\nEstimated time: {total_combos * 0.5 / 60:.1f} minutes")

proceed = input("\nProceed? (y/n) [y]: ").strip().lower() or 'y'

if proceed != 'y':
    print("Cancelled.")
    exit(0)

# Initialize optimizer
optimizer = FilterCombinationOptimizer(
    signals_csv="validation_signals.csv",
    baseline_wr=0.73,
    min_signals=20
)

if optimizer.baseline_signals.empty:
    print("\n❌ Cannot proceed without signals data")
    exit(1)

# Run exhaustive search
print("\n" + "="*70)
print("RUNNING EXHAUSTIVE SEARCH")
print("="*70)

start_time = time.time()

all_results = []
tested = 0

for num_filters in range(1, max_filters + 1):
    print(f"\n🔍 Testing combinations with {num_filters} filter(s)...")
    
    for filter_combo in combinations(available_filters, num_filters):
        filter_names = list(filter_combo)
        filter_params = {f: {} for f in filter_names}
        
        result = optimizer._evaluate_combination(filter_names, filter_params)
        all_results.append(result)
        
        tested += 1
        
        if tested % 50 == 0:
            elapsed = time.time() - start_time
            rate = tested / elapsed
            remaining = (total_combos - tested) / rate / 60
            print(f"  Progress: {tested}/{total_combos} ({tested/total_combos*100:.1f}%) - ETA: {remaining:.1f} min")

optimizer.results.extend(all_results)

elapsed_time = time.time() - start_time

print(f"\n✅ Tested all {tested} combinations in {elapsed_time/60:.1f} minutes")

# Show results
print("\n" + "="*70)
print("TOP RESULTS")
print("="*70)

optimizer.print_summary(top_n=20)
optimizer.save_results("exhaustive_search_results.json")

# Find the absolute best
best = optimizer.get_top_results(1)
if best:
    print("\n" + "="*70)
    print("🏆 BEST COMBINATION FOUND")
    print("="*70)
    print(f"Filters: {best[0].filters}")
    print(f"Val WR: {best[0].val_win_rate*100:.1f}%")
    print(f"Val Signals: {best[0].val_total_signals}")
    print(f"Profit Factor: {best[0].val_profit_factor:.2f}")
    print(f"Beats baseline: {'✅' if best[0].beats_baseline else '❌'}")

print("\n" + "="*70)
print("COMPLETE")
print("="*70)
