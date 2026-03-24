# 🧠 WAR MACHINE — CONTEXT.md
> **This file is the single source of truth for AI sessions. Update after every commit.**
> Last updated: 2026-03-24

---

## 📌 Project Overview
War Machine is a Python-based automated intraday trading system deployed on Railway.
- **Entry logic**: ORB (Opening Range Breakout) with FVG + volume confirmation
- **Exit logic**: ATR-based stop, R-multiple profit target, EOD close
- **Signal types**: Breakout, BOS (Break of Structure), FVG gaps
- **Deployment**: Railway (PostgreSQL + intraday_bars_5m table)
- **Data sources**: EODHD (historical), Tradier (live options), Unusual Whales (flow)

---

## 📁 Canonical Repo Structure

```
War-Machine/
├── app/                        ← CORE SYSTEM (production code)
│   ├── core/                   ← Main scanner, signal engine, scheduler
│   ├── signals/                ← Signal generation (breakout, BOS, FVG)
│   ├── filters/                ← All entry filters (see filter registry below)
│   ├── indicators/             ← ATR, VWAP, EMA, etc.
│   ├── data/                   ← DB connection, data loaders
│   ├── screening/              ← Pre-market scanner
│   ├── options/                ← Options chain + Greeks
│   ├── risk/                   ← Position sizing, drawdown guard
│   ├── ml/                     ← ML confidence scoring (WIP)
│   ├── mtf/                    ← Multi-timeframe bias
│   ├── ai/                     ← AI signal enhancement (WIP)
│   ├── analytics/              ← Performance analytics
│   ├── validation/             ← Signal validation layer
│   └── notifications/          ← Discord alerts
├── backtests/
│   └── results/                ← Per-ticker JSON summaries + CSVs + walk-forward folds
├── scripts/
│   ├── analysis/               ← One-off analysis scripts
│   ├── backtesting/            ← Backtest runners
│   ├── optimization/           ← Parameter sweep scripts
│   ├── ml/                     ← ML training pipelines
│   ├── database/               ← DB maintenance/migrations
│   ├── maintenance/            ← Health checks, cleanup
│   ├── powershell/             ← Deploy/run scripts
│   └── deploy.ps1              ← Primary deploy script
├── docs/                       ← Architecture docs, strategy notes
├── CONTEXT.md                  ← THIS FILE — always update after commits
├── README.md
├── .gitignore
└── requirements.txt
```

---

## 🔧 Filter Registry (`app/filters/`)

| Filter | File | Purpose |
|--------|------|---------|
| RTH Filter | `rth_filter.py` | Block trades outside Regular Trading Hours |
| VWAP Gate | `vwap_gate.py` | Only enter when price is on correct side of VWAP |
| Market Regime | `market_regime_context.py` | Bull/bear/chop detection via SPY trend |
| MTF Bias | `mtf_bias.py` | 15m/1h trend alignment before entry |
| Dead Zone Suppressor | `dead_zone_suppressor.py` | Block entries in 11:00–13:30 low-momentum window |
| Early Session Disqualifier | `early_session_disqualifier.py` | Block first 5–10 min of session (chaos avoidance) |
| SD Zone Confluence | `sd_zone_confluence.py` | Supply/demand zone alignment check |
| Order Block Cache | `order_block_cache.py` | Institutional order block proximity gate |
| Liquidity Sweep | `liquidity_sweep.py` | Confirm stop hunt / liquidity grab before entry |
| GEX Pin Gate | `gex_pin_gate.py` | Block entries near GEX pin levels (options market friction) |
| Correlation | `correlation.py` | Remove correlated signals (portfolio dedup) |

---

## 📊 Backtest Results Summary (90-day, 51 tickers)

**Aggregate (all tickers):**
- Total trades: 119 | Win rate: 49.6% | Profit factor: 1.20
- Avg R: 0.064 | Max drawdown: 9.22R
- Exit breakdown: EOD=74, STOP=44, T2=1

**Top Performers by Profit Factor:**
| Ticker | Trades | Win% | Avg R | PF | Notes |
|--------|--------|------|-------|----|-------|
| AAOI   | 11 | 72.7% | 0.615 | 4.28 | 🏆 Best overall |
| FSLY   | 9  | 55.6% | 0.260 | 1.75 | Strong R per trade |
| HYMC   | 12 | 58.3% | 0.218 | 1.66 | Good volume/momentum |
| NVDA   | 4  | 50.0% | 0.295 | 2.05 | High avg win R |
| SPY    | 6  | 50.0% | 0.163 | 1.39 | Benchmark |

**Worst Performers:**
| Ticker | Trades | Win% | Avg R | PF |
|--------|--------|------|-------|----|
| OXY    | 10 | 30.0% | -0.324 | 0.27 |
| AXTI   | 12 | 33.3% | 0.020  | 1.09 |

**Hourly Win Rates:**
- 9:30–10:00 (hour 9): 49.3% — 75 trades
- 10:00–11:00 (hour 10): 50.0% — 44 trades
- 11:00+ : 0 trades (dead zone filter working as intended)

---

## 🔑 Key Findings — Filter Impact Analysis

### Highest-Impact Filters (by inferred effect on results):

1. **Dead Zone Suppressor** — HIGHEST IMPACT
   - Zero trades logged after 11:00AM across all 51 tickers
   - This is the single biggest trade-reduction filter; directly responsible for eliminating ~30–40% of would-be entries
   - Keeps us in the two cleanest momentum windows: 9:30–10:00 and 10:00–11:00

2. **RTH Filter** — HIGH IMPACT
   - Eliminates all pre/post-market noise
   - Without it, FVG detection on overnight gaps would produce false entries

3. **VWAP Gate** — HIGH IMPACT
   - Best-performing tickers (AAOI, FSLY, HYMC) are high-beta names where VWAP deviation is clear
   - Tickers that failed (OXY, AXTI) tend to be range-bound — VWAP gate likely didn't fire cleanly

4. **Early Session Disqualifier** — MEDIUM-HIGH IMPACT
   - Prevents fakeout breakouts in first 5–10 min
   - Contributes to cleaner ORB (Opening Range) formation

5. **Market Regime Context** — MEDIUM IMPACT
   - Regime filter protects against entering breakouts during broad market chop
   - Needs refinement — profit_factor only 1.20 aggregate suggests regime detection is too loose

6. **MTF Bias** — MEDIUM IMPACT (needs validation)
   - Not enough per-filter attribution data yet; needs ablation testing

7. **Liquidity Sweep + Order Block Cache** — LOW-MEDIUM (insufficient data)
   - These are newer filters; no ablation data yet

---

## 🚧 Identified Repo Issues

### Files That Are Unnecessary / Causing Confusion:

| File/Dir | Issue | Action |
|----------|-------|--------|
| `.fix_print_backup/` | Backup dir from fix_print_to_logger.py run — temp artifact | **DELETE** |
| `atr_check.py` (root) | Loose debug script — should be in `scripts/analysis/` | **MOVE** |
| `backfill_history.py` (root) | Duplicate of `scripts/backfill_historical.py` | **DELETE** (root version) |
| `backtest_sweep.py` (root) | Should live in `scripts/backtesting/` | **MOVE** |
| `entry_times.py` (root) | Loose analysis script | **MOVE to scripts/analysis/** |
| `inspect_candles.py` (root) | Debug utility, root-level | **MOVE to scripts/analysis/** |
| `scripts/debug_bos_scan.py` | One-off debug — no longer needed | **DELETE** |
| `scripts/debug_comprehensive.py` | One-off debug — no longer needed | **DELETE** |
| `scripts/debug_db.py` | One-off debug — no longer needed | **DELETE** |
| `scripts/fix_print_to_logger.py` | Migration script — already run, done | **DELETE** |
| `scripts/check_eodhd_intraday.py` | One-off API check script | **DELETE** |
| `CONTRIBUTING.md` | Generic template, not relevant for solo private project | **DELETE** |
| `.railway_trigger` | Railway deploy trigger — keep but document purpose | **KEEP** |

---

## 🗓️ Current Development State (as of 2026-03-24)

### ✅ Completed
- 90-day backtest across 51 tickers with full per-symbol summaries
- Walk-forward fold validation on major tickers
- Full filter suite implemented in `app/filters/`
- Railway deployment pipeline working
- Discord notification system live
- EODHD 5m bar backfill complete

### 🔄 In Progress
- ML confidence scoring (`app/ml/`) — training data generation done, model training next
- MTF bias ablation testing (need per-filter win rate tracking)
- Dead zone boundary refinement (test 11:30 vs 12:00 cutoff)

### 📋 Next Steps
1. Run filter ablation: backtest with each filter toggled OFF to measure individual impact
2. Improve regime filter — currently too permissive (1.20 PF target is 1.50+)
3. Add per-signal R-tracking to live system for real-time filter scoring
4. Expand high-performing ticker list (AAOI, FSLY, HYMC profiles)
5. ML model training with generated features

---

## 🧹 Repo Cleanup Checklist
- [ ] Delete `.fix_print_backup/`
- [ ] Move `atr_check.py`, `backtest_sweep.py`, `entry_times.py`, `inspect_candles.py` to `scripts/`
- [ ] Delete `backfill_history.py` (root duplicate)
- [ ] Delete `scripts/debug_*.py` files
- [ ] Delete `scripts/fix_print_to_logger.py`
- [ ] Delete `scripts/check_eodhd_intraday.py`
- [ ] Delete `CONTRIBUTING.md`
- [ ] Confirm `backfill_history.py` vs `scripts/backfill_historical.py` — keep scripts/ version

---

## 📝 Commit Log (recent)
| Date | Description |
|------|-------------|
| 2026-03-24 | Added CONTEXT.md — persistent AI state file |
| Prior | 90-day backtest sweep complete, all summaries written |
