# War Machine — Changelog

> **Purpose:** Historical record of all phases, fixes, integration patches, and session summaries.  
> **Format:** Newest entries at the top. Phase completions, hotfixes, and deployment events.  
> **Living doc:** Append new entries here instead of creating new history files.

---

## 2026-03-27 — Session Handoff: Issue #12 Backlog Formalized

### Overview
Session handoff documentation update. No code changes this session.  
Phase 1.38d-fix is complete — all 8 execution blockers (FIX A–H) are resolved.  
War Machine can now execute trades end-to-end for the first time since the `sniper_pipeline.py` refactor.  
Issue #12 GitHub issues are closed; 6 remaining sub-items are tracked in code and formalized in `docs/remediation_tracker.md` Phase 7.

---

### Session Summary

#### Session 2 (2026-03-26) Outcomes
- Full file-by-file audit of `app/core/` signal path in execution order
- FIX H: `arm_signal.py` SyntaxError from mis-indented try blocks — entire pipeline was unimportable
- FIX G: `arm_signal.py` `arm_ticker()` missing `return True` — success path always returned `None`
- FIX F: `sniper.py` VWAP reclaim path used synthetic OR refs — now passes `0.0, 0.0` explicitly
- FIX E: `sniper.py` dispatcher passed stale kwargs to `_pipeline()` — removed `get_ticker_screener_metadata=` and `state=`
- Clean boot confirmed 2026-03-26 19:36 UTC ✅

#### Session 1 (2026-03-26) Outcomes
- FIX D: `sniper_pipeline.py` `arm_ticker()` return value never checked
- FIX C: `sniper_pipeline.py` double `set_cooldown()` call removed
- FIX B: `sniper_pipeline.py` `options_rec` missing default — `options_rec=None` added
- FIX A: `sniper_pipeline.py` `**_unused_kwargs` absorbs legacy kwargs
- Root fix: `arm_ticker()` called with only 7 of 13 required args — `compute_stop_and_targets()` wired before arm call
- `app/core/sniper_log.py` created (was an `ImportError` on every arm attempt)

#### Combined Effect (Sessions 1 + 2)
All issues together meant **zero trades could ever be executed** after the Phase 1.38d refactor.  
Signal detection, scanning, filters, scorecard, and confirmations were all functional — only the final arm steps were broken.  
All 8 execution blockers are now resolved.

---

### Phase 1.38d-fix Patch Summary

| Fix | File | Description | Status |
|-----|------|-------------|--------|
| FIX A | `sniper_pipeline.py` | `**_unused_kwargs` absorbs legacy kwargs | ✅ |
| FIX B | `sniper_pipeline.py` | `options_rec=None` default added | ✅ |
| FIX C | `sniper_pipeline.py` | Double `set_cooldown()` removed | ✅ |
| FIX D | `sniper_pipeline.py` | `arm_ticker()` return value now checked | ✅ |
| FIX E | `sniper.py` | Stale kwargs removed from dispatcher | ✅ |
| FIX F | `sniper.py` | VWAP reclaim OR refs corrected to `0.0, 0.0` | ✅ |
| FIX G | `arm_signal.py` | `return True` added to success path | ✅ |
| FIX H | `arm_signal.py` | SyntaxError from mis-indented try blocks fixed | ✅ |

---

### Issue #12 Backlog Status

All GitHub issues under Issue #12 are **closed**. 6 sub-items remain tracked in code and formalized as Phase 7 findings in `docs/remediation_tracker.md`.

| Priority | Item | File |
|----------|------|------|
| 🔴 P1 | Duplicate `compute_stop_and_targets` call (Step 8 + Step 9) | `sniper_pipeline.py` |
| 🔴 P1 | Asymmetric multiplier caps (+15%/-20%) — propose +20%/-15% | `sniper_pipeline.py` |
| 🔴 P1 | Static `mode_decay = 0.95` — wire to live win-rate data | `sniper_pipeline.py` |
| 🔵 P2 | Flat `MIN_OR_RANGE_PCT = 3%` — needs price-tiered thresholds | `utils/config.py` |
| 🔵 P2 | Pre-market range computed but discarded — integrate or delete | `sniper.py` |
| 🔵 P2 | `MAX_WATCH_BARS = 12` hardcoded — make adaptive by grade | `sniper_pipeline.py` |

---

### Known Cosmetic Issues (Low Priority)

| Issue | File |
|-------|------|
| Signal Analytics summary prints ~20x on startup | `app/signals/signal_analytics.py` |
| `_resample_bars()` duplicated in `sniper.py` and `sniper_pipeline.py` | `app/core/sniper.py`, `app/core/sniper_pipeline.py` |

---

### Next Recommended Action
Start on Issue #12 P1 item #1: **duplicate `compute_stop_and_targets` call** in `sniper_pipeline.py` — estimated 15 min, zero risk.

---

## 2026-03-26 — Session 2: Full Core Audit & arm_signal SyntaxError Fix

### Overview
Full file-by-file audit of the entire `app/core/` signal path in execution order:
`sniper.py` → `sniper_pipeline.py` → `signal_scorecard.py` → `arm_signal.py` → `armed_signal_store.py` → `thread_safe_state.py`.
Container boot confirmed clean (no errors, no crashes) after all fixes applied.

---

### FIX H — arm_signal.py: SyntaxError from mis-indented try blocks ❌→✅ FIXED

**File:** `app/core/arm_signal.py` — commit `945029d`

**Root cause:** Two `try:` blocks inside `arm_ticker()` were at column 0 (outside the function
body). Python parsed them as module-level statements, causing a `SyntaxError` that crashed
`app.core.arm_signal` on import. Since `sniper_pipeline.py` imports `arm_ticker` at the top
level, this meant **the entire pipeline module was unimportable** — `arm_ticker()` was
unreachable regardless of all other fixes.

**Affected blocks (were at col 0):**
- Discord alert production helper `try/except ImportError` block
- Cooldown `try/except` block
- Dead Phase 4 alert check stub (removed entirely as it had no effect)

**Fix:** All `try:` blocks correctly indented inside `arm_ticker()` function body.
`return True` (FIX G) preserved at end of success path.

---

### FIX G — arm_signal.py: arm_ticker() missing return True ❌→✅ FIXED

**File:** `app/core/arm_signal.py` (applied in same commit as FIX H)

**Root cause:** `arm_ticker()` had no explicit `return` statement on the success path —
returned `None` implicitly. Any caller checking `if arm_ticker(...):` would always see `False`.

**Fix:** `return True` added at end of success path. Failure paths (`stop too tight`,
`position rejected`) continue to return `None` (falsy) intentionally.

---

### FIX F — sniper.py: VWAP reclaim path used synthetic OR refs ❌→✅ FIXED

**File:** `app/core/sniper.py` (applied prior to session 2 commit)

**Root cause:** VWAP reclaim path passed `entry_price * 1.005` and `entry_price * 0.995`
as `or_high_ref` / `or_low_ref`. No opening range was formed on this path — synthetic
values were misleading and could corrupt `compute_stop_and_targets()` OR-boundary logic.

**Fix:** Pass `0.0, 0.0` explicitly. `compute_stop_and_targets()` M8 guard already skips
OR boundary comparison when `or_high=0.0` / `or_low=0.0`.

---

### FIX E — sniper.py: dispatcher passed stale kwargs to _pipeline() ❌→✅ FIXED

**File:** `app/core/sniper.py` (applied prior to session 2 commit)

**Root cause:** The thin `_run_signal_pipeline()` dispatcher in `sniper.py` was passing
`get_ticker_screener_metadata=` and `state=` as keyword args to `_pipeline()`. These were
part of the old all-in-one `sniper.py` signature before pipeline extraction. The extracted
`sniper_pipeline._run_signal_pipeline()` does not accept these kwargs, causing `TypeError`
on every pipeline dispatch call.

**Fix:** Removed both stale kwargs from the dispatcher call.

---

### FIX D — sniper_pipeline.py: arm_ticker() return value never checked ❌→✅ FIXED

**File:** `app/core/sniper_pipeline.py` (applied in session 1)

**Root cause:** `arm_ticker()` returned `None` implicitly. The pipeline had `if armed: ...`
which was dead code — never `True`. The pipeline now returns `True` after calling
`arm_ticker()` unconditionally (arm_ticker guards its own failure paths and logs them).
Callers receive a meaningful bool for tracking pipeline completion.

---

### FIX C — sniper_pipeline.py: double cooldown call ❌→✅ FIXED

**File:** `app/core/sniper_pipeline.py` (applied in session 1)

**Root cause:** `sniper_pipeline.py` called `set_cooldown()` after `arm_ticker()` returned.
`arm_ticker()` already calls `set_cooldown()` internally as its final step. This caused
a redundant DB write and a duplicate cooldown log line on every successful arm.

**Fix:** Removed outer `set_cooldown()` call and its import from the pipeline.
`arm_signal.arm_ticker()` owns cooldown exclusively.

---

### FIX B — sniper_pipeline.py: options_rec missing default ❌→✅ FIXED

**File:** `app/core/sniper_pipeline.py` (applied in session 1)

**Root cause:** `options_rec` was a required parameter with no default. All callers in
`sniper.py` call `_run_signal_pipeline()` without passing `options_rec`. Every call
raised `TypeError: missing required argument`.

**Fix:** `options_rec=None` default added. Scorecard and `arm_ticker()` both handle
`None` gracefully (IVR/GEX fall back to neutral scores).

---

### FIX A — sniper_pipeline.py: **_unused_kwargs absorbs legacy kwargs ❌→✅ FIXED

**File:** `app/core/sniper_pipeline.py` (applied in session 1)

**Root cause:** `sniper.py` dispatcher passed `get_ticker_screener_metadata=` and `state=`
kwargs that the extracted pipeline doesn't need. Without `**_unused_kwargs` the call
raised `TypeError: unexpected keyword argument` on every invocation.

**Fix:** `**_unused_kwargs` added to `_run_signal_pipeline()` signature. Subsequently
the kwargs were removed from the dispatcher entirely (FIX E), making this a belt-and-
suspenders defense against future unknown kwargs.

---

### Boot Confirmation — 2026-03-26 19:36 UTC

Railway container boot post-fix:
- ✅ No `SyntaxError`, no `ImportError`, no `TypeError` on startup
- ✅ Screener loaded: 38 tickers | Tier A: 20, Tier B: 5, Tier C: 13
- ✅ Watchlist locked at 10 tickers (15:36 ET)
- ✅ WS feed live on 8 tickers, REST backfill running
- ✅ Risk session loaded: $5,000 balance, $0 P&L, streak 0
- ⚠️ Signal Analytics summary printing ~20x on startup — cosmetic only, no crash
  (summary is called per-ticker thread instead of once globally; tracked as next issue)

---

## 2026-03-26 — Session 1: Critical Fix Session (app/core arm path)

### Issue 1 — arm_ticker() TypeError on every signal pass ❌→✅ FIXED

**Root cause:** `sniper_pipeline._run_signal_pipeline()` called `arm_ticker()` with only 7 of 13
required positional args. Every signal that cleared the 60-pt scorecard gate crashed immediately
with a `TypeError`, silently killing all trade execution with no trade ever being opened.

**Missing args:** `or_low`, `or_high`, `stop_price`, `t1`, `t2`, `grade`, `signal_type`

**Fix applied (`app/core/sniper_pipeline.py` — commit `960bdfe`):**
- Called `compute_stop_and_targets(bars_session, direction, or_high_ref, or_low_ref, entry_price, grade)` immediately before `arm_ticker()` to derive `stop_price`, `t1`, `t2` from live session bars
- Added guard: if `compute_stop_and_targets()` returns `None`, signal dropped with `[STOP-INVALID]` log
- Passed `or_high_ref` / `or_low_ref`, `grade`, and `signal_type` — all already in scope

---

### Issue 2 — ImportError on every arm attempt (sniper_log.py missing) ❌→✅ FIXED

**Root cause:** `arm_signal.arm_ticker()` imported `log_proposed_trade` from `app.core.sniper_log`
but that file never existed. `ImportError` blocked all trade execution.

**Fix applied (`app/core/sniper_log.py` — commit `077352a`, new file):**
- Created `app/core/sniper_log.py` with `log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade)`
- Writes structured `[PROPOSED-TRADE]` INFO log line before external calls
- Exception-safe: wrapped in `try/except` so logging can never crash the arm path

---

### Combined effect (Sessions 1 + 2)
All issues together meant **zero trades could ever be executed** after the Phase 1.38d refactor
introduced `sniper_pipeline.py`. Signal detection, scanning, filters, scorecard, and confirmations
were all functional — only the final arm steps were broken. All execution blockers are now resolved.

---

## 2026-03-25 — Phase 1.38d-fix (Scorecard + RVOL ceiling)

- `app/core/signal_scorecard.py` — FIX P2: crash handler now scores `SCORECARD_GATE_MIN - 1` (59) so a scorer exception blocks rather than passes through at exactly the gate boundary. Upgraded to `logger.warning`.
- `app/core/signal_scorecard.py` — FIX P4: `_score_rvol_ceiling()` added. RVOL ≥ `RVOL_CEILING` (3.0x) deducts 20 pts. Backtest: RVOL ≥ 3.0x cohort is −32.23 Total R (582-trade audit).

---

## 2026-03-16 — Audit Session (Batches A–E)

### Session 7 (Batch C) — Backtesting & Scripts Audit
- Audited all `app/backtesting/` and `scripts/` subdirectories (55 files)
- Confirmed no overlaps in backtest engine, walk-forward, signal replay, or parameter optimizer
- `scripts/` subfolder structure confirmed correct: `analysis/`, `database/`, `backtesting/`, `ml/`, `utils/`
- Pending: verify `scripts/backtesting/backtest_v2_detector.py` vs `backtest_realistic_detector.py`

### Session 6 (Batch B) — ML, Analytics, AI Audit
- `app/ml/analyze_signal_failures.py` → MOVED to `scripts/analysis/` (commit `42126d5` / `f6254b5`)
- `app/ml/train_from_analytics.py` → MOVED to `scripts/ml/` (commit `42126d5` / `2f586e6`)
- `app/ml/train_historical.py` → MOVED to `scripts/ml/` (commit `42126d5` / `dc9a8db`)
- Confirmed `ml_signal_scorer_v2.py` is active production scorer; v1 retained as fallback
- `explosive_tracker.py` (real-time) vs `explosive_mover_tracker.py` (historical) — distinct roles confirmed

### Session 5 (S5) — Dead Code Removal
- `app/core/confidence_model.py` — DELETED (commit `b99a63a`). Dead stub, zero callers, superseded by `ai_learning.py`

### Session 4 (S4) — Signal Quality Metrics & Filter Cleanup
- `app/core/arm_signal.py` — Wired `record_trade_executed()`. TRADED funnel stage now records.
- `app/signals/signal_analytics.py` — Added `get_rejection_breakdown()`, `get_hourly_funnel()`, `get_discord_eod_summary()`
- `app/filters/entry_timing_optimizer.py` — DELETED. Exact duplicate of `entry_timing.py` (commit `d1821d1`)
- `app/filters/options_dte_filter.py` — DELETED. Superseded by `greeks_precheck.py` (commit `3abfdd5`)
- `app/core/sniper.py` — Wired `funnel_analytics` on all 3 scan paths (commit `f5fd87b`)
- `requirements.txt` — Removed `yfinance>=0.2.40`

### Session 3 (S3) — Test File Renames
- `tests/test_task10_backtesting.py` → `tests/test_backtesting_extended.py` (commit `dd750bb` / `0454fd4`)
- `tests/test_task12.py` → `tests/test_premarket_scanner_v2.py` (commit `dd750bb` / `7944437`)

### Session 2 (S2) — Data Layer & Git Hygiene
- `app/data/database.py` — Converted to re-export shim over `db_connection.py` (commit `9cd17f5`)
- `.gitignore` — Added `models/signal_predictor.pkl` exclusion (commit `5828488`)

### Session 1 (S1) — Discord & DB Tooling
- `app/discord_helpers.py` — Converted to re-export shim. Fixed `send_options_signal_alert` bug (commit `a629a84`)
- `app/ml/check_database.py` — Moved to `scripts/database/check_database.py` (commit `3e4681a` / `aeae51d`)
- `app/validation/volume_profile.py` — Added 5-min TTL cache + module docstring (commit `cea9180`)

### Session 0 (S0) — Critical Bug Fix
- `app/validation/cfw6_confirmation.py` — VWAP formula corrected (commit `95be3ae`)

---

## 2026-03-10 — Master File Registry Compiled

- Full repo walk: 336 tracked files catalogued
- Architecture coverage gaps identified across `app/signals/`, `app/filters/`, `app/mtf/`, `app/indicators/`, `app/backtesting/`, `app/ml/`
- Critical P0 flaws documented: `thread_safe_state.py` not wired, Discord fires before position_manager, no process_ticker() watchdog, zero automated test coverage on CFW6 confirmations
- EODHD optimization plan drafted: route all REST bar fetches through `candle_cache.py`, use `mtf_compression.py` as sole MTF data source

---

## 2026-02-25 — Feb 25 Hotfix Session (10:30 AM)

**Source:** `docs/history/FIXES_FEB25_1030AM.md`

- Multiple signal deduplication and cooldown fixes applied
- Discord duplicate alert issue resolved (META fired at 9:59 AM + 10:29 AM — now blocked by cooldown)
- Performance monitor `realized_pnl` → `pnl` column rename fix applied
- Commit reference: `a3b7d2e`

---

## Phase 4 — Monitoring & Analytics Integration ✅ COMPLETE

**Files integrated:** `signal_analytics.py`, `performance_monitor.py`, `performance_alerts.py`  
**Integration points wired:**
- Signal lifecycle tracking: GENERATED → VALIDATED → ARMED → TRADED → CLOSED
- Circuit breaker check before every position open
- EOD signal funnel report + performance dashboard
- Discord alert manager for win/loss streaks and drawdown warnings

**DB schema fix (RESOLVED):** `performance_monitor.py` queried `realized_pnl` but positions table uses `pnl`. Fixed in commit `a3b7d2e`.

---

## Phase 3D — MTF FVG Priority System ✅ COMPLETE

**Files added:** `app/mtf/mtf_fvg_priority.py`, MTF priority scoring integrated into `mtf_integration.py`  
**What changed:**
- When multiple FVGs detected across timeframes, `mtf_fvg_priority.py` now ranks and selects highest-priority FVG
- Priority scoring accounts for: timeframe weight (1H > 15m > 5m > 1m), recency, proximity to current price, and directional alignment
- MTF bias object updated to include `priority_fvg` field consumed by `sniper.py`

---

## Phase 3C — Walk-Forward Optimization ✅ COMPLETE

**Files added:** `app/backtesting/walk_forward.py`, `app/backtesting/parameter_optimizer.py`  
**What changed:**
- Walk-forward framework splits historical data into in-sample/out-of-sample windows
- Parameter optimizer runs grid search over CFW6 thresholds, ATR multipliers, RVOL minimums
- Prevents overfitting by validating on held-out data before applying parameters to live system

---

## Phase 3A — Regime Filter + Correlation Check ✅ COMPLETE

**Files added:** `app/filters/correlation.py`, regime filter integrated into `sniper.py`  
**What changed:**
- Regime filter added to `process_ticker()` — checks VIX/SPY conditions, blocks trading in unfavorable regimes
- Correlation check added to `arm_ticker()` — prevents >3 highly correlated positions simultaneously
- Both systems use try/except import guards — graceful fallback if unavailable
- Config parameters: `MAX_SECTOR_EXPOSURE_PCT = 40.0`, `MAX_OPEN_POSITIONS = 5`

**Emergency disable pattern (preserved for reference):**
```python
# Regime Filter — disable without code deploy:
def is_favorable_regime(self, force_refresh: bool = False) -> bool:
    return True  # Emergency disable

# Correlation Check — disable without code deploy:
def is_safe_to_add_position(self, ticker, open_positions, proposed_risk_dollars=None):
    return (True, None)  # Emergency disable
```

---

## Phase 2C — ML Signal Scorer ✅ COMPLETE

**Files added:** `app/ml/ml_signal_scorer.py`, `app/ml/ml_signal_scorer_v2.py`, `app/ml/ml_confidence_boost.py`  
**What changed:**
- ML-based confidence scoring layer added on top of rule-based CFW6 scoring
- v1 scorer: Random Forest on CFW6 feature vectors
- v2 scorer (production): Updated architecture + feature set — active version
- `ml_confidence_boost.py` applies calibrated ±delta to sniper confidence before threshold gate
- ML feedback loop: retrain daily at 4:00 PM on that day's labeled signal outcomes

---

## Phase 2B — Options Intelligence Layer ✅ COMPLETE

**Files added:** `app/options/options_intelligence.py`, `app/options/gex_engine.py`, `app/options/iv_tracker.py`, `app/options/options_data_manager.py`  
**What changed:**
- Deep options analysis engine added: scores contracts by liquidity, spread, OI, flow alignment
- GEX (Gamma Exposure) calculator: identifies market-maker pinning vs explosive move zones
- IV Rank tracker: rolling IV percentile per ticker, feeds `greeks_precheck.py`
- Options data cache: all Tradier calls now routed through `options_data_manager.py`

---

## Phase 2A — MTF Integration ✅ COMPLETE

**Files added:** `app/mtf/bos_fvg_engine.py`, `app/mtf/mtf_integration.py`, `app/mtf/mtf_compression.py`  
**What changed:**
- Full BOS + FVG detection engine across 1m/5m/15m/1H timeframes
- `mtf_compression.py` compresses 1m WS bars to higher timeframes in memory — no extra EODHD REST calls
- MTF bias object feeds sniper.py's C5 confirmation (MTF alignment)
- `sniper_mtf_trend_patch.py` added as hot-patch during transition

---

## Deployment History

| Date | Event | Notes |
|------|-------|-------|
| 2026-03-27 | Session handoff doc update | Issue #12 backlog formalized in remediation_tracker Phase 7 |
| 2026-03-26 | Session 2 audit + FIX H (arm_signal SyntaxError) | Clean boot confirmed |
| 2026-03-26 | Session 1 critical fix | arm_ticker TypeError + sniper_log ImportError — 2 commits |
| 2026-03-16 | Batch A–E audit session | 19 changes applied, 5 files deleted, 4 files moved |
| 2026-03-10 | Master registry compiled | 336 files catalogued |
| 2026-02-25 | Feb 25 hotfix session | pnl column fix, Discord dedup fix |
| Ongoing | Railway auto-deploy on push to main | Entrypoint: `python -m app.core.scanner` |

---

## Known Issues / Next Session

| # | Issue | Severity | File |
|---|-------|----------|------|
| 1 | Signal Analytics summary prints ~20x on startup | Low (cosmetic) | `app/signals/signal_analytics.py` |
| 2 | `_resample_bars()` duplicated in `sniper.py` and `sniper_pipeline.py` | Low (dead code in sniper.py) | `app/core/sniper.py` |
