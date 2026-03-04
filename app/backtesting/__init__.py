"""
Backtesting Module - Historical Strategy Validation

Provides:
  - Historical signal replay
  - Walk-forward validation
  - Parameter optimization (grid search, genetic algorithm)
  - Performance metrics (Sharpe, Sortino, max drawdown, etc.)

Usage:
  from app.backtesting import BacktestEngine, WalkForward, ParameterOptimizer
  
  engine = BacktestEngine(initial_capital=10000)
  results = engine.run(ticker='AAPL', start_date='2025-01-01', end_date='2026-01-01')
  print(results.summary())
"""
from app.backtesting.backtest_engine import BacktestEngine, BacktestResults
from app.backtesting.performance_metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_expectancy
)

__all__ = [
    'BacktestEngine',
    'BacktestResults',
    'calculate_sharpe_ratio',
    'calculate_sortino_ratio',
    'calculate_max_drawdown',
    'calculate_win_rate',
    'calculate_profit_factor',
    'calculate_expectancy'
]
