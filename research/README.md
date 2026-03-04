# Research & Backtesting

This folder consolidates all backtesting scripts, analysis tools, and historical results for the War Machine trading system.

## Structure

```
research/
├── backtesting_old/     # Legacy backtesting code (pre-Task 10)
├── results/             # All backtest results (.json, .csv files)
├── scripts/             # Analysis and utility scripts
└── archive/             # Old experiments and deprecated code
```

## Notes

- **Production backtesting framework**: Located in `/app/backtesting/` (Task 10)
- This folder contains historical research and legacy tools
- Results are organized by date and type for easy reference

## Migration Status

- [x] Step 1: Created folder structure
- [ ] Step 2: Move old /backtesting/ → backtesting_old/
- [ ] Step 3: Move old /backtests/ → results/backtests/
- [ ] Step 4: Move analysis scripts → scripts/
- [ ] Step 5: Move result files → results/
