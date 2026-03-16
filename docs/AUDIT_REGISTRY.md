# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all 336 tracked files.  
> **Last updated:** 2026-03-16  
> **Auditor:** Perplexity AI (interactive audit with Michael)  
> **Status legend:** ✅ KEEP | ⚠️ REVIEW | 🔀 MERGE → target | 🗃️ QUARANTINE | ❌ DELETE | 🔧 FIXED  
> **Prohibited (runtime-critical) directories:** `app/core`, `app/data`, `app/risk`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`, `utils/`, `migrations/`  
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`  
> **Healthcheck:** `/health` on port 8080  

---

## Progress Tracker

| Batch | Directory Scope | Files | Status |
|-------|----------------|-------|--------|
| A1 | `app/core` | 15 | ✅ Complete |
| A2 | `app/risk`, `app/data`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications` | 44 | ✅ Complete |
| B | `app/ml`, `app/analytics`, `app/ai`, `models/`, `results/` | ~25 | ⏳ Pending |
| C | `app/backtesting`, `scripts/` (all subfolders) | ~55 | ⏳ Pending |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | ~25 | ⏳ Pending |
| E | `tests/`, `docs/`, `audit_reports/`, `backups/`, `migrations/`, root files | ~50 | ⏳ Pending |
| Cross-Batch | Overlap analysis across all batches | 336 total | ⏳ Pending |

---

## Implemented Changes Log

> All changes applied to `main` branch. Each entry includes commit SHA, date, and impact.

| # | Date | File | Change | Commit SHA | Impact |
|---|------|------|--------|-----------|--------|
| 1 | 2026-03-16 | `app/validation/cfw6_confirmation.py` | 🔧 FIXED: Removed `calculate_vwap()` (used `close` price only — wrong formula) and `check_vwap_alignment()`. Replaced with `passes_vwap_gate()` + `compute_vwap()` imported from `app.filters.vwap_gate` (correct `(H+L+C)/3` typical price formula). Added `vwap_reason` logging to CONFIRM output. | `95be3ae` | **Live bug fix** — VWAP alignment gate now uses mathematically correct formula. Grade outcomes near VWAP boundary may shift. Zero external callers of removed functions confirmed via repo-wide search. |

---

## Pending Actions Queue

> Ordered by priority. Work through top-to-bottom.

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1 | ✅ DONE | `app/validation/cfw6_confirmation.py` | Fix wrong VWAP formula | ✅ Committed `95be3ae` |
| 2 | 🔴 BUG | `app/core/confidence_model.py` | Grep callers → update to `app.ai.ai_learning` → DELETE (superseded) | ⏳ Next |
| 3 | 🔴 HIGH | `app/discord_helpers.py` | Grep all imports → update to `app.notifications.discord_helpers` → DELETE | ⏳ Pending |
| 4 | 🔴 HIGH | `app/ml/check_database.py` | Move to `scripts/database/` or DELETE (diagnostic one-off) | ⏳ Pending |
| 5 | 🟡 MEDIUM | `app/core/watch_signal_store.py` | Fix 1 import: `app.discord_helpers` → `app.notifications.discord_helpers` | ⏳ Pending |
| 6 | 🟡 MEDIUM | `app/signals/signal_analytics.py` | Confirm `train_from_analytics.py` target table → likely DELETE (superseded by `funnel_analytics.py`) | ⏳ Pending |
| 7 | 🟡 MEDIUM | `app/filters/entry_timing_optimizer.py` | Wire `record_trade()` output to `EntryTimingValidator` to replace hardcoded `HOURLY_WIN_RATES` | ⏳ Pending |
| 8 | 🟡 MEDIUM | `app/ml/train_ml_booster.py` | Confirm if `MLConfidenceBooster` still wired to live signals → if not, archive to `scripts/` | ⏳ Pending |
| 9 | 🟢 LOW | `app/ai/ai_learning.py` | Fix `import db_connection` → `from app.data import db_connection` | ⏳ Pending |
| 10 | 🟢 LOW | `tests/test_task9_*.py`, `test_task10_*.py`, `test_task12.py` | Rename to descriptive names | ⏳ Pending |

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
| `watch_signal_store.py` | 7.6 KB | Store for watching (pre-armed) signals | `sniper.py`, `scanner.py` | ✅ KEEP | **ACTION PENDING #5:** fix 1 import `app.discord_helpers` → `app.notifications.discord_helpers` |
| `confidence_model.py` | 976 B | Confidence score calculator | `sniper.py` | ⚠️ REVIEW | **ACTION PENDING #2:** Superseded by `app.ai.ai_learning.compute_confidence()` which correctly uses timeframe multipliers. Grep callers → update → DELETE. |
| `gate_stats.py` | 5.8 KB | Gate pass/fail statistics tracker | `sniper.py`, `scanner.py` | ✅ KEEP | Extracted Phase 5 refactor |
| `sniper_log.py` | 4.1 KB | Structured logging for sniper events | `sniper.py` | ✅ KEEP | Extracted Phase 5; also holds validator_stats functions |
| `thread_safe_state.py` | 10.8 KB | Shared mutable state with lock guards | `scanner.py`, `sniper.py` | ✅ KEEP | Critical for thread safety; Fix #1 subject |
| `analytics_integration.py` | 9.2 KB | Bridge between core and analytics layer | `scanner.py` | ✅ KEEP | Previously broken (src import), now stub-fixed |
| `eod_reporter.py` | 3.8 KB | End-of-day Discord summary report | `scanner.py` (cron) | ✅ KEEP | Runs after market close |
| `error_recovery.py` | 17.2 KB | Exception handling + auto-restart logic | `scanner.py` | ✅ KEEP | Large but singular purpose; no duplicate found |
| `health_server.py` | 4.5 KB | HTTP `/health` endpoint for Railway | Railway healthcheck | ✅ KEEP | **PROHIBITED** — required for Railway ON_FAILURE restart |

**Batch A1 result: 13/15 files confirmed KEEP. 1 REVIEW (confidence_model.py), 1 ACTION PENDING (watch_signal_store.py import fix).**

---

## BATCH A2 — Supporting Runtime Modules

> **Completed 2026-03-16.** All files in `app/risk/`, `app/data/`, `app/signals/`, `app/validation/`, `app/filters/`, `app/mtf/`, `app/notifications/` fully read and verified.

### `app/notifications/` — 2 files (1 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 1.1 KB | Package marker + re-exports | All consumers of notifications | ✅ KEEP | Substantive `__init__` — re-exports key send functions |
| `discord_helpers.py` | 23.7 KB | All Discord webhook/embed send functions | `scanner.py`, `sniper.py`, `eod_reporter.py`, `analytics_integration.py` | ✅ KEEP | **CANONICAL copy.** `app/discord_helpers.py` (root-level, 27k SHA confirmed) is a legacy duplicate — see Cross-Batch Flags |

---

### `app/risk/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 29 B | Package marker | All importers of `app.risk` | ✅ KEEP | Minimal, required |
| `risk_manager.py` | 13.3 KB | Core position risk enforcement — max loss, daily loss, heat checks | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** — active risk gate |
| `position_manager.py` | 51.9 KB | Tracks open/closed positions, P&L, lifecycle | `scanner.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** — largest file in risk; no duplicate |
| `trade_calculator.py` | 12.1 KB | Contract sizing, R:R math, max-risk-per-trade | `sniper.py`, `risk_manager.py` | ✅ KEEP | Pure math module; no overlap |
| `dynamic_thresholds.py` | 6.9 KB | Adapts stop/target thresholds based on ATR/vol | `sniper.py` | ✅ KEEP | Distinct from `vix_sizing.py` (VIX focuses on position size, this focuses on threshold levels) |
| `vix_sizing.py` | 10.2 KB | VIX-adjusted position sizing multiplier | `trade_calculator.py`, `risk_manager.py` | ✅ KEEP | See `docs/VIX_SIZING_INTEGRATION.md`; no overlap with `dynamic_thresholds.py` |

**app/risk result: 6/6 KEEP. No overlaps. `dynamic_thresholds.py` and `vix_sizing.py` are complementary (thresholds vs size), not duplicates.**

---

### `app/data/` — 9 files (8 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 30 B | Package marker | All importers of `app.data` | ✅ KEEP | Minimal, required |
| `database.py` | 1.1 KB | High-level DB query convenience wrapper | `scanner.py`, scripts | ✅ KEEP | **PROHIBITED** — thin wrapper over `db_connection.py`; intentionally separate |
| `db_connection.py` | 18.8 KB | PostgreSQL connection pool + all schema ops | `data_manager.py`, `database.py` | ✅ KEEP | **PROHIBITED** — Fix #6 semaphore subject; NOT a duplicate of `database.py` (different layers) |
| `data_manager.py` | 44.2 KB | All bar fetch, store, backfill, intraday ops | `scanner.py`, `ws_feed.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** — largest data file; no duplicate |
| `candle_cache.py` | 19.9 KB | In-memory OHLCV caching layer with TTL | `scanner.py`, `data_manager.py` | ✅ KEEP | Reduces DB round-trips; no overlap |
| `sql_safe.py` | 13.0 KB | SQL injection-safe query builders | `db_connection.py`, `data_manager.py` | ✅ KEEP | Security utility; standalone |
| `unusual_options.py` | 15.8 KB | Fetches unusual options flow from Unusual Whales API | `scanner.py`, `sniper.py` | ✅ KEEP | Sole file touching UW API; no overlap |
| `ws_feed.py` | 23.4 KB | EODHD WebSocket — live trade tick → 1m OHLCV bar builder. Connects to `wss://ws.eodhistoricaldata.com/ws/us`. Includes REST failover | `scanner.py` (startup), `sniper.py` (bar reads) | ✅ KEEP | **PROHIBITED — NOT a duplicate of `ws_quote_feed.py`** — handles trade ticks, not bid/ask quotes. Two different EODHD WebSocket endpoints |
| `ws_quote_feed.py` | 16.7 KB | EODHD WebSocket — live bid/ask quote → spread tracking. Connects to `wss://ws.eodhistoricaldata.com/ws/us-quote`. Provides `is_spread_acceptable()` entry gate | `sniper.py` (spread gate before entry), `analytics`, `target_discovery` | ✅ KEEP | **CONFIRMED DISTINCT from `ws_feed.py`.** Different endpoint (`/ws/us-quote` vs `/ws/us`), different data (quotes vs trades), different consumer API. Both must run simultaneously. Zero overlap. |

**app/data result: 9/9 KEEP. `ws_feed.py` vs `ws_quote_feed.py` overlap RESOLVED — they are complementary, not duplicates (trade bars vs bid/ask spread). `database.py` vs `db_connection.py` overlap RESOLVED — intentional layering.**

---

### `app/signals/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 32 B | Package marker | All importers of `app.signals` | ✅ KEEP | Minimal, required |
| `breakout_detector.py` | 32.4 KB | Breakout signal detection (volume, price level) | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** — core signal generator |
| `opening_range.py` | 35.1 KB | ORB / opening range breakout detection | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** — distinct from `breakout_detector.py` (ORB is time-bounded, breakout is general) |
| `vwap_reclaim.py` | 3.6 KB | VWAP reclaim signal (price reclaims VWAP after dip) | `sniper.py` | ✅ KEEP | Separate signal type; no overlap with `app/filters/vwap_gate.py` (gate blocks, this detects) |
| `signal_analytics.py` | 23.6 KB | Signal outcome tracking, win rate, performance metrics | `scanner.py` (EOD), `analytics_integration.py` | ⚠️ REVIEW | **ACTION PENDING #6:** Confirm which table `train_from_analytics.py` reads — if `signal_analytics`, this file may be superseded by `funnel_analytics.py` |
| `earnings_eve_monitor.py` | 7.7 KB | Detects and filters signals when earnings announced next day | `sniper.py` (pre-entry gate) | ✅ KEEP | Standalone purpose; no overlap |

**app/signals result: 5/6 confirmed KEEP. 1 REVIEW pending (signal_analytics.py).**

---

### `app/filters/` — 11 files (10 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 341 B | Package marker + filter exports | All filter consumers | ✅ KEEP | |
| `rth_filter.py` | 9.9 KB | Regular trading hours gate (9:30–16:00 ET) | `sniper.py`, `scanner.py` | ✅ KEEP | Note: `ws_feed.py` has `ENFORCE_RTH_ONLY` flag but it's `False` by default — `rth_filter.py` is the live enforcement layer |
| `vwap_gate.py` | 1.8 KB | VWAP-based entry gate — **CANONICAL VWAP source** — uses correct `(H+L+C)/3` typical price formula | `sniper.py`, now also `cfw6_confirmation.py` | ✅ KEEP | **CANONICAL.** Now imported by `cfw6_confirmation.py` after VWAP bug fix (commit `95be3ae`). |
| `market_regime_context.py` | 15.0 KB | Market regime classifier (trending/choppy/reversal) using SPY EMA | `sniper.py`, `scanner.py` | ✅ KEEP | SPY EMA used for visual context only per architecture decision |
| `early_session_disqualifier.py` | 3.0 KB | Blocks all signals in first N minutes after open | `sniper.py` | ✅ KEEP | Complements `rth_filter.py` (timing, not hours) |
| `entry_timing_optimizer.py` | 4.8 KB | Scores entry timing quality (bar position, momentum alignment) | `sniper.py` | ✅ KEEP | **ACTION PENDING #7:** Wire `record_trade()` output to `EntryTimingValidator` so hardcoded `HOURLY_WIN_RATES` become dynamic |
| `liquidity_sweep.py` | 3.5 KB | Detects liquidity sweeps (wick below support/above resistance) | `sniper.py` | ✅ KEEP | SMC concept; standalone |
| `options_dte_filter.py` | 5.3 KB | DTE gate — blocks options with DTE outside allowed range | `sniper.py` | ✅ KEEP | Standalone; no duplicate |
| `order_block_cache.py` | 4.0 KB | Caches identified order block zones with TTL | `sniper.py`, `bos_fvg_engine.py` | ✅ KEEP | Cache layer; no duplicate |
| `sd_zone_confluence.py` | 3.9 KB | Supply/demand zone confluence check | `sniper.py` | ✅ KEEP | SMC concept; standalone |
| `correlation.py` | 8.2 KB | Inter-ticker correlation filter (blocks correlated signal stack) | `scanner.py`, `sniper.py` | ✅ KEEP | Risk diversity filter; no overlap |

**app/filters result: 11/11 KEEP. `vwap_gate.py` is now the canonical VWAP implementation used by both `sniper.py` and `cfw6_confirmation.py`.**

---

### `app/mtf/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 325 B | Package marker + MTF exports | All MTF consumers | ✅ KEEP | |
| `bos_fvg_engine.py` | 21.6 KB | BOS (Break of Structure) + FVG (Fair Value Gap) detection | `sniper.py`, `mtf_integration.py` | ✅ KEEP | **PROHIBITED** — core strategy engine |
| `mtf_validator.py` | 4.9 KB | Validates signals have MTF alignment (1m/5m/15m agreement) | `sniper.py` | ✅ KEEP | **PROHIBITED** — gatekeeper for MTF requirement |
| `mtf_integration.py` | 13.3 KB | Wires all MTF modules together; called from scanner pipeline | `scanner.py` | ✅ KEEP | Orchestration layer; no overlap |
| `mtf_compression.py` | 8.3 KB | Compresses 1m bars into 5m/15m/1h synthetic bars | `bos_fvg_engine.py`, `mtf_integration.py` | ✅ KEEP | Core utility for MTF stack; no duplicate |
| `mtf_fvg_priority.py` | 14.5 KB | Scores and ranks FVGs by size, freshness, MTF alignment | `bos_fvg_engine.py`, `sniper.py` | ✅ KEEP | Enhances FVG engine with scoring; distinct from `bos_fvg_engine.py` |

**app/mtf result: 6/6 KEEP. Clean module with clear separation of concerns — detection, validation, wiring, compression, scoring.**

---

### `app/validation/` — 8 files (7 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 1.5 KB | Package marker + validation exports | All validation consumers | ✅ KEEP | Substantive `__init__` |
| `validation.py` | 65.1 KB | Main signal validation orchestrator — calls all gates in sequence | `sniper.py` | ✅ KEEP | **PROHIBITED** — largest file in the repo; single entry point for all validation |
| `cfw6_gate_validator.py` | 15.1 KB | CFW6 gate checks (Confluence For Win 6-factor model) | `validation.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** — core gate logic |
| `cfw6_confirmation.py` | 11.9 KB | CFW6 post-gate confirmation (momentum/bar quality checks after gate passes) | `validation.py` | 🔧 FIXED | **FIXED 2026-03-16 (commit `95be3ae`):** Removed wrong `calculate_vwap()` (close-price-only). Now uses `passes_vwap_gate()` from `app.filters.vwap_gate` (correct `(H+L+C)/3` formula). Added `vwap_reason` to CONFIRM log output. |
| `greeks_precheck.py` | 25.4 KB | Options Greeks pre-validation (delta, theta, IV checks before order) | `sniper.py`, `validation.py` | ✅ KEEP | Standalone Greeks logic; no duplicate |
| `hourly_gate.py` | 5.7 KB | Hourly trade frequency gate (max N trades per hour) | `sniper.py`, `validation.py` | ✅ KEEP | Frequency control; no overlap |
| `entry_timing.py` | 9.3 KB | Entry timing validation (validates bar timing vs session, momentum) | `validation.py` | ⚠️ REVIEW | **ACTION PENDING #7 (related):** vs `app/filters/entry_timing_optimizer.py` — wire dynamic win rates from optimizer into validator's hardcoded `HOURLY_WIN_RATES` |
| `volume_profile.py` | 8.2 KB | Volume profile validation (checks if price is at high-vol node) | `validation.py`, `cfw6_gate_validator.py` | ⚠️ REVIEW | **Cross-batch flag (Batch D):** `app/indicators/volume_profile.py` — add caching to this file; add comment noting relationship |

**app/validation result: 6/8 confirmed KEEP. 1 FIXED (`cfw6_confirmation.py`). 2 REVIEW pending.**

---

## BATCH A2 Summary

| Module | Files | KEEP | FIXED | REVIEW | QUARANTINE/DELETE | Overlaps Found |
|--------|-------|------|-------|--------|--------------------|----------------|
| `app/notifications/` | 2 | 2 | 0 | 0 | 0 | `app/discord_helpers.py` root copy confirmed legacy |
| `app/risk/` | 6 | 6 | 0 | 0 | 0 | None |
| `app/data/` | 9 | 9 | 0 | 0 | 0 | `ws_feed` vs `ws_quote_feed` — **RESOLVED as complementary** |
| `app/signals/` | 6 | 5 | 0 | 1 | 0 | 1 deferred flag (`signal_analytics`) |
| `app/filters/` | 11 | 11 | 0 | 0 | 0 | 1 deferred flag (`entry_timing`) |
| `app/mtf/` | 6 | 6 | 0 | 0 | 0 | None |
| `app/validation/` | 8 | 6 | 1 | 2 | 0 | 2 deferred flags |
| **TOTAL A2** | **48** | **45** | **1** | **3** | **0** | **1 confirmed legacy duplicate** |

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
- `app/validation/volume_profile.py` vs `app/indicators/volume_profile.py` — **priority flag**

---

## BATCH E — Tests, Docs, Backups, Root Files

> Pending — covers: `tests/`, `docs/`, `audit_reports/`, `backups/cleanup_backup_20260309_105038/`, `migrations/`, root files

### Known quarantine candidates (pre-identified):
| File | Reason |
|------|--------|
| `app/discord_helpers.py` | **CONFIRMED** legacy root copy — canonical is `app/notifications/discord_helpers.py`. Quarantine after updating any remaining imports |
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

| Flag | File A | File B | Status | Resolution |
|------|--------|--------|--------|-------------------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | ✅ RESOLVED | A is confirmed legacy root copy; B is canonical. Quarantine A in Batch E (check imports first) |
| ws trade vs quote | `app/data/ws_feed.py` | `app/data/ws_quote_feed.py` | ✅ RESOLVED | Distinct endpoints + distinct data types. Both KEEP. Run simultaneously. |
| db layers | `app/data/database.py` | `app/data/db_connection.py` | ✅ RESOLVED | Intentional layering (query interface vs connection pool). Both KEEP. |
| VWAP formula | `app/validation/cfw6_confirmation.py` (`calculate_vwap`) | `app/filters/vwap_gate.py` (`compute_vwap`) | ✅ FIXED `95be3ae` | Wrong formula removed from confirmation. `vwap_gate.py` is now the single VWAP source. |
| Entry timing | `app/validation/entry_timing.py` | `app/filters/entry_timing_optimizer.py` | ⏳ Pending #7 | Wire dynamic win rates from optimizer into validator |
| Volume profile | `app/validation/volume_profile.py` | `app/indicators/volume_profile.py` | ⏳ Pending Batch D | Add caching to validation version; annotate relationship |
| Explosive tracker | `app/analytics/explosive_mover_tracker.py` | `app/analytics/explosive_tracker.py` | ⏳ Pending Batch B | Likely one supersedes — check imports |
| AB test | `app/analytics/ab_test.py` | `app/analytics/ab_test_framework.py` | ⏳ Pending Batch B | Check if framework wraps test or is replacement |
| Funnel | `app/analytics/funnel_analytics.py` | `app/analytics/funnel_tracker.py` | ⏳ Pending Batch B | Check which is imported by scanner |
| ML scorer | `app/ml/ml_signal_scorer.py` | `app/ml/ml_signal_scorer_v2.py` | ⏳ Pending Batch B | v1 likely superseded — verify imports |
| Confidence model | `app/core/confidence_model.py` | `app/ai/ai_learning.py` (`compute_confidence`) | ⏳ Pending #2 | `confidence_model.py` ignores timeframe param; `ai_learning.py` is correct engine. Grep → update → DELETE |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | ⏳ Pending Batch E | Check if both are referenced or one is stale |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | ⏳ Pending Batch B | Check if both are active or one supersedes |
| Backtest scripts | `scripts/backtesting/*.py` (20 files) | `app/backtesting/backtest_engine.py` | ⏳ Pending Batch C | Scripts likely standalone experiments vs engine is prod module |

---

## Files Cleared (No Action Needed)

- All 15 files in `app/core` — 13 confirmed zero overlaps, all KEEP. 2 pending action items (#2 confidence_model, #5 watch_signal_store import).
- All 48 files in `app/risk`, `app/data`, `app/signals`, `app/filters`, `app/mtf`, `app/validation`, `app/notifications` — 45 confirmed KEEP, 1 FIXED, 3 pending review.

---

*This file is updated progressively after every implemented change. Do not delete. Reference before any file move, merge, or quarantine.*
