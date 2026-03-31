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
| `app/core/` | 15 | 15 | ✅ **COMPLETE** — CORE-1 through CORE-6 |
| `app/data/` | 10 | 6 | 🔄 In Progress — DATA-1 (6/10 audited) |
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

## Session CORE-6 — Pending Fix Clearance
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** TBD (this commit)
**Files fixed:** `signal_scorecard.py`, `sniper_pipeline.py`
**Purpose:** Cleared the two open style/dead-import findings from Session CORE-2.

**Note — Unusual Whales:** `app/data/unusual_options.py` (audited DATA-1) is confirmed
a placeholder stub. All 4 scorer methods (`_detect_large_orders`, `_analyze_options_flow`,
`_detect_sweeps`, `_check_dark_pool_activity`) intentionally return `0.0`. No subscription
or API wiring exists yet. BUG-UOA-1 (cache TTL TypeError) was fixed so the module is
production-safe when real integration eventually lands. No action required until
Unusual Whales subscription is active.

---

### `app/core/signal_scorecard.py`
**SHA pre-fix:** `5734267e` | **Status:** ✅ Fixed — BUG-SC-1

**BUG-SC-1** ⚠️ → 🔧 **FIXED**
- *Location:* Import block, lines immediately after stdlib imports
- *Issue:* `import logging` and `logger = logging.getLogger(__name__)` were on
  consecutive lines with no blank line separator — inconsistent with PEP 8 and
  the rest of the codebase (every other module separates the two).
- *Fix:* Blank line added between `import logging` and `logger = ...`.
- *Also:* Removed unused `from dataclasses import field` (was imported alongside
  `dataclass` but `field` is never used in the file).

---

### `app/core/sniper_pipeline.py`
**SHA pre-fix:** `cb87b539` | **Status:** ✅ Fixed — BUG-SP-3

**BUG-SP-3** ⚠️ → 🔧 **FIXED**
- *Location:* Module-level import block, `from utils.config import ...` line
- *Issue:* `BEAR_SIGNALS_ENABLED` was imported at module scope but never referenced
  anywhere in the file. Bear-signal gating lives in `sniper.py` at the
  `process_ticker()` call site — not in the pipeline. The dead import created
  the false impression that bear-signal logic was active inside the pipeline.
- *Fix:* `BEAR_SIGNALS_ENABLED` removed from the import line.
  Remaining imports from `utils.config`: `RVOL_SIGNAL_GATE`, `RVOL_CEILING`.

---

## Session DATA-1 — `app/data/` Small & Medium Files
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `a982d079`
**Files audited this session:** 6 of 10
- `app/data/__init__.py`
- `app/data/database.py`
- `app/data/intraday_atr.py`
- `app/data/sql_safe.py`
- `app/data/candle_cache.py`
- `app/data/unusual_options.py`

**Remaining for DATA-2/3:** `db_connection.py` (28 KB), `data_manager.py` (44 KB), `ws_feed.py` (23 KB), `ws_quote_feed.py` (21 KB)
**Fixes applied this session:** BUG-IAT-1, BUG-SS-1, BUG-SS-2, BUG-UOA-1

---

### `app/data/__init__.py`
**SHA:** `8cc2fa17` | **Size:** 30 B | **Status:** ✅ Clean

**Purpose:** Namespace marker for `app.data` package.
**Contents:** Single comment: `# Data Management & Pipelines`
**No logic, no imports, no findings.**

---

### `app/data/database.py`
**SHA:** `dd159333` | **Size:** 1,850 B | **Status:** ✅ Clean 🔁

**Purpose:** Compatibility shim. Two legacy callers (`train_from_analytics.py`,
`scripts/generate_ml_training_data.py`) import `get_db_connection()` /
`close_db_connection()` from this module. Rather than breaking those callers,
this shim re-exports the full `db_connection` public API and provides the two
legacy aliases.

**Architecture:**
- `get_db_connection()` → alias for `get_conn()`
- `close_db_connection(conn=None)` → alias for `return_conn(conn)` (no-op if `conn is None`)
- Re-exports full `db_connection` API via `__all__`
- Docstring explicitly states: "Do NOT add new business logic here."

**Checks confirmed clean:**
- `close_db_connection(conn=None)` no-op guard (`if conn is not None`) is correct ✅
- `__all__` lists all 10 exported symbols — complete and accurate ✅
- No circular import risk ✅
- No logic duplication — pure delegation ✅
- No stray prints, no dead imports ✅

**No findings.**

---

### `app/data/intraday_atr.py`
**SHA pre-fix:** `4cef275f` | **SHA post-fix:** `a982d079` | **Size:** ~3.9 KB
**Status:** ✅ Fixed — 1 finding resolved

**Purpose:** Provides `compute_intraday_atr()` and `get_atr_for_breakout()`.
Replaces stale `config.ATR_VALUE` constant with a true Wilder ATR on session 1m bars.

**BUG-IAT-1** ⚠️ → 🔧 **FIXED**
- `logger.info` → `logger.warning` on compute exception in `get_atr_for_breakout()`.

**Checks confirmed clean:**
- Wilder smoothing formula correct ✅
- High-low fallback guard correct ✅
- `getattr(config, "ATR_VALUE", 0.5)` safe fallback ✅
- No stray prints ✅

---

### `app/data/sql_safe.py`
**SHA pre-fix:** `909fdd49` | **SHA post-fix:** `a982d079` | **Size:** ~15.6 KB
**Status:** ✅ Fixed — 2 findings resolved

**Purpose:** SQL injection prevention module. Parameterized query helpers,
fluent `SafeQueryBuilder`, `sanitize_table_name()` / `sanitize_order_by()`.

**BUG-SS-1** 🐛 → 🔧 **FIXED**
- `build_insert()` / `build_update()` / `build_delete()` now call `sanitize_table_name(table)` — closes injection path.

**BUG-SS-2** 🐛 → 🔧 **FIXED**
- `safe_insert_dict()` / `safe_update_dict()` now call `sanitize_table_name(table)` for defense-in-depth.

**Checks confirmed clean:**
- `sanitize_table_name()` whitelist correct ✅
- `sanitize_order_by()` tokenized validator correct ✅
- `SafeQueryBuilder.limit()` / `.offset()` cast via `int()` ✅
- No stray prints, no dead imports ✅

---

### `app/data/candle_cache.py`
**SHA:** `004bb4f3` | **Size:** ~16.6 KB | **Status:** ✅ Clean

**Purpose:** `CandleCache` — PostgreSQL-backed historical candle cache.

**Prior fixes confirmed correctly implemented:**
- C4: atomic upsert + metadata update ✅
- 1.22: `cleanup_old_cache()` orphan cleanup ✅
- 14.H-6: naive datetime → UTC → ET comparison correct ✅
- 14.H-7: `_parse_cache_rows()` `.astimezone(ET)` correct ✅

**No new findings.**

---

### `app/data/unusual_options.py`
**SHA pre-fix:** `579ba2ee` | **SHA post-fix:** `a982d079` | **Size:** ~16.2 KB
**Status:** ✅ Fixed — 1 finding resolved

**Purpose:** `UnusualOptionsDetector` — whale/institutional options flow detection.
All 4 scoring sub-methods are **stubs** (returning `0.0`) — Unusual Whales
subscription not yet active. Module is production-safe as a no-op placeholder.

**BUG-UOA-1** 🔴 → 🔧 **FIXED**
- `_cache_result()` stored raw `datetime` object; `_is_cached()` called
  `datetime.fromisoformat()` on it → `TypeError`. Cache TTL was permanently
  non-functional. Fixed: store `.isoformat()` string.

**Unusual Whales status:** Placeholder only — no subscription, no API wiring.
BUG-UOA-1 ensures the cache works correctly when integration eventually lands.

**No other findings.**

---

## Session CORE-5 — `app/core/scanner.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `7ece10fd`
**Files audited:** 1 file
- `app/core/scanner.py`

**Fixes applied:** SC-A, SC-B, SC-C, SC-E, SC-F, SC-G
**`app/core/` is 100% complete (15/15 files audited).**

---

### `app/core/scanner.py`
**SHA pre-fix:** `2ad421df` | **SHA post-fix:** `8b5a55e0`
**Size:** ~31 KB → ~33 KB (post-fix, version v1.38e)
**Status:** ✅ Fixed — 6 findings resolved

**Purpose:** `start_scanner_loop()` — main scanner orchestrator. Full trading day
lifecycle: WebSocket startup → pre-market watchlist → OR window → intraday scan
loop → position monitoring → EOD reports and daily reset.

**BUG-SC-A** ⚠️ → 🔧 Version mismatch v1.38d → v1.38e (sync with sniper.py)
**BUG-SC-B** ⚠️ → 🔧 Dead `metadata = watchlist_data['metadata']` assignment removed
**BUG-SC-C** 🐛 → 🔧 `watchlist_data['watchlist']` → `.get('watchlist', [])` in both premarket blocks
**BUG-SC-E** ⚠️ → 🔧 Silent `except Exception` in `_get_stale_tickers` → `logger.warning`
**BUG-SC-F** ⚠️ → 🔧 `_REDEPLOY_RETRIES` / `_REDEPLOY_RETRY_WAIT` moved to module-level
**BUG-SC-G** 🐛 → 🔧 `metadata['stage']` → `.get('stage', '?')` defensive access

**Checks confirmed clean (no action required):**
- `start_health_server()` at true module level — Railway 30s probe safe ✅
- Circuit breaker dual-check correct ✅
- EOD reset block: all 8 state variables reset ✅
- No stray `print()` calls ✅

---

## Session CORE-4 — `app/core/sniper.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `e25f3200`
**Files audited:** 1 file

### `app/core/sniper.py`
**SHA pre-fix:** `670de1a7` | **SHA post-fix:** `76d733d5`
**Size:** ~28 KB → ~31 KB (v1.38e)
**Status:** ✅ Fixed — 3 findings resolved

**Purpose:** `process_ticker()` — CFW6 strategy engine. OR-Anchored and
Intraday BOS+FVG paths. Delegates to `sniper_pipeline._run_signal_pipeline`.

**BUG-SN-4** ⚠️ → 🔧 Dispatcher alias documented
**BUG-SN-5** ⚠️ → 🔧 `get_secondary_range_levels` moved to module-top ORB block
**BUG-SN-6** ⚠️ → 🔧 `bos_signal` key access → `.get()` + guard

---

## Session CORE-3 — `app/core/` Pre-Big-Two Files
**Date:** 2026-03-31
**Files:** `arm_signal.py`, `analytics_integration.py`

### `app/core/arm_signal.py`
**SHA:** `d30cd3f5` | **Size:** ~9 KB | **Status:** ✅ Clean

**Purpose:** `arm_ticker()` — final arming step after all pipeline gates pass.
All heavy imports deferred. 6 logical stages: stop check → log → open position
→ analytics → Discord → persist + cooldown.

**Prior fixes confirmed in place:**
- BUG-ARM-1: `import logging` / `logger` moved above docstring ✅
- BUG-S16-1: `'validation'` key → `'validation_data'` in `armed_signal_data` dict
  so `armed_signal_store._persist_armed_signal()` receives the correct key ✅
- FIX G: explicit `return True` at end of successful path ✅
- FIX H: indentation SyntaxError fixed (two `try:` blocks were at col 0) ✅
- FIX P3: `vp_bias` added to fallback Discord alert path ✅

**No new findings.**

---

### `app/core/analytics_integration.py`
**SHA:** `3ebfcf2e` | **Size:** ~9.5 KB | **Status:** ✅ Clean

**Purpose:** `AnalyticsIntegration` — thin delegation wrapper over `SignalTracker`.
`_TRACKER_AVAILABLE` gate on every method.

**Prior fixes confirmed in place:**
- BUG-AI-1: `logger = logging.getLogger(__name__)` (was bare `logging.*`) ✅
- BUG-AI-2: `get_today_stats()` uses `get_funnel_stats()` not `_tracker.session_signals` ✅
- BUG-AI-3: midnight reset now resets both `daily_reset_done` and `eod_report_done` ✅

**No new findings.**

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31
**Files:** `thread_safe_state.py`, `signal_scorecard.py`, `sniper_pipeline.py`

### `app/core/thread_safe_state.py`
**SHA:** `34ae63dc` | **Size:** ~12 KB | **Status:** ✅ Clean

**Purpose:** Thread-safe singleton for global trading state.
Double-checked locking singleton. 5 separate domain locks.
BUG-TSS-1/2/3/4 all confirmed fixed (ET-aware datetimes, unknown stat warning,
logger placement, missing module-level wrappers).

**No new findings.**

---

### `app/core/signal_scorecard.py`
*(See CORE-6 above for BUG-SC-1 fix.)*

---

### `app/core/sniper_pipeline.py`
*(See CORE-6 above for BUG-SP-3 fix.)*

---

## Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31 | **Files:** 6 bootstrap files | **Fixes applied:** None — all clean.

### `app/__init__.py`
**SHA:** `8f86f5e1` | **Size:** 54 B | **Status:** ✅ Clean

### `app/core/__init__.py`
**SHA:** `16b2448a` | **Size:** 22 B | **Status:** ✅ Clean

### `app/core/__main__.py`
**SHA:** `8cbad489` | **Size:** 1,352 B | **Status:** ✅ Clean

### `app/core/logging_config.py`
**SHA:** `d22f6ca1` | **Size:** 3,495 B | **Status:** ✅ Clean

### `app/core/sniper_log.py`
**SHA:** `bdcb22e0` | **Size:** 2,855 B | **Status:** ✅ Clean

### `app/core/eod_reporter.py`
**SHA:** `84d9fe79` | **Size:** 4,267 B | **Status:** ✅ Clean

### `app/core/health_server.py`
**SHA:** `bafbaa9f` | **Size:** 6,087 B | **Status:** ✅ Clean

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31 | **Files:** 5 Python files | **Commit:** `5255863a`

### `app/ml/__init__.py` — ✅ Clean
### `app/ml/metrics_cache.py` — ✅ Clean
### `app/ml/ml_confidence_boost.py` — ✅ Fixed (BUG-MCB-1, BUG-MCB-2)
### `app/ml/ml_signal_scorer_v2.py` — ✅ Clean
### `app/ml/ml_trainer.py` — ✅ Fixed (BUG-MLT-1)

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31

### `app/core/armed_signal_store.py`
**SHA post-fix:** `7ea03339` | **Size:** ~9.5 KB | **Status:** ✅ Fixed

**Purpose:** DB persistence for armed signals. Owns `_ensure_armed_db`,
`_persist_armed_signal`, `_remove_armed_from_db`, `_cleanup_stale_armed_signals`,
`_load_armed_signals_from_db`, `_maybe_load_armed_signals`, `clear_armed_signals`.

**BUG-ASS-1** ⚠️ → 🔧 `import logging` / `logger` moved to top of import block
**BUG-ASS-2** ⚠️ → 🔧 Redundant inner `from app.data.sql_safe import safe_execute` removed from `clear_armed_signals()`
**BUG-ASS-3** 🐛 → 🔧 `_persist_armed_signal()` read `data.get('validation')` but
  `arm_signal.py` sends `'validation_data'` (renamed by BUG-S16-1). Validation
  payload was always `None` in DB on every arm. Fixed to read `'validation_data'`.

**Checks confirmed clean:**
- `_ensure_armed_db()` uses `get_conn()` / `return_conn()` in `try/finally` ✅
- `ON CONFLICT (ticker) DO UPDATE` upsert correct ✅
- `_cleanup_stale_armed_signals()` cross-references live `position_manager` positions ✅
- `_load_armed_signals_from_db()` Postgres vs SQLite date filter branching correct ✅
- `_armed_load_lock` prevents double-load race on startup ✅
- No stray prints ✅

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31

### `app/core/watch_signal_store.py`
**SHA:** `061e6481` | **Size:** ~10.4 KB | **Status:** ✅ Fixed

**Purpose:** DB persistence for watching signals (tickers pending FVG formation).

**BUG-WSS-1** ⚠️ → 🔧 7× `logger.info` → `logger.warning` on all error paths
**BUG-WSS-2** ⚠️ → 🔧 Stray `print()` → `logger.info()`
**BUG-WSS-3** ⚠️ → 🔧 Empty `()` removed from `safe_execute` DELETE call

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | **SHA:** `8c141c9a` | **Status:** ✅ Clean (2 minor findings pending)
- **BUG-OR-1:** `should_scan_now()` dead `or_data` computation. **BUG-OR-2:** `from utils import config` imported twice. Both fix on next `signals/` session.

---

## Open Fix Queue

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-OR-1 | `app/signals/opening_range.py` | ⚠️ | `should_scan_now()` dead `or_data` code | Next `signals/` session |
| BUG-OR-2 | `app/signals/opening_range.py` | ⚠️ | `from utils import config` imported twice in `detect_breakout_after_or()` | Next `signals/` session |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-SC-1 | `signal_scorecard.py` | this commit | Blank line between `import logging` and `logger =`; removed unused `field` import |
| BUG-SP-3 | `sniper_pipeline.py` | this commit | `BEAR_SIGNALS_ENABLED` dead import removed |
| BUG-ASS-3 | `armed_signal_store.py` | `7ea03339` | `_persist_armed_signal()` reads `'validation_data'` — matches key sent by `arm_signal.py` after BUG-S16-1 |
| BUG-S16-1 | `arm_signal.py` | `d30cd3f5` | `armed_signal_data` key `'validation'` → `'validation_data'` |
| BUG-UOA-1 | `unusual_options.py` | `a982d079` | `_cache_result()` stores `.isoformat()` string — fixes TypeError in `_is_cached()`; cache TTL now functional |
| BUG-SS-2 | `sql_safe.py` | `a982d079` | `safe_insert_dict` / `safe_update_dict` now call `sanitize_table_name(table)` — defense-in-depth |
| BUG-SS-1 | `sql_safe.py` | `a982d079` | `build_insert` / `build_update` / `build_delete` now call `sanitize_table_name(table)` — closes injection path |
| BUG-IAT-1 | `intraday_atr.py` | `a982d079` | `logger.info` → `logger.warning` on compute exception |
| BUG-SC-A | `scanner.py` | `7ece10fd` | Version bump v1.38d → v1.38e |
| BUG-SC-B | `scanner.py` | `7ece10fd` | Dead `metadata` assignment removed |
| BUG-SC-C | `scanner.py` | `7ece10fd` | `watchlist_data['watchlist']` → `.get('watchlist', [])` |
| BUG-SC-E | `scanner.py` | `7ece10fd` | Silent except in `_get_stale_tickers` → `logger.warning` |
| BUG-SC-F | `scanner.py` | `7ece10fd` | `_REDEPLOY_RETRIES` / `_REDEPLOY_RETRY_WAIT` moved to module-level |
| BUG-SC-G | `scanner.py` | `7ece10fd` | `metadata['stage']` → `.get()` with fallbacks |
| BUG-SN-4 | `sniper.py` | `e25f3200` | Dispatcher alias documented |
| BUG-SN-5 | `sniper.py` | `e25f3200` | `get_secondary_range_levels` moved to module-top ORB block |
| BUG-SN-6 | `sniper.py` | `e25f3200` | `bos_signal` key access → `.get()` + guard |
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
| 1 🔥 | `app/data/` DATA-2 | `db_connection.py` (28 KB) | DB pool — foundational to everything |
| 2 🔥 | `app/data/` DATA-3 | `data_manager.py` (44 KB) | Largest file in repo — own session |
| 3 | `app/data/` DATA-4 | `ws_feed.py` (23 KB), `ws_quote_feed.py` (21 KB) | WebSocket feeds |
| 4 | `app/signals/` | Remaining files | Fix BUG-OR-1/2. `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 5 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 6 | `app/notifications/` | All files | Discord alert system |
| 7 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 8 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 9 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 10 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
