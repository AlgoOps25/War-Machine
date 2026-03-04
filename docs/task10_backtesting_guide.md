# Task 10: Backtesting Engine - Usage Guide

## Overview

Task 10 provides a comprehensive backtesting framework for validating your trading strategies before deploying them live.

**Key Features:**
- **Historical Signal Replay**: Test your signal logic on past data
- **Walk-Forward Validation**: Out-of-sample testing to prevent overfitting
- **Parameter Optimization**: Grid search to find optimal thresholds
- **Performance Metrics**: Sharpe ratio, Sortino ratio, max drawdown, etc.
- **Realistic Fills**: Slippage and commission modeling

---

## Quick Start

### 1. Simple Backtest

```python
from app.backtesting import BacktestEngine
from app.backtesting.signal_replay import example_simple_breakout_strategy

# Load historical bars (OHLCV with 'datetime' field)
bars = load_historical_data('AAPL', '2025-01-01', '2026-01-01')

# Initialize engine
engine = BacktestEngine(
    initial_capital=10000,
    commission_per_trade=0.50,
    slippage_pct=0.05,
    risk_per_trade_pct=1.0
)

# Run backtest
results = engine.run(
    ticker='AAPL',
    bars=bars,
    strategy=example_simple_breakout_strategy,
    strategy_params={'lookback_bars': 12, 'volume_threshold': 2.0}
)

# Print summary
print(results.summary())
```

**Output:**
```
Backtest Results:
  Total Trades: 45
  Win Rate: 62.2%
  Net P&L: $1,234.56 (+12.35%)
  Sharpe Ratio: 1.85
  Profit Factor: 2.15
  Max Drawdown: 8.5%
```

---

## Using Your Actual Strategy

### Option 1: Wrap BreakoutDetector

```python
from app.backtesting.signal_replay import create_strategy_from_breakout_detector

# Create strategy wrapper
strategy = create_strategy_from_breakout_detector(
    lookback_bars=12,
    volume_multiplier=2.0,
    atr_stop_multiplier=1.5,
    min_candle_body_pct=0.4
)

# Run backtest
results = engine.run(
    ticker='AAPL',
    bars=bars,
    strategy=strategy,
    strategy_params={}  # Default values from wrapper
)
```

### Option 2: Custom Strategy Function

```python
def my_custom_strategy(bars, params):
    """
    Custom strategy function.
    
    Args:
        bars: List of OHLCV bars
        params: Dict of parameters
    
    Returns:
        Signal dict or None
    """
    if len(bars) < 20:
        return None
    
    # Your signal logic here
    from app.signals.breakout_detector import BreakoutDetector
    
    detector = BreakoutDetector(
        lookback_bars=params.get('lookback_bars', 12),
        volume_multiplier=params.get('volume_threshold', 2.0)
    )
    
    signal = detector.detect_breakout(bars, ticker="BACKTEST")
    
    return signal

# Use custom strategy
results = engine.run(
    ticker='AAPL',
    bars=bars,
    strategy=my_custom_strategy,
    strategy_params={'lookback_bars': 12, 'volume_threshold': 2.0}
)
```

---

## Parameter Optimization

### Grid Search

```python
from app.backtesting.parameter_optimizer import ParameterOptimizer

# Initialize optimizer
optimizer = ParameterOptimizer(
    initial_capital=10000,
    optimization_metric='sharpe_ratio',  # or 'profit_factor', 'win_rate', etc.
    min_trades=10
)

# Define parameter grid
param_grid = {
    'lookback_bars': [10, 12, 15],
    'volume_threshold': [1.5, 2.0, 2.5, 3.0],
    'min_confidence': [60, 65, 70],
    'atr_stop_multiplier': [1.5, 2.0, 2.5]
}

# Run grid search
results = optimizer.grid_search(
    ticker='AAPL',
    bars=bars,
    strategy=my_custom_strategy,
    param_grid=param_grid,
    top_n=5  # Return top 5 parameter sets
)

# Get best parameters
best_params = results[0]['params']
print(f"Best parameters: {best_params}")
print(f"Sharpe Ratio: {results[0]['metric_value']:.2f}")
```

**Example Output:**
```
TOP 5 RESULTS:
  #1 {'lookback_bars': 12, 'volume_threshold': 2.5, 'min_confidence': 65, 'atr_stop_multiplier': 2.0}
      Sharpe: 2.15 | Trades: 38 | P&L: $1,456.78
  
  #2 {'lookback_bars': 15, 'volume_threshold': 2.0, 'min_confidence': 60, 'atr_stop_multiplier': 1.5}
      Sharpe: 1.98 | Trades: 42 | P&L: $1,312.45
  
  #3 {'lookback_bars': 10, 'volume_threshold': 3.0, 'min_confidence': 70, 'atr_stop_multiplier': 2.5}
      Sharpe: 1.87 | Trades: 31 | P&L: $1,198.23
```

---

## Walk-Forward Validation

Walk-forward validation prevents overfitting by testing on out-of-sample (OOS) data:

```python
from app.backtesting.walk_forward import WalkForward

# Initialize walk-forward validator
wf = WalkForward(
    train_months=3,  # Optimize on 3 months
    test_months=1,   # Test on 1 month OOS
    step_months=1,   # Roll forward 1 month
    optimization_metric='sharpe_ratio',
    min_train_bars=1000
)

# Run walk-forward validation
results = wf.run(
    ticker='AAPL',
    bars=bars,  # Need at least 4+ months of data
    strategy=my_custom_strategy,
    param_grid=param_grid,
    initial_capital=10000
)

# Print summary
print(results.summary())
```

**Example Output:**
```
WALK-FORWARD VALIDATION RESULTS

Total Windows: 6
Total OOS Trades: 178

AGGREGATE OOS PERFORMANCE:
  Net P&L:       $4,567.89 (+45.68%)
  Win Rate:      58.4%
  Profit Factor: 1.85
  Expectancy:    $25.66
  Sharpe Ratio:  1.42

WINDOW-BY-WINDOW BREAKDOWN:
  Window   Train Period              Test Period               OOS Trades   OOS P&L
  #1       2025-01-01 to 2025-03-31  2025-04-01 to 2025-04-30  28           $812.34
  #2       2025-02-01 to 2025-04-30  2025-05-01 to 2025-05-31  32           $945.67
  #3       2025-03-01 to 2025-05-31  2025-06-01 to 2025-06-30  29           $723.45
  ...
```

---

## Loading Historical Data

### From EODHD API

```python
import requests
from datetime import datetime
from utils import config

def load_historical_bars(ticker, start_date, end_date, interval='1m'):
    """
    Load historical intraday bars from EODHD.
    
    Args:
        ticker: Stock ticker
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        interval: Bar interval ('1m', '5m', '1h', '1d')
    
    Returns:
        List of OHLCV bars with 'datetime' field
    """
    url = f"https://eodhd.com/api/intraday/{ticker}.US"
    params = {
        'api_token': config.EODHD_API_KEY,
        'interval': interval,
        'from': int(datetime.strptime(start_date, '%Y-%m-%d').timestamp()),
        'to': int(datetime.strptime(end_date, '%Y-%m-%d').timestamp()),
        'fmt': 'json'
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    # Convert to backtest format
    bars = []
    for bar in data:
        bars.append({
            'datetime': datetime.fromtimestamp(bar['timestamp']),
            'open': bar['open'],
            'high': bar['high'],
            'low': bar['low'],
            'close': bar['close'],
            'volume': bar['volume']
        })
    
    return bars
```

### From Your Database

```python
from app.data.data_manager import data_manager

def load_bars_from_db(ticker, start_date, end_date):
    """
    Load bars from your intraday_bars table.
    """
    bars = data_manager.get_historical_bars(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date
    )
    
    # Ensure 'datetime' field exists
    for bar in bars:
        if 'timestamp' in bar and 'datetime' not in bar:
            bar['datetime'] = datetime.fromisoformat(bar['timestamp'])
    
    return bars
```

---

## Performance Metrics

### Available Metrics

```python
from app.backtesting import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_expectancy
)

# Calculate individual metrics
returns = [0.02, -0.01, 0.03, -0.005, 0.015]

sharpe = calculate_sharpe_ratio(returns)  # Risk-adjusted returns
sortino = calculate_sortino_ratio(returns)  # Downside risk only

equity_curve = [10000, 10200, 10100, 10400, 10350]
max_dd = calculate_max_drawdown(equity_curve)  # Peak-to-trough decline

trades = results.trades
win_rate = calculate_win_rate(trades)  # % winning trades
profit_factor = calculate_profit_factor(trades)  # Gross profit / gross loss
expectancy = calculate_expectancy(trades)  # Average $ per trade
```

### Metric Interpretations

| Metric | Good | Very Good | Excellent |
|--------|------|-----------|----------|
| Sharpe Ratio | > 1.0 | > 2.0 | > 3.0 |
| Sortino Ratio | > 1.5 | > 2.5 | > 4.0 |
| Profit Factor | > 1.5 | > 2.0 | > 3.0 |
| Win Rate | > 50% | > 60% | > 70% |
| Max Drawdown | < 15% | < 10% | < 5% |

---

## Advanced Configuration

### Backtest Engine Options

```python
engine = BacktestEngine(
    initial_capital=10000,           # Starting capital
    commission_per_trade=0.50,       # Fixed commission per trade
    slippage_pct=0.05,               # Slippage (0.05 = 0.05%)
    max_position_size_pct=100.0,     # Max position as % of capital
    risk_per_trade_pct=1.0,          # Risk per trade (1.0 = 1%)
    max_bars_held=390,               # Max bars to hold (390 = 1 day)
    enable_t1_t2_exits=True          # Use split T1/T2 targets
)
```

### Walk-Forward Options

```python
wf = WalkForward(
    train_months=3,                  # Training window
    test_months=1,                   # Testing window
    step_months=1,                   # Rolling step size
    optimization_metric='sharpe_ratio',  # Metric to optimize
    min_train_bars=1000              # Min bars in train window
)
```

### Optimizer Options

```python
optimizer = ParameterOptimizer(
    initial_capital=10000,
    optimization_metric='sharpe_ratio',  # Optimize this metric
    min_trades=10                    # Min trades to consider valid
)

# Available optimization metrics:
# - 'sharpe_ratio': Risk-adjusted returns
# - 'sortino_ratio': Downside risk-adjusted returns
# - 'profit_factor': Gross profit / gross loss
# - 'win_rate': % winning trades
# - 'expectancy': Average $ per trade
# - 'total_return_pct': Total return %
```

---

## Full Workflow Example

```python
from app.backtesting import BacktestEngine
from app.backtesting.parameter_optimizer import ParameterOptimizer
from app.backtesting.walk_forward import WalkForward

# 1. Load historical data
bars = load_historical_bars('AAPL', '2025-01-01', '2026-01-01', interval='1m')
print(f"Loaded {len(bars)} bars")

# 2. Define your strategy
def my_strategy(bars, params):
    from app.signals.breakout_detector import BreakoutDetector
    
    detector = BreakoutDetector(
        lookback_bars=params.get('lookback_bars', 12),
        volume_multiplier=params.get('volume_threshold', 2.0),
        atr_stop_multiplier=params.get('atr_stop_multiplier', 1.5)
    )
    
    return detector.detect_breakout(bars, ticker="AAPL")

# 3. Quick backtest with default params
print("\n=== INITIAL BACKTEST ===")
engine = BacktestEngine(initial_capital=10000)
results = engine.run(
    ticker='AAPL',
    bars=bars,
    strategy=my_strategy,
    strategy_params={'lookback_bars': 12, 'volume_threshold': 2.0}
)
print(results.summary())

# 4. Optimize parameters
print("\n=== PARAMETER OPTIMIZATION ===")
optimizer = ParameterOptimizer(
    initial_capital=10000,
    optimization_metric='sharpe_ratio'
)

param_grid = {
    'lookback_bars': [10, 12, 15],
    'volume_threshold': [1.5, 2.0, 2.5, 3.0],
    'atr_stop_multiplier': [1.5, 2.0, 2.5]
}

opt_results = optimizer.grid_search(
    ticker='AAPL',
    bars=bars,
    strategy=my_strategy,
    param_grid=param_grid,
    top_n=3
)

best_params = opt_results[0]['params']
print(f"Best parameters: {best_params}")

# 5. Walk-forward validation with best params
print("\n=== WALK-FORWARD VALIDATION ===")
wf = WalkForward(
    train_months=3,
    test_months=1,
    optimization_metric='sharpe_ratio'
)

wf_results = wf.run(
    ticker='AAPL',
    bars=bars,
    strategy=my_strategy,
    param_grid=param_grid,  # Re-optimize in each window
    initial_capital=10000
)

print(wf_results.summary())

# 6. Decision: Deploy or not?
if wf_results.sharpe_ratio > 1.5 and wf_results.win_rate > 55:
    print("\n✅ Strategy validated - ready for live trading!")
    print(f"Deploy with params: {best_params}")
else:
    print("\n❌ Strategy needs more work")
    print(f"Sharpe: {wf_results.sharpe_ratio:.2f} (need > 1.5)")
    print(f"Win Rate: {wf_results.win_rate:.1f}% (need > 55%)")
```

---

## Exporting Results

### Export to JSON

```python
import json

# Export backtest results
results_dict = results.to_dict()

with open('backtest_results.json', 'w') as f:
    json.dump(results_dict, f, indent=2, default=str)

print("Results exported to backtest_results.json")
```

### Export Trades to CSV

```python
import csv

# Export trade journal
with open('trades.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Ticker', 'Entry Time', 'Entry Price', 'Exit Time', 'Exit Price', 
                     'Shares', 'Side', 'P&L', 'P&L %', 'Exit Reason', 'Confidence'])
    
    for trade in results.trades:
        writer.writerow([
            trade.ticker,
            trade.entry_time,
            trade.entry_price,
            trade.exit_time,
            trade.exit_price,
            trade.shares,
            trade.side,
            trade.pnl,
            trade.pnl_pct,
            trade.exit_reason,
            trade.signal_confidence
        ])

print("Trades exported to trades.csv")
```

---

## Best Practices

### 1. Use Walk-Forward Validation
- Always validate with OOS data to prevent overfitting
- Don't optimize on the same data you test on

### 2. Require Minimum Trades
- Set `min_trades=10` or higher in optimizer
- Low trade counts = statistically insignificant

### 3. Test Multiple Timeframes
- Backtest on 1m, 5m, and 15m bars
- Strategy should work across timeframes

### 4. Account for Costs
- Include realistic commission ($0.50-$1.00)
- Include slippage (0.05-0.10%)
- Real results will be worse than backtest

### 5. Watch for Overfitting
- If in-sample Sharpe is 3.0 but OOS is 0.5, you're overfitting
- Simpler strategies often perform better live

### 6. Deploy Conservatively
- Start with 10-20% of intended capital
- Monitor for 2-4 weeks before scaling up
- Track live vs. backtest performance

---

## Troubleshooting

### "No signals generated"
- Check that bars have required fields ('datetime', 'open', 'high', 'low', 'close', 'volume')
- Ensure enough bars (need 50+ for lookback)
- Verify strategy is returning signal dicts

### "All trades hit stops"
- Stops may be too tight
- Increase `atr_stop_multiplier` from 1.5 to 2.0+
- Check if bars have realistic OHLC relationships

### "Walk-forward has 0 windows"
- Need at least `train_months + test_months` of data
- Reduce window sizes or load more data
- Check `min_train_bars` requirement

### "Optimization taking too long"
- Reduce parameter grid size
- Use fewer values per parameter
- Test on smaller date range first

---

## Task 10 Complete!

**Deliverables:**
- ✅ Backtest engine with realistic fills
- ✅ Walk-forward validation
- ✅ Parameter optimization (grid search)
- ✅ Performance metrics (Sharpe, Sortino, etc.)
- ✅ Trade journal export

**Impact:**
- Validate strategies before deploying live
- Find optimal parameters objectively
- Prevent overfitting with OOS testing
- Track performance metrics

**Next Steps:**
1. Backtest your actual strategy
2. Optimize parameters
3. Validate with walk-forward
4. Deploy winners to live trading
