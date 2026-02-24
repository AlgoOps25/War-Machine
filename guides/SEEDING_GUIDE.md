# AI Learning Engine Seeding Guide

## Overview

The AI learning engine adapts War Machine's confidence multipliers based on real trade performance. Instead of starting from zero, you can **seed it with historical backtest data** to give it market-validated patterns from day one.

---

## Why Seed the Learning Engine?

### Without Seeding (Cold Start)
- All tickers start with `1.0x` confidence multiplier
- Takes 10-20 live trades per ticker to calibrate
- Early trades risk overfitting to small samples
- No baseline for underperforming tickers (AAPL, NVDA in your case)

### With Seeding (Warm Start)
- Learning engine starts with 30-60 days of real market data
- Ticker multipliers pre-calibrated to historical win rates
- Confidence gates tuned to actual signal quality
- Underperforming tickers (low WR) get penalty multipliers immediately
- FVG/ORB thresholds optimized to winning trades

---

## Quick Start

### 1. Seed with Your Watchlist (Recommended)

```bash
python seed_learning_engine.py --use-watchlist --days 30 --reset
```

**What this does:**
- Backtests last 30 days on your entire screener watchlist
- Assigns grades (A+/A/A-) to each trade based on signal quality
- Imports all trades into the AI learning engine
- Recalibrates confidence multipliers per ticker
- Generates baseline performance report

**Expected output:**
```
[SEED] Using screener watchlist: 50 tickers
[SEED] Running backtest...
  [1/50] Processing AAPL...
    → 1,200 bars fetched
    → 8 signals detected
    ✅ AAPL BULL | TARGET 2 | P&L: $+320.00
    ❌ AAPL BEAR | STOP LOSS | P&L: $-180.00
    ...
[SEED] ✅ Imported 156 trades
[SEED] Recalibrating confidence multipliers...
  [AI] Confirmation weights optimized:
    vwap: 1.05
    prev_day: 0.98
    institutional: 1.12
    options_flow: 1.08
[SEED] Ticker Confidence Multipliers:
  SPY: 1.10x (15 trades, 73.3% WR)
  AAPL: 0.90x (8 trades, 37.5% WR)
  NVDA: 0.90x (6 trades, 33.3% WR)
  ...
[SEED] ✅ Seeding complete.
```

---

### 2. Seed Specific Tickers

```bash
python seed_learning_engine.py --tickers AAPL,SPY,NVDA,TSLA --days 60 --reset
```

Use this when:
- Testing a new ticker before adding to watchlist
- Deep-diving a specific underperformer
- Validating strategy on high-confidence names only

---

### 3. Add Historical Data Without Resetting

```bash
python seed_learning_engine.py --use-watchlist --days 30
```

**Omit `--reset`** to merge backtest data with existing live trades. Useful when:
- You've been running live for a few days and want more history
- Testing a new ticker and don't want to clear existing data

---

## Understanding the Output

### Ticker Confidence Multipliers

The AI learning engine assigns multipliers based on win rate:

| Win Rate | Multiplier | Effect |
|----------|-----------|--------|
| ≥75% | `1.10x` | Boosts confidence → easier to pass gates |
| ≥65% | `1.05x` | Slight boost for consistent performers |
| 45-65% | `1.00x` | Neutral (no adjustment) |
| ≤45% | `0.90x` | Penalty → harder to pass confidence gate |
| ≤55% | `0.95x` | Light penalty for marginal performers |

**Example:**
- **SPY at 73% WR** → `1.10x` multiplier → signals more likely to arm
- **AAPL at 37% WR** → `0.90x` multiplier → signals need higher base confidence

---

### Grade Distribution

Grades are assigned based on signal quality:

- **A+**: T1 hit + profitable + strong OR range (>0.5%)
- **A**: Profitable or T1 hit
- **A-**: Loss without T1 hit

In live trading, `cfw6_confirmation.grade_signal_with_confirmations()` uses full multi-timeframe analysis. For seeding, we use outcome-based heuristics since we can't re-run confirmations on historical bars.

---

## When to Re-Seed

### After 30 Days of Live Trading
Once you have 50+ real trades, the live data is more valuable than backtests. At that point:
```bash
# Don't re-seed — let it learn from live execution
```

### After Major Strategy Changes
If you modify CFW6 confirmation logic, FVG thresholds, or stop placement:
```bash
python seed_learning_engine.py --use-watchlist --days 60 --reset
```

### When Adding New Tickers
If you add a new ticker to the watchlist:
```bash
python seed_learning_engine.py --tickers NEWTICKER --days 30
# (omit --reset to merge with existing data)
```

---

## Troubleshooting

### "No trades executed" in backtest
- **Cause:** No CFW6 signals fired during the backtest period
- **Fix:** Increase `--days` to 60 or 90, or choose more volatile tickers

### EODHD API rate limits
- **Cause:** Too many tickers, API throttling
- **Fix:** Reduce ticker count or run in batches:
  ```bash
  python seed_learning_engine.py --tickers AAPL,SPY,TSLA --days 30 --reset
  python seed_learning_engine.py --tickers NVDA,MSFT,AMD --days 30
  ```

### Learning data not persisting after Railway restart
- **Cause:** Learning data stored in PostgreSQL, not local JSON
- **Fix:** Already handled — `ai_learning.py` uses Railway's `DATABASE_URL` automatically

---

## Advanced: Custom Grading Logic

If you want to assign grades differently (e.g., based on pre-market volume, IV rank, or dark pool flow), edit `assign_grade_to_trade()` in `seed_learning_engine.py`:

```python
def assign_grade_to_trade(trade: dict, signals_map: dict) -> str:
    # Your custom logic here
    if trade["pnl"] > 500 and trade["t1_hit"]:
        return "A+"
    elif trade["pnl"] > 0:
        return "A"
    else:
        return "A-"
```

---

## Next Steps

After seeding:

1. **Review the baseline report** — check which tickers are underperforming
2. **Adjust `MIN_CONFIDENCE_BY_GRADE`** in `config.py` if needed
3. **Run a paper trading session** — verify confidence gates are working
4. **Monitor the first 10 live trades** — compare to backtest expectations

**The learning engine will continue to adapt** as you trade live. The seeded data provides a strong starting point, but real-world execution (fills, slippage, timing) will fine-tune it further.

---

## Questions?

- Check `ai_learning.py` for the learning logic
- See `backtesting_engine.py` for signal detection rules
- Review `sniper.py` to understand how confidence multipliers affect arming
