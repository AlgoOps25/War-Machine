# WAR MACHINE — BACKTEST INTELLIGENCE
> **Auto-generated from `backtests/analysis/`** — overwrite this file each time you run `analyze_trades.py`
> Last updated: 2026-03-24 | Dataset: 107 trades (119 with duplicates) | Win rate: 48.6%

---

## 📊 Core Performance Metrics

| Metric | Value |
|---|---|
| Total trades | 107 |
| Win rate (baseline) | 48.6% |
| Win rate w/ RVOL ≥ 1.276 filter | **60.5% (+11.9pp)** |
| Trades retained after RVOL filter | 43 (40%) |
| EOD exits (no T1/T2 hit) | 74 / 119 (62%) |
| T1 hits | ~5% |
| T2 hits | 1 (2.0R) |

---

## 🔑 #1 Priority Filter — RVOL Gate

The single most impactful lever identified by the backtest:

```
rvol >= 1.276  →  WR jumps 48.6% → 60.5%  (+11.9pp, 43 trades retained)
```

**Action:** Enforce `rvol >= 1.28` as a hard gate in signal logic before any other filter.

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

> ⚠️ **CRITICAL FINDING:** `confidence` score is **inversely correlated with wins** (p=0.006). Higher confidence → more losses. The confidence scoring model is miscalibrated and must be audited/inverted.

---

## 🏆 Ticker Performance Tier List

### ✅ Keep (Positive avg R, ≥2 trades)

| Ticker | Avg R | Win Rate | Trades |
|---|---|---|---|
| AAOI | +0.615 | 72.7% | 11 |
| QQQ | +0.350 | — | — |
| NVDA | +0.295 | — | — |
| SPY | positive | — | — |
| MSFT | positive | — | — |
| FSLY | +0.260 | — | — |
| HYMC | +0.218 | — | — |
| BAC | positive | — | — |

### ❌ Remove / Deprioritize (Negative avg R)

| Ticker | Avg R | Win Rate | Action |
|---|---|---|---|
| ORCL | -0.670 | 0% | 🗑️ Remove from watchlist |
| MSTR | -0.530 | 0% | 🗑️ Remove from watchlist |
| LYB | -0.342 | — | 🗑️ Remove |
| OXY | -0.324 | — | 🗑️ Remove |
| PYPL | -0.244 | — | 🗑️ Remove |
| CMCSA | -0.188 | — | 🗑️ Remove |

---

## 🚪 Recommended Filter Candidates

Ranked by win rate improvement (from `filter_candidates.txt`):

| Filter | Baseline WR | Filtered WR | Gain | Trades Retained |
|---|---|---|---|---|
| `rvol >= 1.276` | 48.6% | **60.5%** | +11.9pp | 43 (40%) |
| FVG size filter | 48.6% | ~52% | +3pp | — |
| Minutes-from-open filter | 48.6% | ~51% | +3pp | — |

---

## ⚠️ EOD Exit Problem

62% of trades exit EOD with no T1 or T2 hit. Root causes to investigate:

- Profit targets (T1/T2) may be too wide relative to intraday momentum
- Breakout signals may be firing on moves that stall before target
- Consider tightening T1 to ~1.2–1.5R from current levels
- The single T2 hit (2.0R) proves target logic works — it just rarely fires

---

## 🎯 Immediate Action Items

1. **Add `rvol >= 1.28` as a hard gate** in `app/core/scanner.py` or signal scoring
2. **Audit confidence scoring logic** — it is anticorrelated with wins (p=0.006); likely needs inversion or full rebuild
3. **Remove ORCL, MSTR, OXY, LYB, PYPL, CMCSA** from static watchlist in `watchlist_funnel.py`
4. **Tighten T1 target** — investigate EOD exit rate; 62% is too high
5. **Re-run analysis after each major change** and overwrite this file

---

## 🔄 How to Update This File

After each backtest run, execute:

```python
# scripts/generate_backtest_intelligence.py
# Reads: backtests/analysis/*.csv + filter_candidates.txt
# Writes: docs/BACKTEST_INTELLIGENCE.md
# Then: git add docs/BACKTEST_INTELLIGENCE.md && git commit -m "docs: update backtest intelligence YYYY-MM-DD"
```

> This file is the single source of truth for War Machine signal quality. Never let it go stale.
