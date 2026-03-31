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
| `app/core/` | 15 | 14 | 🔄 In Progress — CORE-1 (6) + CORE-2 (3) + CORE-3 (2) + CORE-4 (1) + ASS-1 + WSS-1 |
| `app/data/` | — | — | ⬜ Pending |
| `app/filters/` | — | — | ⬜ Pending |
| `app/indicators/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 |
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

## Session CORE-4 — `app/core/sniper.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `e25f3200`
**Files audited:** 1 file
- `app/core/sniper.py`

**Fixes applied:** BUG-SN-4, BUG-SN-5, BUG-SN-6 — all fixed in this session.

---

### `app/core/sniper.py`
**SHA pre-fix:** `670de1a7` | **SHA post-fix:** `76d733d5`
**Size:** ~28 KB (pre-fix) → ~31 KB (post-fix, version bumped to v1.38e)
**Status:** ✅ Fixed — 3 findings resolved

**Purpose:** `process_ticker()` — the CFW6 strategy engine. Two-path scanner:
OR-Anchored (opening range breakout + FVG) and Intraday BOS+FVG fallback.
Delegates signal pipeline execution to `sniper_pipeline._run_signal_pipeline`
via a thin local dispatcher wrapper. Called once per ticker per scanner cycle.

**Architecture:**
- Single public function: `process_ticker(ticker)`
- Thin dispatcher: `_run_signal_pipeline()` — local wrapper over `_pipeline` (imported alias)
- Two helper logging functions: `_log_bos_event()`, `_log_fvg_event()`
- One utility: `_get_or_threshold()` — VIX-adjusted OR threshold
- EOD reset: `clear_bos_alerts()` — clears `_bos_watch_alerted` dedup set
- 13 optional try/except import blocks with correct stubs — all gated on boolean flags
- Module-level `_state = get_state()` — singleton thread-safe state

**Prior audit notes (Session 18 / v1.38d) — pre-CORE-4:**
- BUG-SN-1: `logger` moved before optional try/except blocks — confirmed fixed ✅
- BUG-SN-2: VWAP reclaim block documented as structurally unreachable (intentional, architectural) ✅
- BUG-SN-3: Resolved by BUG-SN-1 fix ✅

**CORE-4 Findings and Fixes:**

**BUG-SN-4** ⚠️ (clarity) — **FIXED**
- *Location:* `_run_signal_pipeline()` dispatcher function definition
- *Issue:* The local wrapper function `_run_signal_pipeline` has the same name as
  the symbol imported from `sniper_pipeline` (imported as `_pipeline` to avoid
  collision). The aliasing was intentional but undocumented, creating confusion
  risk for future developers about whether the wrapper was recursive or shadowed.
- *Fix:* Added explicit docstring note clarifying: `_pipeline` = implementation
  (sniper_pipeline), `_run_signal_pipeline` = public surface used by scanner.py.
  Not a logic change — clarity only.

**BUG-SN-5** ⚠️ (consistency) — **FIXED**
- *Location:* Secondary range fallback block inside `process_ticker`, ~line 290
- *Issue:* `get_secondary_range_levels` was imported via a deferred inline
  `from app.signals.opening_range import get_secondary_range_levels` inside
  the `if scan_mode is None and _now_et().time() >= time(10, 30):` block.
  All other `opening_range` symbols are imported at module top in the
  `ORB_TRACKER_ENABLED` try/except block. The deferred import was structurally
  safe (only reachable when OR data exists, which requires ORB detector to work)
  but inconsistent with every other `opening_range` import in the file.
- *Fix:* Moved `get_secondary_range_levels` into the top-level ORB_TRACKER_ENABLED
  try/except block. Added `get_secondary_range_levels = None` to the except stub.
  Secondary range fallback now guards with `if get_secondary_range_levels is not None:`
  before calling, matching the null-safe pattern used by all other optional symbols.

**BUG-SN-6** ⚠️ (defensive) — **FIXED**
- *Location:* Intraday BOS+FVG path inside `process_ticker`, ~line 340
- *Issue:* `bos_signal["fvg_low"]`, `bos_signal["fvg_high"]`, and
  `bos_signal["bos_price"]` were direct `[]` key access. `scan_bos_fvg()`
  contract guarantees these keys, but a malformed return dict would raise a
  `KeyError` inside the outer `try/except Exception` — swallowed silently with
  only `logger.error("process_ticker error ...")`, losing the specific key context.
- *Fix:* All three replaced with `.get()` and safe `0.0` defaults. Extracted into
  `_fvg_low`, `_fvg_high`, `_bos_price` locals. Added explicit guard:
  `if not direction or breakout_idx is None or _fvg_low == 0.0 or _fvg_high == 0.0:`
  → `logger.warning("BUG-SN-6: bos_signal missing required keys") + return`.
  MTF fallback paths and `or_high_ref`/`or_low_ref` assignments updated to use
  the extracted locals instead of re-accessing the dict.

**Checks confirmed clean (no action required):**
- All 13 optional try/except import blocks have correct stubs and bool flag gates ✅
- `import logging` + `logger =` correctly placed before all optional blocks (BUG-SN-1) ✅
- `_ET` assigned immediately after logger — no NameError risk ✅
- `clear_bos_alerts()` is a clean one-liner — `_bos_watch_alerted.clear()` ✅
- `_log_bos_event()` / `_log_fvg_event()` both wrapped in try/except — non-fatal ✅
- `_get_or_threshold()` falls back to VIX=20.0 on exception — safe ✅
- `run_eod_report()` called with no args (v1.38d fix confirmed) ✅
- `breakout_bar_dt` DB restore logic for `breakout_idx` is correct — explicit bar scan + discard on miss ✅
- `MAX_WATCH_BARS` expiry logic correct: `bars_since = len(bars_session) - w["breakout_idx"]` ✅
- `_bos_watch_alerted` dedup set — key format `ticker:direction:datetime` consistent across both watch paths ✅
- `send_bos_watch_alert()` called with correct 6 args on both primary and secondary range paths ✅
- `_run_signal_pipeline` dispatcher receives all 9 positional + 4 keyword args correctly ✅
- `skip_cfw6_confirmation=(scan_mode == "INTRADAY_BOS")` — correct boolean expression ✅
- VWAP reclaim block: BUG-SN-2 comment preserved and accurate ✅
- No stray `print()` calls ✅
- No dead imports ✅

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
**SHA:** `d30cd3f5` | **Size:** ~9 KB | **Status:** ✅ Clean

**Purpose:** `arm_ticker()` — final arming step after all pipeline gates pass.
Opens position via `position_manager`, fires Discord alert only on confirmed
position open, persists armed signal state to DB and in-memory state, records
TRADED stage in signal analytics, then sets cooldown.

**Architecture:** Single function, all heavy imports deferred (avoids circular import).
6 logical stages: stop check → log → open position → analytics → Discord → persist + cooldown.
Dual Discord path: production_helpers if available, direct send_options_signal_alert otherwise.

**Checks passed:** All 6 deferred imports correct. FIX G `return True` confirmed.
BUG-S16-1 `validation_data` key confirmed. FIX P3 `vp_bias` both Discord paths confirmed.
All 10 armed_signal_data keys present. No stray prints. No dead imports.

**No findings.**

---

### `app/core/analytics_integration.py`
**SHA:** `3ebfcf2e` | **Size:** ~9.5 KB | **Status:** ✅ Clean

**Purpose:** `AnalyticsIntegration` — thin delegation wrapper over `SignalTracker`.
Single entry-point used by `scanner.py`. `_TRACKER_AVAILABLE` gate on every method.
`check_scheduled_tasks()` handles open/EOD/midnight timing internally.

**Checks passed:** BUG-AI-1/2/3 all confirmed fixed. `midnight reset` correctly resets
`eod_report_done`. No bare `logging.warning()` calls. All 4 no-op fallback keys present.

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
- `_CONFIGURED` guard idempotent. `root.handlers.clear()` prevents duplicates. `_QUIET_LOGGERS` correct.

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
- BUG-ASS-1: `import logging` moved to top. BUG-ASS-2: Redundant inner `import safe_execute` removed.

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
| BUG-SN-4 | `sniper.py` | `e25f3200` | Dispatcher alias documented — `_pipeline` vs `_run_signal_pipeline` clarity |
| BUG-SN-5 | `sniper.py` | `e25f3200` | `get_secondary_range_levels` moved to module-top ORB block; null stub added |
| BUG-SN-6 | `sniper.py` | `e25f3200` | `bos_signal` key access → `.get()` + guard + `logger.warning` on malformed dict |
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
| 1 🔥 | `app/core/scanner.py` | 1 file (~31 KB) | Main loop — last `app/core/` file, then folder complete |
| 2 | `app/data/` | All files | DB pool, `sql_safe`, schema — foundational |
| 3 | `app/signals/` | Remaining files | Fix BUG-OR-1/2. `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 4 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 5 | `app/notifications/` | All files | Discord alert system |
| 6 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 7 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 8 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 9 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
