# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all 336 tracked files.  
> **Last updated:** 2026-03-16 Session 7 (Batch C)  
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
| C | `app/backtesting/`, `scripts/` (all subfolders) | 55 | ✅ Complete |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | ~25 | ⏳ Next |
| E | `tests/`, `docs/`, `audit_reports/`, `backups/`, `migrations/`, root files | ~50 | ⏳ Pending |
| Cross-Batch | Overlap analysis across all batches | 336 total | ⏳ Pending |

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
| 19 | 2026-03-16 | S7 | `docs/AUDIT_REGISTRY.md` | Batch C complete — all `app/backtesting/` and `scripts/` fully audited. | this commit | Registry current |

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
| 8 | 🟡 MEDIUM | `app/core/eod_reporter.py` | Confirm Discord send of `get_discord_eod_summary()` | ⏳ Batch D |
| 9 | 🟡 MEDIUM | `app/signals/signal_analytics.py` | Wire `get_hourly_funnel()` into EOD output | ⏳ Batch D |
| 10 | 🟡 MEDIUM | `app/ml/metrics_cache.py` | Standardize to `db_connection` pool (currently uses raw sqlalchemy) | ⏳ Batch D |
| 11 | 🟡 LOW | `tests/test_task9_funnel_analytics.py` | Rename → `tests/test_funnel_analytics.py` | ⏳ Batch E |
| 12 | 🟡 LOW | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Batch E |
| 13 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Batch E |
| 14 | 🟢 LOW | `models/signal_predictor.pkl` | `git rm --cached` to untrack binary (LOCAL ACTION) | ⏳ Pending |
| 15 | 🟢 LOW | `models/training_dataset.csv` | `git rm --cached` to untrack CSV (LOCAL ACTION) | ⏳ Pending |

---

## LOCAL ACTIONS REQUIRED (Cannot Be Done via GitHub)

Run these locally in PowerShell before next push:

```powershell
# Untrack binary/data model files (already in .gitignore)
git rm --cached models/signal_predictor.pkl
git rm --cached models/training_dataset.csv
git commit -m "chore: untrack binary model files (already in .gitignore)"
git push
```

No other local-only files found on GitHub. `ws_feed.py.backup`, `discord_helpers_backup.py`, and `backups/` directory are local-only and not tracked in the repo.

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers of `app.core` | ✅ KEEP | |
| `__main__.py` | 177 B | Railway entrypoint shim | Railway start command | ✅ KEEP | |
| `scanner.py` | 42 KB | Main scan loop | Entrypoint | ✅ KEEP | **PROHIBITED** |
| `sniper.py` | 55 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** |
| `arm_signal.py` | 7 KB | Signal arming | `sniper.py` | ✅ KEEP | `record_trade_executed()` wired (S4) |
| `armed_signal_store.py` | 8 KB | Armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `watch_signal_store.py` | 7.6 KB | Pre-armed signal store | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `confidence_model.py` | — | ❌ DELETED (S5) | — | Dead stub. Commit `b99a63a`. |
| `gate_stats.py` | 5.8 KB | Gate statistics | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `sniper_log.py` | 4.1 KB | Structured logging | `sniper.py` | ✅ KEEP | |
| `thread_safe_state.py` | 10.8 KB | Thread-safe shared state | `scanner.py`, `sniper.py` | ✅ KEEP | |
| `analytics_integration.py` | 9.2 KB | Core↔analytics bridge | `scanner.py` | ✅ KEEP | |
| `eod_reporter.py` | 3.8 KB | EOD cleanup + stats | `scanner.py` | ✅ KEEP ⚠️ | Verify Discord send (Batch D) |
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
| `ml_trainer.py` | ✅ KEEP | RF/GBM training engine — called by `scripts/ml/train_historical.py` |
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
| `funnel_tracker.py` | ✅ KEEP (shim) | CI fallback shim over `funnel_analytics.py` — cannot remove without Batch E test refactor |
| `ab_test_framework.py` | ✅ KEEP | **CANONICAL** A/B test engine |
| `ab_test.py` | ✅ KEEP (shim) | CI fallback shim over `ab_test_framework.py` — cannot remove without Batch E test refactor |
| `explosive_mover_tracker.py` | ✅ KEEP | **CANONICAL** explosive move tracker |
| `explosive_tracker.py` | ✅ KEEP (shim) | Re-export shim — `sniper.py` PROHIBITED imports from this path |
| `cooldown_tracker.py` | ✅ KEEP | Per-ticker cooldown enforcement |
| `grade_gate_tracker.py` | ✅ KEEP | Grade-level gate tracking |
| `target_discovery.py` | ✅ KEEP | Price target/TP zone analysis |
| `eod_discord_report.py` | ✅ KEEP | EOD Discord embed builder — distinct from `eod_reporter.py` |

**app/analytics: 14/14 KEEP. All 3 overlap pairs confirmed as intentional shim patterns.**

> **Shim consolidation note:** All 4 shims (`discord_helpers.py`, `explosive_tracker.py`, `funnel_tracker.py`, `ab_test.py`) have been confirmed **unmergeable at this time** without touching PROHIBITED files or breaking CI test imports. Schedule consolidation in Batch E when test files are in scope.

### `app/ai/` — 2 files, all KEEP

| File | Verdict | Notes |
|------|---------|-------|
| `__init__.py` | ✅ KEEP | |
| `ai_learning.py` | ✅ KEEP | **CANONICAL** confidence engine. `compute_confidence()` uses timeframe multiplier. |

**app/ai: 2/2 KEEP.**

---

## BATCH C — Backtesting & Scripts

> **Completed 2026-03-16 Session 7. Zero overlapping files found. Zero deletions executed (all candidates are local-only).**

### Shim Merge Analysis — Final Verdict

All 4 shims (`app/discord_helpers.py`, `app/analytics/explosive_tracker.py`, `app/analytics/funnel_tracker.py`, `app/analytics/ab_test.py`) **cannot be merged yet** because their callers are either PROHIBITED runtime files or active CI test paths. Consolidation is a Batch E action.

### `app/backtesting/` — 7 files

| File | Size | Role | Verdict | Notes |
|------|------|------|---------|-------|
| `__init__.py` | 1.7 KB | Package marker + re-exports | ✅ KEEP | |
| `backtest_engine.py` | 19.6 KB | Generic framework — Trade/Position, slippage sim, T1/T2 exits, P&L | ✅ KEEP | **No overlap** with `historical_trainer.py` — different purpose and consumer |
| `historical_trainer.py` | 43.2 KB | ML training pipeline — EODHD bar fetch, BOS+FVG replay, WIN/LOSS labeling, 20-feature vectors | ✅ KEEP | **No overlap** — feeds `scripts/ml/train_historical.py`. Self-contained, no live DB. |
| `parameter_optimizer.py` | 5.9 KB | Grid/random search over strategy params using `BacktestEngine` | ✅ KEEP | Correct dependency chain |
| `performance_metrics.py` | 7.3 KB | Sharpe, Sortino, max drawdown, profit factor, expectancy | ✅ KEEP | **Distinct from** `app/analytics/performance_monitor.py` (backtested vs live P&L) |
| `signal_replay.py` | 6.9 KB | Replays logged signals from DB against historical bars | ✅ KEEP | Distinct from `historical_trainer.py` — uses actual logged signals, not synthetic replay |
| `walk_forward.py` | 11.5 KB | Walk-forward validation framework with temporal splits | ✅ KEEP | Wraps `BacktestEngine` |

**app/backtesting: 7/7 KEEP. Zero deletions. Zero overlaps.**

> `backtest_engine.py` vs `historical_trainer.py` — **CONFIRMED NOT OVERLAPPING.** Engine = generic framework that simulates fills/slippage/commissions for any strategy. Trainer = ML-specific pipeline that outputs WIN/LOSS labeled feature vectors for model training. They serve entirely different consumers and can be used together.

### `scripts/` root — 11 files

| File | Verdict | Notes |
|------|---------|-------|
| `README_ML_TRAINING.md` | ✅ KEEP | ML training workflow documentation |
| `audit_repo.py` | 🗃️ QUARANTINE → Batch E | One-time audit script; superseded by this registry |
| `check_eodhd_intraday.py` | ✅ KEEP | Dev utility — verify EODHD intraday API connectivity |
| `debug_bos_scan.py` | ✅ KEEP | Dev debug tool for BOS scan logic |
| `debug_comprehensive.py` | ✅ KEEP | Full system debug runner — distinct from BOS debug |
| `deploy.ps1` | ✅ KEEP | Railway deploy automation — actively used |
| `extract_positions_from_db.py` | ✅ KEEP | DB extraction utility for trade review |
| `extract_signals_from_logs.py` | ✅ KEEP | Log parser for post-session analysis |
| `generate_ml_training_data.py` | ✅ KEEP | Standalone ML data generator — distinct from `historical_trainer.py` |
| `scanner_startup_template.py` | ✅ KEEP | Dev reference template |
| `system_health_check.py` | ✅ KEEP | Pre-flight system health check for Railway deploy verification |

### `scripts/backtesting/` — 15 files

| File | Verdict | Notes |
|------|---------|-------|
| `analyze_losers.py` | ✅ KEEP | Analyzes losing trade patterns |
| `analyze_signal_patterns.py` | ✅ KEEP | Pattern analysis across signal history |
| `backtest_comprehensive.py` | ✅ KEEP | Full multi-ticker comprehensive backtest runner |
| `backtest_enhanced_filters.py` | ✅ KEEP | Tests enhanced filter combinations — research |
| `backtest_optimized_params.py` | ✅ KEEP | Runs optimized parameter sets — production tuning |
| `backtest_realistic_detector.py` | ✅ KEEP | Realistic execution simulation with slippage |
| `backtest_v2_detector.py` | ⚠️ REVIEW → Batch E | "v2" naming — verify vs `backtest_realistic_detector.py` for possible supersession |
| `backtest_with_eodhd.py` | ✅ KEEP | EODHD-specific backtest — distinct data source |
| `extract_candles_from_db.py` | ✅ KEEP | DB candle extraction for offline backtesting |
| `historical_advisor.py` | ✅ KEEP | Historical pattern advisor — distinct from trainer |
| `production_indicator_backtest.py` | ✅ KEEP | Tests production indicators against historical data |
| `run_full_dte_backtest.py` | ✅ KEEP | DTE-specific backtest — options focused |
| `simulate_from_candles.py` | ✅ KEEP | Candle-based simulation engine |
| `test_dte_logic.py` | ✅ KEEP | DTE logic validation |
| `unified_production_backtest.py` | ✅ KEEP | **Most current** unified backtest — canonical production param testing script |

### `scripts/backtesting/campaign/` — 7 files (complete numbered pipeline)

| File | Verdict | Notes |
|------|---------|-------|
| `README.md` | ✅ KEEP | Documents numbered pipeline steps |
| `00_export_from_railway.py` | ✅ KEEP | Step 0a: Export DB from Railway |
| `00b_backfill_eodhd.py` | ✅ KEEP | Step 0b: Backfill EODHD data |
| `01_fetch_candles.py` | ✅ KEEP | Step 1: Fetch candle data |
| `02_run_campaign.py` | ✅ KEEP | Step 2: Run backtest campaign |
| `03_analyze_results.py` | ✅ KEEP | Step 3: Analyze results |
| `probe_railway.py` | ✅ KEEP | Railway connectivity probe utility |

**Campaign: 7/7 KEEP. Sequential numbered pipeline — all files intentional.**

### `scripts/analysis/` — 3 files

| File | Verdict | Notes |
|------|---------|-------|
| `analyze_ml_training_data.py` | ✅ KEEP | ML data quality analyzer |
| `analyze_signal_failures.py` | 📦 MOVED HERE (S6) | Moved from `app/ml/` — correct location |
| `inspect_signal_outcomes.py` | ✅ KEEP | Signal outcome inspector — distinct from analyzer |

### `scripts/ml/` — 3 files

| File | Verdict | Notes |
|------|---------|-------|
| `train_from_analytics.py` | 📦 MOVED HERE (S6) | Moved from `app/ml/` — correct location |
| `train_historical.py` | 📦 MOVED HERE (S6) | Moved from `app/ml/` — calls `historical_trainer.py` |
| `train_ml_booster.py` | ✅ KEEP | Trains `ml_confidence_boost.py` model — distinct from `train_historical.py` |

### `scripts/database/` — 6 files

| File | Verdict | Notes |
|------|---------|-------|
| `check_database.py` | 📦 MOVED HERE (S1) | Moved from `app/ml/` |
| `db_diagnostic.py` | 📦 MOVED HERE | Previously in `tests/` |
| `dte_selector_demo.py` | 📦 MOVED HERE | Previously `tests/dte_selector.py` |
| `inspect_database_schema.py` | ✅ KEEP | Schema inspection utility |
| `load_historical_data.py` | ✅ KEEP | Historical data loader for backtesting |
| `setup_database.py` | ✅ KEEP | DB initialization script |

### `scripts/maintenance/` — 1 file

| File | Verdict | Notes |
|------|---------|-------|
| `update_sniper_greeks.py` | ✅ KEEP | Maintenance script to refresh Greeks data |

### `scripts/optimization/` — 1 file

| File | Verdict | Notes |
|------|---------|-------|
| `smart_optimization.py` | ✅ KEEP | 26 KB optimizer — production-ready optimization engine |

### `scripts/powershell/` — 2 files

| File | Verdict | Notes |
|------|---------|-------|
| `dependency_analyzer.ps1` | ✅ KEEP | Import dependency graph analyzer |
| `restore_and_deploy.ps1` | ✅ KEEP | Railway restore + deploy automation |

**BATCH C TOTAL: 55/55 KEEP (net). Zero deletions executed on GitHub. All local-only file removals are manual actions listed in the Local Actions section above.**

---

## BATCH D — Screening, Options, Indicators, Utils (Next)

### Key flags to resolve:
- `app/indicators/technical_indicators.py` vs `app/indicators/technical_indicators_extended.py` — additive or superseding?
- `app/options/options_data_manager.py` vs `app/data/data_manager.py` — scope overlap?
- `app/indicators/vwap_calculator.py` vs `app/filters/vwap_gate.py` — designate one canonical VWAP source
- `utils/` — fully map all utilities; confirm none duplicate `app/data/` helpers
- `app/indicators/volume_profile.py` vs `app/validation/volume_profile.py` — already confirmed distinct (A2); note here for cross-reference

---

## BATCH E — Tests, Docs, Backups, Root Files (Pending)

### Known quarantine candidates:
| File | Reason |
|------|--------|
| `scripts/audit_repo.py` | One-time audit script — superseded by this registry |
| `app/discord_helpers_backup.py` | Explicit backup — local-only |
| `app/data/ws_feed.py.backup` | Non-module backup — local-only |
| `backups/cleanup_backup_20260309_105038/` | Old backup folder — local-only |
| `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` |
| `docs/history/*.md` and `*.txt` | Phase notes — consolidate to CHANGELOG |
| `audit_reports/` (all files) | Generated reports — archive or delete |
| `war_machine_architecture_doc.txt` | Move to `docs/` |
| `market_memory.db` | Verify if replaced by PostgreSQL |
| `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` |

### Pending renames for Batch E:
- `tests/test_task9_funnel_analytics.py` → `tests/test_funnel_analytics.py`

---

## Cross-Batch Overlap Flags (Running List)

| Flag | File A | File B | Status | Resolution |
|------|--------|--------|--------|-----------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | ✅ RESOLVED | A is shim; B canonical. Cannot merge until Batch E. |
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
| Backtest engine vs trainer | `app/backtesting/backtest_engine.py` | `app/backtesting/historical_trainer.py` | ✅ RESOLVED | Distinct: engine=generic framework, trainer=ML labeling pipeline |
| Backtest metrics vs live | `app/backtesting/performance_metrics.py` | `app/analytics/performance_monitor.py` | ✅ RESOLVED | Distinct: backtested vs live P&L |
| Backtest v2 vs realistic | `scripts/backtesting/backtest_v2_detector.py` | `scripts/backtesting/backtest_realistic_detector.py` | ⏳ Batch E | Verify if v2 is superseded |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | ⏳ Batch E | Check if both referenced or one stale |
| technical_indicators | `app/indicators/technical_indicators.py` | `app/indicators/technical_indicators_extended.py` | ⏳ Batch D | Additive vs superseding? |
| VWAP canonical | `app/indicators/vwap_calculator.py` | `app/filters/vwap_gate.py` | ⏳ Batch D | Designate one canonical |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | ✅ RESOLVED | Different jobs |

---

## Files Cleared (No Action Needed)

- **app/core:** 13 KEEP, 1 DELETED
- **app/risk, app/data, app/signals, app/filters, app/mtf, app/validation, app/notifications:** 45 KEEP, 1 FIXED, 2 DELETED
- **Signal metrics deep audit (S4-S5):** 4 KEEP/cleared, 1 DELETED, 2 partial
- **app/ml:** 6 KEEP, 3 MOVED to scripts/
- **app/analytics:** 14 KEEP, 0 issues
- **app/ai:** 2 KEEP
- **app/backtesting:** 7 KEEP, 0 issues, 0 overlaps
- **scripts/ (all subfolders):** 48 KEEP, 1 QUARANTINE (Batch E), 1 REVIEW (Batch E)

**Total actions to date: 3 DELETED, 4 MOVED, 4 FIXED/shimmed, 1 annotated. 4 shims confirmed unmergeable until Batch E.**

---

*Updated: Session 7, 2026-03-16 ~23:20 EDT. Batch C complete. Next: Batch D.*
