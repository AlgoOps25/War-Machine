# Smart Optimization System - Setup & Usage

## 🎯 Overview

This optimization system finds the best indicator parameters for War Machine using:
- **Bayesian Optimization** - Smart search (1000x faster than grid search)
- **Walk-Forward Validation** - Prevents overfitting  
- **38 Optimizable Parameters** - Complete indicator coverage
- **Production-Ready Output** - JSON config file

---

## 📦 Installation

### 1. Install Dependencies

```bash
pip install scikit-optimize numpy pandas
```

### 2. Verify Installation

```bash
python -c "from skopt import gp_minimize; print('✅ Ready')"
```

---

## 🗄️ Data Requirements

### What You Need:

**Historical signals with outcomes** stored in one of:
- PostgreSQL database
- SQLite database  
- CSV file
- JSON file

### Required Fields Per Signal:

```python
{
    'timestamp': datetime,       # When signal fired
    'ticker': 'AAPL',           # Stock symbol
    'direction': 'CALL',        # 'CALL' or 'PUT'
    'outcome': {
        'r_multiple': 2.5,      # R-multiple (profit/risk)
        'pnl': 125.50,          # Dollar P&L
        'hold_time_minutes': 23 # How long held
    }
}
```

### Example CSV Format:

```csv
timestamp,ticker,direction,r_multiple,pnl,hold_time_minutes
2026-02-01 09:45:00,AAPL,CALL,2.5,125.50,23
2026-02-01 10:15:00,NVDA,PUT,-1.0,-50.00,15
2026-02-01 14:30:00,TSLA,CALL,1.8,90.00,34
```

---

## 🚀 Usage

### Step 1: Prepare Your Data

**Option A: From Database**

```python
# Edit smart_optimization.py, line 850
def load_historical_signals():
    import psycopg2
    conn = psycopg2.connect(your_db_url)
    
    query = """
    SELECT 
        timestamp,
        ticker,
        direction,
        r_multiple,
        pnl,
        hold_time_minutes
    FROM signals
    WHERE timestamp >= NOW() - INTERVAL '60 days'
    ORDER BY timestamp
    """
    
    df = pd.read_sql(query, conn)
    
    signals = []
    for _, row in df.iterrows():
        signals.append({
            'timestamp': row['timestamp'],
            'ticker': row['ticker'],
            'direction': row['direction'],
            'outcome': {
                'r_multiple': row['r_multiple'],
                'pnl': row['pnl'],
                'hold_time_minutes': row['hold_time_minutes']
            }
        })
    
    return signals
```

**Option B: From CSV**

```python
# Edit smart_optimization.py, line 850
def load_historical_signals():
    df = pd.read_csv('signals_history.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    signals = []
    for _, row in df.iterrows():
        signals.append({
            'timestamp': row['timestamp'],
            'ticker': row['ticker'],
            'direction': row['direction'],
            'outcome': {
                'r_multiple': row['r_multiple'],
                'pnl': row['pnl'],
                'hold_time_minutes': row['hold_time_minutes']
            }
        })
    
    return signals
```

### Step 2: Run Optimization

```bash
python smart_optimization.py
```

**Expected Output:**

```
================================================================================
WAR MACHINE - SMART OPTIMIZATION
================================================================================
Start time: 2026-03-02 00:15:00 EST

✅ Loaded 1,247 signals
   Date range: 2026-01-01 to 2026-02-28

Starting Bayesian optimization...
  Search space: 38 parameters
  Iterations: 1000
  Expected runtime: 3-5 hours

Iteration 1/1000 | Current best: -0.523
Iteration 50/1000 | Current best: 1.234
...

================================================================================
OPTIMIZATION COMPLETE
================================================================================
Best Sharpe Ratio: 2.156

Best Parameters:
{
  "adx_threshold": 24.3,
  "rsi_overbought": 72.5,
  "rsi_oversold": 28.1,
  ...
}

✅ Results saved to: optimization_results.json

End time: 2026-03-02 04:23:00 EST
```

### Step 3: Review Results

```bash
cat optimization_results.json
```

**Output Structure:**

```json
{
  "timestamp": "2026-03-02T04:23:00-05:00",
  "best_sharpe": 2.156,
  "best_params": {
    "adx_threshold": 24.3,
    "rsi_overbought": 72.5,
    "rsi_oversold": 28.1,
    "mfi_overbought": 78.2,
    "mfi_oversold": 21.5,
    "macd_lookback": 3,
    "stoch_overbought": 80.1,
    "stoch_oversold": 19.8,
    "bb_squeeze_threshold": 0.038,
    "volume_ratio_min": 1.72,
    "vwap_min_deviation": 0.45,
    "atr_multiplier": 2.13,
    "ema_period": 50,
    "obv_lookback": 5,
    "divergence_lookback": 8,
    "rvol_threshold": 1.43,
    "fvg_size_threshold": 0.62,
    "bos_break_strength": 1.15,
    "orb_percentile": 22.0,
    "recent_hl_lookback": 12,
    "consolidation_bars": 5,
    "breakout_confirm_bars": 2,
    "ema_weight": 0.12,
    "volume_weight": 0.15,
    "momentum_weight": 0.18,
    "volume_confluence_weight": 0.10,
    "divergence_penalty": -0.08,
    "squeeze_bonus": 0.06,
    "rvol_bonus": 0.07,
    "crossover_bonus": 0.05,
    "require_ema_align": true,
    "require_vwap_confirm": false,
    "require_mfi_confirm": true,
    "require_obv_confirm": false,
    "require_trend_strength": true,
    "require_volume_confirm": true,
    "block_divergence": false,
    "require_crossover": false
  },
  "all_results": [
    ...
  ]
}
```

---

## 📊 Understanding Results

### Key Metrics:

- **Sharpe Ratio** - Risk-adjusted returns (>1.5 = good, >2.0 = excellent)
- **Win Rate** - % of winning trades
- **Avg R-Multiple** - Average profit/loss ratio
- **Max Drawdown** - Largest peak-to-trough decline

### Parameter Categories:

1. **Indicator Thresholds** (16) - When indicators trigger
2. **Price Action** (6) - Breakout/pattern detection
3. **Confirmation Weights** (8) - How much each signal matters
4. **Hard Filters** (8) - Required conditions (on/off)

### Walk-Forward Validation:

- Trains on 60 days → Tests on next 7 days
- Rolls forward weekly
- Prevents overfitting to historical data
- Results closer to real trading performance

---

## 🔧 Configuration

### Adjust Search Space:

Edit `SEARCH_SPACE` in `smart_optimization.py` (line 270):

```python
# Example: Tighten RSI range
Real(68.0, 75.0, name='rsi_overbought'),  # Was 65-80

# Example: Add more EMA options
Categorical([9, 20, 50, 200], name='ema_period'),  # Was just 20/50/200
```

### Adjust Optimization Settings:

Edit `main()` function (line 967):

```python
result = gp_minimize(
    objective,
    SEARCH_SPACE,
    n_calls=2000,        # More iterations = better (but slower)
    n_initial_points=100, # Random samples before Bayesian
    random_state=42,
    verbose=True
)
```

### Speed vs Accuracy:

| n_calls | Runtime | Quality |
|---------|---------|----------|
| 100     | 30 min  | Quick test |
| 500     | 2 hours | Good enough |
| 1000    | 4 hours | Recommended |
| 2000    | 8 hours | Maximum precision |

---

## 🐛 Troubleshooting

### Issue: "No historical signals found"

**Solution:** Update `load_historical_signals()` to load your data.

### Issue: "ModuleNotFoundError: skopt"

**Solution:**
```bash
pip install scikit-optimize
```

### Issue: "Too few trades" warning

**Solution:** Your parameters are too restrictive. Check:
- `require_*` filters (try setting some to False)
- Indicator thresholds (may be too tight)
- Signal history (need >100 signals minimum)

### Issue: Optimization stuck/slow

**Solution:**
- Reduce `n_calls` to 500
- Reduce walk-forward windows (edit line 670)
- Check indicator cache is working

---

## 📈 Next Steps

### After Optimization:

1. **Copy best parameters** to production config
2. **Paper trade for 1 week** to validate
3. **Monitor live performance** vs backtest
4. **Re-optimize monthly** as market conditions change

### Production Integration:

```python
# In your scanner/validator
from smart_optimization import OptimizationConfig
import json

# Load optimized config
with open('optimization_results.json') as f:
    results = json.load(f)
    config = OptimizationConfig(**results['best_params'])

# Use in validation
passes, confidence = validate_signal(ticker, direction, config)
if passes and confidence > 0.65:
    # Execute trade
    ...
```

---

## 📝 Notes

- **Overfitting risk**: Always validate on unseen data
- **Market regime changes**: Re-optimize every 30-60 days
- **Sample size**: Need 200+ signals for reliable results
- **Runtime**: Proportional to (signals × n_calls)

---

## 🆘 Support

If optimization fails or results look suspicious:

1. Check data quality (no gaps, valid outcomes)
2. Verify indicator functions work standalone
3. Run with fewer iterations first (n_calls=100)
4. Check logs for API errors or cache misses

---

**Built for War Machine** | Last updated: 2026-03-02
