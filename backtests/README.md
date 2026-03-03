# War Machine Backtesting Suite

Backtest your DTE selection logic and validate historical trading decisions.

## Setup

### 1. Extract Historical Data

You have sample data in the CSV files, but for real analysis you need your actual trading history.

#### Option A: Extract from Logs

```bash
python scripts/extract_signals_from_logs.py path/to/your/logfile.txt
```

This parses log files for SIGNAL entries and creates `backtests/historical_signals.csv`.

#### Option B: Extract from Database

**PostgreSQL:**
```bash
python scripts/extract_positions_from_db.py --db-type postgres --db-url "postgresql://user:pass@host:5432/wardb"
```

**SQLite:**
```bash
python scripts/extract_positions_from_db.py --db-type sqlite --db-path trades.db
```

#### Option C: Manual CSV Creation

Edit the CSV files directly with your trade data.

**historical_signals.csv format:**
```
timestamp,symbol,signal_type,entry_price
2026-02-24 09:35:00,SPY,BOS_BULL,678.50
```

**position_history.csv format:**
```
entry_time,exit_time,symbol,strike,dte,entry_price,exit_price,pnl,pnl_pct
2026-02-24 09:35:00,2026-02-24 09:42:00,SPY,679.0,0,1.25,1.85,60.00,48.00
```

### 2. Run Backtests

#### Test DTE Logic on Historical Signals

```bash
python backtests/test_dte_logic.py
```

This shows what DTE would have been selected at each signal timestamp and evaluates decision quality.

**Output:**
- Console summary with DTE distribution and optimal % 
- `backtests/dte_backtest_results.csv` with detailed results

#### Analyze Historical Position Outcomes

```bash
python backtests/historical_advisor.py
```

This compares actual DTE used vs recommended DTE and calculates win rates by DTE.

**Output:**
- Win rate by DTE (0, 1, 2+)
- Matched vs unmatched recommendation performance
- Assessment of each position's DTE choice
- `backtests/historical_advisor_results.csv` with detailed analysis

## Understanding the Results

### DTE Backtest Metrics

- **Optimal Percentage**: % of signals where DTE selector made the "correct" choice based on time rules
- **DTE Distribution**: How often each DTE (0, 1, 2) would be selected
- **By Hour Analysis**: DTE selection patterns throughout trading day

### Historical Advisor Metrics

- **Match Rate**: % of trades where you used the recommended DTE
- **Matched Win Rate**: Win rate when following recommendations
- **Unmatched Win Rate**: Win rate when deviating from recommendations
- **Win Rate by DTE**: Which DTE values produce best outcomes

### Key Insights to Look For

1. **Does following DTE recommendations improve win rate?**
   - If matched win rate > unmatched win rate → strategy is working
   - If unmatched win rate > matched win rate → rules may need adjustment

2. **Which DTE performs best?**
   - 0 DTE should excel in quick scalps (< 5 min holds)
   - 1-2 DTE should handle longer holds better
   - Wednesday 0DTE should have lower win rate (if avoided)

3. **Time-of-day patterns**
   - Early signals (< 10 AM) with 0 DTE should be winners
   - Late signals (> 10:30 AM) with 2 DTE should avoid time decay losses

## Customizing DTE Config

Edit the config in both backtest scripts to match your production settings:

```python
config = DTEConfig(
    default_dte=0,
    pre_1000_dte=0,      # Before 10:00 AM
    post_1000_dte=1,     # 10:00-10:30 AM
    post_1030_dte=2,     # After 10:30 AM
    avoid_wed_0dte=True, # Skip Wednesday 0DTE
    min_time_value=0.05,
    enable_smart_routing=True
)
```

## Next Steps

1. Run backtests on sample data first to see output format
2. Extract your real trading history
3. Re-run backtests with actual data
4. Adjust DTE config based on insights
5. Deploy updated config to production
6. Monitor live results vs backtest predictions
