# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all 336 tracked files.  
> **Last updated:** 2026-03-16  
> **Auditor:** Perplexity AI (interactive audit with Michael)  
> **Status legend:** ✅ KEEP | ⚠️ REVIEW | 🔀 MERGE → target | 🗃️ QUARANTINE | ❌ DELETE  
> **Prohibited (runtime-critical) directories:** `app/core`, `app/data`, `app/risk`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`, `utils/`, `migrations/`  
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`  
> **Healthcheck:** `/health` on port 8080  

---

## Progress Tracker

| Batch | Directory Scope | Files | Status |
|-------|----------------|-------|--------|
| A1 | `app/core` | 15 | 🔄 In progress |
| A2 | `app/risk`, `app/data`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications` | ~45 | ⏳ Pending |
| B | `app/ml`, `app/analytics`, `app/ai`, `models/`, `results/` | ~25 | ⏳ Pending |
| C | `app/backtesting`, `scripts/` (all subfolders) | ~55 | ⏳ Pending |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | ~25 | ⏳ Pending |
| E | `tests/`, `docs/`, `audit_reports/`, `backups/`, `migrations/`, root files | ~50 | ⏳ Pending |
| Cross-Batch | Overlap analysis across all batches | 336 total | ⏳ Pending |

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

> **Rule:** Every file here is loaded at startup via `python -m app.core.scanner`. Treat as PROHIBITED unless explicitly confirmed redundant.

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers of `app.core` | ✅ KEEP | Minimal, required |
| `__main__.py` | 177 B | Railway entrypoint shim | Railway start command | ✅ KEEP | Required for `python -m app.core` |
| `scanner.py` | 42 KB | Main scan loop orchestrator | Entrypoint — never touch | ✅ KEEP | **PROHIBITED** — primary runtime brain |
| `sniper.py` | 55 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** — still large; Phase 6 trim pending |
| `arm_signal.py` | 7 KB | Signal arming logic extracted from sniper | `sniper.py` | ✅ KEEP | Extracted Phase 5 refactor |
| `armed_signal_store.py` | 8 KB | Thread-safe store for armed signals | `sniper.py`, `scanner.py` | ✅ KEEP | Pairs with `watch_signal_store.py` — distinct roles |
| `watch_signal_store.py` | 7.6 KB | Store for watching (pre-armed) signals | `sniper.py`, `scanner.py` | ✅ KEEP | Distinct from `armed_signal_store.py` — no overlap |
| `confidence_model.py` | 976 B | Confidence score calculator | `sniper.py` | ✅ KEEP | Small but live; extracted from sniper |
| `gate_stats.py` | 5.8 KB | Gate pass/fail statistics tracker | `sniper.py`, `scanner.py` | ✅ KEEP | Extracted Phase 5 refactor |
| `sniper_log.py` | 4.1 KB | Structured logging for sniper events | `sniper.py` | ✅ KEEP | Extracted Phase 5; also holds validator_stats functions |
| `thread_safe_state.py` | 10.8 KB | Shared mutable state with lock guards | `scanner.py`, `sniper.py` | ✅ KEEP | Critical for thread safety; Fix #1 subject |
| `analytics_integration.py` | 9.2 KB | Bridge between core and analytics layer | `scanner.py` | ✅ KEEP | Previously broken (src import), now stub-fixed |
| `eod_reporter.py` | 3.8 KB | End-of-day Discord summary report | `scanner.py` (cron) | ✅ KEEP | Runs after market close |
| `error_recovery.py` | 17.2 KB | Exception handling + auto-restart logic | `scanner.py` | ✅ KEEP | Large but singular purpose; no duplicate found |
| `health_server.py` | 4.5 KB | HTTP `/health` endpoint for Railway | Railway healthcheck | ✅ KEEP | **PROHIBITED** — required for Railway ON_FAILURE restart |

**Batch A1 result: 15/15 files KEEP. Zero overlaps. Zero quarantine candidates.**

---

## BATCH A2 — Supporting Runtime Modules

> Pending — covers: `app/risk/`, `app/data/`, `app/signals/`, `app/validation/`, `app/filters/`, `app/mtf/`, `app/notifications/`

### `app/notifications/` (1 file)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | — | Package marker | — | ✅ KEEP | — |
| `discord_helpers.py` | — | Discord send functions | `scanner.py`, `sniper.py`, `eod_reporter.py` | ✅ KEEP | **CROSS-BATCH FLAG:** `app/discord_helpers.py` (root-level) and `app/discord_helpers_backup.py` are potential duplicates — review in Batch E |

### `app/risk/` (5 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `risk_manager.py` | Core position risk enforcement | ✅ KEEP | PROHIBITED |
| `position_manager.py` | Tracks open positions | ✅ KEEP | PROHIBITED |
| `trade_calculator.py` | Size/R:R math | ✅ KEEP | — |
| `dynamic_thresholds.py` | Adaptive stop/target thresholds | ✅ KEEP | — |
| `vix_sizing.py` | VIX-adjusted position sizing | ✅ KEEP | See `docs/VIX_SIZING_INTEGRATION.md` |

### `app/data/` (8 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `database.py` | High-level DB query interface | ✅ KEEP | PROHIBITED |
| `db_connection.py` | PostgreSQL connection pool | ✅ KEEP | PROHIBITED — Fix #6 semaphore subject |
| `data_manager.py` | Data fetch orchestration | ✅ KEEP | — |
| `candle_cache.py` | In-memory candle caching | ✅ KEEP | — |
| `sql_safe.py` | SQL injection protection helpers | ✅ KEEP | — |
| `unusual_options.py` | Unusual Whales options data fetch | ✅ KEEP | — |
| `ws_feed.py` | WebSocket live price feed | ✅ KEEP | PROHIBITED |
| `ws_feed.py.backup` | Stale backup of ws_feed.py | 🗃️ QUARANTINE | Not a .py module — dead file in tracked tree. Move to `backups/` |
| `ws_quote_feed.py` | Quote-specific WebSocket feed | ⚠️ REVIEW | Clarify if distinct from `ws_feed.py` or superseded |

### `app/signals/` (5 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `breakout_detector.py` | Breakout signal detection | ✅ KEEP | PROHIBITED |
| `opening_range.py` | ORB/opening range detection | ✅ KEEP | PROHIBITED |
| `vwap_reclaim.py` | VWAP reclaim signal | ✅ KEEP | — |
| `signal_analytics.py` | Signal outcome tracking | ✅ KEEP | — |
| `earnings_eve_monitor.py` | Earnings-eve signal filter | ✅ KEEP | — |

### `app/filters/` (9 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `rth_filter.py` | Regular trading hours gate | ✅ KEEP | — |
| `vwap_gate.py` | VWAP-based entry gate | ✅ KEEP | — |
| `market_regime_context.py` | Regime detection (trend/chop) | ✅ KEEP | SPY EMA visual-only per architecture decision |
| `early_session_disqualifier.py` | Blocks signals in first N mins | ✅ KEEP | — |
| `entry_timing_optimizer.py` | Optimal entry timing logic | ✅ KEEP | — |
| `liquidity_sweep.py` | Detects liquidity sweeps | ✅ KEEP | — |
| `options_dte_filter.py` | DTE-based options filter | ✅ KEEP | — |
| `order_block_cache.py` | Caches order block zones | ✅ KEEP | — |
| `sd_zone_confluence.py` | Supply/demand zone confluence | ✅ KEEP | — |
| `correlation.py` | Inter-ticker correlation filter | ✅ KEEP | — |

### `app/mtf/` (5 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `bos_fvg_engine.py` | BOS+FVG detection engine | ✅ KEEP | PROHIBITED — core strategy |
| `mtf_validator.py` | Multi-timeframe validation | ✅ KEEP | PROHIBITED |
| `mtf_integration.py` | Wires MTF into scanner | ✅ KEEP | — |
| `mtf_compression.py` | Timeframe compression logic | ✅ KEEP | — |
| `mtf_fvg_priority.py` | FVG priority scoring | ✅ KEEP | — |

### `app/validation/` (6 files + `__init__.py`)
| File | Role | Verdict | Notes |
|------|------|---------|-------|
| `__init__.py` | Package marker | ✅ KEEP | — |
| `validation.py` | Main validation orchestrator | ✅ KEEP | PROHIBITED |
| `cfw6_gate_validator.py` | CFW6 gate check | ✅ KEEP | PROHIBITED — core gate |
| `cfw6_confirmation.py` | CFW6 confirmation logic | ✅ KEEP | — |
| `greeks_precheck.py` | Options Greeks pre-validation | ✅ KEEP | — |
| `hourly_gate.py` | Hourly trade frequency gate | ✅ KEEP | — |
| `entry_timing.py` | Entry timing validation | ⚠️ REVIEW | **CROSS-BATCH FLAG:** possible overlap with `app/filters/entry_timing_optimizer.py` — review in cross-batch pass |
| `volume_profile.py` | Volume profile validation | ⚠️ REVIEW | **CROSS-BATCH FLAG:** `app/indicators/volume_profile.py` exists — possible overlap |

---

## BATCH B — ML, Analytics, AI, Models

> Pending — covers: `app/ml/`, `app/analytics/`, `app/ai/`, `models/`, `results/backtests/`

### Key flags to resolve:
- `app/ml/ml_signal_scorer.py` vs `app/ml/ml_signal_scorer_v2.py` — likely v1 superseded
- `app/analytics/explosive_mover_tracker.py` vs `app/analytics/explosive_tracker.py` — likely duplicate
- `app/analytics/ab_test_framework.py` vs `app/analytics/ab_test.py` — likely one supersedes the other
- `app/analytics/funnel_analytics.py` vs `app/analytics/funnel_tracker.py` — likely duplicate
- `models/ml_model_historical.pkl` vs `models/signal_predictor.pkl` — verify which is loaded at runtime

---

## BATCH C — Backtesting & Scripts

> Pending — covers: `app/backtesting/`, `scripts/backtesting/` (20 scripts), `scripts/analysis/`, `scripts/optimization/`, `scripts/database/`, `scripts/maintenance/`, `scripts/powershell/`, root-level scripts

### Key flags to resolve:
- `app/backtesting/backtest_engine.py` vs 20 scripts in `scripts/backtesting/` — are any scripts now superseded by the engine?
- `scripts/backtesting/backtest_comprehensive.py` vs `backtest_enhanced_filters.py` vs `backtest_optimized_params.py` vs `unified_production_backtest.py` — likely 1-2 are current, rest are experiments
- `scripts/war_machine.db` vs root `war_machine.db` — is one of these stale?

---

## BATCH D — Screening, Options, Indicators, Utils

> Pending — covers: `app/screening/`, `app/options/`, `app/indicators/`, `utils/`

### Key flags to resolve:
- `app/indicators/technical_indicators.py` vs `app/indicators/technical_indicators_extended.py` — likely extended supersedes base or they're additive
- `app/options/options_data_manager.py` vs `app/data/data_manager.py` — check for scope overlap
- `app/enhancements/signal_boosters.py` — only 1 file in folder; check if it should be in `app/ml/` or `app/signals/`

---

## BATCH E — Tests, Docs, Backups, Root Files

> Pending — covers: `tests/`, `docs/`, `audit_reports/`, `backups/cleanup_backup_20260309_105038/`, `migrations/`, root files

### Known quarantine candidates (pre-identified):
| File | Reason |
|------|--------|
| `app/discord_helpers.py` | Possible duplicate of `app/notifications/discord_helpers.py` |
| `app/discord_helpers_backup.py` | Explicit backup file — quarantine |
| `app/data/ws_feed.py.backup` | Non-module backup — quarantine |
| `audit_repo.py` | One-time audit script — quarantine after confirming not scheduled |
| `backups/cleanup_backup_20260309_105038/sniper_backup_20260306_232502.py` | Old sniper backup — quarantine |
| `backups/cleanup_backup_20260309_105038/sniper_backup_20260306_232640.py` | Old sniper backup — quarantine |
| `backups/cleanup_backup_20260309_105038/breakout_detector.py` | Root-level copy — quarantine |
| `backups/cleanup_backup_20260309_105038/MIGRATION_SCRIPT_FIX_1.py` | One-time migration — quarantine |
| All `backups/cleanup_backup_20260309_105038/docs/*.md` | Historical completion notes — quarantine entire folder |
| All `docs/history/*.md` and `*.txt` | Phase completion notes — consider consolidating into 1 CHANGELOG |
| `audit_reports/` (all 10 files) | Generated by `audit_repo.py` — quarantine after confirming no live references |
| `war_machine_architecture_doc.txt` | Plain-text architecture doc — superseded by this registry + `docs/README.md` |
| `.railway_trigger` | Intentional deploy trigger file — KEEP |
| `market_memory.db` | SQLite DB at root — verify if used or replaced by PostgreSQL |
| `scripts/war_machine.db` | SQLite DB in scripts/ — verify if used or stale |

---

## Cross-Batch Overlap Flags (Running List)

These will be resolved after all batches complete:

| Flag | File A | File B | Likely Resolution |
|------|--------|--------|-------------------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | A is legacy root copy; B is canonical — quarantine A |
| Volume profile | `app/validation/volume_profile.py` | `app/indicators/volume_profile.py` | Check if one validates and one calculates — may both be needed |
| Entry timing | `app/validation/entry_timing.py` | `app/filters/entry_timing_optimizer.py` | Check for functional overlap |
| Explosive tracker | `app/analytics/explosive_mover_tracker.py` | `app/analytics/explosive_tracker.py` | Likely one supersedes — check imports |
| AB test | `app/analytics/ab_test.py` | `app/analytics/ab_test_framework.py` | Check if framework wraps test or is replacement |
| Funnel | `app/analytics/funnel_analytics.py` | `app/analytics/funnel_tracker.py` | Check which is imported by scanner |
| ML scorer | `app/ml/ml_signal_scorer.py` | `app/ml/ml_signal_scorer_v2.py` | v1 likely superseded — verify imports |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | Check if both are referenced or one is stale |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | Check if both are active or one supersedes |
| Backtest scripts | `scripts/backtesting/*.py` (20 files) | `app/backtesting/backtest_engine.py` | Scripts may be standalone experiments vs. engine is prod module |

---

## Files Cleared (No Action Needed)

All 15 files in `app/core` — confirmed zero overlaps, all KEEP.

---

*This file is updated progressively. Do not delete. Reference before any file move, merge, or quarantine.*
