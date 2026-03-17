# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all 336 tracked files.  
> **Last updated:** 2026-03-16 Session 5  
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
| S4-S5 | Signal quality metrics deep audit (`signal_analytics`, `performance_monitor`, `performance_alerts`, `arm_signal`, `confidence_model`, `ai_learning`, `eod_reporter`) | 7 | ✅ Complete |
| B | `app/ml`, `app/analytics` (remainder), `app/ai`, `models/`, `results/` | ~18 | ⏳ Pending |
| C | `app/backtesting`, `scripts/` (all subfolders) | ~55 | ⏳ Pending |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | ~25 | ⏳ Pending |
| E | `tests/`, `docs/`, `audit_reports/`, `backups/`, `migrations/`, root files | ~50 | ⏳ Pending |
| Cross-Batch | Overlap analysis across all batches | 333 total | ⏳ Pending |

---

## Implemented Changes Log

> All changes applied to `main` branch. Each entry includes commit SHA, date, and impact.

| # | Date | Session | File | Change | Commit SHA | Impact |
|---|------|---------|------|--------|-----------|--------|
| 1 | 2026-03-16 | S0 | `app/validation/cfw6_confirmation.py` | 🔧 FIXED: Removed `calculate_vwap()` (used `close` price only — wrong formula) and `check_vwap_alignment()`. Replaced with `passes_vwap_gate()` + `compute_vwap()` imported from `app.filters.vwap_gate` (correct `(H+L+C)/3` typical price formula). Added `vwap_reason` logging to CONFIRM output. | `95be3ae` | **Live bug fix** — VWAP alignment gate now uses mathematically correct formula. Grade outcomes near VWAP boundary may shift. Zero external callers of removed functions confirmed via repo-wide search. |
| 2 | 2026-03-16 | S1 | `app/discord_helpers.py` | Converted to re-export shim over `app.notifications.discord_helpers`. Fixed live `send_options_signal_alert` bug. Re-confirmed KEEP in S3 — 10 callers confirmed. | `a629a84` | Live bug fix + legacy compatibility |
| 3 | 2026-03-16 | S1 | `app/ml/check_database.py` | Moved to `scripts/database/check_database.py` + `argparse --db` flag. Original deleted. | `3e4681a` / `aeae51d` | Clean separation of dev tools from app module |
| 4 | 2026-03-16 | S1 | `app/validation/volume_profile.py` | Annotated + 5-min TTL cache added. Module docstring documents intentional separation from `app/indicators/volume_profile.py`. | `cea9180` | Performance improvement + clarity |
| 5 | 2026-03-16 | S2 | `app/data/database.py` | Converted to re-export shim over `db_connection.py`. 2 callers now route through pooled, semaphore-gated production connection manager. | `9cd17f5` | All callers now use production-grade connection pool |
| 6 | 2026-03-16 | S2 | `.gitignore` | Added `models/signal_predictor.pkl` exclusion. | `5828488` | Prevents 34.8 KB binary from being tracked going forward |
| 7 | 2026-03-16 | S3 | `tests/test_task10_backtesting.py` | Renamed → `tests/test_backtesting_extended.py`. Old file deleted. | `dd750bb` / `0454fd4` | Cleaner test discovery |
| 8 | 2026-03-16 | S3 | `tests/test_task12.py` | Renamed → `tests/test_premarket_scanner_v2.py`. Old file deleted. | `dd750bb` / `7944437` | Cleaner test discovery |
| 9 | 2026-03-16 | S4 | `app/core/arm_signal.py` | Wired `record_trade_executed()` after `open_position()` returns `position_id > 0`. TRADED funnel stage now records correctly. | pre-confirmed | `get_funnel_stats()['traded']` now populated |
| 10 | 2026-03-16 | S4 | `app/signals/signal_analytics.py` | Added `get_rejection_breakdown(days)`, `get_hourly_funnel(days)`, `get_discord_eod_summary()`. Extended `get_daily_summary()` with rejection + hourly sections. | pre-confirmed | Full signal quality metrics instrumentation now live |
| 11 | 2026-03-16 | S4 | `app/filters/entry_timing_optimizer.py` | DELETED — exact duplicate of `app/validation/entry_timing.py`. | `d1821d1` | -1 file, 4.8 KB removed |
| 12 | 2026-03-16 | S4 | `app/filters/options_dte_filter.py` | DELETED — superseded by `greeks_precheck.py` on Tradier data. Only yfinance caller in codebase. | `3abfdd5` | -1 file, 5.3 KB removed; yfinance removed from requirements |
| 13 | 2026-03-16 | S4 | `app/core/sniper.py` | Wired `funnel_analytics` calls on all 3 scan paths (OR, secondary range, INTRADAY_BOS). All calls wrapped in `try/except`. | `f5fd87b` | Funnel analytics now fires on every scan type |
| 14 | 2026-03-16 | S4 | `requirements.txt` | Removed `yfinance>=0.2.40` — only caller deleted in item 12. | [this commit] | Faster Railway deploys; no dead package |
| 15 | 2026-03-16 | S5 | `app/core/confidence_model.py` | DELETED — confirmed dead stub (976 B). `compute_confidence()` ignored timeframe param entirely. Zero callers confirmed via repo-wide search. Superseded by `app/ai/ai_learning.py`. | `b99a63a` | -1 file, dead code removed. `ai_learning.py` confirmed as live confidence engine. |

---

## Pending Actions Queue

> Ordered by priority. Work through top-to-bottom.

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1 | ✅ DONE | `app/validation/cfw6_confirmation.py` | Fix wrong VWAP formula | ✅ Committed `95be3ae` |
| 2 | ✅ DONE | `app/core/confidence_model.py` | DELETED — dead stub superseded by `ai_learning.py` | ✅ Committed `b99a63a` |
| 3 | ✅ DONE | `app/discord_helpers.py` | Converted to re-export shim | ✅ Committed `a629a84` |
| 4 | ✅ DONE | `app/ml/check_database.py` | Moved to `scripts/database/check_database.py` | ✅ Committed `3e4681a` |
| 5 | ✅ DONE | `app/core/watch_signal_store.py` | Import fix was part of shim resolution | ✅ Resolved via `a629a84` shim |
| 6 | ✅ DONE | `app/signals/signal_analytics.py` | Confirmed NOT superseded by `funnel_analytics.py` — distinct scopes (per-signal metadata vs funnel-level counts). Both kept. New methods added. | ✅ Confirmed + extended |
| 7 | ✅ DONE | `app/filters/entry_timing_optimizer.py` | DELETED — duplicate of `entry_timing.py` | ✅ Committed `d1821d1` |
| 8 | ✅ DONE | `app/ml/train_ml_booster.py` | Confirmed `MLConfidenceBooster` is wired live to `signal_boosters.py` | ✅ Confirmed KEEP |
| 9 | ✅ DONE | `app/ai/ai_learning.py` | Import fix was part of `database.py` shim resolution | ✅ Resolved via `9cd17f5` shim |
| 10 | ✅ DONE | `tests/test_task9_*.py`, `test_task10_*.py`, `test_task12.py` | Two renamed (task10 + task12). test_task9 rename pending. | ⚠️ Partial — `test_task9_funnel_analytics.py` still pending rename |
| 11 | 🟡 MEDIUM | `app/core/eod_reporter.py` | Confirm `get_discord_eod_summary()` result is sent to Discord via `send_simple_message()` — may only be printing to Railway logs | ⏳ Next |
| 12 | 🟡 MEDIUM | `app/signals/signal_analytics.py` | Wire `get_hourly_funnel()` output into `eod_reporter.py` print/Discord output | ⏳ Next |
| 13 | 🟡 LOW | `tests/test_task9_funnel_analytics.py` | Rename → `tests/test_funnel_analytics.py` | ⏳ Next |
| 14 | 🟡 LOW | `tests/db_diagnostic.py` | Rename or move to `scripts/` — not `test_` prefixed, pytest won't discover it | ⏳ Pending |
| 15 | 🟡 LOW | `tests/dte_selector.py` | Same issue — rename or move to `scripts/` | ⏳ Pending |
| 16 | 🟢 LOW | `models/signal_predictor.pkl` | Run `git rm --cached models/signal_predictor.pkl` to untrack from history | ⏳ Pending |
| 17 | 🟢 LOW | `models/training_dataset.csv` | Run `git rm --cached models/training_dataset.csv` to untrack from history | ⏳ Pending |

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

> **Rule:** Every file here is loaded at startup via `python -m app.core.scanner`. Treat as PROHIBITED unless explicitly confirmed redundant.

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers of `app.core` | ✅ KEEP | Minimal, required |
| `__main__.py` | 177 B | Railway entrypoint shim | Railway start command | ✅ KEEP | Required for `python -m app.core` |
| `scanner.py` | 42 KB | Main scan loop orchestrator | Entrypoint — never touch | ✅ KEEP | **PROHIBITED** — primary runtime brain |
| `sniper.py` | 55 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** — `funnel_analytics` wired on all 3 scan paths (S4) |
| `arm_signal.py` | 7 KB | Signal arming logic extracted from sniper | `sniper.py` | ✅ KEEP | `record_trade_executed()` wired (S4/S5 confirmed) |
| `armed_signal_store.py` | 8 KB | Thread-safe store for armed signals | `sniper.py`, `scanner.py` | ✅ KEEP | Pairs with `watch_signal_store.py` — distinct roles confirmed |
| `watch_signal_store.py` | 7.6 KB | Store for watching (pre-armed) signals | `sniper.py`, `scanner.py` | ✅ KEEP | Import fixed via discord_helpers shim |
| `confidence_model.py` | — | ✅ DELETED (S5) | — | Dead stub — confirmed zero callers. Superseded by `app/ai/ai_learning.py`. Commit `b99a63a`. |
| `gate_stats.py` | 5.8 KB | Gate pass/fail statistics tracker | `sniper.py`, `scanner.py` | ✅ KEEP | Extracted Phase 5 refactor |
| `sniper_log.py` | 4.1 KB | Structured logging for sniper events | `sniper.py` | ✅ KEEP | Extracted Phase 5 |
| `thread_safe_state.py` | 10.8 KB | Shared mutable state with lock guards | `scanner.py`, `sniper.py` | ✅ KEEP | Critical for thread safety |
| `analytics_integration.py` | 9.2 KB | Bridge between core and analytics layer | `scanner.py` | ✅ KEEP | Previously broken (src import), now stub-fixed |
| `eod_reporter.py` | 3.8 KB | End-of-day cleanup + stats printer | `scanner.py` (cron) | ✅ KEEP ⚠️ | Confirmed NOT duplicate of `eod_discord_report.py`. **S5 note:** Verify `get_discord_eod_summary()` is sent to Discord (not just printed). |
| `error_recovery.py` | 17.2 KB | Exception handling + auto-restart logic | `scanner.py` | ✅ KEEP | Large but singular purpose |
| `health_server.py` | 4.5 KB | HTTP `/health` endpoint for Railway | Railway healthcheck | ✅ KEEP | **PROHIBITED** — required for Railway ON_FAILURE restart |

**Batch A1 result: 13/14 active files KEEP. 1 DELETED (`confidence_model.py`, S5). 1 pending verify (`eod_reporter.py` Discord send).**

---

## BATCH A2 — Supporting Runtime Modules

> **Completed 2026-03-16.** All files in `app/risk/`, `app/data/`, `app/signals/`, `app/validation/`, `app/filters/`, `app/mtf/`, `app/notifications/` fully read and verified.

### `app/notifications/` — 2 files (1 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 1.1 KB | Package marker + re-exports | All consumers of notifications | ✅ KEEP | Substantive `__init__` — re-exports key send functions |
| `discord_helpers.py` | 23.7 KB | All Discord webhook/embed send functions | `scanner.py`, `sniper.py`, `eod_reporter.py`, `analytics_integration.py` | ✅ KEEP | **CANONICAL copy.** `app/discord_helpers.py` (root-level) is a shim — see Cross-Batch Flags |

---

### `app/risk/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 29 B | Package marker | All importers of `app.risk` | ✅ KEEP | Minimal, required |
| `risk_manager.py` | 13.3 KB | Core position risk enforcement — max loss, daily loss, heat checks | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** — active risk gate |
| `position_manager.py` | 51.9 KB | Tracks open/closed positions, P&L, lifecycle | `scanner.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** — largest file in risk; no duplicate |
| `trade_calculator.py` | 12.1 KB | Contract sizing, R:R math, max-risk-per-trade | `sniper.py`, `risk_manager.py` | ✅ KEEP | Pure math module; no overlap |
| `dynamic_thresholds.py` | 6.9 KB | Adapts stop/target thresholds based on ATR/vol | `sniper.py` | ✅ KEEP | Distinct from `vix_sizing.py` (thresholds vs size) |
| `vix_sizing.py` | 10.2 KB | VIX-adjusted position sizing multiplier | `trade_calculator.py`, `risk_manager.py` | ✅ KEEP | See `docs/VIX_SIZING_INTEGRATION.md` |

**app/risk result: 6/6 KEEP. No overlaps.**

---

### `app/data/` — 9 files (8 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 30 B | Package marker | All importers of `app.data` | ✅ KEEP | |
| `database.py` | 1.8 KB | Re-export shim over `db_connection.py` | `scanner.py`, scripts | ✅ SHIM (S2) | Converted to shim. Exposes `get_db_connection()`/`close_db_connection()`. 2 callers now route through pool. |
| `db_connection.py` | 18.8 KB | PostgreSQL connection pool + all schema ops | `data_manager.py`, `database.py` | ✅ KEEP | **PROHIBITED** — canonical connection layer |
| `data_manager.py` | 44.2 KB | All bar fetch, store, backfill, intraday ops | `scanner.py`, `ws_feed.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** — largest data file; no duplicate |
| `candle_cache.py` | 19.9 KB | In-memory OHLCV caching layer with TTL | `scanner.py`, `data_manager.py` | ✅ KEEP | |
| `sql_safe.py` | 13.0 KB | SQL injection-safe query builders | `db_connection.py`, `data_manager.py` | ✅ KEEP | |
| `unusual_options.py` | 15.8 KB | Fetches unusual options flow from Unusual Whales API | `scanner.py`, `sniper.py` | ✅ KEEP | |
| `ws_feed.py` | 23.4 KB | EODHD WebSocket — live trade tick → 1m OHLCV bar builder | `scanner.py`, `sniper.py` | ✅ KEEP | **PROHIBITED — NOT a duplicate of `ws_quote_feed.py`** — handles trade ticks, not bid/ask quotes |
| `ws_quote_feed.py` | 16.7 KB | EODHD WebSocket — live bid/ask quote → spread tracking | `sniper.py` (spread gate) | ✅ KEEP | **CONFIRMED DISTINCT.** Different endpoint, different data type. Both must run simultaneously. |

**app/data result: 9/9 KEEP. All overlaps resolved.**

---

### `app/signals/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 32 B | Package marker | All importers of `app.signals` | ✅ KEEP | |
| `breakout_detector.py` | 32.4 KB | Breakout signal detection | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** |
| `opening_range.py` | 35.1 KB | ORB detection | `sniper.py`, `scanner.py` | ✅ KEEP | **PROHIBITED** |
| `vwap_reclaim.py` | 3.6 KB | VWAP reclaim signal | `sniper.py` | ✅ KEEP | |
| `signal_analytics.py` | 23.6 KB | Signal outcome tracking + quality metrics | `scanner.py`, `analytics_integration.py` | ✅ KEEP (S4/S5) | **Confirmed NOT superseded by `funnel_analytics.py`** — distinct scopes. `get_rejection_breakdown()`, `get_hourly_funnel()`, `get_discord_eod_summary()` added. TRADED stage now records. |
| `earnings_eve_monitor.py` | 7.7 KB | Earnings eve filter | `sniper.py` | ✅ KEEP | |

**app/signals result: 6/6 KEEP. `signal_analytics.py` fully confirmed and extended (S4/S5).**

---

### `app/filters/` — 9 files (was 11)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 341 B | Package marker + filter exports | All filter consumers | ✅ KEEP | |
| `rth_filter.py` | 9.9 KB | Regular trading hours gate | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `vwap_gate.py` | 1.8 KB | VWAP-based entry gate — **CANONICAL VWAP source** | `sniper.py`, `cfw6_confirmation.py` | ✅ KEEP | `(H+L+C)/3` formula. Now imported by `cfw6_confirmation.py` after VWAP bug fix. |
| `market_regime_context.py` | 15.0 KB | Market regime classifier | `sniper.py`, `scanner.py` | ✅ KEEP | |
| `early_session_disqualifier.py` | 3.0 KB | Blocks signals in first N minutes after open | `sniper.py` | ✅ KEEP | |
| `entry_timing_optimizer.py` | — | ✅ DELETED (S4) | — | Exact duplicate of `entry_timing.py`. Commit `d1821d1`. |
| `liquidity_sweep.py` | 3.5 KB | Liquidity sweep detection | `sniper.py` | ✅ KEEP | |
| `options_dte_filter.py` | — | ✅ DELETED (S4) | — | Superseded by `greeks_precheck.py`. Commit `3abfdd5`. |
| `order_block_cache.py` | 4.0 KB | Caches order block zones | `sniper.py`, `bos_fvg_engine.py` | ✅ KEEP | |
| `sd_zone_confluence.py` | 3.9 KB | Supply/demand zone confluence check | `sniper.py` | ✅ KEEP | |
| `correlation.py` | 8.2 KB | Inter-ticker correlation filter | `scanner.py`, `sniper.py` | ✅ KEEP | |

**app/filters result: 9/9 active files KEEP. 2 DELETED (S4).**

---

### `app/mtf/` — 6 files (5 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 325 B | Package marker + MTF exports | All MTF consumers | ✅ KEEP | |
| `bos_fvg_engine.py` | 21.6 KB | BOS + FVG detection | `sniper.py`, `mtf_integration.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_validator.py` | 4.9 KB | MTF alignment validation | `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `mtf_integration.py` | 13.3 KB | Wires all MTF modules | `scanner.py` | ✅ KEEP | |
| `mtf_compression.py` | 8.3 KB | 1m → 5m/15m/1h bar compression | `bos_fvg_engine.py`, `mtf_integration.py` | ✅ KEEP | |
| `mtf_fvg_priority.py` | 14.5 KB | FVG scoring and ranking | `bos_fvg_engine.py`, `sniper.py` | ✅ KEEP | |

**app/mtf result: 6/6 KEEP. Clean module.**

---

### `app/validation/` — 8 files (7 real + `__init__.py`)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 1.5 KB | Package marker + validation exports | All validation consumers | ✅ KEEP | |
| `validation.py` | 65.1 KB | Main signal validation orchestrator | `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_gate_validator.py` | 15.1 KB | CFW6 gate checks | `validation.py`, `sniper.py` | ✅ KEEP | **PROHIBITED** |
| `cfw6_confirmation.py` | 11.9 KB | CFW6 post-gate confirmation | `validation.py` | 🔧 FIXED (S0) | VWAP formula corrected. Commit `95be3ae`. |
| `greeks_precheck.py` | 25.4 KB | Options Greeks pre-validation via Tradier | `sniper.py`, `validation.py` | ✅ KEEP — canonical | Supersedes deleted `options_dte_filter.py`. |
| `hourly_gate.py` | 5.7 KB | Hourly trade frequency gate | `sniper.py`, `validation.py` | ✅ KEEP | |
| `entry_timing.py` | 9.3 KB | Entry timing validation | `validation.py` | ✅ KEEP — canonical | `entry_timing_optimizer.py` was its duplicate — deleted S4. |
| `volume_profile.py` | 8.2 KB | Volume profile validation | `validation.py`, `cfw6_gate_validator.py` | ✅ DONE (S1) | Annotated + TTL cache. Intentionally separate from `app/indicators/volume_profile.py`. |

**app/validation result: 7/7 active files KEEP. 1 FIXED (S0). Entry timing duplicate deleted S4.**

---

## SESSION 5 — Signal Quality Metrics Deep Audit

> **Completed 2026-03-16 ~21:30 EDT.** Covers `signal_analytics.py`, `performance_monitor.py`, `performance_alerts.py`, `arm_signal.py`, `confidence_model.py`, `ai_learning.py`, `eod_reporter.py`.

### Findings Summary

| File | Finding | Resolution | Status |
|------|---------|------------|--------|
| `app/core/arm_signal.py` | `record_trade_executed()` never called → TRADED stage always 0 | Pre-wired S4, confirmed functional S5 | ✅ DONE |
| `app/signals/signal_analytics.py` | Missing `get_rejection_breakdown()`, `get_hourly_funnel()`, Discord summary | All 3 added S4, confirmed live S5 | ✅ DONE |
| `app/core/confidence_model.py` | Dead 976 B stub, zero callers, ignores timeframe | DELETED (commit `b99a63a`) | ✅ DONE |
| `app/ai/ai_learning.py` | Was marked ⚠️ REVIEW — confirmed live confidence engine | Verdict updated → ✅ KEEP | ✅ CLEARED |
| `app/analytics/performance_monitor.py` | Was marked ⚠️ REVIEW vs `performance_alerts.py` | Confirmed distinct: monitor = metrics, alerts = Discord notifications | ✅ CLEARED |
| `app/analytics/performance_alerts.py` | See above | See above | ✅ CLEARED |
| `app/core/eod_reporter.py` | `get_discord_eod_summary()` exists but Discord send not confirmed | Pending verification | ⚠️ Partial |

### Remaining S5 Gaps (Not Yet Fixed)

| Gap | File | Description | Priority |
|-----|------|-------------|----------|
| Stage chain on restart | `signal_analytics.py` | Session cache cleared on Railway restart → GENERATED event missing → `record_signal_armed()` silently fails | 🟡 LOW |
| Hourly funnel not wired to EOD output | `eod_reporter.py` | `get_hourly_funnel()` available but not printed/sent | 🟡 MEDIUM |
| Discord send not confirmed | `eod_reporter.py` | `get_discord_eod_summary()` may only print to logs | 🟡 MEDIUM |

---

## BATCH B — ML, Analytics (remainder), AI, Models

> Pending — covers: `app/ml/` (8 files), `app/analytics/` (remaining files), `app/ai/ai_learning.py` (confirmed KEEP, S5), `models/`, `results/backtests/`

### Key flags to resolve:
- `app/ml/ml_signal_scorer.py` vs `app/ml/ml_signal_scorer_v2.py` — likely v1 superseded
- `app/analytics/explosive_mover_tracker.py` vs `app/analytics/explosive_tracker.py` — likely one is a shim
- `app/analytics/ab_test_framework.py` vs `app/analytics/ab_test.py` — likely one is a CI shim
- `app/analytics/funnel_analytics.py` vs `app/analytics/funnel_tracker.py` — likely one is a shim
- `models/ml_model_historical.pkl` vs `models/signal_predictor.pkl` — verify which is loaded at runtime

---

## BATCH C — Backtesting & Scripts

> Pending — covers: `app/backtesting/`, `scripts/backtesting/` (20 scripts), `scripts/analysis/`, `scripts/optimization/`, `scripts/database/`, `scripts/maintenance/`, `scripts/powershell/`, root-level scripts

### Key flags to resolve:
- `scripts/war_machine.db` vs root `war_machine.db` — is one stale?
- Backtest scripts: which are current vs experiments?

---

## BATCH D — Screening, Options, Indicators, Utils

> Pending — covers: `app/screening/`, `app/options/`, `app/indicators/`, `utils/`

### Key flags to resolve:
- `app/indicators/technical_indicators.py` vs `app/indicators/technical_indicators_extended.py` — additive vs superseding
- `app/options/options_data_manager.py` vs `app/data/data_manager.py` — check for scope overlap
- `app/validation/volume_profile.py` vs `app/indicators/volume_profile.py` — annotated S1, confirmed distinct
- `app/indicators/vwap_calculator.py` — designate one canonical VWAP source

---

## BATCH E — Tests, Docs, Backups, Root Files

> Pending — covers: `tests/`, `docs/`, `audit_reports/`, `backups/cleanup_backup_20260309_105038/`, `migrations/`, root files

### Known quarantine candidates (pre-identified):
| File | Reason |
|------|--------|
| `app/discord_helpers_backup.py` | Explicit backup file — quarantine |
| `app/data/ws_feed.py.backup` | Non-module backup — quarantine |
| `audit_repo.py` | One-time audit script — quarantine after confirming not scheduled |
| `backups/cleanup_backup_20260309_105038/` | All old backup files — quarantine entire folder |
| All `docs/history/*.md` and `*.txt` | Phase completion notes — consolidate into CHANGELOG |
| `audit_reports/` (all 10 files) | Generated reports — quarantine after confirming no live references |
| `war_machine_architecture_doc.txt` | Plain-text doc — move to `docs/` or supersede with registry |
| `market_memory.db` | SQLite DB at root — verify if used or replaced by PostgreSQL |
| `scripts/war_machine.db` | SQLite DB in scripts/ — verify if used or stale |

---

## Cross-Batch Overlap Flags (Running List)

| Flag | File A | File B | Status | Resolution |
|------|--------|--------|--------|-------------------|
| Discord helpers | `app/discord_helpers.py` | `app/notifications/discord_helpers.py` | ✅ RESOLVED | A is shim; B is canonical. |
| ws trade vs quote | `app/data/ws_feed.py` | `app/data/ws_quote_feed.py` | ✅ RESOLVED | Distinct endpoints + data types. Both KEEP. |
| db layers | `app/data/database.py` | `app/data/db_connection.py` | ✅ RESOLVED | Intentional layering. A is shim. |
| VWAP formula | `app/validation/cfw6_confirmation.py` | `app/filters/vwap_gate.py` | ✅ FIXED `95be3ae` | Wrong formula removed. `vwap_gate.py` is canonical VWAP. |
| Entry timing | `app/validation/entry_timing.py` | `app/filters/entry_timing_optimizer.py` | ✅ RESOLVED | `entry_timing_optimizer.py` DELETED (d1821d1). `entry_timing.py` canonical. |
| DTE filter | `app/filters/options_dte_filter.py` | `app/validation/greeks_precheck.py` | ✅ RESOLVED | `options_dte_filter.py` DELETED (3abfdd5). `greeks_precheck.py` canonical. |
| Confidence engine | `app/core/confidence_model.py` | `app/ai/ai_learning.py` | ✅ RESOLVED (S5) | `confidence_model.py` DELETED (b99a63a). `ai_learning.py` confirmed live engine. |
| Performance metrics | `app/analytics/performance_monitor.py` | `app/analytics/performance_alerts.py` | ✅ RESOLVED (S5) | Distinct roles: monitor = metrics, alerts = Discord notifications. Both KEEP. |
| Volume profile | `app/validation/volume_profile.py` | `app/indicators/volume_profile.py` | ✅ RESOLVED (S1) | Intentionally distinct scopes (20-bin gate vs 50-bin broad). Both annotated. |
| Explosive tracker | `app/analytics/explosive_mover_tracker.py` | `app/analytics/explosive_tracker.py` | ⏳ Pending Batch B | Likely one is shim — check imports |
| AB test | `app/analytics/ab_test.py` | `app/analytics/ab_test_framework.py` | ⏳ Pending Batch B | Likely CI shim vs canonical |
| Funnel | `app/analytics/funnel_analytics.py` | `app/analytics/funnel_tracker.py` | ⏳ Pending Batch B | Likely DB-resilient shim vs canonical |
| ML scorer | `app/ml/ml_signal_scorer.py` | `app/ml/ml_signal_scorer_v2.py` | ⏳ Pending Batch B | v1 likely superseded |
| SQLite DB | `war_machine.db` (root) | `scripts/war_machine.db` | ⏳ Pending Batch E | Check if both are referenced or one is stale |
| EOD report | `app/core/eod_reporter.py` | `app/analytics/eod_discord_report.py` | ✅ RESOLVED (S2) | Different jobs — both keep. |
| signal_analytics vs funnel_analytics | `app/signals/signal_analytics.py` | `app/analytics/funnel_analytics.py` | ✅ RESOLVED (S5) | Distinct scopes: per-signal metadata vs funnel-level counts. Both KEEP. |
| Backtest scripts | `scripts/backtesting/*.py` (20 files) | `app/backtesting/backtest_engine.py` | ⏳ Pending Batch C | Scripts likely standalone experiments vs engine is prod module |

---

## Files Cleared (No Action Needed)

- All 14 active files in `app/core` — 13 KEEP, 1 DELETED (`confidence_model.py`).
- All 48 files in `app/risk`, `app/data`, `app/signals`, `app/filters`, `app/mtf`, `app/validation`, `app/notifications` — 45 confirmed KEEP, 1 FIXED, 3 resolved (2 deleted, 1 annotated).
- 7 files in signal quality metrics deep audit (S5) — 4 KEEP/cleared, 1 DELETED, 2 partial.

---

*This file is updated progressively after every implemented change. Do not delete. Reference before any file move, merge, or quarantine.*  
*Session 5 completed: 2026-03-16 ~21:30 EDT — confidence_model.py deleted, performance_monitor/alerts cleared, signal_analytics confirmed and extended, ai_learning.py confirmed live confidence engine.*
