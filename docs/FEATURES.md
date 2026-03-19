# War Machine — Feature Reference

> **Purpose:** Living reference for all major features — what they do, how they're configured, and their current status.  
> **Scope:** Explosive movers, regime filter, VPVR, optimization methodology, ML weights, backtest results.  
> **Living doc:** Update this when features change configuration or status.

---

## Table of Contents
1. [Explosive Mover Tracker](#1-explosive-mover-tracker)
2. [Regime Filter](#2-regime-filter)
3. [VPVR (Volume Profile Visible Range)](#3-vpvr-volume-profile-visible-range)
4. [Optimization Methodology](#4-optimization-methodology)
5. [ML Confidence Weights](#5-ml-confidence-weights)
6. [Backtest Results](#6-backtest-results)

---

## 1. Explosive Mover Tracker

**Modules:**
- `app/analytics/explosive_mover_tracker.py` — Historical explosive move database builder
- `app/analytics/explosive_tracker.py` — Real-time session monitoring

**Status:** ✅ LIVE

### What It Does

Tracks tickers that make explosive intraday moves (>3% in a single session) to:
1. Build a historical database of explosive-move setups for ML training
2. Apply an `explosive_override` boost to signal confidence for known explosive movers
3. Surface prior-day explosive movers as priority candidates for next-day pre-market scan

### Configuration

```python
EXPLOSIVE_MOVE_THRESHOLD = 0.03    # 3% minimum intraday move to qualify
EXPLOSIVE_HISTORY_LOOKBACK = 30    # Days of history to maintain
EXPLOSIVE_CONFIDENCE_BOOST = 8     # Points added to signal confidence
EXPLOSIVE_TRACKER_MIN_RVOL = 1.5   # Minimum RVOL to count as explosive
```

### Two-Tracker Architecture

| Module | Role | When it fires |
|--------|------|---------------|
| `explosive_tracker.py` | Real-time session monitor | Every scan tick during RTH |
| `explosive_mover_tracker.py` | Historical cataloguer + ML feeder | EOD, feeds `ai_learning.py` |

These are intentionally separate — the real-time tracker is stateless and fast; the historical tracker writes to PostgreSQL and feeds ML retraining.

### Data Flow
```
explosive_tracker.py (real-time)
  → signals explosive_override flag → sniper.py confidence boost
  → signal_boosters.py adds score points

explosive_mover_tracker.py (historical)
  → PostgreSQL explosive_movers table
  → ai_learning.py (daily retraining)
  → target_discovery.py (missed signal analysis)
  → premarket_scanner.py (next-day priority candidates)
```

---

## 2. Regime Filter

**Module:** `app/filters/correlation.py` + regime logic inline in `app/core/sniper.py`  
**Status:** ✅ LIVE  
**Full wiring guide:** See `docs/INTEGRATION_GUIDE.md` § 5

### Regime States

| State | VIX Range | SPY Condition | Action |
|-------|-----------|---------------|--------|
| `NORMAL` | < 15 | Any trend | Full trading |
| `ELEVATED_VOL` | 15–20 | Any trend | Normal with tighter stops |
| `VOLATILE` | 20–30 | Any trend | Reduced size (VIX sizer active) |
| `EXTREME` | > 30 | Any trend | Block new entries |
| `CHOPPY` | Any | SPY range-bound | Require stronger MTF confirmation |

### Correlation Groups (Sector Buckets)

```python
CORRELATION_GROUPS = {
    'TECH_MEGA': ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN'],
    'SEMIS': ['NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'SMCI', 'MU'],
    'EV': ['TSLA', 'RIVN', 'LCID', 'NIO'],
    'FINANCE': ['JPM', 'GS', 'MS', 'BAC', 'C'],
    'BIOTECH': ['MRNA', 'BNTX', 'NVAX'],
    'ENERGY': ['XOM', 'CVX', 'OXY', 'SLB'],
}
# Max 2 positions from same group simultaneously
```

---

## 3. VPVR (Volume Profile Visible Range)

**Modules:**
- `app/indicators/volume_profile.py` — POC/VAH/VAL calculator
- `app/validation/volume_profile.py` — Signal validation gate

**Status:** ✅ LIVE  
**Cache:** 5-min TTL (added Session 1, commit `cea9180`)

### What It Does

Builds an intraday volume profile to identify:
- **POC (Point of Control):** Price level with highest traded volume — acts as price magnet
- **VAH (Value Area High):** Top of the 70% volume zone
- **VAL (Value Area Low):** Bottom of the 70% volume zone
- **Low-volume nodes:** Price gaps with thin volume — fast-move zones favored for entries

### Validation Gate Logic

```python
# validation/volume_profile.py
# Signal entry price must NOT be at a high-volume node (price magnet)
# Preferred: entries at low-volume nodes near POC boundaries

if entry_price_is_at_hvn(entry_price, volume_profile):
    return False, "Entry at high-volume node — reduced momentum potential"

if entry_price_near_poc(entry_price, poc, tolerance=0.002):
    confidence_penalty = -5  # Slight penalty for POC entries
```

### VPVR Deployment Notes

- VPVR requires at least 30 minutes of intraday bar data before the profile is meaningful
- Pre-market signals skip VPVR validation (insufficient intraday volume)
- The volume profile resets at each session open (9:30 AM ET)
- Historical VPVR (prior day profile) is available but not currently used in validation — future enhancement opportunity

### Performance Impact

- Calculation: O(n) where n = number of price levels (typically 200–500)
- With 5-min TTL cache: 1 calculation per 5 minutes per ticker = negligible overhead
- Without cache (pre-Session 1): recalculated on every signal = ~50ms per call at scale

---

## 4. Optimization Methodology

**Module:** `app/backtesting/parameter_optimizer.py` + `app/backtesting/walk_forward.py`  
**Status:** ✅ LIVE (manual trigger) | ⏳ Automated weekend run — PENDING

### CFW6 Optimizable Parameters

| Parameter | Current Value | Search Range | Optimization Method |
|-----------|--------------|--------------|--------------------|
| Min RVOL threshold | 1.5x | 1.2x – 2.5x | Grid search |
| ADX minimum | 20 | 15 – 35 | Grid search |
| ATR stop multiplier | 1.5x | 1.0x – 2.5x | Grid search |
| MTF alignment weight | 1.15x | 1.0x – 1.3x | Grid search |
| Confidence gate (A+) | 82 | 78 – 90 | Grid search |
| Confidence gate (A) | 74 | 70 – 82 | Grid search |
| Confidence gate (A-) | 66 | 62 – 74 | Grid search |
| BOS lookback bars | 20 | 10 – 40 | Grid search |

### Walk-Forward Protocol

```
Data window: Last 90 trading days
In-sample: 60 days (parameter optimization)
Out-of-sample: 30 days (validation)
Step size: 5 days (rolling forward)
Min trades to evaluate: 20 per window
Objective function: Sharpe ratio (annualized)
Overfit protection: Out-of-sample Sharpe must be ≥ 70% of in-sample Sharpe
```

### Optimization Cadence

- **Current:** Manual trigger via `scripts/backtesting/run_optimization.py`
- **Target:** Automated every weekend (Sunday night), auto-apply if out-of-sample Sharpe improvement > 0.1
- **Safety:** Parameters only update after human review in Railway environment variables

---

## 5. ML Confidence Weights

**Modules:** `app/ml/ml_signal_scorer_v2.py` (active), `app/ml/ml_confidence_boost.py`  
**Status:** ✅ LIVE (v2 scorer)

### ML Confidence Adjustment Table

| ML Win Probability | Confidence Adjustment | Effect |
|-------------------|----------------------|--------|
| ≥ 70% | +10 points | Strong ML confirmation |
| 60–70% | +5 points | Moderate ML confirmation |
| 50–60% | 0 points | Neutral |
| 40–50% | -5 points | Mild ML skepticism |
| < 40% | -15 points | Strong ML veto |

### Feature Vector (v2 Scorer)

The ML model takes these features per signal:
- `rvol` — relative volume vs 20-day average
- `vix` — current VIX level
- `score` — raw CFW6 rule-based score (0–100)
- `time_of_day` — encoded as float (9.5 = 9:30 AM)
- `confidence` — pre-ML confidence percentage
- `regime` — encoded regime state
- `adx` — ADX strength at signal time
- `mtf_alignment` — number of aligned timeframes (0–3)
- `ivr` — IV Rank of the underlying (0–100)
- `uoa_score` — unusual options activity score

### Known Gap — Resolved 2026-03-16

Previous issue: ML weights file `models/signal_predictor.pkl` was tracked in git as a binary, causing bloated repo history. Fixed: added to `.gitignore` (commit `5828488`). Model is now generated locally and deployed separately.

### Training Cadence

```python
# ai_learning.py — fires at EOD (4:00 PM ET)
ml.retrain_daily()  # Trains on that day's labeled signal outcomes
# Minimum 20 completed trades required to update model weights
# Falls back to previous model weights if insufficient data
```

---

## 6. Backtest Results

**Status:** Results from parameter optimization runs on EODHD historical data.

### Current Production Parameters — Backtest Performance

| Metric | Value | Period |
|--------|-------|--------|
| Win Rate | ~62–65% | Last 90 days |
| Avg Win / Avg Loss | ~1.8R | Last 90 days |
| Sharpe Ratio | ~1.4 (annualized) | Last 90 days |
| Max Drawdown | ~8% | Last 90 days |
| Profit Factor | ~2.1 | Last 90 days |
| Avg Hold Time | ~18 min | Last 90 days |

> **Note:** Live performance may vary. Backtest results use EODHD data with realistic slippage model (0.02% per side). No look-ahead bias — signals only use data available at signal time.

### Signal Grade Breakdown (Backtest)

| Grade | Confidence Range | Win Rate | Avg R |
|-------|-----------------|----------|-------|
| A+ | 82–100 | ~72% | ~2.1R |
| A | 74–81 | ~63% | ~1.7R |
| A- | 66–73 | ~54% | ~1.3R |

### Key Finding: Time-of-Day Performance

| Window | Win Rate | Signal Count | Notes |
|--------|----------|-------------|-------|
| 9:45–10:30 AM | ~71% | High | Best window |
| 10:30–11:30 AM | ~65% | Medium | Strong |
| 11:30 AM–1:00 PM | ~48% | Low | Below edge |
| 1:00–2:30 PM | ~58% | Medium | Acceptable |
| 2:30–3:30 PM | ~64% | Medium | Power hour recovery |
| 3:30–4:00 PM | N/A | 0 | Blocked by entry_timing.py |

---

*Last updated: 2026-03-16 | Batch E consolidation | Replaces: EXPLOSIVE_MOVER_INTEGRATION.md, REGIME_FILTER_SUMMARY.md, docs/features/README_REGIME_FILTER.md, VPVR_INTEGRATION_GUIDE.md, docs/features/VPVR_DEPLOYED.md, OPTIMIZATION_README.md, ML_WEIGHTS_GAP.md, backtests.md*
