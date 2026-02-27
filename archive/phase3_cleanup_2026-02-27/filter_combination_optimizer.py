"""
War Machine Filter Combination Optimizer - UPDATED
Now uses real filters from market_filters.py
"""

import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set
from itertools import combinations, product
import json
from pathlib import Path
import time
from dataclasses import dataclass
import random
from collections import defaultdict

from market_filters import MarketFilters, get_available_filters
from config import WarMachineConfig

# ========================================
# RESULT TRACKING
# ========================================

@dataclass
class FilterCombinationResult:
    """Results for a filter combination"""
    filters: List[str]
    filter_params: Dict
    
    # Training metrics
    train_total_signals: int
    train_winners: int
    train_losers: int
    train_win_rate: float
    train_avg_return: float
    train_profit_factor: float
    
    # Validation metrics
    val_total_signals: int
    val_winners: int
    val_losers: int
    val_win_rate: float
    val_avg_return: float
    val_profit_factor: float
    
    # Quality metrics
    degradation_pct: float
    signals_retained_pct: float
    is_statistically_significant: bool
    beats_baseline: bool
    
    # Metadata
    timestamp: str
    execution_time: float


# ========================================
# FILTER COMBINATION OPTIMIZER
# ========================================

class FilterCombinationOptimizer:
    """Optimize filter combinations"""
    
    def __init__(self, 
                 db_path: str = "market_memory.db",
                 signals_csv: str = "validation_signals.csv",
                 baseline_wr: float = 0.73,
                 min_signals: int = 20):
        """Initialize optimizer"""
        self.db_path = db_path
        self.signals_csv = signals_csv
        self.baseline_wr = baseline_wr
        self.min_signals = min_signals
        
        self.filters = MarketFilters(db_path=db_path)
        
        # Load baseline signals
        self.baseline_signals = self._load_baseline_signals()
        
        # Split into train/validation
        self.train_signals, self.val_signals = self._split_train_val(
            self.baseline_signals, 
            split_ratio=0.7
        )
        
        # Results storage
        self.results: List[FilterCombinationResult] = []
        
        print(f"\nLoaded {len(self.baseline_signals)} baseline signals")
        print(f"Train: {len(self.train_signals)}, Validation: {len(self.val_signals)}")
        print(f"Baseline WR: {baseline_wr*100:.1f}%")
    
    def _load_baseline_signals(self) -> pd.DataFrame:
        """Load baseline signals from CSV"""
        if Path(self.signals_csv).exists():
            df = pd.read_csv(self.signals_csv)
            print(f"\nLoaded signals from {self.signals_csv}")
            return df
        else:
            print(f"\n❌ Signals file not found: {self.signals_csv}")
            return pd.DataFrame()
    
    def _split_train_val(self, df: pd.DataFrame, split_ratio: float = 0.7) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Split signals into train/validation sets"""
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        if 'date' in df.columns:
            df = df.sort_values('date')
        elif 'timestamp' in df.columns:
            df = df.sort_values('timestamp')
        
        split_idx = int(len(df) * split_ratio)
        return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()
    
    def _apply_filters_to_signals(self, signals_df: pd.DataFrame, filter_names: List[str], filter_params: Dict) -> pd.DataFrame:
        """Apply filter combination to signals"""
        if signals_df.empty or not filter_names:
            return signals_df
        
        filtered_signals = []
        
        for idx, row in signals_df.iterrows():
            symbol = row['symbol']
            
            try:
                results = self.filters.run_filter_combination(
                    symbol, filter_names, filter_params
                )
                
                if results['all_filters_passed']:
                    filtered_signals.append(row)
                    
            except Exception as e:
                # Skip signals that cause errors
                continue
        
        return pd.DataFrame(filtered_signals) if filtered_signals else pd.DataFrame()
    
    def _calculate_performance(self, signals_df: pd.DataFrame) -> Dict:
        """Calculate performance metrics"""
        if signals_df.empty:
            return {
                'total_signals': 0, 'winners': 0, 'losers': 0,
                'win_rate': 0.0, 'avg_return': 0.0, 'profit_factor': 0.0
            }
        
        winners = len(signals_df[signals_df['outcome'] == 'WIN']) if 'outcome' in signals_df.columns else 0
        losers = len(signals_df[signals_df['outcome'] == 'LOSS']) if 'outcome' in signals_df.columns else 0
        total = winners + losers
        win_rate = winners / total if total > 0 else 0.0
        
        if 'return_pct' in signals_df.columns:
            avg_return = signals_df['return_pct'].mean()
            winning_returns = signals_df[signals_df['return_pct'] > 0]['return_pct'].sum()
            losing_returns = abs(signals_df[signals_df['return_pct'] < 0]['return_pct'].sum())
            profit_factor = winning_returns / losing_returns if losing_returns > 0 else 0.0
        else:
            avg_return = 0.0
            profit_factor = 0.0
        
        return {
            'total_signals': total, 'winners': winners, 'losers': losers,
            'win_rate': win_rate, 'avg_return': avg_return, 'profit_factor': profit_factor
        }
    
    def _evaluate_combination(self, filter_names: List[str], filter_params: Dict) -> FilterCombinationResult:
        """Evaluate a filter combination"""
        start_time = time.time()
        
        # Training
        train_filtered = self._apply_filters_to_signals(self.train_signals, filter_names, filter_params)
        train_perf = self._calculate_performance(train_filtered)
        
        # Validation
        val_filtered = self._apply_filters_to_signals(self.val_signals, filter_names, filter_params)
        val_perf = self._calculate_performance(val_filtered)
        
        # Metrics
        degradation_pct = (
            ((train_perf['win_rate'] - val_perf['win_rate']) / train_perf['win_rate'] * 100)
            if train_perf['win_rate'] > 0 else 0.0
        )
        
        signals_retained_pct = (
            (val_perf['total_signals'] / len(self.val_signals) * 100)
            if len(self.val_signals) > 0 else 0.0
        )
        
        is_significant = self._test_significance(
            val_perf['winners'], val_perf['losers'], self.baseline_wr
        )
        
        beats_baseline = (
            val_perf['win_rate'] > self.baseline_wr and
            val_perf['total_signals'] >= self.min_signals
        )
        
        execution_time = time.time() - start_time
        
        return FilterCombinationResult(
            filters=filter_names, filter_params=filter_params,
            train_total_signals=train_perf['total_signals'],
            train_winners=train_perf['winners'], train_losers=train_perf['losers'],
            train_win_rate=train_perf['win_rate'], train_avg_return=train_perf['avg_return'],
            train_profit_factor=train_perf['profit_factor'],
            val_total_signals=val_perf['total_signals'],
            val_winners=val_perf['winners'], val_losers=val_perf['losers'],
            val_win_rate=val_perf['win_rate'], val_avg_return=val_perf['avg_return'],
            val_profit_factor=val_perf['profit_factor'],
            degradation_pct=degradation_pct, signals_retained_pct=signals_retained_pct,
            is_statistically_significant=is_significant, beats_baseline=beats_baseline,
            timestamp=datetime.now().isoformat(), execution_time=execution_time
        )
    
    def _test_significance(self, winners: int, losers: int, baseline_wr: float) -> bool:
        """Test statistical significance using chi-square"""
        total = winners + losers
        if total < self.min_signals:
            return False
        
        expected_winners = total * baseline_wr
        expected_losers = total * (1 - baseline_wr)
        
        if expected_winners == 0 or expected_losers == 0:
            return False
        
        chi_square = (
            ((winners - expected_winners) ** 2 / expected_winners) +
            ((losers - expected_losers) ** 2 / expected_losers)
        )
        
        return chi_square > 3.841  # 95% confidence
    
    # ========================================
    # SEARCH STRATEGIES
    # ========================================
    
    def greedy_forward_selection(self, max_filters: int = 5, filter_whitelist: Optional[List[str]] = None) -> List[FilterCombinationResult]:
        """Greedy forward selection - add best filter iteratively"""
        available_filters = set(filter_whitelist or get_available_filters())
        
        print(f"\n{'='*70}")
        print(f"GREEDY FORWARD SELECTION")
        print(f"Max filters: {max_filters}")
        print(f"Available: {len(available_filters)} filters")
        print(f"{'='*70}")
        
        selected_filters = []
        all_results = []
        
        for iteration in range(max_filters):
            print(f"\n🔍 Iteration {iteration + 1}: Testing {len(available_filters)} candidates...")
            
            best_result = None
            best_filter = None
            tested = 0
            
            for candidate_filter in available_filters:
                test_filters = selected_filters + [candidate_filter]
                
                # Use default params for now
                filter_params = {f: {} for f in test_filters}
                
                result = self._evaluate_combination(test_filters, filter_params)
                
                if best_result is None or result.val_win_rate > best_result.val_win_rate:
                    best_result = result
                    best_filter = candidate_filter
                
                tested += 1
                if tested % 5 == 0:
                    print(f"  Progress: {tested}/{len(available_filters)}")
            
            if best_result and best_result.val_total_signals >= self.min_signals:
                selected_filters.append(best_filter)
                available_filters.remove(best_filter)
                all_results.append(best_result)
                
                print(f"\n  ✅ Added: {best_filter}")
                print(f"     Val WR: {best_result.val_win_rate*100:.1f}%")
                print(f"     Signals: {best_result.val_total_signals} ({best_result.signals_retained_pct:.1f}%)")
                print(f"     Beats baseline: {best_result.beats_baseline}")
            else:
                print("  ⚠️  No improvement found, stopping.")
                break
        
        self.results.extend(all_results)
        return all_results
    
    def random_search(self, n_iterations: int = 100, max_filters: int = 5) -> List[FilterCombinationResult]:
        """Random search - test random filter combinations"""
        available_filters = list(get_available_filters())
        
        print(f"\n{'='*70}")
        print(f"RANDOM SEARCH")
        print(f"Iterations: {n_iterations}")
        print(f"Available: {len(available_filters)} filters")
        print(f"{'='*70}")
        
        all_results = []
        
        for i in range(n_iterations):
            num_filters = random.randint(1, min(max_filters, len(available_filters)))
            filter_names = random.sample(available_filters, num_filters)
            filter_params = {f: {} for f in filter_names}
            
            result = self._evaluate_combination(filter_names, filter_params)
            all_results.append(result)
            
            if (i + 1) % 20 == 0:
                print(f"  Progress: {i + 1}/{n_iterations}")
        
        self.results.extend(all_results)
        return all_results
    
    # ========================================
    # RESULTS ANALYSIS
    # ========================================
    
    def get_top_results(self, n: int = 10) -> List[FilterCombinationResult]:
        """Get top N results sorted by validation win rate"""
        valid_results = [
            r for r in self.results
            if r.val_total_signals >= self.min_signals
        ]
        
        valid_results.sort(key=lambda x: x.val_win_rate, reverse=True)
        return valid_results[:n]
    
    def print_summary(self, top_n: int = 10):
        """Print optimization summary"""
        print(f"\n{'='*70}")
        print("OPTIMIZATION RESULTS")
        print(f"{'='*70}")
        
        print(f"\nTotal combinations tested: {len(self.results)}")
        print(f"Baseline win rate: {self.baseline_wr*100:.1f}%")
        
        top_results = self.get_top_results(top_n)
        
        if not top_results:
            print("\n⚠️  No valid results (not enough signals passed filters)")
            return
        
        print(f"\n🏆 Top {len(top_results)} filter combinations:\n")
        
        for i, result in enumerate(top_results, 1):
            print(f"{i}. Filters: {result.filters if result.filters else 'None'}")
            print(f"   Val WR: {result.val_win_rate*100:.1f}% ({result.val_winners}W / {result.val_losers}L)")
            print(f"   Train WR: {result.train_win_rate*100:.1f}%")
            print(f"   Signals: {result.val_total_signals} ({result.signals_retained_pct:.1f}% retained)")
            print(f"   Profit Factor: {result.val_profit_factor:.2f}")
            print(f"   Beats baseline: {'✅' if result.beats_baseline else '❌'}")
            print()
    
    def save_results(self, filename: str = "filter_optimization_results.json"):
        """Save results to JSON"""
        results_data = []
        
        for result in self.results:
            results_data.append({
                'filters': result.filters,
                'train_win_rate': result.train_win_rate,
                'val_win_rate': result.val_win_rate,
                'val_total_signals': result.val_total_signals,
                'val_profit_factor': result.val_profit_factor,
                'signals_retained_pct': result.signals_retained_pct,
                'beats_baseline': result.beats_baseline,
                'timestamp': result.timestamp
            })
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"\n💾 Results saved to {filename}")


# ========================================
# MAIN
# ========================================

def main():
    """Run filter optimization"""
    
    print("="*70)
    print("WAR MACHINE FILTER OPTIMIZER")
    print("Real filter testing with market data")
    print("="*70)
    
    # Show available filters
    available = get_available_filters()
    print(f"\n📊 Available filters ({len(available)}):")
    for i, f in enumerate(available, 1):
        print(f"  {i:2d}. {f}")
    
    # Initialize
    optimizer = FilterCombinationOptimizer(
        signals_csv="validation_signals.csv",
        baseline_wr=0.73,
        min_signals=20
    )
    
    if optimizer.baseline_signals.empty:
        print("\n❌ Cannot proceed without signals data")
        return
    
    print("\n" + "="*70)
    print("SELECT STRATEGY")
    print("="*70)
    print("1. Greedy Forward Selection (recommended)")
    print("2. Random Search (faster)")
    
    choice = input("\nChoice (1-2) [1]: ").strip() or "1"
    
    if choice == "1":
        optimizer.greedy_forward_selection(max_filters=5)
    else:
        optimizer.random_search(n_iterations=100, max_filters=5)
    
    optimizer.print_summary(top_n=10)
    optimizer.save_results()
    
    print("\n" + "="*70)
    print("✅ COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()
