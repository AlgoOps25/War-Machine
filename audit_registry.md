# War Machine — Master Audit Registry

> **Purpose:** Single source of truth for every file-by-file, line-by-line audit session.
> Every finding, fix, and status change is recorded here chronologically.
> Never delete entries — append only.
>
> **Size rule:** Keep this file under 90 KB. If it approaches that limit, archive
> completed sections to `audit_reports/AUDIT_ARCHIVE_<date>.md` and add a
> reference link here.

---

## Audit Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Clean — no issues found |
| ⚠️ | Finding — non-crashing, style/consistency issue |
| 🐛 | Bug — logic error, data corruption risk, or silent failure |
| 🔴 | Critical — crashing or silent wrong behaviour confirmed |
| 🔧 | Fixed in this session |
| ⬜ | Pending audit |
| 🔁 | Shim/alias file — delegates to another module |

---

## Overall Folder Progress

| Folder | Files | Audited | Status |
|--------|-------|---------|--------|
| `app/` (root) | 1 | 1 | ✅ Complete — Session CORE-1 |
| `app/ai/` | 2 | 0 | ⬜ Pending |
| `app/analytics/` | 9 | 9 | ✅ Complete (prior sessions) |
| `app/backtesting/` | 7 | 0 | ⬜ Pending |
| `app/core/` | 15 | 13 | 🔄 In Progress — CORE-1 (6) + CORE-2 (3) + CORE-3 (2) + ASS-1 + WSS-1 |
| `app/data/` | — | — | ⬜ Pending |
| `app/filters/` | — | — | ⬜ Pending |
| `app/indicators/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 (2026-03-31) |
| `app/mtf/` | — | — | ⬜ Pending |
| `app/notifications/` | — | — | ⬜ Pending |
| `app/options/` | — | — | ⬜ Pending |
| `app/risk/` | — | — | ⬜ Pending |
| `app/screening/` | — | — | ⬜ Pending |
| `app/signals/` | 1 | 1 | 🔄 In Progress — `opening_range.py` audited S-OR-1 |
| `app/validation/` | — | — | ⬜ Pending |
| `audit_reports/` | 1 | — | Reference only |
| `backtests/` | — | — | ⬜ Pending |
| `docs/` | — | — | ⬜ Pending |
| `migrations/` | — | — | ⬜ Pending |
| `scripts/` | — | — | ⬜ Pending |
| `tests/` | — | — | ⬜ Pending |
| `utils/` | — | — | ⬜ Pending |
| Root config files | 8 | 0 | ⬜ Pending |

---

## Session CORE-3 — `app/core/` Pre-Big-Two Files
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Files audited:** 2 files
- `app/core/arm_signal.py`
- `app/core/analytics_integration.py`

**Fixes applied:** None — both files are clean. 0 findings.

---

### `app/core/arm_signal.py`
**SHA:** `d30cd3f500032a6c31493a2a7be646c23710fb54`
**Size:** ~9 KB
**Status:** ✅ Clean

**Purpose:** `arm_ticker()` — the final arming step after all pipeline gates pass.
Opens the position via `position_manager`, fires Discord alert **only** on confirmed
position open (position_id > 0), persists armed signal state to DB and in-memory
state, records TRADED stage in signal analytics, then sets cooldown.

**Architecture:**
- Single top-level function — no class, no module-level state
- ALL heavy imports deferred inside function body (avoids circular import at load time)
- 6 logical stages: stop check → log → open position → analytics → Discord → persist + cooldown
- Dual Discord path: `production_helpers._send_alert_safe()` if available, direct `send_options_signal_alert()` otherwise

**Import strategy confirmed:**
- `import logging` + `logger = logging.getLogger(__name__)` are the ONLY module-level lines (besides the docstring)
- All 6 functional imports (`position_manager`, `get_state`, `_persist_armed_signal`, `get_ticker_screener_metadata`, `send_options_signal_alert`, `log_proposed_trade`) deferred inside function body ✅
- `production_helpers` import wrapped in `try/except ImportError` with `PRODUCTION_HELPERS_ENABLED` bool flag — clean optional dependency ✅
- `signal_tracker.record_trade_executed()` import deferred in its own `try/except Exception` — non-fatal analytics step ✅
- `get_cached_greeks()` import inside inner `try/except` inside the fallback Discord block — non-fatal enrichment ✅
- `set_cooldown()` import deferred in its own `try/except Exception` — non-fatal tail step ✅

**Checks passed:**
- `import logging` + `logger =` at module scope above docstring (BUG-ARM-1 fix confirmed — docstring is correctly assigned to `__doc__`) ✅
- Stop tightness guard: `abs(entry - stop) < entry * 0.001` → `logger.warning` + `return` (falsy) ✅
- `mode_label` ARM log uses `logger.info` — correct (this is success-path, not error-path) ✅
- `log_proposed_trade()` called before position open — audit trail recorded even if open fails ✅
- `metadata = metadata or get_ticker_screener_metadata(ticker)` — caller metadata honoured, fetched only when missing ✅
- `mtf_convergence_count` safely extracted: guards `mtf_result` for `None` then `.get('convergence')` then `len(get('timeframes', []))` — no KeyError ✅
- `position_manager.open_position()` receives all 12 required keyword args — no TypeError ✅
- `position_id == -1` check → `logger.warning` + `return` — risk manager rejection path clean ✅
- Discord production path: all 14 keyword args present including `vp_bias` (FIX P3 confirmed) ✅
- Discord fallback path: `greeks_data` enrichment wrapped in inner `try/except` — non-fatal ✅
- Discord fallback path: all 15 keyword args including `greeks_data` and `vp_bias` (FIX P3 confirmed) ✅
- `armed_signal_data` dict uses key `"validation_data"` (BUG-S16-1 fix confirmed) — DB persistence now correct ✅
- `armed_signal_data` contains all 10 required keys: `position_id`, `direction`, `entry_price`, `stop_price`, `t1`, `t2`, `confidence`, `grade`, `signal_type`, `validation_data` ✅
- `_state.set_armed_signal(ticker, armed_signal_data)` + `_persist_armed_signal()` called in correct order (memory first, then DB) ✅
- `return True` at end of successful path (FIX G confirmed) — callers checking `if armed:` work correctly ✅
- All error paths `return` (None/falsy) implicitly — no accidental `True` on failure paths ✅
- All `logger.warning` on rejection/error paths — correct log level hierarchy ✅
- No stray `print()` calls
- No dead imports

**No findings.**

---

### `app/core/analytics_integration.py`
**SHA:** `3ebfcf2e92dcd16d1466c244c45902e5d66a5e98`
**Size:** ~9.5 KB
**Status:** ✅ Clean

**Purpose:** `AnalyticsIntegration` — thin delegation wrapper over `SignalTracker`
(`app/signals/signal_analytics.py`). The ONLY entry-point used by `scanner.py`.
Proxies all lifecycle calls (generate → validate → arm → trade) through to
`signal_tracker` so there is exactly one source of truth in the `signal_events` table.

**Architecture:**
- Module-level `try/except` import of `signal_tracker` — class degrades to no-op mode if tracker unavailable
- `_TRACKER_AVAILABLE` bool gate on every public method — no crash in no-op mode
- `check_scheduled_tasks()` called once per minute by scanner — handles open/EOD/midnight timing internally
- All methods return `-1` in no-op mode (not `None`) — callers can distinguish unavailable from zero

**Checks passed:**
- `from __future__ import annotations` NOT present — no union types requiring it; `Optional[int]` etc. use `from typing import ...` ✅
- Import order: stdlib (`logging`, `datetime`, `zoneinfo`, `typing`) → no third-party → conditional local (`signal_tracker`) ✅
- `logger = logging.getLogger(__name__)` placed after all imports, before class definition ✅
- BUG-AI-1 fix confirmed: `logger = logging.getLogger(__name__)` used — no bare `logging.warning()` / `logging.info()` module-level calls ✅
- Module-level `_tracker` import wrapped in `try/except Exception` (not just `ImportError`) — catches DB errors on first import, not just missing module ✅
- `__init__` keeps `db_connection` parameter for API compatibility — SignalTracker manages its own pool, not passed in ✅
- `__init__` initialises all three EOD flags: `daily_reset_done`, `eod_ml_done`, `eod_report_done` ✅
- `process_signal()`: returns `1` (truthy) in no-op mode — scanner correctly proceeds on no-op ✅
- `process_signal()`: all 9 signal fields extracted with safe `.get()` defaults — no KeyError on partial dicts ✅
- `process_signal()`: `event_id < 0` check with `logger.warning` — tracker failure surfaced in Railway logs ✅
- `validate_signal()`: all 12 parameters forwarded verbatim — no silent drop ✅
- `arm_signal()`: `confirmation_type="retest"` default preserved — matches `SignalTracker.record_signal_armed()` signature ✅
- `record_trade()`: simplest delegation — 2 args, both forwarded ✅
- `monitor_active_signals()`: documented `pass` placeholder — intentional no-op (position_manager handles this) ✅
- `check_scheduled_tasks()`: `datetime.now(ZoneInfo("America/New_York"))` — ET-aware ✅
- `check_scheduled_tasks()`: market open block at 9:30 resets `daily_reset_done=True` and also resets `eod_ml_done=False` and `eod_report_done=False` ✅
- `check_scheduled_tasks()`: EOD block at 16:05 sets `eod_report_done=True` ✅
- BUG-AI-3 fix confirmed: midnight reset block resets both `daily_reset_done=False` AND `eod_report_done=False` — EOD report fires correctly on every trading day ✅
- `get_today_stats()`: BUG-AI-2 fix confirmed — uses `_tracker.get_funnel_stats()` public method, not `_tracker.session_signals` attribute directly ✅
- `get_today_stats()` no-op fallback returns all 4 expected keys with zero values — callers don't need to guard for missing keys ✅
- `get_today_stats()` live path returns 7 keys (superset of no-op 4) — backward compatible ✅
- No stray `print()` calls
- No dead imports
- `eod_ml_done` initialised in `__init__` but never written in `check_scheduled_tasks()` — this is **intentional**: ML retrain is triggered elsewhere (Railway cron / `ml_trainer.py`), not from this wrapper. Not a bug. ✅

**No findings.**

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31 | **Files:** `thread_safe_state.py`, `signal_scorecard.py`, `sniper_pipeline.py`
**Fixes applied:** None — 2 minor findings logged for fix-on-next-touch.

### `app/core/thread_safe_state.py`
**SHA:** `34ae63dc` | **Size:** ~12 KB | **Status:** ✅ Clean
- Double-checked locking singleton. 5 separate domain locks (no deadlock risk). `.copy()` on all dict returns. BUG-TSS-1/2/3/4 all confirmed fixed.

### `app/core/signal_scorecard.py`
**SHA:** `57342678` | **Size:** ~12 KB | **Status:** ⚠️ BUG-SC-1 (style, non-crashing)
- Pure scoring module, 11-contributor scorecard, crash-safe `build_scorecard()` returns 59 on exception (gate-blocking). All score tier logic and guards correct.
- **BUG-SC-1:** `import logging` and `logger =` consecutive with no blank line separator. Fix on next touch.

### `app/core/sniper_pipeline.py`
**SHA:** `cb87b539` | **Size:** ~14 KB | **Status:** ⚠️ BUG-SP-3 (dead import, non-crashing)
- 14-gate pipeline. Gate order correct (TIME first). BUG-SP-1/2 and FIX A/B/C/D all confirmed. `arm_ticker()` receives all 16 args.
- **BUG-SP-3:** `BEAR_SIGNALS_ENABLED` imported at module scope but never used. Remove on next touch.

---

## Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31 | **Files:** 6 bootstrap files | **Fixes applied:** None — all clean.

### `app/__init__.py`
**SHA:** `8f86f5e1` | **Size:** 54 B | **Status:** ✅ Clean — single comment, no logic.

### `app/core/__init__.py`
**SHA:** `16b2448a` | **Size:** 22 B | **Status:** ✅ Clean — single comment, no logic.

### `app/core/__main__.py`
**SHA:** `8cbad489` | **Size:** 1,352 B | **Status:** ✅ Clean
- Boot order: logging → health server → scanner import → loop. No dead imports, no stray prints.

### `app/core/logging_config.py`
**SHA:** `d22f6ca1` | **Size:** 3,495 B | **Status:** ✅ Clean
- `_CONFIGURED` guard idempotent. `root.handlers.clear()` prevents duplicates. `_QUIET_LOGGERS` correct. BUG-LC-1 confirmed.

### `app/core/sniper_log.py`
**SHA:** `bdcb22e0` | **Size:** 2,855 B | **Status:** ✅ Clean
- Never raises. Fallback `print()` intentional (BUG-SL-1). All 6 params logged. Correct `confidence × 100` display.

### `app/core/eod_reporter.py`
**SHA:** `84d9fe79` | **Size:** 4,267 B | **Status:** ✅ Clean
- Independent `try/except` per block. ET-aware. `clear_session_cache()` called. No stray prints.

### `app/core/health_server.py`
**SHA:** `bafbaa9f` | **Size:** 6,087 B | **Status:** ✅ Clean
- `_started` guard prevents double-bind. `_is_market_hours()` called once per request. Heartbeat seeded at startup.

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31 | **Files:** 5 Python files | **Commit:** `5255863a`

### `app/ml/__init__.py`
**SHA:** `7cc0e794` | **Status:** ✅ Clean — single comment.

### `app/ml/metrics_cache.py`
**SHA:** `f2dbbf05` | **Status:** ✅ Clean
- `get_conn()`/`return_conn()` with `conn=None` guard. `ph()` dual-dialect. `logger.warning` on error. ET-aware.

### `app/ml/ml_confidence_boost.py`
**SHA post-fix:** commit `5255863` | **Status:** ✅ Fixed — BUG-MCB-1 (import order), BUG-MCB-2 (3× `logger.info` → `logger.warning`).

### `app/ml/ml_signal_scorer_v2.py`
**SHA:** `42392e74` | **Status:** ✅ Clean
- HistGBM → XGBoost → heuristic resolution chain. `adx` defaults to 20.0. `-1.0`/`0.5` sentinels correct.

### `app/ml/ml_trainer.py`
**SHA post-fix:** commit `5255863` | **Status:** ✅ Fixed — BUG-MLT-1 (`df = df.copy()` CoW-safe).

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `6263afa7` | **Status:** ✅ Fixed in-file
- BUG-ASS-1: `import logging` moved to top. BUG-ASS-2: Removed redundant inner `import safe_execute`.

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e6481` | **Status:** ✅ Fixed in-file
- BUG-WSS-1: 7× `logger.info` → `logger.warning`. BUG-WSS-2: stray `print()` → `logger.info()`. BUG-WSS-3: empty `()` removed from `safe_execute` DELETE.

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | **SHA:** `8c141c9a` | **Status:** ✅ Clean (2 minor findings pending)
- `OpeningRangeDetector` — OR classification + Phase B1 secondary range. Core logic clean.
- **BUG-OR-1:** `should_scan_now()` dead `or_data` computation. **BUG-OR-2:** `from utils import config` imported twice in same function. Both fix on next `signals/` session.

---

## Open Fix Queue

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-SC-1 | `app/core/signal_scorecard.py` | ⚠️ | `import logging` + `logger =` no blank separator (style) | Next `signal_scorecard.py` touch |
| BUG-SP-3 | `app/core/sniper_pipeline.py` | ⚠️ | `BEAR_SIGNALS_ENABLED` imported but never used — dead import | Next `sniper_pipeline.py` touch |
| BUG-OR-1 | `app/signals/opening_range.py` | ⚠️ | `should_scan_now()` dead `or_data` code | Next `signals/` session |
| BUG-OR-2 | `app/signals/opening_range.py` | ⚠️ | `from utils import config` imported twice in `detect_breakout_after_or()` | Next `signals/` session |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-WSS-1 | `watch_signal_store.py` | in-file | 7× `logger.info` → `logger.warning` |
| BUG-WSS-2 | `watch_signal_store.py` | in-file | Stray `print()` → `logger.info()` |
| BUG-WSS-3 | `watch_signal_store.py` | in-file | Empty `()` removed from `safe_execute` DELETE |
| BUG-ASS-1 | `armed_signal_store.py` | in-file | `import logging` moved to top |
| BUG-ASS-2 | `armed_signal_store.py` | in-file | Redundant inner `import safe_execute` removed |
| BUG-MCB-1 | `ml_confidence_boost.py` | `5255863` | `import logging` moved to top |
| BUG-MCB-2 | `ml_confidence_boost.py` | `5255863` | 3× `logger.info` → `logger.warning` |
| BUG-MLT-1 | `ml_trainer.py` | `5255863` | `df = df.copy()` — CoW-safe |
| BUG-ML-2 | `metrics_cache.py` | Session 11 | `ph()` abstraction + positional tuple params |
| BUG-ML-1 | `ml_signal_scorer_v2.py` | Session 11 | File created — Gate 5 ImportError silent failure |
| BUG-#41 | `ml_confidence_boost.py` | prior | `train()` `print()` → `logger.info()` |
| BUG-#42 | `ml_confidence_boost.py` | prior | `save_model()` naive datetime → ET-aware |
| BUG-#25–27 | `ml_trainer.py` | prior | walk_forward_cv, connection pool, LIVE_FEATURE_COLS |
| BUG-#39–40 | `ml_trainer.py` | prior | All `datetime.now()` → `datetime.now(ET)` |

---

## Next Session Queue

| Priority | Target | Files | Notes |
|----------|--------|-------|-------|
| 1 🔥 | `app/core/sniper.py` | 1 file (~28 KB) | Strategy engine — all supporting files now confirmed clean |
| 2 🔥 | `app/core/scanner.py` | 1 file (~31 KB) | Main loop — audit after sniper.py |
| 3 | `app/data/` | All files | DB pool, `sql_safe`, schema — foundational |
| 4 | `app/signals/` | Remaining files | Fix BUG-OR-1/2. `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 5 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 6 | `app/notifications/` | All files | Discord alert system |
| 7 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 8 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 9 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 10 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
