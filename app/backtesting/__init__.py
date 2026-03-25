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
  logger.info(results.summary())
"""
import logging
logger = logging.getLogger(__name__)

from app.backtesting.backtest_engine import BacktestEngine, BacktestResults, Trade, Position
from app.backtesting.performance_metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_expectancy
)
from app.backtesting.walk_forward import WalkForward, WalkForwardResults
from app.backtesting.parameter_optimizer import ParameterOptimizer
from app.backtesting.signal_replay import (
    create_strategy_from_breakout_detector,
    create_strategy_from_signal_generator,
    example_simple_breakout_strategy
)

__all__ = [
    # Core engine
    'BacktestEngine',
    'BacktestResults',
    'Trade',
    'Position',
    
    # Performance metrics
    'calculate_sharpe_ratio',
    'calculate_sortino_ratio',
    'calculate_max_drawdown',
    'calculate_win_rate',
    'calculate_profit_factor',
    'calculate_expectancy',
    
    # Walk-forward validation
    'WalkForward',
    'WalkForwardResults',
    
    # Parameter optimization
    'ParameterOptimizer',
    
    # Signal replay helpers
    'create_strategy_from_breakout_detector',
    'create_strategy_from_signal_generator',
    'example_simple_breakout_strategy'
]
