# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all 336 tracked files.  
> **Last updated:** 2026-03-16 Session 6 (Batch B)  
> **Auditor:** Perplexity AI (interactive audit with Michael)  
> **Status legend:** ✅ KEEP | ⚠️ REVIEW | 🔀 MERGE → target | 🗃️ QUARANTINE | ❌ DELETE | 🔧 FIXED | 📦 MOVED  
> **Prohibited (runtime-critical) directories:** `app/core`, `app/data`, `app/risk`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`, `utils/`, `migrations/`  
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`  
> **Healthcheck:** `/health` on port 8080  

---

## Progress Tracker

| Batch | Directory Scope | Files | Status |
|-------|----------------|-------|--------|
| A1 | `app/core` | 15 | ✅ Complete |
| A2 | `app/risk`, `app/data`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications` | 44 | ✅ Complete |
| S4-S5 | Signal quality metrics deep audit | 7 | ✅ Complete |
| B | `app/ml`, `app/analytics`, `app/ai` | 27 | ✅ Complete |
| C | `app/backtesting`, `scripts/` (all subfolders) | ~55 | ⏳ Next |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | ~25 | ⏳ Pending |
| E | `tests/`, `docs/`, `audit_reports/`, `backups/`, `migrations/`, root files | ~50 | ⏳ Pending |
| Cross-Batch | Overlap analysis across all batches | 330 total | ⏳ Pending |

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
| 16 | 2026-03-16 | S6 | `app/ml/analyze_signal_failures.py` | 📦 MOVED → `scripts/analysis/analyze_signal_failures.py`. Zero import callers. | `42126d5` / `f6254b5` | Dev tool in correct location |
| 17 | 2026-03-16 | S6 | `app/ml/train_from_analytics.py` | 📦 MOVED → `scripts/ml/train_from_analytics.py`. CLI tool, not runtime module. | `42126d5` / `2f586e6` | Dev tool in correct location |
| 18 | 2026-03-16 | S6 | `app/ml/train_historical.py` | 📦 MOVED → `scripts/ml/train_historical.py`. CLI tool, not runtime module. | `42126d5` / `dc9a8db` | Dev tool in correct location |

---

## Pending Actions Queue

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1 | ✅ DONE | `app/validation/cfw6_confirmation.py` | Fix wrong VWAP formula | ✅ |
| 2 | ✅ DONE | `app/core/confidence_model.py` | DELETED | ✅ |
| 3 | ✅ DONE | `app/discord_helpers.py` | Re-export shim | ✅ |
| 4 | ✅ DONE | `app/ml/check_database.py` | Moved to scripts/database/ | ✅ |
| 5 | ✅ DONE | `app/ml/analyze_signal_failures.py` | Moved to scripts/analysis/ | ✅ |
| 6 | ✅ DONE | `app/ml/train_from_analytics.py` | Moved to scripts/ml/ | ✅ |
| 7 | ✅ DONE | `app/ml/train_historical.py` | Moved to scripts/ml/ | ✅ |
| 8 | 🟡 MEDIUM | `app/core/eod_reporter.py` | Confirm Discord send of `get_discord_eod_summary()` | ⏳ Batch C |
| 9 | 🟡 MEDIUM | `app/signals/signal_analytics.py` | Wire `get_hourly_funnel()` into EOD output | ⏳ Batch C |
| 10 | 🟡 MEDIUM | `app/ml/metrics_cache.py` | Standardize to `db_connection` pool (currently uses raw sqlalchemy) | ⏳ Batch C |
| 11 | 🟡 LOW | `tests/test_task9_funnel_analytics.py` | Rename → `tests/test_funnel_analytics.py` | ⏳ Batch C |
| 12 | 🟡 LOW | `tests/db_diagnostic.py` | Move to `scripts/` | ⏳ Batch C |
| 13 | 🟡 LOW | `tests/dte_selector.py` | Move to `scripts/` | ⏳ Batch C |
| 14 | 🟢 LOW | `models/signal_predictor.pkl` | `git rm --cached` to untrack binary | ⏳ Pending |
| 15 | 🟢 LOW | `models/training_dataset.csv` | `git rm --cached` to untrack CSV | ⏳ Pending |

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers of `app.core` | ✅ KEEP | |
| `__main__.py` | 177 B | Railway entrypoint shim | Railway start command | ✅ KEEP | |
| `scanner.py` | 42 KB | Main scan loop | Entrypoint | ✅ KEEP | **PROHIBITED** |
| `sniper.py` | 55 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** |
| `arm_signal.py` | 7 KB | Signal arming | `sniper.py` | ✅ KEEP | `record_trade_executed()` wired |
| `armed_signal_store.py` | 8 KB | Armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `watch_signal_store.py` | 7.6 KB | Pre-armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `confidence_model.py` | — | ❌ DELETED (S5) | — | Dead stub. Commit `b99a63a`. |
| `gate_stats.py` | 5.8 KB | Gate statistics | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `sniper_log.py` | 4.1 KB | Structured logging | `sniper.py` | ✅ KEEP | |
| `thread_safe_state.py` | 10.8 KB | Thread-safe shared state | `scanner.py`, `sniper.py` | ✅ KEEP | |
| `analytics_integration.py` | 9.2 KB | Core↔analytics bridge | `scanner.py` | ✅ KEEP | |
| `eod_reporter.py` | 3.8 KB | EOD cleanup + stats | `scanner.py` | ✅ KEEP ⚠️ | Verify Discord send |
| `error_recovery.py` | 17.2 KB | Exception handling | `scanner.py` | ✅ KEEP | |
| `health_server.py` | 4.5 KB | `/health` endpoint | Railway healthcheck | ✅ KEEP | **PROHIBITED** |

**A1: 13/14 KEEP. 1 DELETED.**

---

## BATCH A2 — Supporting Runtime Modules

### `app/notifications/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | Re-exports key send functions |
| `discord_helpers.py` | ✅ KEEP | **CANONICAL** Discord send layer |

### `app/risk/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `risk_manager.py` | ✅ KEEP | **PROHIBITED** |
| `position_manager.py` | ✅ KEEP | **PROHIBITED** |
| `trade_calculator.py` | ✅ KEEP | |
| `dynamic_thresholds.py` | ✅ KEEP | |
| `vix_sizing.py` | ✅ KEEP | |

**app/risk: 6/6 KEEP.**

### `app/data/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `database.py` | ✅ SHIM | Re-exports `db_connection.py` |
| `db_connection.py` | ✅ KEEP | **PROHIBITED** — canonical connection layer |
| `data_manager.py` | ✅ KEEP | **PROHIBITED** |
| `candle_cache.py` | ✅ KEEP | |
| `sql_safe.py` | ✅ KEEP | |
| `unusual_options.py` | ✅ KEEP | |
| `ws_feed.py` | ✅ KEEP | **PROHIBITED** — trade ticks |
| `ws_quote_feed.py` | ✅ KEEP | Distinct — bid/ask quotes |

**app/data: 9/9 KEEP.**

### `app/signals/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `breakout_detector.py` | ✅ KEEP | **PROHIBITED** |
| `opening_range.py` | ✅ KEEP | **PROHIBITED** |
| `vwap_reclaim.py` | ✅ KEEP | |
| `signal_analytics.py` | ✅ KEEP | Distinct from `funnel_analytics.py`. Extended S4/S5. |
| `earnings_eve_monitor.py` | ✅ KEEP | |

### `app/filters/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `rth_filter.py` | ✅ KEEP | |
| `vwap_gate.py` | ✅ KEEP | **CANONICAL VWAP source** |
| `market_regime_context.py` | ✅ KEEP | |
| `early_session_disqualifier.py` | ✅ KEEP | |
| `entry_timing_optimizer.py` | ❌ DELETED (S4) | Duplicate of `entry_timing.py`. `d1821d1` |
| `liquidity_sweep.py` | ✅ KEEP | |
| `options_dte_filter.py` | ❌ DELETED (S4) | Superseded by `greeks_precheck.py`. `3abfdd5` |
| `order_block_cache.py` | ✅ KEEP | |
| `sd_zone_confluence.py` | ✅ KEEP | |
| `correlation.py` | ✅ KEEP | |

**app/filters: 9/11 KEEP. 2 DELETED.**

### `app/mtf/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `bos_fvg_engine.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_validator.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_integration.py` | ✅ KEEP | |
| `mtf_compression.py` | ✅ KEEP | |
| `mtf_fvg_priority.py` | ✅ KEEP | |

**app/mtf: 6/6 KEEP.**

### `app/validation/`

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `validation.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_gate_validator.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_confirmation.py` | 🔧 FIXED (S0) | VWAP formula corrected. `95be3ae` |
| `greeks_precheck.py` | ✅ KEEP | Supersedes deleted `options_dte_filter.py` |
| `hourly_gate.py` | ✅ KEEP | |
| `entry_timing.py` | ✅ KEEP | Canonical — `entry_timing_optimizer.py` was duplicate |
| `volume_profile.py` | ✅ KEEP | Distinct from `app/indicators/volume_profile.py` |

**app/validation: 7/7 active KEEP. 1 FIXED.**

---

## BATCH B — ML, Analytics, AI

> **Completed 2026-03-16 Session 6.**

### `app/ml/` — 6 active files (was 9)

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `README.md` | ✅ KEEP | Dev reference |
| `INTEGRATION.md` | ✅ KEEP | Wiring guide |
| `ml_trainer.py` | ✅ KEEP | RF/GBM training engine — called by `train_historical.py` |
| `ml_confidence_boost.py` | ✅ KEEP | Applies ML delta to confidence — wired via `signal_boosters.py` |
| `metrics_cache.py` | ✅ KEEP ⚠️ | Rolling per-ticker win rate. **Flagged:** uses raw sqlalchemy vs `db_connection` pool |
| `analyze_signal_failures.py` | 📦 MOVED (S6) | → `scripts/analysis/`. Zero import callers. `42126d5` / `f6254b5` |
| `train_from_analytics.py` | 📦 MOVED (S6) | → `scripts/ml/`. CLI tool. `42126d5` / `2f586e6` |
| `train_historical.py` | 📦 MOVED (S6) | → `scripts/ml/`. CLI tool. `42126d5` / `dc9a8db` |

**app/ml: 6/9 active KEEP. 3 MOVED to scripts/.**

### `app/analytics/` — 14 files, all KEEP

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | Re-exports |
| `VOLUME_INDICATORS_README.md` | ✅ KEEP | Dev reference |
| `performance_monitor.py` | ✅ KEEP | P&L metrics, Sharpe, drawdown |
| `performance_alerts.py` | ✅ KEEP | Discord alert triggers — distinct from monitor |
| `funnel_analytics.py` | ✅ KEEP | **CANONICAL** funnel DB tracker |
| `funnel_tracker.py` | ✅ KEEP (shim) | CI fallback shim over `funnel_analytics.py` |
| `ab_test_framework.py` | ✅ KEEP | **CANONICAL** A/B test engine |
| `ab_test.py` | ✅ KEEP (shim) | CI fallback shim over `ab_test_framework.py` |
| `explosive_mover_tracker.py` | ✅ KEEP | **CANONICAL** explosive move tracker |
| `explosive_tracker.py` | ✅ KEEP (shim) | Re-export shim — `sniper.py` imports from this path |
| `cooldown_tracker.py` | ✅ KEEP | Per-ticker cooldown enforcement |
| `grade_gate_tracker.py` | ✅ KEEP | Grade-level gate tracking |
| `target_discovery.py` | ✅ KEEP | Price target/TP zone analysis |
| `eod_discord_report.py` | ✅ KEEP | EOD Discord embed builder — distinct from `eod_reporter.py` |

**app/analytics: 14/14 KEEP. All 3 overlap pairs confirmed as intentional shim patterns.**

### `app/ai/` — 2 files, all KEEP

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `ai_learning.py` | ✅ KEEP | **CANONICAL** confidence engine. `compute_confidence()` uses timeframe multiplier. |

**app/ai: 2/2 KEEP.**

---

## BATCH C — Backtesting & Scripts (Next)

> **Pending.** Covers: `app/backtesting/`, `scripts/backtesting/` (20 scripts), `scripts/analysis/`, `scripts/optimization/`, `scripts/database/`, `scripts/maintenance/`, `scripts/powershell/`, `scripts/ml/` (new), root-level scripts.

### Key flags to resolve:
- `scripts/war_machine.db` vs root `war_machine.db` — is one stale?
- Backtest scripts: which are current vs experiments?
- `app/backtesting/` — does `historical_trainer.py` duplicate anything in `backtest_engine.py`?

---

## BATCH D — Screening, Options, Indicators, Utils (Pending)

### Key flags:
- `app/indicators/technical_indicators.py` vs `app/indicators/technical_indicators_extended.py`
- `app/options/options_data_manager.py` vs `app/data/data_manager.py` scope overlap
- `app/indicators/vwap_calculator.py` vs `app/filters/vwap_gate.py` — canonical VWAP designation

---

## BATCH E — Tests, Docs, Backups, Root Files (Pending)

### Known quarantine candidates:
| File | Reason |
|------|--------|
| `app/discord_helpers_backup.py` | Explicit backup |
| `app/data/ws_feed.py.backup` | Non-module backup |
| `audit_repo.py` | One-time audit script |
| `backups/cleanup_backup_20260309_105038/` | Old backup folder |
| `docs/history/*.md` and `*.txt` | Phase notes — consolidate to CHANGELOG |
| `audit_reports/` (all 10 files) | Generated reports |
| `war_machine_architecture_doc.txt` | Move to `docs/` |
| `market_memory.db` | Verify if replaced by PostgreSQL |
| `scripts/war_machine.db` | Verify if stale |

---

## Cross-Batch Overlap Flags (Running List)

| Flag | File A | File B | Status | Resolution |
|------|--------|--------|--------|-------------------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | ✅ RESOLVED | A is shim; B canonical |
| ws trade vs quote | `app/data/ws_feed.py` | `app/data/ws_quote_feed.py` | ✅ RESOLVED | Distinct endpoints |
| db layers | `app/data/database.py` | `app/data/db_connection.py` | ✅ RESOLVED | Intentional layering |
| VWAP formula | `app/validation/cfw6_confirmation.py` | `app/filters/vwap_gate.py` | ✅ FIXED | `95be3ae` |
| Entry timing | `app/validation/entry_timing.py` | `app/filters/entry_timing_optimizer.py` | ✅ RESOLVED | Optimizer deleted |
| DTE filter | `app/filters/options_dte_filter.py` | `app/validation/greeks_precheck.py` | ✅ RESOLVED | Filter deleted |
| Confidence engine | `app/core/confidence_model.py` | `app/ai/ai_learning.py` | ✅ RESOLVED | Stub deleted |
| Performance layers | `app/analytics/performance_monitor.py` | `app/analytics/performance_alerts.py` | ✅ RESOLVED | Distinct roles |
| Volume profile | `app/validation/volume_profile.py` | `app/indicators/volume_profile.py` | ✅ RESOLVED | Distinct scopes |
| Explosive tracker | `app/analytics/explosive_mover_tracker.py` | `app/analytics/explosive_tracker.py` | ✅ RESOLVED | Tracker=canonical, tracker.py=shim |
| AB test | `app/analytics/ab_test.py` | `app/analytics/ab_test_framework.py` | ✅ RESOLVED | ab_test.py=CI shim |
| Funnel | `app/analytics/funnel_analytics.py` | `app/analytics/funnel_tracker.py` | ✅ RESOLVED | tracker.py=CI shim |
| signal_analytics vs funnel | `app/signals/signal_analytics.py` | `app/analytics/funnel_analytics.py` | ✅ RESOLVED | Distinct scopes |
| ML scorer | `app/ml/ml_signal_scorer.py` | `app/ml/ml_signal_scorer_v2.py` | ✅ NOTE | Both files no longer present in `app/ml/` after moves — confirm in Batch C |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | ⏳ Batch C | Check if both referenced or one stale |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | ✅ RESOLVED | Different jobs |
| Backtest scripts vs engine | `scripts/backtesting/*.py` | `app/backtesting/backtest_engine.py` | ⏳ Batch C | Scripts=standalone, engine=prod |
| technical_indicators | `app/indicators/technical_indicators.py` | `app/indicators/technical_indicators_extended.py` | ⏳ Batch D | Additive vs superseding |
| VWAP canonical | `app/indicators/vwap_calculator.py` | `app/filters/vwap_gate.py` | ⏳ Batch D | Designate one canonical |

---

## Files Cleared (No Action Needed)

- **app/core:** 13 KEEP, 1 DELETED
- **app/risk, app/data, app/signals, app/filters, app/mtf, app/validation, app/notifications:** 45 KEEP, 1 FIXED, 2 DELETED
- **Signal metrics deep audit (S4-S5):** 4 KEEP/cleared, 1 DELETED, 2 partial
- **app/ml:** 6 KEEP, 3 MOVED to scripts/
- **app/analytics:** 14 KEEP, 0 issues
- **app/ai:** 2 KEEP

**Total actions to date: 3 DELETED, 4 MOVED, 4 FIXED/shimmed, 1 annotated.**

---

*Updated: Session 6, 2026-03-16 ~21:45 EDT. Batch B complete. Next: Batch C.*
