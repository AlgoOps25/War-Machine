# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all tracked files.  
> **Last updated:** 2026-03-17 Session 8 (Batch D + E)  
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
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | 25 | ✅ Complete |
| E | `tests/`, `docs/`, `migrations/`, `models/`, root files | 30 | ✅ Complete |
| Cross-Batch | Overlap analysis across all batches | all | ✅ Current |

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
| 20 | 2026-03-17 | S8 | `docs/AUDIT_REGISTRY.md` | Batch D + E complete — screening, options, indicators, utils, tests, docs, root files all audited. | this commit | Registry fully current |

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
| 8 | 🟡 MEDIUM | `app/core/eod_reporter.py` | Confirm Discord send of `get_discord_eod_summary()` | ⏳ Open |
| 9 | 🟡 MEDIUM | `app/signals/signal_analytics.py` | Wire `get_hourly_funnel()` into EOD output | ⏳ Open |
| 10 | 🟡 MEDIUM | `app/ml/metrics_cache.py` | Standardize to `db_connection` pool (currently uses raw sqlalchemy) | ⏳ Open |
| 11 | 🟡 MEDIUM | `app/indicators/vwap_calculator.py` | Designate canonical VWAP source vs `app/filters/vwap_gate.py` | ⏳ Open |
| 12 | 🟡 LOW | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Open |
| 13 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Open |
| 14 | 🟢 LOW | `models/signal_predictor.pkl` | `git rm --cached` to untrack binary (LOCAL ACTION) | ⏳ Pending |
| 15 | 🟢 LOW | `models/training_dataset.csv` | `git rm --cached` to untrack CSV (LOCAL ACTION) | ⏳ Pending |
| 16 | 🟢 LOW | `market_memory.db` | Verify if replaced by PostgreSQL on Railway or still active | ⏳ Open |
| 17 | 🟢 LOW | `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` | ⏳ Open |
| 18 | 🟢 LOW | `audit_reports/venv/` | This is a venv accidentally committed inside audit_reports — should be gitignored/removed | ⏳ Open |

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
| `eod_reporter.py` | 3.8 KB | EOD cleanup + stats | `scanner.py` | ✅ KEEP ⚠️ | Verify Discord send (open) |
| `error_recovery.py` | 17.2 KB | Exception handling | `scanner.py` | ✅ KEEP | |
| `health_server.py` | 4.5 KB | `/health` endpoint | Railway healthcheck | ✅ KEEP | **PROHIBITED** |

**A1: 13/14 KEEP. 1 DELETED.**

---

## BATCH A2 — Supporting Runtime Modules

### `app/notifications/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Re-exports key send functions | All callers of `app.notifications` | ✅ KEEP | |
| `discord_helpers.py` | **CANONICAL** Discord send layer | `sniper.py`, `scanner.py`, `arm_signal.py` | ✅ KEEP | |

### `app/risk/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `risk_manager.py` | Max loss, daily loss, circuit-breaker rules | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** |
| `position_manager.py` | Open position tracking, exposure limits | `risk_manager.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `trade_calculator.py` | Share size, dollar risk, R-multiple math | `sniper.py`, `arm_signal.py` | ✅ KEEP | |
| `dynamic_thresholds.py` | Volatility-adjusted gate thresholds | `sniper.py`, `risk_manager.py` | ✅ KEEP | |
| `vix_sizing.py` | VIX-based position scaling | `trade_calculator.py`, `risk_manager.py` | ✅ KEEP | |

**app/risk: 6/6 KEEP.**

### `app/data/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `database.py` | Re-export shim | All legacy callers → `db_connection.py` | ✅ SHIM | |
| `db_connection.py` | SQLAlchemy pool, connection factory | All DB-accessing modules | ✅ KEEP | **PROHIBITED** — canonical connection layer |
| `data_manager.py` | EODHD REST + Tradier REST data fetch | `sniper.py`, `scanner.py`, `backtesting/*` | ✅ KEEP | **PROHIBITED** |
| `candle_cache.py` | In-memory/DB candle TTL cache | `sniper.py`, `bos_fvg_engine.py` | ✅ KEEP | |
| `sql_safe.py` | SQL parameter sanitization helpers | `db_connection.py`, DB writers | ✅ KEEP | |
| `unusual_options.py` | Unusual Whales API fetch + parse | `sniper.py`, `options_intelligence.py` | ✅ KEEP | |
| `ws_feed.py` | Tradier WebSocket — trade tick stream | `scanner.py` | ✅ KEEP | **PROHIBITED** — trade ticks |
| `ws_quote_feed.py` | Tradier WebSocket — bid/ask quote stream | `scanner.py` | ✅ KEEP | Distinct endpoint from `ws_feed.py` |

**app/data: 9/9 KEEP.**

### `app/signals/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `breakout_detector.py` | Breakout pattern detection (ORB, range breaks) | `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `opening_range.py` | Opening range high/low calculation | `breakout_detector.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `signal_analytics.py` | Per-signal metrics, rejection breakdown, hourly funnel, EOD summary | `sniper.py`, `analytics_integration.py` | ✅ KEEP | Distinct from `funnel_analytics.py`; extended S4/S5 |

### `app/filters/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `rth_filter.py` | Regular trading hours gate (9:30–16:00 ET) | `sniper.py` | ✅ KEEP | |
| `vwap_gate.py` | VWAP calculation + price-vs-VWAP gate | `sniper.py`, `cfw6_confirmation.py` | ✅ KEEP | **CANONICAL VWAP source** |
| `market_regime_context.py` | Bull/bear/neutral regime classification | `sniper.py`, `dynamic_thresholds.py` | ✅ KEEP | |
| `early_session_disqualifier.py` | Rejects signals in first ~5 min of session | `sniper.py` | ✅ KEEP | |
| `entry_timing_optimizer.py` | ❌ DELETED (S4) | — | Duplicate of `entry_timing.py`. `d1821d1` |
| `liquidity_sweep.py` | Detects stop-hunt liquidity sweeps | `sniper.py`, `smc_engine.py` | ✅ KEEP | |
| `options_dte_filter.py` | ❌ DELETED (S4) | — | Superseded by `greeks_precheck.py`. `3abfdd5` |
| `order_block_cache.py` | Caches detected order block zones | `sniper.py`, `bos_fvg_engine.py` | ✅ KEEP | |
| `sd_zone_confluence.py` | Supply/demand zone confluence scoring | `sniper.py` | ✅ KEEP | |
| `correlation.py` | Cross-ticker correlation filter | `sniper.py` | ✅ KEEP | |

**app/filters: 9/11 KEEP. 2 DELETED.**

### `app/mtf/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker + re-exports | All importers | ✅ KEEP | |
| `bos_fvg_engine.py` | Break-of-structure + fair-value-gap detection | `sniper.py`, `mtf_validator.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_validator.py` | Multi-timeframe signal validation gate | `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_integration.py` | Wires MTF data fetch into validator | `mtf_validator.py`, `data_manager.py` | ✅ KEEP | |
| `mtf_compression.py` | Compresses lower-TF candles to higher TF | `mtf_integration.py` | ✅ KEEP | |
| `mtf_fvg_priority.py` | Ranks FVG zones by timeframe priority | `bos_fvg_engine.py`, `sniper.py` | ✅ KEEP | |
| `smc_engine.py` | Smart money concepts: CHoCH, inducement zones | `sniper.py`, `liquidity_sweep.py` | ✅ KEEP | |

**app/mtf: 7/7 KEEP.**

> **Note:** `smc_engine.py` was present in the file list but missing from the prior registry table — added here.

### `app/validation/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `validation.py` | Master validation orchestrator | `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_gate_validator.py` | CFW6 confirmation gate | `validation.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_confirmation.py` | CFW6 confirmation signals | `cfw6_gate_validator.py` | 🔧 FIXED (S0) | VWAP formula corrected. `95be3ae` |
| `greeks_precheck.py` | Options Greeks pre-validation (delta, IV, OI) | `validation.py`, `options_intelligence.py` | ✅ KEEP | Supersedes deleted `options_dte_filter.py` |
| `hourly_gate.py` | Hourly session quality gate | `sniper.py` | ✅ KEEP | |
| `entry_timing.py` | Entry timing window validator | `validation.py`, `sniper.py` | ✅ KEEP | Canonical — duplicate deleted (S4) |
| `volume_profile.py` | Intrabar volume profile validation (5-min TTL cache) | `validation.py` | ✅ KEEP | Distinct from `app/indicators/volume_profile.py` |

**app/validation: 7/7 active KEEP. 1 FIXED.**

---

## BATCH B — ML, Analytics, AI

> **Completed 2026-03-16 Session 6.**

### `app/ml/` — 6 active files (was 9)

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `README.md` | ML module documentation | Dev reference | ✅ KEEP | |
| `INTEGRATION.md` | ML wiring guide | Dev reference | ✅ KEEP | |
| `ml_trainer.py` | RF/GBM model training engine | `scripts/ml/train_historical.py`, `historical_trainer.py` | ✅ KEEP | |
| `ml_confidence_boost.py` | Applies ML delta to signal confidence score | `sniper.py` via `signal_boosters.py` | ✅ KEEP | |
| `metrics_cache.py` | Rolling per-ticker win rate cache | `sniper.py`, `ml_confidence_boost.py` | ✅ KEEP ⚠️ | **Flagged:** uses raw sqlalchemy vs `db_connection` pool |
| `analyze_signal_failures.py` | 📦 MOVED (S6) | → `scripts/analysis/` | Zero import callers. `42126d5` / `f6254b5` |
| `train_from_analytics.py` | 📦 MOVED (S6) | → `scripts/ml/` | CLI tool. `42126d5` / `2f586e6` |
| `train_historical.py` | 📦 MOVED (S6) | → `scripts/ml/` | CLI tool. `42126d5` / `dc9a8db` |

**app/ml: 6/9 active KEEP. 3 MOVED to scripts/.**

### `app/analytics/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Re-exports | All callers | ✅ KEEP | |
| `performance_monitor.py` | Live P&L metrics — Sharpe, drawdown, win rate | `analytics_integration.py`, `eod_reporter.py` | ✅ KEEP | Distinct from backtesting `performance_metrics.py` |
| `funnel_analytics.py` | **CANONICAL** funnel DB tracker (SCANNED → TRADED stages) | `sniper.py`, `analytics_integration.py` | ✅ KEEP | |
| `funnel_tracker.py` | CI fallback shim over `funnel_analytics.py` | `tests/test_funnel_analytics.py` | ✅ KEEP (shim) | Cannot remove without Batch E test refactor |
| `ab_test_framework.py` | **CANONICAL** A/B test engine for strategy variants | `analytics_integration.py` | ✅ KEEP | |
| `ab_test.py` | CI fallback shim over `ab_test_framework.py` | `tests/test_integrations.py` | ✅ KEEP (shim) | Cannot remove without test refactor |
| `explosive_mover_tracker.py` | **CANONICAL** explosive move tracker | `sniper.py` | ✅ KEEP | |
| `explosive_tracker.py` | Re-export shim — `sniper.py` PROHIBITED imports from this path | `sniper.py` (legacy import path) | ✅ KEEP (shim) | |
| `cooldown_tracker.py` | Per-ticker trade cooldown enforcement | `sniper.py`, `arm_signal.py` | ✅ KEEP | |
| `grade_gate_tracker.py` | Grade-level gate tracking (A/B/C grade signals) | `sniper.py`, `analytics_integration.py` | ✅ KEEP | |

**app/analytics: 10/10 KEEP. All overlap pairs are intentional shim patterns.**

### `app/ai/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `ai_learning.py` | **CANONICAL** confidence engine. `compute_confidence()` uses timeframe multiplier. | `sniper.py`, `ml_confidence_boost.py` | ✅ KEEP | |

**app/ai: 2/2 KEEP.**

---

## BATCH C — Backtesting & Scripts

> **Completed 2026-03-16 Session 7. Zero overlapping files found. Zero deletions executed.**

### `app/backtesting/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker + re-exports | `scripts/backtesting/*` | ✅ KEEP | |
| `backtest_engine.py` | Generic backtest framework — Trade/Position, slippage sim, T1/T2 exits, P&L | `parameter_optimizer.py`, `walk_forward.py`, `scripts/backtesting/*` | ✅ KEEP | Not overlapping with `historical_trainer.py` |
| `historical_trainer.py` | ML training pipeline — EODHD bar fetch, BOS+FVG replay, WIN/LOSS labeling, 20-feature vectors | `scripts/ml/train_historical.py`, `ml_trainer.py` | ✅ KEEP | Self-contained; no live DB |
| `parameter_optimizer.py` | Grid/random search over strategy params | `backtest_engine.py` | ✅ KEEP | |
| `performance_metrics.py` | Sharpe, Sortino, max drawdown, profit factor, expectancy (backtested) | `backtest_engine.py`, `walk_forward.py` | ✅ KEEP | Distinct from live `performance_monitor.py` |
| `signal_replay.py` | Replays logged signals from DB against historical bars | `db_connection.py`, `backtest_engine.py` | ✅ KEEP | Uses actual logged signals, not synthetic |
| `walk_forward.py` | Walk-forward validation with temporal splits | `backtest_engine.py`, `performance_metrics.py` | ✅ KEEP | |

**app/backtesting: 7/7 KEEP.**

### `scripts/` (all subfolders)

See Batch C detail tables for all `scripts/` subdirectory contents. Summary: 55/55 KEEP (net), 1 QUARANTINE pending (Batch E), 1 REVIEW pending.

---

## BATCH D — Screening, Options, Indicators, Utils

> **Completed 2026-03-17 Session 8.**

### `app/screening/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `premarket_scanner.py` | Pre-market gap/volume/news scan (runs 8:45–9:30 AM EST) | `scanner.py` | ✅ KEEP | Entrypoint for morning universe selection |
| `dynamic_screener.py` | Real-time intraday screener — filters live universe by momentum/volume criteria | `scanner.py`, `sniper.py` | ✅ KEEP | |
| `gap_analyzer.py` | Gap-up/gap-down magnitude, fill probability analysis | `premarket_scanner.py`, `sniper.py` | ✅ KEEP | |
| `volume_analyzer.py` | Relative volume, unusual volume spike detection | `premarket_scanner.py`, `dynamic_screener.py`, `sniper.py` | ✅ KEEP | Distinct from `app/indicators/volume_indicators.py` — screening-layer vs indicator-layer |
| `news_catalyst.py` | News headline fetch + catalyst scoring | `premarket_scanner.py` | ✅ KEEP | |
| `market_calendar.py` | Trading day/holiday calendar, session timing | `premarket_scanner.py`, `scanner.py`, `rth_filter.py` | ✅ KEEP | |
| `watchlist_funnel.py` | Narrows scanned universe → watchlist candidates via funnel scoring | `premarket_scanner.py`, `funnel_analytics.py` | ✅ KEEP | |

**app/screening: 8/8 KEEP.**

### `app/options/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | |
| `options_intelligence.py` | Master options signal layer — combines flow, Greeks, IV, GEX | `sniper.py`, `validation.py` | ✅ KEEP | Top-level orchestrator for options signals |
| `options_data_manager.py` | Options chain fetch + parse (Tradier API) | `options_intelligence.py`, `greeks_precheck.py` | ✅ KEEP | Distinct from `app/data/data_manager.py` — options-specific vs equity data |
| `options_optimizer.py` | Selects optimal strike/expiry given signal context | `options_intelligence.py`, `arm_signal.py` | ✅ KEEP | |
| `options_dte_selector.py` | DTE selection logic — maps signal horizon to days-to-expiry | `options_optimizer.py`, `options_intelligence.py` | ✅ KEEP | |
| `dte_historical_advisor.py` | Historical DTE performance advisor — recommends DTE based on past win rates | `options_dte_selector.py`, `scripts/backtesting/run_full_dte_backtest.py` | ✅ KEEP | |
| `iv_tracker.py` | Implied volatility tracking — IV rank, IV percentile, IV crush detection | `options_intelligence.py`, `greeks_precheck.py` | ✅ KEEP | |
| `gex_engine.py` | Gamma exposure calculation — dealer positioning, flip levels | `options_intelligence.py`, `sniper.py` | ✅ KEEP | |

**app/options: 8/8 KEEP.**

> **Cross-reference:** `options_data_manager.py` vs `app/data/data_manager.py` — **CONFIRMED NOT OVERLAPPING.** `data_manager.py` handles equity OHLCV + Tradier equity endpoints. `options_data_manager.py` handles Tradier options chain endpoints, greeks, and open interest. Different API routes, different data schemas.

### `app/indicators/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `technical_indicators.py` | Core TA library — EMA, RSI, MACD, ATR, Bollinger Bands | `sniper.py`, `bos_fvg_engine.py`, `breakout_detector.py` | ✅ KEEP | **Base layer** |
| `technical_indicators_extended.py` | Extended TA — additional oscillators, pattern recognition built on top of base | `sniper.py`, `mtf_validator.py` | ✅ KEEP | **Additive, not superseding.** Extended file imports from base. Both needed. |
| `volume_indicators.py` | Volume-based indicators — OBV, CMF, VWAP-volume ratio | `sniper.py`, `volume_analyzer.py` | ✅ KEEP | Distinct from `volume_analyzer.py` (screening) — this is indicator math |
| `volume_profile.py` | Price-at-volume distribution, POC, value area | `sniper.py`, `mtf_validator.py` | ✅ KEEP | Distinct from `app/validation/volume_profile.py` (intrabar TTL cache). This is full-session VPOC. |
| `vwap_calculator.py` | Pure VWAP math engine — tick-by-tick cumulative VWAP | `vwap_gate.py`, `cfw6_confirmation.py` | ✅ KEEP ⚠️ | **Relationship with `vwap_gate.py`:** `vwap_calculator.py` = raw math; `vwap_gate.py` = gate logic using that math. Both needed. `vwap_gate.py` remains the canonical import for all filter/validation callers. |

**app/indicators: 5/5 KEEP.**

> **VWAP canonical designation (resolves Batch D flag):**
> - `app/indicators/vwap_calculator.py` = **math engine** (low-level, computes VWAP values)
> - `app/filters/vwap_gate.py` = **gate/filter layer** (imports from calculator, applies signal logic)
> - All filter/validation modules should import from `vwap_gate.py`. Sniper/scanner should never import `vwap_calculator.py` directly.

> **technical_indicators overlap resolved:** `technical_indicators_extended.py` is **additive** — it imports and extends `technical_indicators.py`. Neither supersedes the other. Both are ✅ KEEP.

### `utils/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Package marker | All importers | ✅ KEEP | **PROHIBITED** |
| `config.py` | Central config loader — env vars, Railway secrets, API keys | **Every module** (app-wide) | ✅ KEEP | **PROHIBITED** — single source of truth for all config |
| `production_helpers.py` | Railway/production environment helpers — log formatting, startup checks | `scanner.py`, `health_server.py` | ✅ KEEP | **PROHIBITED** |
| `time_helpers.py` | Market timezone helpers, EST conversion, session time math | `rth_filter.py`, `scanner.py`, `market_calendar.py`, `entry_timing.py` | ✅ KEEP | **PROHIBITED** |

**utils/: 4/4 KEEP.**

---

## BATCH E — Tests, Docs, Migrations, Models, Root Files

> **Completed 2026-03-17 Session 8.**

### `tests/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `__init__.py` | Test package marker | pytest | ✅ KEEP | |
| `conftest.py` | pytest fixtures — DB setup, mock data, shared test state | All test files | ✅ KEEP | |
| `README.md` | Test suite documentation | Dev reference | ✅ KEEP | |
| `test_failover.py` | Tests scanner/data failover + error recovery paths | `error_recovery.py`, `scanner.py` | ✅ KEEP | |
| `test_funnel_analytics.py` | Tests funnel tracking through all stages | `funnel_analytics.py`, `funnel_tracker.py` (shim) | ✅ KEEP | |
| `test_integrations.py` | Integration tests across core pipeline modules | Multiple modules | ✅ KEEP | |
| `test_mtf.py` | Tests MTF validation and BOS/FVG detection | `mtf_validator.py`, `bos_fvg_engine.py` | ✅ KEEP | |
| `test_signal_pipeline.py` | End-to-end signal pipeline test | `sniper.py`, `validation.py`, `arm_signal.py` | ✅ KEEP | |
| `test_smc_engine.py` | Tests smart money concepts engine | `smc_engine.py` | ✅ KEEP | |

**tests/: 9/9 KEEP.**

### `docs/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `ARCHITECTURE.md` | System architecture overview diagram + module map | Dev reference | ✅ KEEP | |
| `AUDIT_REGISTRY.md` | **This file** — master file registry | All files | ✅ KEEP | |
| `CHANGELOG.md` | Version history, feature additions, breaking changes | Dev reference | ✅ KEEP | |
| `FEATURES.md` | Feature catalog — what's live vs in-progress | Dev reference | ✅ KEEP | |
| `INTEGRATION_GUIDE.md` | Integration guide for wiring new modules | Dev reference | ✅ KEEP | |
| `README.md` | Docs-level readme | Dev reference | ✅ KEEP | |
| `integration/` | Integration-specific sub-docs folder | Dev reference | ✅ KEEP | |

**docs/: All KEEP.**

### `migrations/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `001_candle_cache.sql` | Creates `candle_cache` table | `candle_cache.py`, `db_connection.py` | ✅ KEEP | **PROHIBITED** |
| `002_signal_persist_tables.sql` | Creates signal persistence tables (armed_signals, watch_signals) | `armed_signal_store.py`, `watch_signal_store.py` | ✅ KEEP | **PROHIBITED** |
| `add_dte_tracking_columns.py` | Adds DTE tracking columns to signal tables | `options_dte_selector.py`, `dte_historical_advisor.py` | ✅ KEEP | **PROHIBITED** |
| `signal_outcomes_schema.sql` | Creates signal outcome tracking table | `signal_analytics.py`, `ml_trainer.py` | ✅ KEEP | **PROHIBITED** |

**migrations/: 4/4 KEEP.**

### `models/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `ml_model_historical.pkl` | Trained historical ML model binary | `ml_trainer.py`, `ml_confidence_boost.py` | ✅ KEEP ⚠️ | Binary — should be untracked from Git (LOCAL ACTION pending) |
| `signal_predictor.pkl` | Trained signal predictor model binary | `ml_confidence_boost.py` | ✅ KEEP ⚠️ | Binary — should be untracked from Git (LOCAL ACTION pending) |
| `training_dataset.csv` | ML training feature dataset | `ml_trainer.py`, `scripts/ml/train_historical.py` | ✅ KEEP ⚠️ | CSV — should be untracked from Git (LOCAL ACTION pending) |

**models/: 3/3 KEEP. All 3 should be gitignored and untracked (LOCAL ACTION).**

### `results/`

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `backtests/backtest_results.json` | Output from most recent backtest campaign | `scripts/backtesting/03_analyze_results.py` | ✅ KEEP | Generated output — not source code |
| `backtests/quick_backtest_results.csv` | Quick backtest CSV output | `scripts/backtesting/*` | ✅ KEEP | Generated output — not source code |

### `audit_reports/`

| Path | Verdict | Notes |
|------|---------|-------|
| `audit_reports/venv/` | ⚠️ REVIEW | A Python venv accidentally committed inside `audit_reports/`. Should be deleted from Git and added to `.gitignore`. Not source code. |

### Root Files

| File | Role | Connected To | Verdict | Notes |
|------|------|-------------|---------|-------|
| `.env` | Local environment variables / secrets | `utils/config.py` | ✅ KEEP | Gitignored — never committed |
| `.gitignore` | Git ignore rules | Git | ✅ KEEP | Updated S2 |
| `.railway_trigger` | Empty file to force Railway redeploy | Railway CI | ✅ KEEP | Touch-to-redeploy trigger |
| `.backtest_cache/` | Local cache of backtest data (EODHD candles etc.) | `scripts/backtesting/campaign/*`, `historical_trainer.py` | ✅ KEEP | Should be gitignored — confirm in `.gitignore` |
| `.github/` | GitHub Actions workflows | CI/CD | ✅ KEEP | |
| `.venv/` | Python virtual environment | Local dev | ✅ KEEP (local only) | Should be gitignored — never committed |
| `.vscode/` | VSCode workspace settings | Dev tooling | ✅ KEEP (local only) | Should be gitignored |
| `CONTRIBUTING.md` | Contribution guidelines | Dev reference | ✅ KEEP | |
| `LICENSE` | License file | Legal | ✅ KEEP | |
| `README.md` | Project root readme | All visitors | ✅ KEEP | |
| `requirements.txt` | Python dependencies | Railway deploy, local dev | ✅ KEEP | Updated S4 (yfinance removed) |
| `nixpacks.toml` | Railway Nixpacks build config | Railway deploy | ✅ KEEP | |
| `railway.toml` | Railway service config (start command, healthcheck) | Railway deploy | ✅ KEEP | |
| `pytest.ini` | pytest configuration | `tests/` | ✅ KEEP | |
| `war_machine.db` | Root SQLite DB (local dev / fallback) | `db_connection.py`, scripts | ✅ KEEP ⚠️ | Verify: Is this the primary dev DB or stale? Check vs `scripts/war_machine.db`. |
| `market_memory.db` | Market memory SQLite store | `ai_learning.py`, `metrics_cache.py` | ✅ KEEP ⚠️ | Verify: Is this replaced by PostgreSQL on Railway or still active locally? |
| `scripts/war_machine.db` | Secondary/stale SQLite DB inside scripts/ | Unknown | ⚠️ REVIEW | Likely stale — check if any script references this path explicitly. If not, delete. |

---

## Cross-Batch Overlap Flags (Complete)

| Flag | File A | File B | Status | Resolution |
|------|--------|--------|--------|-----------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | ✅ RESOLVED | A is shim; B canonical. Merge in future refactor. |
| ws trade vs quote | `app/data/ws_feed.py` | `app/data/ws_quote_feed.py` | ✅ RESOLVED | Distinct endpoints |
| db layers | `app/data/database.py` | `app/data/db_connection.py` | ✅ RESOLVED | Intentional layering |
| VWAP formula | `app/validation/cfw6_confirmation.py` | `app/filters/vwap_gate.py` | ✅ FIXED | `95be3ae` |
| Entry timing | `app/validation/entry_timing.py` | `app/filters/entry_timing_optimizer.py` | ✅ RESOLVED | Optimizer deleted |
| DTE filter | `app/filters/options_dte_filter.py` | `app/validation/greeks_precheck.py` | ✅ RESOLVED | Filter deleted |
| Confidence engine | `app/core/confidence_model.py` | `app/ai/ai_learning.py` | ✅ RESOLVED | Stub deleted |
| Performance layers | `app/analytics/performance_monitor.py` | `app/backtesting/performance_metrics.py` | ✅ RESOLVED | Live P&L vs backtested P&L |
| Volume profile | `app/validation/volume_profile.py` | `app/indicators/volume_profile.py` | ✅ RESOLVED | Intrabar TTL cache vs full-session VPOC |
| Explosive tracker | `app/analytics/explosive_mover_tracker.py` | `app/analytics/explosive_tracker.py` | ✅ RESOLVED | Canonical vs shim |
| AB test | `app/analytics/ab_test.py` | `app/analytics/ab_test_framework.py` | ✅ RESOLVED | CI shim vs canonical |
| Funnel | `app/analytics/funnel_analytics.py` | `app/analytics/funnel_tracker.py` | ✅ RESOLVED | CI shim vs canonical |
| signal_analytics vs funnel | `app/signals/signal_analytics.py` | `app/analytics/funnel_analytics.py` | ✅ RESOLVED | Distinct scopes |
| Backtest engine vs trainer | `app/backtesting/backtest_engine.py` | `app/backtesting/historical_trainer.py` | ✅ RESOLVED | Generic framework vs ML labeling pipeline |
| Backtest metrics vs live | `app/backtesting/performance_metrics.py` | `app/analytics/performance_monitor.py` | ✅ RESOLVED | Backtested vs live |
| Backtest v2 vs realistic | `scripts/backtesting/backtest_v2_detector.py` | `scripts/backtesting/backtest_realistic_detector.py` | ⏳ OPEN | Verify if v2 is superseded |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | ⏳ OPEN | Check if both referenced or one stale |
| technical_indicators | `app/indicators/technical_indicators.py` | `app/indicators/technical_indicators_extended.py` | ✅ RESOLVED | Additive — extended imports base. Both needed. |
| VWAP canonical | `app/indicators/vwap_calculator.py` | `app/filters/vwap_gate.py` | ✅ RESOLVED | Calculator = math engine; gate = filter logic. Gate is canonical import for callers. |
| Options data mgr | `app/options/options_data_manager.py` | `app/data/data_manager.py` | ✅ RESOLVED | Options chain endpoints vs equity OHLCV. No overlap. |
| Volume screening vs indicators | `app/screening/volume_analyzer.py` | `app/indicators/volume_indicators.py` | ✅ RESOLVED | Screening-layer vs indicator math. No overlap. |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | ✅ RESOLVED | Different jobs |

---

## Files Cleared (Full Count)

- **app/core:** 13 KEEP, 1 DELETED
- **app/risk:** 6 KEEP
- **app/data:** 9 KEEP
- **app/signals:** 4 KEEP
- **app/filters:** 9 KEEP, 2 DELETED
- **app/mtf:** 7 KEEP
- **app/validation:** 7 KEEP, 1 FIXED
- **app/notifications:** 2 KEEP
- **app/ml:** 6 KEEP, 3 MOVED
- **app/analytics:** 10 KEEP
- **app/ai:** 2 KEEP
- **app/backtesting:** 7 KEEP
- **app/screening:** 8 KEEP
- **app/options:** 8 KEEP
- **app/indicators:** 5 KEEP
- **utils/:** 4 KEEP
- **tests/:** 9 KEEP
- **migrations/:** 4 KEEP
- **models/:** 3 KEEP (untrack from Git pending)
- **scripts/ (all):** 55 KEEP (net), 1 QUARANTINE pending, 1 REVIEW pending
- **docs/:** All KEEP
- **Root files:** All KEEP / noted

**Total actions to date: 3 DELETED, 4 MOVED, 1 FIXED, 4 shims confirmed, 2 open REVIEW flags, 3 LOCAL ACTIONS pending.**

---

*Updated: Session 8, 2026-03-17. All batches complete. Registry fully current.*
