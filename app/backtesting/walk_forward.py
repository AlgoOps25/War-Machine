"""
Walk-Forward Validation - Out-of-Sample Testing

Prevents overfitting by:
  1. Split data into train/test windows
  2. Optimize on train window
  3. Test on OOS test window
  4. Roll forward and repeat

Example:
  Train: Jan-Mar (optimize parameters)
  Test:  Apr (validate on unseen data)

  Train: Feb-Apr (re-optimize)
  Test:  May (validate)

  ... continue rolling forward

Usage:
  wf = WalkForward(
      train_months=3,
      test_months=1,
      step_months=1
  )

  results = wf.run(
      ticker='AAPL',
      bars=historical_bars,
      strategy=my_strategy,
      param_grid={'volume_threshold': [2.0, 3.0], 'min_confidence': [60, 70]}
  )

NOTE (BUG-WF-1, S21): Window boundaries are computed as timedelta(days=30 * months).
This is a known approximation — February and 31-day months cause 1-2 day drift per
window over long runs. For calendar-precise splits use dateutil.relativedelta.
"""
from typing import Dict, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
import statistics

from app.backtesting.backtest_engine import BacktestEngine, BacktestResults
from app.backtesting.parameter_optimizer import ParameterOptimizer
import logging

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    """Represents a single walk-forward window."""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_bars: List[Dict]
    test_bars: List[Dict]
    optimal_params: Dict = None
    train_results: BacktestResults = None
    test_results: BacktestResults = None


class WalkForwardResults:
    """Container for walk-forward validation results."""

    def __init__(self, windows: List[WalkForwardWindow], initial_capital: float):
        self.windows = windows
        self.initial_capital = initial_capital

        self.total_windows = len(windows)
        self.all_test_trades = []
        for window in windows:
            if window.test_results:
                self.all_test_trades.extend(window.test_results.trades)

        if self.all_test_trades:
            self.total_pnl = sum(t.pnl for t in self.all_test_trades)
            self.total_commission = sum(t.commission for t in self.all_test_trades)
            self.net_pnl = self.total_pnl - self.total_commission
            self.total_return_pct = self.net_pnl / initial_capital * 100

            from app.backtesting.performance_metrics import (
                calculate_win_rate,
                calculate_profit_factor,
                calculate_expectancy,
                calculate_sharpe_ratio,
            )

            self.win_rate = calculate_win_rate(self.all_test_trades)
            self.profit_factor = calculate_profit_factor(self.all_test_trades)
            self.expectancy = calculate_expectancy(self.all_test_trades)

            returns = [t.pnl_pct for t in self.all_test_trades]
            self.sharpe_ratio = calculate_sharpe_ratio(returns)
        else:
            self.total_pnl = 0
            self.net_pnl = 0
            self.total_return_pct = 0
            self.win_rate = 0
            self.profit_factor = 0
            self.expectancy = 0
            self.sharpe_ratio = 0

    def summary(self) -> str:
        """Return formatted summary of walk-forward results."""
        lines = []
        lines.append("=" * 80)
        lines.append("WALK-FORWARD VALIDATION RESULTS")
        lines.append("=" * 80)
        lines.append(f"Total Windows: {self.total_windows}")
        lines.append(f"Total OOS Trades: {len(self.all_test_trades)}")
        lines.append("")

        lines.append("AGGREGATE OOS PERFORMANCE:")
        lines.append(f"  Net P&L:       ${self.net_pnl:,.2f} ({self.total_return_pct:+.2f}%)")
        lines.append(f"  Win Rate:      {self.win_rate:.1f}%")
        lines.append(f"  Profit Factor: {self.profit_factor:.2f}")
        lines.append(f"  Expectancy:    ${self.expectancy:.2f}")
        lines.append(f"  Sharpe Ratio:  {self.sharpe_ratio:.2f}")
        lines.append("")

        lines.append("WINDOW-BY-WINDOW BREAKDOWN:")
        lines.append(f"{'Window':<8} {'Train Period':<25} {'Test Period':<25} {'OOS Trades':<12} {'OOS P&L':<15}")
        lines.append("-" * 80)

        for i, window in enumerate(self.windows, 1):
            train_period = f"{window.train_start.date()} to {window.train_end.date()}"
            test_period = f"{window.test_start.date()} to {window.test_end.date()}"

            if window.test_results:
                oos_trades = len(window.test_results.trades)
                oos_pnl = window.test_results.net_pnl
                lines.append(f"#{i:<7} {train_period:<25} {test_period:<25} {oos_trades:<12} ${oos_pnl:>13,.2f}")
            else:
                lines.append(f"#{i:<7} {train_period:<25} {test_period:<25} {'N/A':<12} {'N/A':<15}")

        lines.append("=" * 80)
        return "\n".join(lines)


class WalkForward:
    """Walk-forward validation engine."""

    def __init__(self,
                 train_months: int = 3,
                 test_months: int = 1,
                 step_months: int = 1,
                 optimization_metric: str = 'sharpe_ratio',
                 min_train_bars: int = 1000):
        """
        Args:
            train_months: Training window size in months
            test_months: Test window size in months
            step_months: Step size for rolling window
            optimization_metric: Metric to optimize
            min_train_bars: Minimum bars required in train window
        """
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months
        self.optimization_metric = optimization_metric
        self.min_train_bars = min_train_bars

        logger.info(
            f"[WALK-FORWARD] Initialized — train={train_months}m test={test_months}m "
            f"step={step_months}m optimize={optimization_metric}"
        )

    def create_windows(self, bars: List[Dict]) -> List[WalkForwardWindow]:
        """
        Create train/test windows from bars.

        NOTE: Month boundaries use timedelta(days=30 * months) — approximation.
        See module docstring (BUG-WF-1) for details.

        Args:
            bars: Historical OHLCV bars with 'datetime' field

        Returns:
            List of WalkForwardWindow objects
        """
        if not bars:
            return []

        windows = []
        start_date = bars[0]['datetime']
        end_date = bars[-1]['datetime']

        current_start = start_date

        while True:
            train_start = current_start
            train_end = train_start + timedelta(days=30 * self.train_months)

            test_start = train_end
            test_end = test_start + timedelta(days=30 * self.test_months)

            if test_end > end_date:
                break

            train_bars = [b for b in bars if train_start <= b['datetime'] < train_end]
            test_bars = [b for b in bars if test_start <= b['datetime'] < test_end]

            if len(train_bars) < self.min_train_bars or len(test_bars) < 100:
                current_start += timedelta(days=30 * self.step_months)
                continue

            windows.append(WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_bars=train_bars,
                test_bars=test_bars,
            ))

            current_start += timedelta(days=30 * self.step_months)

        return windows

    def run(self,
            ticker: str,
            bars: List[Dict],
            strategy: Callable,
            param_grid: Dict[str, List],
            initial_capital: float = 10000) -> WalkForwardResults:
        """
        Run walk-forward validation.

        Args:
            ticker: Stock ticker
            bars: Historical OHLCV bars
            strategy: Strategy function
            param_grid: Parameter grid for optimization
            initial_capital: Starting capital

        Returns:
            WalkForwardResults object
        """
        logger.info(f"[WALK-FORWARD] Starting validation for {ticker} | bars={len(bars)}")
        logger.info(f"  Period: {bars[0]['datetime'].date()} to {bars[-1]['datetime'].date()}")

        windows = self.create_windows(bars)
        logger.info(f"[WALK-FORWARD] Windows created: {len(windows)}")

        if not windows:
            logger.warning("[WALK-FORWARD] No valid windows created — insufficient data")
            return WalkForwardResults([], initial_capital)

        for i, window in enumerate(windows, 1):
            logger.info(
                f"[WALK-FORWARD] Window {i}/{len(windows)} — "
                f"Train: {window.train_start.date()}–{window.train_end.date()} ({len(window.train_bars)} bars) | "
                f"Test: {window.test_start.date()}–{window.test_end.date()} ({len(window.test_bars)} bars)"
            )

            optimizer = ParameterOptimizer(
                initial_capital=initial_capital,
                optimization_metric=self.optimization_metric,
            )

            train_results = optimizer.grid_search(
                ticker=ticker,
                bars=window.train_bars,
                strategy=strategy,
                param_grid=param_grid,
            )

            if not train_results:
                logger.warning(f"[WALK-FORWARD] Window {i}: no train results from optimization")
                continue

            best_result = train_results[0]
            window.optimal_params = best_result['params']
            window.train_results = best_result['results']

            logger.info(
                f"  [TRAIN] Best params: {window.optimal_params} "
                f"{self.optimization_metric}={getattr(best_result['results'], self.optimization_metric):.2f}"
            )

            engine = BacktestEngine(initial_capital=initial_capital)
            window.test_results = engine.run(
                ticker=ticker,
                bars=window.test_bars,
                strategy=strategy,
                strategy_params=window.optimal_params,
            )

            logger.info(
                f"  [TEST] OOS trades={len(window.test_results.trades)} "
                f"pnl=${window.test_results.net_pnl:,.2f} ({window.test_results.total_return_pct:+.1f}%) "
                f"win_rate={window.test_results.win_rate:.1f}%"
            )

        results = WalkForwardResults(windows, initial_capital)

        logger.info(
            f"[WALK-FORWARD] Complete — OOS trades={len(results.all_test_trades)} "
            f"pnl=${results.net_pnl:,.2f} ({results.total_return_pct:+.1f}%)"
        )

        return results


if __name__ == "__main__":
    logger.info("Walk-Forward Validation - Example Usage")
    logger.info("=" * 80)
    logger.info("See docs/task10_backtesting_guide.md for examples.")
