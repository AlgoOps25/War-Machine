"""
Performance Metrics - Statistical Analysis for Backtests

Provides:
  - Sharpe Ratio: Risk-adjusted returns
  - Sortino Ratio: Downside risk-adjusted returns
  - Max Drawdown: Largest peak-to-trough decline
  - Win Rate: Percentage of winning trades
  - Profit Factor: Gross profit / gross loss
  - Expectancy: Average $ per trade
  - Calmar Ratio: Return / max drawdown
  - Recovery Factor: Net profit / max drawdown

Usage:
  from app.backtesting.performance_metrics import calculate_sharpe_ratio

  returns = [0.02, -0.01, 0.03, -0.005, 0.015]
  sharpe = calculate_sharpe_ratio(returns)

FIX S21 (APR 1, 2026):
  BUG-PM-1: calculate_sortino_ratio() returned float('inf') when no
    downside returns exist (a perfect win streak). Callers propagate inf
    into logs, JSON serialisation, and numeric comparisons silently.
    Fixed: cap at 10.0 — a practical ceiling that signals "very low
    downside risk" without poisoning downstream arithmetic.
"""
from typing import List
import statistics
import logging

logger = logging.getLogger(__name__)

# Practical cap for ratios that would otherwise be float('inf').
# Calmar and recovery factor retain inf semantics (deliberate — they are
# used in display-only contexts). Sortino is used in numeric optimisation
# comparisons, so it gets a finite cap.
_SORTINO_INF_CAP = 10.0


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sharpe Ratio (risk-adjusted returns).

    Formula: (Mean Return - Risk Free Rate) / Std Dev of Returns

    Interpretation:
      > 1.0 = Good
      > 2.0 = Very good
      > 3.0 = Excellent

    Args:
        returns: List of trade returns (as decimals, e.g., 0.02 = 2%)
        risk_free_rate: Risk-free rate (default 0.0)

    Returns:
        Sharpe ratio
    """
    if not returns or len(returns) < 2:
        return 0.0

    mean_return = statistics.mean(returns)
    std_dev = statistics.stdev(returns)

    if std_dev == 0:
        return 0.0

    return (mean_return - risk_free_rate) / std_dev


def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sortino Ratio (downside risk-adjusted returns).

    Similar to Sharpe, but only considers downside volatility.
    More appropriate for asymmetric return distributions.

    Formula: (Mean Return - Risk Free Rate) / Downside Std Dev

    BUG-PM-1 fix: capped at _SORTINO_INF_CAP (10.0) when no downside
    returns exist, instead of returning float('inf').

    Args:
        returns: List of trade returns
        risk_free_rate: Risk-free rate

    Returns:
        Sortino ratio (capped at 10.0 for all-win streaks)
    """
    if not returns or len(returns) < 2:
        return 0.0

    mean_return = statistics.mean(returns)

    downside_returns = [r for r in returns if r < risk_free_rate]

    # BUG-PM-1: was float('inf') — poisons JSON serialisation and numeric comparisons
    if not downside_returns:
        return _SORTINO_INF_CAP

    downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else abs(downside_returns[0])

    if downside_std == 0:
        return 0.0

    return (mean_return - risk_free_rate) / downside_std


def calculate_max_drawdown(equity_curve: List[float]) -> float:
    """
    Calculate maximum drawdown from equity curve.

    Max drawdown = largest peak-to-trough decline in account value.

    Args:
        equity_curve: List of account values over time

    Returns:
        Max drawdown as percentage (e.g., 15.5 = 15.5% drawdown)
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0

    max_dd = 0.0
    peak = equity_curve[0]

    for value in equity_curve:
        if value > peak:
            peak = value

        drawdown = ((peak - value) / peak * 100) if peak > 0 else 0
        max_dd = max(max_dd, drawdown)

    return max_dd


def calculate_win_rate(trades: List) -> float:
    """
    Calculate win rate (percentage of profitable trades).

    Args:
        trades: List of Trade objects with 'pnl' attribute

    Returns:
        Win rate as percentage (e.g., 65.5 = 65.5%)
    """
    if not trades:
        return 0.0

    winners = sum(1 for t in trades if t.pnl > 0)
    return winners / len(trades) * 100


def calculate_profit_factor(trades: List) -> float:
    """
    Calculate profit factor (gross profit / gross loss).

    Interpretation:
      > 1.0 = Profitable
      > 2.0 = Good
      > 3.0 = Excellent

    Args:
        trades: List of Trade objects

    Returns:
        Profit factor
    """
    if not trades:
        return 0.0

    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def calculate_expectancy(trades: List) -> float:
    """
    Calculate expectancy (average $ per trade).

    Positive expectancy = profitable system over time.

    Args:
        trades: List of Trade objects

    Returns:
        Expectancy in dollars
    """
    if not trades:
        return 0.0

    total_pnl = sum(t.pnl for t in trades)
    return total_pnl / len(trades)


def calculate_calmar_ratio(total_return_pct: float, max_drawdown_pct: float) -> float:
    """
    Calculate Calmar Ratio (return / max drawdown).

    Measures return per unit of risk (drawdown).
    Higher is better.

    Args:
        total_return_pct: Total return as percentage
        max_drawdown_pct: Max drawdown as percentage

    Returns:
        Calmar ratio
    """
    if max_drawdown_pct == 0:
        return float('inf') if total_return_pct > 0 else 0.0

    return total_return_pct / max_drawdown_pct


def calculate_recovery_factor(net_profit: float, max_drawdown_dollars: float) -> float:
    """
    Calculate Recovery Factor (net profit / max drawdown $).

    Interpretation:
      > 2.0 = Good (profit is 2x max drawdown)
      > 5.0 = Excellent

    Args:
        net_profit: Net profit in dollars
        max_drawdown_dollars: Max drawdown in dollars

    Returns:
        Recovery factor
    """
    if max_drawdown_dollars == 0:
        return float('inf') if net_profit > 0 else 0.0

    return net_profit / max_drawdown_dollars


def calculate_trade_distribution_stats(trades: List) -> dict:
    """
    Calculate detailed trade distribution statistics.

    Args:
        trades: List of Trade objects

    Returns:
        Dict with distribution stats
    """
    if not trades:
        return {}

    pnls = [t.pnl for t in trades]
    winners = [t.pnl for t in trades if t.pnl > 0]
    losers = [t.pnl for t in trades if t.pnl < 0]

    return {
        'mean_pnl': statistics.mean(pnls),
        'median_pnl': statistics.median(pnls),
        'std_pnl': statistics.stdev(pnls) if len(pnls) > 1 else 0,
        'mean_winner': statistics.mean(winners) if winners else 0,
        'median_winner': statistics.median(winners) if winners else 0,
        'mean_loser': statistics.mean(losers) if losers else 0,
        'median_loser': statistics.median(losers) if losers else 0,
        'largest_winner': max(pnls),
        'largest_loser': min(pnls),
        'win_loss_ratio': abs(statistics.mean(winners) / statistics.mean(losers)) if winners and losers else 0,
    }


if __name__ == "__main__":
    logger.info("Performance Metrics - Example Usage")
    logger.info("=" * 80)

    returns = [0.02, -0.01, 0.03, -0.005, 0.015, 0.01, -0.02, 0.025]
    logger.info(f"Sample returns: {returns}")
    logger.info(f"Sharpe Ratio: {calculate_sharpe_ratio(returns):.2f}")
    logger.info(f"Sortino Ratio: {calculate_sortino_ratio(returns):.2f}")

    equity = [10000, 10200, 10100, 10400, 10350, 10500, 10300, 10600]
    logger.info(f"Sample equity curve: {equity}")
    logger.info(f"Max Drawdown: {calculate_max_drawdown(equity):.2f}%")
