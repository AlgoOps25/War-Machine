"""
Parameter Optimizer - Grid Search for Strategy Tuning

Finds optimal parameters by:
  1. Testing all combinations in param grid
  2. Ranking by specified metric (Sharpe, profit factor, etc.)
  3. Returning top N parameter sets

Example:
  optimizer = ParameterOptimizer()
  
  param_grid = {
      'volume_threshold': [2.0, 2.5, 3.0],
      'min_confidence': [60, 65, 70],
      'lookback_bars': [10, 12, 15]
  }
  
  results = optimizer.grid_search(
      ticker='AAPL',
      bars=historical_bars,
      strategy=my_strategy,
      param_grid=param_grid
  )
  
  best_params = results[0]['params']
"""
from typing import Dict, List, Callable, Tuple
from itertools import product
from dataclasses import dataclass

from app.backtesting.backtest_engine import BacktestEngine, BacktestResults


@dataclass
class OptimizationResult:
    """Single parameter set result."""
    params: Dict
    results: BacktestResults
    metric_value: float


class ParameterOptimizer:
    """Grid search parameter optimization."""
    
    def __init__(self,
                 initial_capital: float = 10000,
                 optimization_metric: str = 'sharpe_ratio',
                 min_trades: int = 10):
        """
        Args:
            initial_capital: Starting capital for backtests
            optimization_metric: Metric to optimize
                Options: 'sharpe_ratio', 'sortino_ratio', 'profit_factor',
                         'win_rate', 'expectancy', 'total_return_pct'
            min_trades: Minimum trades required to consider result valid
        """
        self.initial_capital = initial_capital
        self.optimization_metric = optimization_metric
        self.min_trades = min_trades
        
        self.valid_metrics = [
            'sharpe_ratio', 'sortino_ratio', 'profit_factor',
            'win_rate', 'expectancy', 'total_return_pct'
        ]
        
        if optimization_metric not in self.valid_metrics:
            raise ValueError(f"Invalid metric: {optimization_metric}. Choose from {self.valid_metrics}")
        
        print(f"[OPTIMIZER] Initialized")
        print(f"  Capital: ${initial_capital:,.2f}")
        print(f"  Optimizing: {optimization_metric}")
        print(f"  Min trades: {min_trades}")
    
    def grid_search(self,
                    ticker: str,
                    bars: List[Dict],
                    strategy: Callable,
                    param_grid: Dict[str, List],
                    top_n: int = 5) -> List[Dict]:
        """
        Perform grid search over parameter combinations.
        
        Args:
            ticker: Stock ticker
            bars: Historical OHLCV bars
            strategy: Strategy function
            param_grid: Dict of param_name -> list of values to test
            top_n: Return top N results
        
        Returns:
            List of dicts with 'params', 'results', 'metric_value'
        """
        print(f"\n[OPTIMIZER] Starting grid search for {ticker}")
        print(f"  Parameter grid: {param_grid}")
        
        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        
        total_combinations = len(combinations)
        print(f"  Total combinations: {total_combinations}")
        
        # Test each combination
        results = []
        
        for i, combo in enumerate(combinations, 1):
            # Create param dict
            params = dict(zip(param_names, combo))
            
            print(f"\n  [{i}/{total_combinations}] Testing: {params}")
            
            # Run backtest
            engine = BacktestEngine(initial_capital=self.initial_capital)
            
            try:
                backtest_results = engine.run(
                    ticker=ticker,
                    bars=bars,
                    strategy=strategy,
                    strategy_params=params
                )
                
                # Check if result is valid
                if backtest_results.total_trades < self.min_trades:
                    print(f"    Skipped (only {backtest_results.total_trades} trades)")
                    continue
                
                # Get metric value
                metric_value = getattr(backtest_results, self.optimization_metric)
                
                results.append({
                    'params': params,
                    'results': backtest_results,
                    'metric_value': metric_value
                })
                
                print(f"    {self.optimization_metric}: {metric_value:.2f} | "
                      f"Trades: {backtest_results.total_trades} | "
                      f"P&L: ${backtest_results.net_pnl:,.2f}")
                
            except Exception as e:
                print(f"    Error: {e}")
                continue
        
        # Sort by metric value (descending)
        results.sort(key=lambda x: x['metric_value'], reverse=True)
        
        # Return top N
        top_results = results[:top_n]
        
        print(f"\n[OPTIMIZER] Grid search complete")
        print(f"  Valid results: {len(results)} / {total_combinations}")
        
        if top_results:
            print(f"\n  TOP {len(top_results)} RESULTS:")
            for i, result in enumerate(top_results, 1):
                print(f"    #{i} {result['params']}")
                print(f"        {self.optimization_metric}: {result['metric_value']:.2f} | "
                      f"Trades: {result['results'].total_trades} | "
                      f"P&L: ${result['results'].net_pnl:,.2f}")
        
        return top_results


if __name__ == "__main__":
    print("Parameter Optimizer - Example Usage")
    print("="*80)
    print("\nSee docs/task10_backtesting_guide.md for examples.")
