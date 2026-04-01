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

FIX S21 (APR 1, 2026):
  BUG-PO-1: metric_value could be float('inf') when profit_factor has zero
    gross loss (all-winner run on thin data). inf sorts to the top silently,
    making an unreliable parameter set appear optimal. Capped at
    _METRIC_INF_CAP (10.0) before appending to results list.
"""
from typing import Dict, List, Callable
from itertools import product
from dataclasses import dataclass
import math

from app.backtesting.backtest_engine import BacktestEngine, BacktestResults
import logging

logger = logging.getLogger(__name__)

# Finite cap applied to any metric_value that resolves to inf/nan.
# Keeps sort stable and prevents thin-data all-winner runs from
# appearing as the best parameter set.
_METRIC_INF_CAP = 10.0


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
            'win_rate', 'expectancy', 'total_return_pct',
        ]

        if optimization_metric not in self.valid_metrics:
            raise ValueError(f"Invalid metric: {optimization_metric}. Choose from {self.valid_metrics}")

        logger.debug(f"[OPTIMIZER] Initialized — capital=${initial_capital:,.2f}, metric={optimization_metric}, min_trades={min_trades}")

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
        logger.info(f"[OPTIMIZER] Starting grid search for {ticker} | grid={param_grid}")

        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        total_combinations = len(combinations)

        logger.info(f"[OPTIMIZER] Total combinations: {total_combinations}")

        results = []

        for i, combo in enumerate(combinations, 1):
            params = dict(zip(param_names, combo))
            logger.debug(f"[OPTIMIZER] [{i}/{total_combinations}] Testing: {params}")

            engine = BacktestEngine(initial_capital=self.initial_capital)

            try:
                backtest_results = engine.run(
                    ticker=ticker,
                    bars=bars,
                    strategy=strategy,
                    strategy_params=params
                )

                if backtest_results.total_trades < self.min_trades:
                    logger.debug(f"[OPTIMIZER] Skipped (only {backtest_results.total_trades} trades)")
                    continue

                raw_metric = getattr(backtest_results, self.optimization_metric)

                # BUG-PO-1: cap inf/nan so thin-data all-winner runs don't
                # silently float to the top of the sorted results.
                if not math.isfinite(raw_metric):
                    logger.debug(
                        f"[OPTIMIZER] [{i}/{total_combinations}] metric_value={raw_metric} "
                        f"capped to {_METRIC_INF_CAP} (params={params})"
                    )
                    raw_metric = _METRIC_INF_CAP

                results.append({
                    'params': params,
                    'results': backtest_results,
                    'metric_value': raw_metric,
                })

                logger.info(
                    f"[OPTIMIZER] [{i}/{total_combinations}] {self.optimization_metric}={raw_metric:.2f} "
                    f"trades={backtest_results.total_trades} pnl=${backtest_results.net_pnl:,.2f}"
                )

            except Exception as e:
                logger.warning(f"[OPTIMIZER] [{i}/{total_combinations}] Error: {e}")
                continue

        results.sort(key=lambda x: x['metric_value'], reverse=True)
        top_results = results[:top_n]

        logger.info(f"[OPTIMIZER] Grid search complete — valid={len(results)}/{total_combinations}")

        if top_results:
            logger.info(f"[OPTIMIZER] TOP {len(top_results)} RESULTS:")
            for i, result in enumerate(top_results, 1):
                logger.info(
                    f"  #{i} {result['params']} "
                    f"{self.optimization_metric}={result['metric_value']:.2f} "
                    f"trades={result['results'].total_trades} "
                    f"pnl=${result['results'].net_pnl:,.2f}"
                )

        return top_results


if __name__ == "__main__":
    logger.info("Parameter Optimizer - Example Usage")
    logger.info("=" * 80)
    logger.info("See docs/task10_backtesting_guide.md for examples.")
