# War Machine — Full Backtest Campaign

A 3-step exhaustive backtest system that finds the highest-probability
indicator combination across 90 days of cached bar data.

---

## Quick Start

```powershell
# From repo root in your venv
(.venv) PS C:\Dev\War-Machine> python scripts/backtesting/campaign/01_fetch_candles.py
(.venv) PS C:\Dev\War-Machine> python scripts/backtesting/campaign/02_run_campaign.py
(.venv) PS C:\Dev\War-Machine> python scripts/backtesting/campaign/03_analyze_results.py
```

---

## Step 1 — Data Audit (`01_fetch_candles.py`)

Scans `market_memory.db` and lists every ticker with its bar count and date
range. Writes `usable_tickers.txt` (tickers with ≥ 500 bars / 30 trading days)
for the campaign engine to pick up automatically.

**Nothing is downloaded** — reads only what is already cached.

---

## Step 2 — Campaign Engine (`02_run_campaign.py`)

Tests every combination of the following 8 indicator axes:

| Axis | Values tested |
|---|---|
| `bos_strength` | 0.10%, 0.15%, 0.18%, 0.22%, 0.30% |
| `tf_confirm` | 1m, 3m, 5m, 5m+3m, 5m+3m+1m |
| `vwap_zone` | above_1sd, above_vwap, none |
| `rvol_min` | 2×, 3×, 4×, 5× |
| `mfi_min` | 50, 55, 60, off |
| `obv_bars` | rising 3 bars, rising 5 bars, off |
| `session` | OR only (9:30–10:00), early (9:30–11:00), all day |
| `direction` | CALL only, PUT only, both |

**~97,200 total combinations.**

Each combination is scored on:
- **Win Rate** (primary)
- **Avg R-multiple** (secondary — T1=1R, T2=2R, stop=-1R)
- **Score** = `win_rate × avg_r` (used for ranking)
- Combos with fewer than 15 trades are discarded to prevent overfitting.

Output: `campaign_results.db` (SQLite).

### CLI flags
```powershell
# Use specific tickers
python scripts/backtesting/campaign/02_run_campaign.py --tickers AAPL,NVDA,TSLA

# Use only 60 days of history
python scripts/backtesting/campaign/02_run_campaign.py --days 60

# Require at least 20 trades per combo
python scripts/backtesting/campaign/02_run_campaign.py --min-trades 20
```

---

## Step 3 — Analyzer (`03_analyze_results.py`)

Produces:
1. **Top-20 leaderboard** sorted by score
2. **Dimension heatmap** — which single parameter value contributes most to wins
3. **Best combo per direction** (CALL only / PUT only / both)
4. **Champion config dict** — ready to paste into `utils/config.py`

### CLI flags
```powershell
# Show top 30 combos requiring at least 20 trades and 65% win rate
python scripts/backtesting/campaign/03_analyze_results.py --top 30 --min-trades 20 --min-wr 0.65
```

---

## Scoring Formula

```
score = win_rate × avg_r
```

A combo with 70% WR and +0.80 avg-R scores `0.56` — better than a
90% WR combo with only +0.10 avg-R (score `0.09`). This balances
accuracy with real-dollar expectancy.

---

## Files Created

| File | Created by | Description |
|---|---|---|
| `usable_tickers.txt` | Step 1 | Tickers with sufficient history |
| `campaign_results.db` | Step 2 | All qualifying combo results |

Both files are in `.gitignore` (no bloat in the repo).
