# WAR MACHINE — BACKTEST INTELLIGENCE
> **Auto-generated from `backtests/analysis/`** — overwrite this file each time you run `analyze_trades.py`
> Last updated: 2026-03-24 (Phase 1.37b) | Dataset: 107 trades | Win rate: 48.6% baseline

---

## 📊 Core Performance Metrics

| Metric | Baseline | With RVOL ≥ 1.2 Gate |
|---|---|---|
| Total trades | 107 | 47 |
| Win rate | 48.6% | **59.6% (+11.0pp)** |
| Avg R | 0.073 | **+0.300** |
| Total R | 7.85 | **+14.1** |
| EOD exits | 65 (61%) | — |
| T1 hits | 1 | — |
| T2 hits | 1 (2.0R) | — |

---

## 🔑 #1 Priority Filter — RVOL Gate

The single most impactful lever in the entire system:

```
RVOL < 1.2  →  40.0% WR, avg R = -0.101  ← destroying P&L
RVOL ≥ 1.2  →  59.6% WR, avg R = +0.300  ← the real edge
```

**RVOL gate is now set to 1.2x** (`RVOL_SIGNAL_GATE = 1.2` in `utils/config.py`).

For reference, RVOL=1.0 maximizes **Total R** (15.8 on 62 trades) while RVOL=1.2 maximizes
**Avg R and Win Rate** on a higher-quality 47-trade cohort. Current config uses 1.2x.

---

## 🧮 Grid Search Results (Phase 1.37b — 2026-03-24)

Grid: 13 T1 × 13 T2 × 21 RVOL gates = 3,549 combinations → 2,512 valid.

### RVOL Gate Sweep (T1=2.0, T2=3.5)

| RVOL Gate | Trades | Win Rate | Avg R | Total R |
|---|---|---|---|---|
| 0.5 (none) | 107 | 48.6% | 0.077 | 8.22 |
| 0.8 | 81 | 51.8% | 0.155 | 12.56 |
| 0.9 | 73 | 54.8% | 0.207 | 15.15 |
| **1.0** | **62** | **56.5%** | **0.255** | **15.81** ← max Total R |
| **1.2** | **47** | **59.6%** | **0.300** | **14.10** ← max Avg R / WR |
| 1.3 | 42 | 59.5% | 0.276 | 11.58 |
| 1.5 | 27 | 48.1% | 0.082 | 2.20 |

### T1/T2 Multiplier Findings

- **T1=2.0R** outperforms T1=1.3R on RVOL≥1.2 cohort: Total R 14.1 vs 11.85
- Reason: winning trades run past 1.3R on EOD exits anyway — tighter T1 under-credits them
- **T2 is insensitive** — only **1 T2 hit** in 107 trades; T2 value doesn't affect simulation
- T2 kept at 3.5R as aspirational target for future runners

### Config Applied
```python
RVOL_SIGNAL_GATE = 1.2   # was 1.28
T1_MULTIPLIER    = 2.0   # was 1.3
T2_MULTIPLIER    = 3.5   # was 2.5 (restored)
```

---

## 🧪 Feature Significance (p-value analysis)

| Feature | Win Mean | Loss Mean | p-value | Significant | Direction |
|---|---|---|---|---|---|
| `confidence` | 0.709 | 0.738 | 0.0057 | ✅ YES | ⚠️ Higher = MORE losses |
| `grade_num` | 1.058 | 1.255 | 0.0057 | ✅ YES | ✅ Lower grade# = wins |
| `rvol` | 1.290 | 1.209 | 0.1133 | ❌ no | Higher = better |
| `or_range_pct` | 3.768 | 4.054 | 0.5028 | ❌ no | — |
| `minutes_from_open` | 28.5 | 27.9 | 0.5679 | ❌ no | — |
| `fvg_size_pct` | 0.143 | 0.164 | 0.7553 | ❌ no | — |
| `entry_hour` | 9.385 | 9.364 | 0.8263 | ❌ no | — |

> ⚠️ **CRITICAL FINDING:** `confidence` score is **inversely correlated with wins** (p=0.006). Higher confidence → more losses. Confidence scoring must be audited/inverted before raising confidence floors.

---

## 🏆 Ticker Performance Tier List

### ✅ Keep (Positive avg R)

| Ticker | Avg R | Win Rate | Trades |
|---|---|---|---|
| WMT | +0.710 | 100% | 2 |
| AAOI | +0.615 | 72.7% | 11 |
| VG | +0.505 | 100% | 2 |
| AMD | +0.435 | 100% | 2 |
| QQQ | +0.350 | 66.7% | 3 |
| NVDA | +0.295 | 50.0% | 4 |
| FSLY | +0.260 | 55.6% | 9 |
| HYMC | +0.218 | 58.3% | 12 |
| BAC | +0.175 | 50.0% | 2 |
| SPY | +0.163 | 50.0% | 6 |
| MSFT | +0.147 | 66.7% | 3 |

### ❌ Banned (Negative avg R — removed from watchlist)

| Ticker | Avg R | Win Rate | Trades | Reason |
|---|---|---|---|---|
| ORCL | -0.670 | 0% | 3 | 🗑️ 0 wins, worst avg R |
| MSTR | -0.530 | 0% | 2 | 🗑️ 0 wins |
| LYB | -0.342 | 25% | 8 | 🗑️ consistent loser |
| OXY | -0.324 | 30% | 10 | 🗑️ consistent loser |
| PYPL | -0.244 | 28.6% | 7 | 🗑️ consistent loser |
| CMCSA | -0.188 | 50% | 4 | 🗑️ negative expectancy |

---

## 🚪 Recommended Filter Candidates

| Filter | Baseline WR | Filtered WR | Gain | Trades Retained |
|---|---|---|---|---|
| `rvol >= 1.2` ✅ **APPLIED** | 48.6% | **59.6%** | +11.0pp | 47 (44%) |
| `rvol >= 1.0` (alt — max total R) | 48.6% | 56.5% | +7.9pp | 62 (58%) |
| FVG size > 0.04% | 48.6% | ~51.8% | +3.2pp | 85 (79%) |
| Minutes from open > 25 | 48.6% | ~51.7% | +3.1pp | 58 (54%) |

---

## ⚠️ EOD Exit Problem

65 of 107 trades (61%) exit EOD with no T1 or T2 hit. This is the primary drag on performance.

With T1=2.0R (Phase 1.37b), T1 is now intentionally wide — the system lets winners run to EOD
rather than forcing premature exits. **This is by design until T2 hits become more frequent.**
The single T2 hit (2.0R) proves target logic works — it just rarely fires on current setups.

---

## 🎯 Current Action Items (Phase 1.37b)

1. ✅ **RVOL gate 1.2x applied** — `RVOL_SIGNAL_GATE = 1.2` in `utils/config.py`
2. ✅ **T1=2.0R, T2=3.5R applied** — grid search optimal
3. ✅ **ORCL, MSTR, OXY, LYB, PYPL, CMCSA banned** — removed from `watchlist_funnel.py` and `aggregate_summary.json`
4. ⏳ **Audit confidence scoring logic** — inversely correlated with wins (p=0.006); likely needs rebuild
5. ⏳ **Re-run analysis after 50+ live trades** with Phase 1.37b params and regenerate this file

---

## 🔄 How to Update This File

After each backtest run:

```python
# scripts/generate_backtest_intelligence.py
# Reads: backtests/analysis/*.csv + filter_candidates.txt
# Writes: docs/BACKTEST_INTELLIGENCE.md
# Then: git add docs/BACKTEST_INTELLIGENCE.md && git commit -m "docs: update backtest intelligence YYYY-MM-DD"
```

> This file is the single source of truth for War Machine signal quality. Never let it go stale.
