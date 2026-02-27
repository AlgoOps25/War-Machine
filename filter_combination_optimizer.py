"""
War Machine Filter Combination Optimizer - Phase 4
COMPLETE VERSION with all methods implemented
Uses YOUR EODHD plan features (no fundamentals)
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

from market_filters import MarketFilters
from config import WarMachineConfig

# ========================================
# AVAILABLE FILTERS (YOUR EODHD PLAN)
# ========================================

def get_available_filters_for_your_plan():
    """
    Filters compatible with YOUR exact EODHD plan:
    - EOD + Intraday All World Extended ($29.99/mo)
    - US Stock Options Data API ($29.99/mo)
    """
    return {
        'basic_filters': [
            'price_range', 'volume_surge', 'gap_size', 'volume_profile',
            'premarket_volume', 'morning_range', 'intraday_momentum', 'consolidation'
        ],
        'technical_filters': [
            'atr_threshold', 'trend_alignment', 'bollinger_position', 'macd_signal',
            'rsi_threshold', 'stochastic', 'adx_strength', 'momentum_quality', 'volatility_regime'
        ],
        'options_filters': [
            'options_volume', 'implied_volatility', 'options_oi_change',
            'put_call_ratio', 'gamma_exposure', 'vanna_charm'
        ],
        'market_filters': [
            'time_of_day', 'vix_level', 'market_breadth'
        ],
        'fundamentals_excluded': [
            'market_cap', 'sector', 'earnings_date', 'short_interest',
            'analyst_rating', 'institutional_holding', 'pe_ratio', 'earnings_surprise'
        ]
    }


def get_compatible_filters():
    """Get list of all compatible filters"""
    filters = get_available_filters_for_your_plan()
    return (
        filters['basic_filters'] + 
        filters['technical_filters'] + 
        filters['options_filters'] + 
        filters['market_filters']
    )


def print_filter_categories():
    """Print available filters by category"""
    filters = get_available_filters_for_your_plan()
    
    print("="*70)
    print("AVAILABLE FILTERS FOR YOUR EODHD PLAN")
    print("="*70)
    
    print("\n✅ PRICE & VOLUME FILTERS (EOD + Intraday Plan)")
    for i, f in enumerate(filters['basic_filters'], 1):
        print(f"  {i:2d}. {f}")
    
    print("\n✅ TECHNICAL INDICATORS (Built-in with your plan)")
    for i, f in enumerate(filters['technical_filters'], 1):
        print(f"  {i:2d}. {f}")
    
    print("\n✅ OPTIONS FILTERS (Your Options Data API)")
    for i, f in enumerate(filters['options_filters'], 1):
        print(f"  {i:2d}. {f}")
    
    print("\n✅ MARKET CONDITION FILTERS (No API needed)")
    for i, f in enumerate(filters['market_filters'], 1):
        print(f"  {i:2d}. {f}")
    
    print(f"\n📊 TOTAL AVAILABLE: {len(get_compatible_filters())} filters")
    
    print("\n" + "="*70)
    print("❌ EXCLUDED FILTERS (Require Fundamentals Plan - $59.99/mo)")
    print("="*70)
    for i, f in enumerate(filters['fundamentals_excluded'], 1):
        print(f"  {i:2d}. {f}")
    print("\nUpgrade at: https://eodhd.com/pricing")


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
    """Optimize filter combinations to improve baseline performance"""
    
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
        
        self.filters = MarketFilters()
        self.config = WarMachineConfig()
        
        # Load baseline signals
        self.baseline_signals = self._load_baseline_signals()
        
        # Split into train/validation
        self.train_signals, self.val_signals = self._split_train_val(
            self.baseline_signals, 
            split_ratio=0.7
        )
        
        # Results storage
        self.results: List[FilterCombinationResult] = []
        self.best_result: Optional[FilterCombinationResult] = None
        
        print(f"Loaded {len(self.baseline_signals)} baseline signals")
        print(f"Train: {len(self.train_signals)}, Validation: {len(self.val_signals)}")
        print(f"Baseline WR: {baseline_wr*100:.1f}%")
    
    def _load_baseline_signals(self) -> pd.DataFrame:
        """Load baseline signals from CSV"""
        if Path(self.signals_csv).exists():
            df = pd.read_csv(self.signals_csv)
            print(f"Loaded signals from {self.signals_csv}")
            return df
        else:
            print(f"Signals file not found: {self.signals_csv}")
            print("Run validation script first to generate signals")
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
        """Test statistical significance"""
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
    
    def exhaustive_search(self, max_filters: int = 3, filter_whitelist: Optional[List[str]] = None) -> List[FilterCombinationResult]:
        """Exhaustive search"""
        available_filters = filter_whitelist or get_compatible_filters()
        
        print(f"\n{'='*70}")
        print(f"EXHAUSTIVE SEARCH - Max {max_filters} filters")
        print(f"Using {len(available_filters)} compatible filters")
        print(f"{'='*70}")
        
        all_results = []
        total_combinations = sum(
            len(list(combinations(available_filters, r)))
            for r in range(1, max_filters + 1)
        )
        
        print(f"Testing {total_combinations} combinations...")
        
        tested = 0
        for num_filters in range(1, max_filters + 1):
            for filter_combo in combinations(available_filters, num_filters):
                filter_names = list(filter_combo)
                
                self.config.load_preset('baseline')
                for fname in filter_names:
                    self.config.enable_filter(fname)
                filter_params = self.config.get_filter_params()
                
                result = self._evaluate_combination(filter_names, filter_params)
                all_results.append(result)
                
                tested += 1
                if tested % 100 == 0:
                    print(f"  Progress: {tested}/{total_combinations} ({tested/total_combinations*100:.1f}%)")
        
        self.results.extend(all_results)
        return all_results
    
    def greedy_forward_selection(self, max_filters: int = 5, filter_whitelist: Optional[List[str]] = None) -> List[FilterCombinationResult]:
        """Greedy forward selection"""
        available_filters = set(filter_whitelist or get_compatible_filters())
        
        print(f"\n{'='*70}")
        print(f"GREEDY FORWARD SELECTION - Max {max_filters} filters")
        print(f"Using {len(available_filters)} compatible filters")
        print(f"{'='*70}")
        
        selected_filters = []
        all_results = []
        
        for iteration in range(max_filters):
            print(f"\nIteration {iteration + 1}: Testing {len(available_filters)} candidates...")
            
            best_result = None
            best_filter = None
            
            for candidate_filter in available_filters:
                test_filters = selected_filters + [candidate_filter]
                
                self.config.load_preset('baseline')
                for fname in test_filters:
                    self.config.enable_filter(fname)
                filter_params = self.config.get_filter_params()
                
                result = self._evaluate_combination(test_filters, filter_params)
                
                if best_result is None or result.val_win_rate > best_result.val_win_rate:
                    best_result = result
                    best_filter = candidate_filter
            
            if best_result and (not selected_filters or best_result.val_win_rate > self.baseline_wr):
                selected_filters.append(best_filter)
                available_filters.remove(best_filter)
                all_results.append(best_result)
                
                print(f"  Added: {best_filter}")
                print(f"  Val WR: {best_result.val_win_rate*100:.1f}%")
                print(f"  Signals: {best_result.val_total_signals}")
            else:
                print("  No improvement found, stopping.")
                break
        
        self.results.extend(all_results)
        return all_results
    
    def genetic_algorithm_search(self, population_size: int = 50, generations: int = 20, mutation_rate: float = 0.15, filter_whitelist: Optional[List[str]] = None) -> List[FilterCombinationResult]:
        """Genetic algorithm search"""
        available_filters = list(filter_whitelist or get_compatible_filters())
        
        print(f"\n{'='*70}")
        print(f"GENETIC ALGORITHM SEARCH")
        print(f"Population: {population_size}, Generations: {generations}")
        print(f"Using {len(available_filters)} compatible filters")
        print(f"{'='*70}")
        
        # Initialize population
        population = []
        for _ in range(population_size):
            num_filters = random.randint(1, 5)
            filters = random.sample(available_filters, min(num_filters, len(available_filters)))
            population.append(filters)
        
        all_results = []
        best_ever = None
        
        for gen in range(generations):
            print(f"\nGeneration {gen + 1}/{generations}")
            
            gen_results = []
            for filter_combo in population:
                self.config.load_preset('baseline')
                for fname in filter_combo:
                    self.config.enable_filter(fname)
                filter_params = self.config.get_filter_params()
                
                result = self._evaluate_combination(filter_combo, filter_params)
                gen_results.append((filter_combo, result))
            
            gen_results.sort(key=lambda x: x[1].val_win_rate, reverse=True)
            
            best_this_gen = gen_results[0][1]
            if best_ever is None or best_this_gen.val_win_rate > best_ever.val_win_rate:
                best_ever = best_this_gen
            
            print(f"  Best WR: {best_this_gen.val_win_rate*100:.1f}%")
            print(f"  Best filters: {gen_results[0][0]}")
            
            all_results.extend([r for _, r in gen_results[:10]])
            
            # Selection
            survivors = [combo for combo, _ in gen_results[:population_size // 2]]
            
            # Crossover & Mutation
            new_population = survivors.copy()
            
            while len(new_population) < population_size:
                parent1, parent2 = random.sample(survivors, 2)
                child = list(set(parent1 + parent2))
                
                if random.random() < mutation_rate:
                    if random.random() < 0.5 and len(child) > 1:
                        child.remove(random.choice(child))
                    else:
                        new_filter = random.choice(available_filters)
                        if new_filter not in child and len(child) < 10:
                            child.append(new_filter)
                
                new_population.append(child)
            
            population = new_population
        
        self.results.extend(all_results)
        return all_results
    
    def random_search(self, n_iterations: int = 100, max_filters: int = 5, filter_whitelist: Optional[List[str]] = None) -> List[FilterCombinationResult]:
        """Random search"""
        available_filters = list(filter_whitelist or get_compatible_filters())
        
        print(f"\n{'='*70}")
        print(f"RANDOM SEARCH - {n_iterations} iterations")
        print(f"Using {len(available_filters)} compatible filters")
        print(f"{'='*70}")
        
        all_results = []
        
        for i in range(n_iterations):
            num_filters = random.randint(1, min(max_filters, len(available_filters)))
            filter_names = random.sample(available_filters, num_filters)
            
            self.config.load_preset('baseline')
            for fname in filter_names:
                self.config.enable_filter(fname)
            filter_params = self.config.get_filter_params()
            
            result = self._evaluate_combination(filter_names, filter_params)
            all_results.append(result)
            
            if (i + 1) % 20 == 0:
                print(f"  Progress: {i + 1}/{n_iterations}")
        
        self.results.extend(all_results)
        return all_results
    
    # ========================================
    # RESULTS ANALYSIS
    # ========================================
    
    def get_top_results(self, n: int = 10, min_signals: Optional[int] = None) -> List[FilterCombinationResult]:
        """Get top N results"""
        min_sig = min_signals or self.min_signals
        
        valid_results = [
            r for r in self.results
            if r.val_total_signals >= min_sig and r.beats_baseline
        ]
        
        valid_results.sort(key=lambda x: x.val_win_rate, reverse=True)
        return valid_results[:n]
    
    def print_summary(self, top_n: int = 10):
        """Print summary"""
        print(f"\n{'='*70}")
        print("FILTER COMBINATION OPTIMIZATION SUMMARY")
        print(f"{'='*70}")
        
        print(f"\nTotal combinations tested: {len(self.results)}")
        print(f"Baseline win rate: {self.baseline_wr*100:.1f}%")
        
        top_results = self.get_top_results(top_n)
        
        if not top_results:
            print("\nNo combinations beat the baseline!")
            return
        
        print(f"\nTop {len(top_results)} combinations that beat baseline:\n")
        
        for i, result in enumerate(top_results, 1):
            print(f"{i}. {', '.join(result.filters)}")
            print(f"   Val WR: {result.val_win_rate*100:.1f}% (Train: {result.train_win_rate*100:.1f}%)")
            print(f"   Val Signals: {result.val_total_signals} ({result.signals_retained_pct:.1f}% of baseline)")
            print(f"   Val PF: {result.val_profit_factor:.2f}")
            print(f"   Degradation: {result.degradation_pct:.1f}%")
            print(f"   Significant: {result.is_statistically_significant}")
            print()
    
    def save_results(self, filename: str = "filter_optimization_results.json"):
        """Save results"""
        results_data = []
        
        for result in self.results:
            results_data.append({
                'filters': result.filters,
                'filter_params': result.filter_params,
                'train_win_rate': result.train_win_rate,
                'train_total_signals': result.train_total_signals,
                'val_win_rate': result.val_win_rate,
                'val_total_signals': result.val_total_signals,
                'val_profit_factor': result.val_profit_factor,
                'degradation_pct': result.degradation_pct,
                'signals_retained_pct': result.signals_retained_pct,
                'beats_baseline': result.beats_baseline,
                'is_statistically_significant': result.is_statistically_significant,
                'timestamp': result.timestamp,
                'execution_time': result.execution_time
            })
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"\nResults saved to {filename}")
    
    def export_top_configs(self, n: int = 5, output_dir: str = "optimized_configs"):
        """Export top configs"""
        Path(output_dir).mkdir(exist_ok=True)
        
        top_results = self.get_top_results(n)
        
        for i, result in enumerate(top_results, 1):
            config = WarMachineConfig()
            config.load_preset('baseline')
            
            for filter_name in result.filters:
                config.enable_filter(filter_name)
                if filter_name in result.filter_params:
                    config.update_filter_params(filter_name, result.filter_params[filter_name])
            
            filename = f"{output_dir}/config_rank{i}_wr{result.val_win_rate*100:.1f}.json"
            config.save_to_file(filename)
            
            print(f"Exported config #{i}: {filename}")


# ========================================
# MAIN EXECUTION
# ========================================

def main():
    """Run filter combination optimization"""
    
    print("="*70)
    print("WAR MACHINE FILTER OPTIMIZER")
    print("Using YOUR EODHD Plan Features:")
    print("  - EOD + Intraday All World Extended")
    print("  - US Stock Options Data API")
    print("="*70)
    
    print_filter_categories()
    
    optimizer = FilterCombinationOptimizer(
        signals_csv="validation_signals.csv",
        baseline_wr=0.73,
        min_signals=20
    )
    
    print("\n" + "="*70)
    print("SELECT OPTIMIZATION STRATEGY")
    print("="*70)
    print("1. Greedy Forward Selection (recommended - fast & effective)")
    print("2. Random Search (quick exploration)")
    print("3. Genetic Algorithm (thorough but slow)")
    print("4. Exhaustive Search (very slow, max 3 filters)")
    
    choice = input("\nEnter choice (1-4) [1]: ").strip() or "1"
    
    if choice == "1":
        optimizer.greedy_forward_selection(max_filters=5)
    elif choice == "2":
        optimizer.random_search(n_iterations=200, max_filters=5)
    elif choice == "3":
        optimizer.genetic_algorithm_search(population_size=50, generations=20)
    elif choice == "4":
        optimizer.exhaustive_search(max_filters=3)
    else:
        print("Invalid choice, using Greedy Forward Selection")
        optimizer.greedy_forward_selection(max_filters=5)
    
    optimizer.print_summary(top_n=10)
    optimizer.save_results("filter_optimization_results.json")
    optimizer.export_top_configs(n=5, output_dir="optimized_configs")
    
    print("\n" + "="*70)
    print("OPTIMIZATION COMPLETE")
    print("="*70)
    print("\nNext steps:")
    print("1. Review top configurations in optimized_configs/")
    print("2. Backtest top configs with realistic_backtest.py")
    print("3. Deploy best config to production scanner")


if __name__ == "__main__":
    main()
