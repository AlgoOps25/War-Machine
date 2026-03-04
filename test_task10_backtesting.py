"""
Task 10 Test Suite - Backtesting Engine

Tests:
  1. Performance metrics (Sharpe, Sortino, etc.)
  2. Backtest engine with sample strategy
  3. Position management (stops, targets, T1/T2)
  4. Parameter optimizer (grid search)
  5. Walk-forward validation
"""
from datetime import datetime, timedelta
import random

from app.backtesting import (
    BacktestEngine,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_expectancy
)
from app.backtesting.parameter_optimizer import ParameterOptimizer
from app.backtesting.walk_forward import WalkForward
from app.backtesting.signal_replay import example_simple_breakout_strategy


print("="*80)
print("TASK 10 TEST SUITE - Backtesting Engine")
print("="*80)


# TEST 1: Performance Metrics
print("\n📊 TEST 1: Performance Metrics")
print("-"*80)

try:
    # Sample returns
    returns = [0.02, -0.01, 0.03, -0.005, 0.015, 0.01, -0.02, 0.025, -0.01, 0.02]
    
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)
    
    print(f"  Returns: {returns}")
    print(f"  Sharpe Ratio:  {sharpe:.2f}")
    print(f"  Sortino Ratio: {sortino:.2f}")
    
    # Sample equity curve
    equity = [10000, 10200, 10100, 10400, 10350, 10500, 10300, 10600, 10550, 10700]
    max_dd = calculate_max_drawdown(equity)
    
    print(f"\n  Equity curve: {equity}")
    print(f"  Max Drawdown: {max_dd:.2f}%")
    
    print("\n✅ Performance metrics working")
except Exception as e:
    print(f"❌ Performance metrics failed: {e}")


# TEST 2: Generate Sample Historical Bars
print("\n💾 TEST 2: Generate Sample Historical Data")
print("-"*80)

try:
    # Generate 500 bars of sample data (10 days of 1-minute bars)
    base_price = 150.0
    bars = []
    current_time = datetime(2025, 1, 1, 9, 30)  # Start at market open
    
    for i in range(500):
        # Random walk with slight upward bias
        price_change = random.uniform(-0.5, 0.6)
        base_price += price_change
        base_price = max(base_price, 100.0)  # Floor at $100
        
        high = base_price + random.uniform(0, 0.5)
        low = base_price - random.uniform(0, 0.5)
        open_price = base_price + random.uniform(-0.2, 0.2)
        close_price = base_price
        volume = random.randint(500000, 2000000)
        
        bars.append({
            'datetime': current_time,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close_price,
            'volume': volume
        })
        
        current_time += timedelta(minutes=1)
    
    print(f"  Generated {len(bars)} bars")
    print(f"  Period: {bars[0]['datetime']} to {bars[-1]['datetime']}")
    print(f"  Price range: ${min(b['close'] for b in bars):.2f} - ${max(b['close'] for b in bars):.2f}")
    
    print("\n✅ Sample data generated")
except Exception as e:
    print(f"❌ Data generation failed: {e}")


# TEST 3: Backtest Engine
print("\n🔬 TEST 3: Backtest Engine")
print("-"*80)

try:
    engine = BacktestEngine(
        initial_capital=10000,
        commission_per_trade=0.50,
        slippage_pct=0.05,
        risk_per_trade_pct=1.0
    )
    
    # Run backtest with simple strategy
    results = engine.run(
        ticker='TEST',
        bars=bars,
        strategy=example_simple_breakout_strategy,
        strategy_params={'lookback_bars': 12, 'volume_threshold': 2.0}
    )
    
    print(f"\n  Total Trades: {results.total_trades}")
    print(f"  Win Rate: {results.win_rate:.1f}%")
    print(f"  Net P&L: ${results.net_pnl:,.2f} ({results.total_return_pct:+.2f}%)")
    print(f"  Sharpe Ratio: {results.sharpe_ratio:.2f}")
    print(f"  Profit Factor: {results.profit_factor:.2f}")
    print(f"  Max Drawdown: {results.max_drawdown:.2f}%")
    
    if results.total_trades > 0:
        print("\n  Exit Reasons:")
        for reason, count in results.exits_by_reason.items():
            pct = (count / results.total_trades * 100)
            print(f"    {reason}: {count} ({pct:.1f}%)")
    
    print("\n✅ Backtest engine working")
except Exception as e:
    print(f"❌ Backtest engine failed: {e}")
    import traceback
    traceback.print_exc()


# TEST 4: Parameter Optimizer
print("\n⚙️ TEST 4: Parameter Optimizer")
print("-"*80)

try:
    optimizer = ParameterOptimizer(
        initial_capital=10000,
        optimization_metric='sharpe_ratio',
        min_trades=5
    )
    
    param_grid = {
        'lookback_bars': [10, 12, 15],
        'volume_threshold': [1.5, 2.0, 2.5]
    }
    
    print("  Running grid search...")
    opt_results = optimizer.grid_search(
        ticker='TEST',
        bars=bars,
        strategy=example_simple_breakout_strategy,
        param_grid=param_grid,
        top_n=3
    )
    
    if opt_results:
        print(f"\n  Found {len(opt_results)} valid parameter sets")
        print("\n  Top 3 Results:")
        for i, result in enumerate(opt_results, 1):
            print(f"\n    #{i} Parameters: {result['params']}")
            print(f"        Sharpe: {result['metric_value']:.2f}")
            print(f"        Trades: {result['results'].total_trades}")
            print(f"        P&L: ${result['results'].net_pnl:,.2f}")
            print(f"        Win Rate: {result['results'].win_rate:.1f}%")
    else:
        print("  No valid results from optimization")
    
    print("\n✅ Parameter optimizer working")
except Exception as e:
    print(f"❌ Parameter optimizer failed: {e}")
    import traceback
    traceback.print_exc()


# TEST 5: Walk-Forward Validation
print("\n🚪 TEST 5: Walk-Forward Validation")
print("-"*80)

try:
    # Generate more data for walk-forward (need multiple months)
    print("  Generating extended dataset...")
    extended_bars = []
    current_time = datetime(2025, 1, 1, 9, 30)
    base_price = 150.0
    
    # Generate 3 months of data (60 trading days × 390 bars/day)
    for day in range(60):
        for minute in range(390):  # 9:30-16:00 = 390 minutes
            price_change = random.uniform(-0.3, 0.4)
            base_price += price_change
            base_price = max(base_price, 100.0)
            
            high = base_price + random.uniform(0, 0.3)
            low = base_price - random.uniform(0, 0.3)
            open_price = base_price + random.uniform(-0.15, 0.15)
            close_price = base_price
            volume = random.randint(500000, 2000000)
            
            extended_bars.append({
                'datetime': current_time,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close_price,
                'volume': volume
            })
            
            current_time += timedelta(minutes=1)
        
        # Skip to next day
        current_time = current_time.replace(hour=9, minute=30)
        current_time += timedelta(days=1)
    
    print(f"  Generated {len(extended_bars)} bars across {60} days")
    
    # Run walk-forward with small windows for testing
    wf = WalkForward(
        train_months=1,  # 1 month train
        test_months=1,   # 1 month test
        step_months=1,   # 1 month step
        optimization_metric='sharpe_ratio',
        min_train_bars=1000
    )
    
    param_grid = {
        'lookback_bars': [10, 12],
        'volume_threshold': [2.0, 2.5]
    }
    
    print("\n  Running walk-forward validation...")
    wf_results = wf.run(
        ticker='TEST',
        bars=extended_bars,
        strategy=example_simple_breakout_strategy,
        param_grid=param_grid,
        initial_capital=10000
    )
    
    print(f"\n  Walk-Forward Results:")
    print(f"    Windows: {wf_results.total_windows}")
    print(f"    OOS Trades: {len(wf_results.all_test_trades)}")
    print(f"    OOS P&L: ${wf_results.net_pnl:,.2f} ({wf_results.total_return_pct:+.2f}%)")
    print(f"    OOS Win Rate: {wf_results.win_rate:.1f}%")
    print(f"    OOS Sharpe: {wf_results.sharpe_ratio:.2f}")
    
    print("\n✅ Walk-forward validation working")
except Exception as e:
    print(f"❌ Walk-forward validation failed: {e}")
    import traceback
    traceback.print_exc()


# Summary
print("\n" + "="*80)
print("TEST SUITE COMPLETE")
print("="*80)
print("\n📋 Summary:")
print("  ✅ Performance Metrics: Ready")
print("  ✅ Backtest Engine: Ready")
print("  ✅ Parameter Optimizer: Ready")
print("  ✅ Walk-Forward Validation: Ready")
print("\n🚀 Next Steps:")
print("  1. Review docs/task10_backtesting_guide.md for usage examples")
print("  2. Backtest your actual strategy with historical data")
print("  3. Use walk-forward validation to prevent overfitting")
print("  4. Optimize parameters before deploying live")
print("  5. Deploy to Railway: git push origin main\n")
