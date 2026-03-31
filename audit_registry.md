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
| `app/core/` | 15 | 15 | ✅ **COMPLETE** — CORE-1 through CORE-5 |
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

## Session CORE-5 — `app/core/scanner.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `7ece10fd`
**Files audited:** 1 file
- `app/core/scanner.py`

**Fixes applied:** SC-A, SC-B, SC-C, SC-E, SC-F, SC-G — all fixed in this session.
**`app/core/` is now 100% complete (15/15 files audited).**

---

### `app/core/scanner.py`
**SHA pre-fix:** `2ad421df` | **SHA post-fix:** `8b5a55e0`
**Size:** ~31 KB → ~33 KB (post-fix, version bumped to v1.38e)
**Status:** ✅ Fixed — 6 findings resolved

**Purpose:** `start_scanner_loop()` — main scanner orchestrator. Manages the
full trading day lifecycle: WebSocket startup → pre-market watchlist build →
OR window detection → intraday ticker scan loop → position monitoring → EOD
reports and daily reset. Delegates per-ticker analysis to `sniper.process_ticker()`
via `_run_ticker_with_timeout()` watchdog wrapper.

**Architecture:**
- Module-level health server start (Railway /health probe, must be first)
- 6 module-level optional try/except import blocks (analytics, validation, options, etc.)
- 5 pure utility functions: `_run_ticker_with_timeout`, `_get_stale_tickers`,
  `_fire_and_forget`, `build_watchlist`, `subscribe_and_prefetch_tickers`
- 3 time helpers: `_now_et()`, `is_premarket()`, `is_market_hours()`, `_is_or_window()`
- 2 adaptive tuning functions: `get_adaptive_scan_interval()`, `calculate_optimal_watchlist_size()`
- 1 main loop: `start_scanner_loop()` — 3-branch state machine (premarket / market / after-hours)
- EOD reset block clears all in-memory state, resets funnel, clears sniper signals

**Prior audit notes (AUDIT S17 / v1.38d) — pre-CORE-5:**
- SC-1: PEP 8 blank lines standardized ✔
- SC-2: `future.cancel()` limitation documented ✔
- SC-3: Lambda tuple order documented ✔
- SC-4: `API_KEY[:8]` safety documented ✔
- SC-5: Startup Discord message fixed (Pre-market vs OR window) ✔
- SC-6: `_run_analytics(conn=None)` parameter documented ✔

**CORE-5 Findings and Fixes:**

**BUG-SC-A** ⚠️ (clarity) — **FIXED**
- *Location:* Docstring + `logger.info("WAR MACHINE CFW6 SCANNER v1.38d")` + Discord message
- *Issue:* `scanner.py` still reported version `v1.38d` in its banner and Discord startup
  message. `sniper.py` was bumped to `v1.38e` in CORE-4. Version mismatch creates confusion
  in Railway logs when both files log on startup.
- *Fix:* Docstring, `logger.info` banner, and Discord `send_simple_message` all updated
  to `v1.38e`.

**BUG-SC-B** ⚠️ (dead code) — **FIXED**
- *Location:* Premarket first-build block, after `watchlist_data = get_watchlist_with_metadata(...)`
- *Issue:* `metadata = watchlist_data['metadata']` was assigned immediately after the
  `watchlist_data` call in the first-build block but never read anywhere within that block.
  The only use of `metadata` in the entire function is in the refresh block's `logger.info`.
  Dead assignment also used direct `[]` access (see SC-C).
- *Fix:* Line removed entirely.

**BUG-SC-C** 🐛 (defensive) — **FIXED**
- *Location:* Two premarket path blocks — first-build (~line 320) and refresh (~line 360)
- *Issue:* `watchlist_data['watchlist']` used direct `[]` key access in both premarket blocks.
  If `get_watchlist_with_metadata()` returned a partial dict (e.g., missing `'watchlist'`
  key due to an early-exit funnel error), a `KeyError` would be raised and caught by the
  outer `except Exception as e:` as `"Funnel error: 'watchlist'"` — misleading. The
  redeploy path already used `.get('watchlist', [])` correctly.
- *Fix:* Both instances changed to `.get('watchlist', [])`. Consistent with the redeploy
  block. Also changed `watchlist_data['metadata']` in the refresh block to
  `watchlist_data.get('metadata', {})` (see SC-G fix).

**BUG-SC-E** ⚠️ (silent failure) — **FIXED**
- *Location:* `_get_stale_tickers()`, `except Exception:` clause
- *Issue:* On any exception inside the stale-check loop (import error, missing attribute,
  etc.), all tickers were returned as stale, triggering a full EODHD backfill for every
  startup ticker. The conservative behavior is correct, but the exception was swallowed
  silently — no log entry. A developer seeing a full backfill on Railway startup had no
  way to know if it was intentional (cache miss) or caused by a code error.
- *Fix:* Added `logger.warning(f"[CACHE] Stale-check failed ({e}) — treating all
  {len(tickers)} tickers as stale")` before `return list(tickers)`.

**BUG-SC-F** ⚠️ (style) — **FIXED**
- *Location:* `start_scanner_loop()`, ~line 398
- *Issue:* `_REDEPLOY_RETRIES = 2` and `_REDEPLOY_RETRY_WAIT = 3` were defined as local
  variables inside `start_scanner_loop()`. By convention, module-level constants (like
  `TICKER_TIMEOUT_SECONDS`) belong at module scope where they are visible, reusable, and
  consistent with the rest of the file.
- *Fix:* Moved both constants to module scope, adjacent to `TICKER_TIMEOUT_SECONDS`.
  References in the loop body unchanged.

**BUG-SC-G** 🐛 (defensive minor) — **FIXED**
- *Location:* Premarket refresh block, `logger.info(f"[FUNNEL] Stage: {metadata['stage']}...")`
- *Issue:* Direct `metadata['stage']` and `metadata['stage_description']` subscript access.
  If `get_watchlist_with_metadata()` returned a `metadata` dict missing either key, a
  `KeyError` would be raised and caught as `"Refresh error: 'stage'"` — misleading.
- *Fix:* Changed to `metadata.get('stage', '?').upper()` and
  `metadata.get('stage_description', '?')`. Fallback `'?'` clearly signals missing data
  in the log line without crashing.

**Checks confirmed clean (no action required):**
- `start_health_server()` at true module level (before all imports) — Railway 30s probe safe ✅
- `_fire_and_forget()` daemon thread + try/except wrapper — non-fatal, correct ✅
- `subscribe_and_prefetch_tickers()` lambda tuple both functions execute left-to-right ✅
- `_run_ticker_with_timeout()` watchdog with `FuturesTimeoutError` — SC-2 documented ✅
- `get_adaptive_scan_interval()` 5-tier time table — correct intervals, logged once per change ✅
- `calculate_optimal_watchlist_size()` 4-tier time table — logged once per change ✅
- Redeploy path uses `.get('watchlist', [])` — already correct pre-CORE-5 ✅
- Circuit breaker: 3 losses + 0 wins OR `_pm.has_loss_streak(3)` — dual-check correct ✅
- `monitor_open_positions()` WS → REST → DB fallback chain — correct ✅
- `_run_analytics(conn=None)` — SC-6 documented, `_db_operation_safe` compatible ✅
- EOD reset block: all 8 state variables reset + funnel + sniper signals cleared ✅
- `KeyboardInterrupt` re-raised after EOD report log — clean Railway shutdown ✅
- `time.sleep(30)` on critical error before retry — prevents CPU spin ✅
- No stray `print()` calls ✅
- No dead imports ✅

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
**Date:** 2026-03-31 | **Files:** `arm_signal.py`, `analytics_integration.py`
**Fixes applied:** None — both files are clean. 0 findings.

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
| BUG-SC-A | `scanner.py` | `7ece10fd` | Version bump v1.38d → v1.38e (sync with sniper.py) |
| BUG-SC-B | `scanner.py` | `7ece10fd` | Removed dead `metadata = watchlist_data['metadata']` in first-build block |
| BUG-SC-C | `scanner.py` | `7ece10fd` | `watchlist_data['watchlist']` → `.get('watchlist', [])` in both premarket blocks |
| BUG-SC-E | `scanner.py` | `7ece10fd` | Silent `except Exception` in `_get_stale_tickers` → `logger.warning` before return |
| BUG-SC-F | `scanner.py` | `7ece10fd` | `_REDEPLOY_RETRIES` / `_REDEPLOY_RETRY_WAIT` moved to module-level constants |
| BUG-SC-G | `scanner.py` | `7ece10fd` | `metadata['stage']`/`['stage_description']` → `.get()` with `'?'` fallbacks |
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
| 1 🔥 | `app/data/` | All files | DB pool, `sql_safe`, schema — foundational |
| 2 | `app/signals/` | Remaining files | Fix BUG-OR-1/2. `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 3 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 4 | `app/notifications/` | All files | Discord alert system |
| 5 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 6 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 7 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 8 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
