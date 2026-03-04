# Research Folder - Backtesting Tools & Analysis

This folder contains all backtesting scripts, results, and research tools for developing and validating trading strategies.

## 📁 Structure

```
research/
├── backtesting_old/    # Legacy backtesting code (pre-Task 10)
├── results/            # All backtest results (.json, .csv files)
├── scripts/            # Analysis and optimization scripts
└── archive/            # Old experiments and deprecated code
```

---

## 🎯 Purpose

**Separation of Concerns:**
- **Production Code**: `/app/backtesting/` - Task 10 framework for production use
- **Research Code**: `/research/` - Experimental scripts and analysis tools

---

## 📊 What Goes Here?

### `/research/scripts/`
- Parameter optimization scripts
- Historical data loaders
- ML training data analysis
- Custom backtest runners
- One-off analysis tools

### `/research/results/`
- Backtest result files (`.json`, `.csv`)
- Optimization outputs
- Performance reports
- Trade journals

### `/research/backtesting_old/`
- Legacy backtesting implementations
- Old framework code (before Task 10)
- Deprecated modules

### `/research/archive/`
- Old experiments
- Deprecated scripts
- Historical code snapshots

---

## 🚀 Using Task 10 Framework

For new backtests, use the production framework:

```python
from app.backtesting import BacktestEngine, WalkForward, ParameterOptimizer

# See docs/task10_backtesting_guide.md for full examples
engine = BacktestEngine(initial_capital=10000)
results = engine.run(ticker='AAPL', bars=bars, strategy=my_strategy)
```

---

## 📝 Migration Status

- ✅ Step 1: Created research/ folder structure
- ⏳ Step 2: Move /backtesting/ → /research/backtesting_old/
- ⏳ Step 3: Move /backtests/ → /research/results/backtests/
- ⏳ Step 4: Move analysis scripts → /research/scripts/
- ⏳ Step 5: Move result files → /research/results/

---

## 🔄 Workflow

**Research Phase:**
1. Use scripts in `/research/scripts/` to analyze data
2. Optimize parameters
3. Save results to `/research/results/`

**Deployment Phase:**
1. Validate with Task 10 framework (`/app/backtesting/`)
2. Update production config
3. Deploy to Railway

---

**Last Updated:** March 4, 2026
