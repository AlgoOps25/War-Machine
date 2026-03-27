# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all tracked files.  
> **Last updated:** 2026-03-27 Session 12 — app/mtf deep audit complete; BUG-MTF-1/2/3 fixed  
> **Auditor:** Perplexity AI (interactive audit with Michael)  
> **Status legend:** ✅ KEEP | ⚠️ REVIEW | 🔀 MERGE → target | 🗃️ QUARANTINE | ❌ DELETE | 🔧 FIXED | 📦 MOVED  
> **Prohibited (runtime-critical) directories:** `app/core`, `app/data`, `app/risk`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`, `utils/`, `migrations/`  
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`  
> **Healthcheck:** `/health` on port 8080  

---

## Progress Tracker

| Batch | Directory Scope | Files | Status |
|-------|----------------|-------|--------|
| A1 | `app/core` | 15 | ✅ Complete — reconciled Session 9 |
| A2 | `app/risk`, `app/data`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications` | 47 | ✅ Complete — reconciled Session 9 |
| S4-S5 | Signal quality metrics deep audit | 7 | ✅ Complete |
| B | `app/ml`, `app/analytics`, `app/ai` | 27 | ✅ Complete — app/ml deep-audited Session 11 |
| C | `app/backtesting/`, `scripts/` (all subfolders) | 55 | ✅ Complete |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | 27 | ✅ Complete — reconciled Session 9 |
| E | `tests/`, `docs/`, `migrations/`, `models/`, root files | 30 | ✅ Complete |
| Cross-Batch | Overlap analysis across all batches | all | ✅ Current |
| **Session 9** | **Full live-repo reconciliation vs registry** | **all** | **✅ Complete 2026-03-25** |
| **Session 10** | **Hotfix logging + pending queue #8/#9/#10 closed** | **3 items** | **✅ Complete 2026-03-25** |
| **Session 11** | **app/ml line-by-line deep audit — BUG-ML-1/2/6 fixed** | **3 fixes + 1 new file** | **✅ Complete 2026-03-27** |
| **Session 12** | **app/mtf line-by-line deep audit — BUG-MTF-1/2/3 fixed** | **3 fixes across 2 files** | **✅ Complete 2026-03-27** |

---

## Implemented Changes Log

| # | Date | Session | File | Change | Commit SHA | Impact |
|---|------|---------|------|--------|-----------|--------|
| 1 | 2026-03-16 | S0 | `app/validation/cfw6_confirmation.py` | 🔧 FIXED: VWAP formula corrected. | `95be3ae` | Live bug fix |
| 2 | 2026-03-16 | S1 | `app/discord_helpers.py` | Converted to re-export shim. Fixed `send_options_signal_alert` bug. | `a629a84` | Live bug fix + legacy compat |
| 3 | 2026-03-16 | S1 | `app/ml/check_database.py` | Moved to `scripts/database/check_database.py`. | `3e4681a` / `aeae51d` | Clean separation |
| 4 | 2026-03-16 | S1 | `app/validation/volume_profile.py` | 5-min TTL cache + module docstring. | `cea9180` | Perf improvement + clarity |
| 5 | 2026-03-16 | S2 | `app/data/database.py` | Converted to re-export shim over `db_connection.py`. | `9cd17f5` | All callers use production pool |
| 6 | 2026-03-16 | S2 | `.gitignore` | Added `models/signal_predictor.pkl` exclusion. | `5828488` | Prevents binary tracking |
| 7 | 2026-03-16 | S3 | `tests/test_task10_backtesting.py` | Renamed → `tests/test_backtesting_extended.py`. | `dd750bb` / `0454fd4` | Cleaner test discovery |
| 8 | 2026-03-16 | S3 | `tests/test_task12.py` | Renamed → `tests/test_premarket_scanner_v2.py`. | `dd750bb` / `7944437` | Cleaner test discovery |
| 9 | 2026-03-16 | S4 | `app/core/arm_signal.py` | Wired `record_trade_executed()`. TRADED funnel stage now records. | pre-confirmed | Funnel stats now complete |
| 10 | 2026-03-16 | S4 | `app/signals/signal_analytics.py` | Added `get_rejection_breakdown()`, `get_hourly_funnel()`, `get_discord_eod_summary()`. | pre-confirmed | Full metrics instrumentation |
| 11 | 2026-03-16 | S4 | `app/filters/entry_timing_optimizer.py` | DELETED — exact duplicate of `entry_timing.py`. | `d1821d1` | -1 file, 4.8 KB |
| 12 | 2026-03-16 | S4 | `app/filters/options_dte_filter.py` | DELETED — superseded by `greeks_precheck.py`. | `3abfdd5` | -1 file, 5.3 KB; yfinance removed |
| 13 | 2026-03-16 | S4 | `app/core/sniper.py` | Wired `funnel_analytics` on all 3 scan paths. | `f5fd87b` | Funnel fires on every scan |
| 14 | 2026-03-16 | S4 | `requirements.txt` | Removed `yfinance>=0.2.40`. | [this commit] | Faster deploys |
| 15 | 2026-03-16 | S5 | `app/core/confidence_model.py` | DELETED — dead stub, zero callers, superseded by `ai_learning.py`. | `b99a63a` | Dead code removed |
| 16 | 2026-03-16 | S6 | `app/ml/analyze_signal_failures.py` | 📦 MOVED → `scripts/analysis/analyze_signal_failures.py`. | `42126d5` / `f6254b5` | Dev tool in correct location |
| 17 | 2026-03-16 | S6 | `app/ml/train_from_analytics.py` | 📦 MOVED → `scripts/ml/train_from_analytics.py`. | `42126d5` / `2f586e6` | Dev tool in correct location |
| 18 | 2026-03-16 | S6 | `app/ml/train_historical.py` | 📦 MOVED → `scripts/ml/train_historical.py`. | `42126d5` / `dc9a8db` | Dev tool in correct location |
| 19 | 2026-03-16 | S7 | `docs/AUDIT_REGISTRY.md` | Batch C complete — all `app/backtesting/` and `scripts/` audited. | this commit | Registry current |
| 20 | 2026-03-17 | S8 | `docs/AUDIT_REGISTRY.md` | Batch D + E complete. | this commit | Registry current |
| 21 | 2026-03-25 | S9 | `app/options/options_intelligence.py` | 🔧 FIXED: `get_chain()` dead-code in cache branch removed. | `edb6ba9` | Runtime bug fix |
| 22 | 2026-03-25 | S9 | `app/validation/greeks_precheck.py` | 🔧 FIXED: Missing `ZoneInfo` import added. | `08648df` | Runtime bug fix |
| 23 | 2026-03-25 | S9 | `app/signals/breakout_detector.py` | 🔧 FIXED: `resistance_source` NameError + duplicate PDH/PDL resolved. | `df2e625` | Runtime bug fix |
| 24 | 2026-03-25 | S9 | `docs/AUDIT_REGISTRY.md` | Full live-repo reconciliation. | this commit | Registry 100% current |
| 25 | 2026-03-25 | S10 | `app/screening/watchlist_funnel.py` | 🔧 FIXED: spurious `()` on `datetime.now(tz=ET)` — crashing every pre-market cycle. | manual patch | Critical runtime crash fix |
| 26 | 2026-03-25 | S10 | `app/core/scanner.py` | 🔧 FIXED: `_run_analytics()` missing `conn=None` parameter. | manual patch | Critical runtime crash fix |
| 27 | 2026-03-25 | S10 | `app/ml/metrics_cache.py` | 🔧 FIXED: Raw SQLAlchemy pool replaced with `get_conn()`/`return_conn()`. | manual patch | Connection leak eliminated |
| 28 | 2026-03-27 | S11 | `app/ml/metrics_cache.py` | 🔧 FIXED BUG-ML-2: `%(since)s` named param → `ph()` positional + tuple. | `900e211` | ML feature correctness |
| 29 | 2026-03-27 | S11 | `app/ml/ml_signal_scorer_v2.py` | 🔧 FIXED BUG-ML-1: Created missing file — Gate 5 was silently dead. | `0fad513` | Gate 5 ML now functional |
| 30 | 2026-03-27 | S11 | `app/analytics/performance_monitor.py` | 🔧 FIXED BUG-ML-6: `_consecutive_losses` counter wired + Discord alert. | `74ce832` | Risk control now active |
| 31 | 2026-03-27 | S11 | `docs/AUDIT_REGISTRY.md` | Session 11 logged. | `f4fc398` | Registry current |
| 32 | 2026-03-27 | S12 | `app/mtf/mtf_compression.py` | 🔧 FIXED BUG-MTF-1: `compress_to_1m()` direction-aware high/low step placement. Bull: high_step=4/low_step=0. Bear: high_step=0/low_step=4. Was hardcoded i==2/i==3 — inverted price sequence on bear bars, could produce false 1m FVGs. | `6fc7c7b` | FVG signal quality fix |
| 33 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 FIXED BUG-MTF-2: `detect_fvg_on_timeframe()` volume check moved from `c2` (post-gap bar) to `c1` (impulse/middle bar). Valid FVGs were being rejected when c2 was low-volume; bad FVGs passing when c1 was thin. | `137f36f` | FVG volume filter correctness |
| 34 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 FIXED BUG-MTF-3: `get_full_mtf_analysis()` now builds `15m` and `30m` bars via `_resample()`. After 10 AM `get_available_timeframes()` returned those TFs but they were absent from `bars_mtf` — higher-TF FVGs never detected; `_priority_stats` 1h/30m/15m permanently 0. | `137f36f` | Higher-TF FVG detection now active |

---

## Pending Actions Queue

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1–10 | ✅ DONE | Various | See log above | ✅ |
| 11 | 🟡 MEDIUM | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Open |
| 12 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Open |
| 13 | 🟢 LOW | `models/signal_predictor.pkl` | `git rm --cached` (LOCAL ACTION) | ⏳ Pending |
| 14 | 🟢 LOW | `models/training_dataset.csv` | `git rm --cached` (LOCAL ACTION) | ⏳ Pending |
| 15 | 🟢 LOW | `market_memory.db` | Verify if replaced by PostgreSQL on Railway or still active | ⏳ Open |
| 16 | 🟢 LOW | `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` | ⏳ Open |
| 17 | 🟢 LOW | `audit_reports/venv/` | Venv accidentally committed — should be gitignored/removed | ⏳ Open |
| 18–20 | ✅ DONE | BUG-ML-2/1/6 | S11 | ✅ |
| 21 | 🟡 MEDIUM | `app/ml/ml_trainer.py` | BUG-ML-3: Platt calibration + threshold on same slice — data leakage | ⏳ Open |
| 22 | 🟡 MEDIUM | `app/validation/cfw6_gate_validator.py` | BUG-ML-4: `get_validation_stats()` permanent stub — wire or delete | ⏳ Open |
| 23 | 🟢 LOW | `app/ml/ml_confidence_boost.py` | BUG-ML-5: `.iterrows()` in logging loop — replace with `itertuples()` | ⏳ Open |
| 24–26 | ✅ DONE | BUG-MTF-1/2/3 | S12 | ✅ |
| 27 | 🔴 HIGH | `app/core/sniper.py` | Full line-by-line deep audit (largest file, highest risk) | ⏳ Open — Session 13 |
| 28 | 🔴 HIGH | `app/core/scanner.py` | Full line-by-line deep audit | ⏳ Open |
| 29 | 🔴 HIGH | `app/risk/risk_manager.py` | Full line-by-line deep audit | ⏳ Open |
| 30 | 🔴 HIGH | `app/risk/position_manager.py` | Full line-by-line deep audit | ⏳ Open |

---

## LOCAL ACTIONS REQUIRED (Cannot Be Done via GitHub)

```powershell
git rm --cached models/signal_predictor.pkl
git rm --cached models/training_dataset.csv
git commit -m "chore: untrack binary model files (already in .gitignore)"
git push
```

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers | ✅ KEEP | |
| `__main__.py` | 177 B | Railway entrypoint shim | Railway start | ✅ KEEP | |
| `scanner.py` | 42 KB | Main scan loop | Entrypoint | ✅ KEEP | **PROHIBITED** — 🔧 FIXED S10. Deep audit pending S13 |
| `sniper.py` | 72 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** — Deep audit pending S13 |
| `arm_signal.py` | 7 KB | Signal arming | `sniper.py` | ✅ KEEP | `record_trade_executed()` wired S4 |
| `armed_signal_store.py` | 8 KB | Armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `watch_signal_store.py` | 7.6 KB | Pre-armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `confidence_model.py` | — | ❌ DELETED S5 | — | Dead stub. `b99a63a` |
| `gate_stats.py` | — | ❌ DELETED S9 | — | Absorbed into `signal_scorecard.py` |
| `sniper_log.py` | — | ❌ DELETED S9 | — | Superseded by `logging_config.py` |
| `error_recovery.py` | — | ❌ DELETED S9 | — | Zero live imports |
| `logging_config.py` | 3.6 KB | Centralized logging setup | `__main__.py` | ✅ KEEP | NEW — Sprint 1 |
| `signal_scorecard.py` | 10.1 KB | 0–100 signal scoring gate | `sniper.py` | ✅ KEEP | NEW — Sprint 1 |
| `analytics_integration.py` | 9.2 KB | Core↔analytics bridge | `scanner.py` | ✅ KEEP | |
| `eod_reporter.py` | 3.8 KB | EOD cleanup + stats | `scanner.py` | ✅ KEEP | ✅ CONFIRMED S10 |
| `health_server.py` | 4.5 KB | `/health` endpoint | Railway healthcheck | ✅ KEEP | **PROHIBITED** |
| `thread_safe_state.py` | 10.8 KB | Thread-safe shared state | `scanner.py`, `sniper.py` | ✅ KEEP | |

---

## BATCH A2 — Supporting Runtime Modules

### `app/notifications/` — 2/2 KEEP
### `app/risk/` — 6/6 KEEP (deep audit pending S13)
### `app/data/` — 9/9 KEEP
### `app/signals/` — 5 KEEP, 1 FIXED (breakout_detector)
### `app/filters/` — 12 KEEP, 2 DELETED, 3 NEW

### `app/mtf/` — **Session 12 deep audit complete**

| File | Size | Role | Connected To | Verdict | Notes |
|------|------|------|-------------|---------|-------|
| `__init__.py` | 0.8 KB | Package marker + re-exports | All importers | ✅ KEEP | Exports: `scan_bos_fvg`, `enhance_signal_with_mtf`, `run_mtf_trend_step`, `enrich_signal_with_smc`, `MTFTrendValidator`, `MTFValidator`, `get_mtf_trend_validator`, `mtf_validator`, `validate_signal_mtf` |
| `bos_fvg_engine.py` | ~14 KB | BOS+FVG primary detector | `sniper.py` (via `scan_bos_fvg`) | ✅ KEEP | **PROHIBITED**. Fixes 40.H-1/2/3 all present and correct. Confirmation-wait-then-enter-next-bar logic verified. `is_valid_entry_time()` and `is_force_close_time()` correct. No issues found. |
| `mtf_validator.py` | ~6 KB | EMA 9/21 MTF trend alignment (Step 8.5) | `mtf_integration.py`, `sniper.py` | ✅ KEEP | **PROHIBITED**. Fix 41.H-3 (DB fetch skip) correct. `PASS_THRESHOLD=6.0` on 10-pt weighted scale is appropriate. Singleton pattern correct. No issues found. |
| `mtf_integration.py` | ~14 KB | MTF convergence + Step 8.5 wiring | `sniper.py` (Step 8.2 + 8.5) | ✅ KEEP | **PROHIBITED**. Fixes 40.H-4 (stale cache key), 40.M-7 (adaptive FVG threshold), 40.M-9 (OR window alignment) all correct. `reset_daily_stats()` correctly calls `clear_smc_cache()`. No issues found. |
| `mtf_compression.py` | 9.8 KB | Timeframe compression (5m→1m/2m/3m/15m/30m) | `mtf_integration.py`, `mtf_fvg_priority.py` | ✅ KEEP | 🔧 FIXED S12 BUG-MTF-1: `compress_to_1m()` now direction-aware (`is_bull` determines `high_step`/`low_step`). Commit `6fc7c7b`. |
| `mtf_fvg_priority.py` | 15.9 KB | Highest-TF FVG resolver; time-aware priority | `sniper.py`, `mtf_integration.py` | ✅ KEEP | 🔧 FIXED S12 BUG-MTF-2: volume check moved from `c2` → `c1` (impulse bar). 🔧 FIXED S12 BUG-MTF-3: `get_full_mtf_analysis()` now builds `15m`+`30m` bars. Commit `137f36f`. |
| `smc_engine.py` | ~17 KB | SMC context: CHoCH, Inducement, OB, Phase | `sniper.py` (via `enrich_signal_with_smc`) | ✅ KEEP | **PROHIBITED**. `clear_smc_cache()` correctly wired via `reset_daily_stats()`. DB persistence non-fatal. `ph()` usage correct. `smc_context` defined before cache write. No issues found. |

**app/mtf: 7/7 KEEP. 3 FIXED (BUG-MTF-1/2/3). Session 12 audit complete.**

### `app/validation/` — 7/7 KEEP, 2 FIXED

---

## BATCH B — ML, Analytics, AI

### `app/ml/` — 7 active KEEP, 1 CREATED, 2 FIXED (Session 11)
### `app/analytics/` — 10/10 KEEP, 1 FIXED (performance_monitor)
### `app/ai/` — 2/2 KEEP

---

## BATCH C — Backtesting & Scripts

### `app/backtesting/` — 7/7 KEEP
### `scripts/` — 55 KEEP (net), 1 QUARANTINE pending, 1 REVIEW pending

---

## BATCH D — Screening, Options, Indicators, Utils

### `app/screening/` — 8/8 KEEP, 1 FIXED (watchlist_funnel)
### `app/options/` — 9 KEEP, 1 FIXED, 1 NEW
### `app/indicators/` — 5/5 KEEP
### `utils/` — 4/4 KEEP

---

## BATCH E — Tests, Docs, Migrations, Models, Root Files

### `tests/` — 9/9 KEEP
### `migrations/`, `models/`, `docs/`, Root Files — all KEEP / noted

---

## Cross-Batch Overlap Flags

All previously resolved flags remain resolved. No new overlaps found in Session 12 `app/mtf` audit.

New confirmation from S12:
- `bos_fvg_engine.py` FVG detection vs `mtf_fvg_priority.py` FVG detection — ✅ RESOLVED: `bos_fvg_engine` scans post-BOS only (single TF, BOS-anchored). `mtf_fvg_priority` scans recent 30 bars across all TFs for standalone FVGs (no BOS required). Different purposes, different callers, no overlap.
- `mtf_validator.py` EMA trend vs `mtf_integration.py` convergence — ✅ RESOLVED: Trend validator checks EMA alignment (Step 8.5). Convergence checks same OR+BOS+FVG pattern across 5m/3m/2m/1m (Step 8.2). Different signal layers.
- `mtf_compression.py` `expand_to_15m/30m` vs `mtf_fvg_priority.py` `_resample()` — ✅ NOTED: Both produce 15m/30m bars but via different methods. `expand_to_15m` uses chunk-based aggregation (used by `compress_bars()`). `_resample()` uses floor-bucketing by minute (used internally by `get_full_mtf_analysis()`). Results are equivalent for aligned 5m bars. No conflict.

---

## Files Cleared (Full Count — Session 12 Current)

- **app/core:** 12 active KEEP, 4 DELETED, 2 NEW — deep audit S13
- **app/risk:** 6 KEEP — deep audit S13
- **app/data:** 9 KEEP
- **app/signals:** 5 KEEP (1 NEW), 1 FIXED
- **app/filters:** 12 KEEP (3 NEW), 2 DELETED
- **app/mtf:** 7 KEEP, 3 FIXED — **✅ Session 12 complete**
- **app/validation:** 7 KEEP, 2 FIXED
- **app/notifications:** 2 KEEP
- **app/ml:** 7 KEEP (1 CREATED), 3 MOVED, 2 FIXED
- **app/analytics:** 10 KEEP, 1 FIXED
- **app/ai:** 2 KEEP
- **app/backtesting:** 7 KEEP
- **app/screening:** 8 KEEP, 1 FIXED
- **app/options:** 9 KEEP (1 NEW), 1 FIXED
- **app/indicators:** 5 KEEP
- **utils/:** 4 KEEP
- **tests/:** 9 KEEP
- **migrations/:** 4 KEEP
- **models/:** 3 KEEP (untrack pending)
- **scripts/ (all):** 55 KEEP (net)
- **docs/:** All KEEP
- **Root files:** All KEEP / noted

**Total actions to date: 7 DELETED, 4 MOVED, 11 FIXED (S9-S12), 1 FIXED (S0), 3 CONFIRMED, 4 shims confirmed, 2 open REVIEW flags, 3 LOCAL ACTIONS pending, 1 CREATED.**

---

## Session 13 — Next

Priority order:
1. `app/core/sniper.py` — 72 KB, largest file, highest runtime risk (**fetch in sections due to size**)
2. `app/core/scanner.py` — 42 KB
3. `app/risk/risk_manager.py` + `position_manager.py` — risk layer
4. BUG-ML-3/4/5 fixes (ml_trainer, cfw6_gate_validator, ml_confidence_boost)

*Updated: Session 12, 2026-03-27. BUG-MTF-1/2/3 fixed. Commits: `6fc7c7b`, `137f36f`. Next: Session 13 — sniper.py deep audit.*
