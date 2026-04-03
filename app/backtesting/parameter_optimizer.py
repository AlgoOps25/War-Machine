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

BUG-PO-2 (Apr 03, 2026):
  grid_search() passed raw CLI params to engine.run() without injecting
  _ticker, so war_machine_strategy never merged TICKER_PARAMS during the
  optimizer sweep. Low-vol tickers (AAPL/MSFT) ran with default rvol_min=1.5
  and fvg_min_size_pct=0.005 instead of their per-ticker overrides, producing
  far fewer trades than the live strategy would. Fix: inject ticker as
  _ticker in every param combo passed to engine.run().

BUG-PO-3 (Apr 03, 2026):
  min_trades default of 10 silently dropped all combos for low-frequency
  tickers (AAPL 5 trades, NVDA 8 trades on 59-day windows), returning
  valid=0/27 and causing WalkForward.run() to skip the window entirely.
  Fix: lowered default to 5. Walk-forward windows are already short (1m/1m
  on ~59-day data = ~20 trading days per test window); 5 trades is a
  reasonable floor for OOS evaluation without over-filtering sparse tickers.
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
                 min_trades: int = 5):
        """
        Args:
            initial_capital: Starting capital for backtests
            optimization_metric: Metric to optimize
                Options: 'sharpe_ratio', 'sortino_ratio', 'profit_factor',
                         'win_rate', 'expectancy', 'total_return_pct'
            min_trades: Minimum trades required to consider result valid.
                BUG-PO-3: lowered from 10 to 5. Short walk-forward windows
                (~20 trading days) on sparse tickers produce 5-9 trades per
                combo; the old floor of 10 silently returned valid=0/27.
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

            # BUG-PO-2: inject _ticker so war_machine_strategy merges TICKER_PARAMS
            # during the optimizer sweep (same as run_single does for live runs).
            # Without this, low-vol tickers used default rvol_min/fvg_min_size_pct
            # and produced far fewer trades than the live strategy would.
            params_with_ticker = dict(params)
            params_with_ticker['_ticker'] = ticker

            logger.debug(f"[OPTIMIZER] [{i}/{total_combinations}] Testing: {params}")

            engine = BacktestEngine(initial_capital=self.initial_capital)

            try:
                backtest_results = engine.run(
                    ticker=ticker,
                    bars=bars,
                    strategy=strategy,
                    strategy_params=params_with_ticker,
                )

                if backtest_results.total_trades < self.min_trades:
                    logger.debug(f"[OPTIMIZER] Skipped (only {backtest_results.total_trades} trades < min={self.min_trades})")
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
