# Save as: optimize_parameters_and_combinations.py
"""
Phase 1: Optimize each filter's parameters individually
Phase 2: Test combinations with optimized parameters
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from filter_combination_optimizer import FilterCombinationOptimizer
from market_filters import get_available_filters
from itertools import combinations, product
import json

print("="*70)
print("WAR MACHINE 2-PHASE OPTIMIZATION")
print("Phase 1: Parameter optimization per filter")
print("Phase 2: Combination optimization with best params")
print("="*70)

# Initialize
optimizer = FilterCombinationOptimizer(
    signals_csv="validation_signals.csv",
    baseline_wr=0.73,
    min_signals=20
)

if optimizer.baseline_signals.empty:
    print("\n❌ No signals")
    exit(1)

# ========================================
# PHASE 1: PARAMETER OPTIMIZATION
# ========================================

print("\n" + "="*70)
print("PHASE 1: OPTIMIZING PARAMETERS FOR EACH FILTER")
print("="*70)

# Define parameter grids for each filter
PARAMETER_GRIDS = {
    'price_range': {
        'min_price': [1, 5, 10, 20],
        'max_price': [100, 200, 300, 500, 1000]
    },
    'volume_surge': {
        'min_surge': [1.5, 2.0, 2.5, 3.0, 4.0],
        'lookback': [10, 20, 30]
    },
    'gap_size': {
        'min_gap': [1.0, 2.0, 3.0, 5.0],
        'max_gap': [10.0, 15.0, 20.0, 30.0]
    },
    'atr_threshold': {
        'min_atr': [0.3, 0.5, 1.0, 1.5, 2.0],
        'period': [7, 14, 20]
    },
    'rsi_threshold': {
        'min_rsi': [20, 25, 30, 35],
        'max_rsi': [65, 70, 75, 80],
        'period': [10, 14, 20]
    },
    'trend_alignment': {
        'fast_period': [5, 10, 20],
        'slow_period': [20, 50, 100]
    },
    'bollinger_position': {
        'period': [10, 20, 30],
        'std_dev': [1.5, 2.0, 2.5],
        'min_position': [0.0, 0.2],
        'max_position': [0.8, 1.0]
    },
    'macd_signal': {
        'fast': [8, 12, 16],
        'slow': [21, 26, 30],
        'signal': [7, 9, 11]
    },
    'vix_level': {
        'min_vix': [0, 10, 15],
        'max_vix': [30, 50, 100]
    }
}

best_params_per_filter = {}

for filter_name in get_available_filters():
    print(f"\n🔍 Optimizing: {filter_name}")
    
    if filter_name == 'time_of_day':
        # Skip - no params to optimize for EOD data
        print("  ⏭️  Skipped (no params for EOD)")
        best_params_per_filter[filter_name] = {}
        continue
    
    if filter_name not in PARAMETER_GRIDS:
        print("  ⏭️  Skipped (no param grid defined)")
        best_params_per_filter[filter_name] = {}
        continue
    
    param_grid = PARAMETER_GRIDS[filter_name]
    
    # Generate all parameter combinations
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    
    all_param_combos = list(product(*param_values))
    total_combos = len(all_param_combos)
    
    print(f"  Testing {total_combos} parameter combinations...")
    
    best_wr = 0
    best_params = {}
    best_result = None
    
    for i, param_combo in enumerate(all_param_combos):
        params = dict(zip(param_names, param_combo))
        
        # Test this single filter with these params
        result = optimizer._evaluate_combination(
            [filter_name],
            {filter_name: params}
        )
        
        # Track best
        if result.val_total_signals >= optimizer.min_signals:
            if result.val_win_rate > best_wr:
                best_wr = result.val_win_rate
                best_params = params
                best_result = result
        
        # Progress
        if (i + 1) % 20 == 0 or (i + 1) == total_combos:
            print(f"    Progress: {i+1}/{total_combos} - Best WR so far: {best_wr*100:.1f}%")
    
    if best_result:
        best_params_per_filter[filter_name] = best_params
        print(f"  ✅ Best params: {best_params}")
        print(f"     Val WR: {best_result.val_win_rate*100:.1f}%")
        print(f"     Signals: {best_result.val_total_signals} ({best_result.signals_retained_pct:.1f}%)")
    else:
        best_params_per_filter[filter_name] = {}
        print(f"  ❌ No valid configuration found (all filtered < {optimizer.min_signals} signals)")

# Save Phase 1 results
with open('optimized_filter_parameters.json', 'w') as f:
    json.dump(best_params_per_filter, f, indent=2)

print("\n" + "="*70)
print("PHASE 1 COMPLETE")
print("="*70)
print(f"Optimized parameters saved to: optimized_filter_parameters.json")

# ========================================
# PHASE 2: COMBINATION OPTIMIZATION
# ========================================

print("\n" + "="*70)
print("PHASE 2: TESTING COMBINATIONS WITH OPTIMIZED PARAMS")
print("="*70)

# Only use filters that found valid params
effective_filters = [
    f for f, params in best_params_per_filter.items()
    if params  # Has params (not empty dict)
]

print(f"\nEffective filters with valid params: {len(effective_filters)}")
for f in effective_filters:
    print(f"  - {f}: {best_params_per_filter[f]}")

# Test all combinations up to 3 filters
max_filters = 3
all_combo_results = []

for num_filters in range(1, min(max_filters, len(effective_filters)) + 1):
    print(f"\n🔍 Testing {num_filters}-filter combinations...")
    
    for filter_combo in combinations(effective_filters, num_filters):
        filter_names = list(filter_combo)
        
        # Use optimized params for each filter
        filter_params = {
            fname: best_params_per_filter[fname]
            for fname in filter_names
        }
        
        result = optimizer._evaluate_combination(filter_names, filter_params)
        all_combo_results.append(result)
        
        print(f"  {str(filter_names):60s} Val WR: {result.val_win_rate*100:5.1f}% Signals: {result.val_total_signals}")

optimizer.results.extend(all_combo_results)

# ========================================
# FINAL RESULTS
# ========================================

print("\n" + "="*70)
print("FINAL RESULTS - RANKED BY VALIDATION WIN RATE")
print("="*70)

optimizer.print_summary(top_n=10)
optimizer.save_results("two_phase_optimization_results.json")

# Best combination
best = optimizer.get_top_results(1)
if best:
    print("\n" + "="*70)
    print("🏆 OPTIMAL CONFIGURATION FOUND")
    print("="*70)
    print(f"Filters: {best[0].filters}")
    print(f"Parameters:")
    for fname in best[0].filters:
        print(f"  {fname}: {best[0].filter_params.get(fname, {})}")
    print(f"\nPerformance:")
    print(f"  Val WR: {best[0].val_win_rate*100:.1f}% ({best[0].val_winners}W / {best[0].val_losers}L)")
    print(f"  Train WR: {best[0].train_win_rate*100:.1f}%")
    print(f"  Signals: {best[0].val_total_signals} ({best[0].signals_retained_pct:.1f}% retained)")
    print(f"  Profit Factor: {best[0].val_profit_factor:.2f}")
    print(f"  Improvement: +{(best[0].val_win_rate - 0.73)*100:.1f}% vs baseline")

print("\n" + "="*70)
print("OPTIMIZATION COMPLETE")
print("="*70)
