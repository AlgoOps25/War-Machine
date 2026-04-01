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
| `app/data/` | 10 | 10 | ✅ **COMPLETE** — DATA-1 through DATA-4 |
| `app/filters/` | — | — | ⬜ Pending |
| `app/indicators/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 |
| `app/mtf/` | — | — | ⬜ Pending |
| `app/notifications/` | — | — | ⬜ Pending |
| `app/options/` | — | — | ⬜ Pending |
| `app/risk/` | — | — | ⬜ Pending |
| `app/screening/` | — | — | ⬜ Pending |
| `app/signals/` | ~10 | 3 | 🔄 In Progress — SIG-1, SIG-2 |
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

## Session SIG-2 — Dead Code Fixes (BUG-OR-1, BUG-OR-2, BUG-BD-1)
**Date:** 2026-04-01
**Auditor:** Perplexity AI
**Commit:** `cbfc26d`
**Files fixed:** `app/signals/opening_range.py`, `app/signals/breakout_detector.py`
**Fixes applied:** BUG-OR-1, BUG-OR-2, BUG-BD-1

---

### `app/signals/opening_range.py`
**SHA post-fix:** `cbfc26d` | **Status:** ✅ Fixed — 2 findings resolved

**BUG-OR-1** ⚠️ → 🔧 **FIXED**
- *Location:* `should_scan_now()` — `or_data = self.classify_or(ticker, current_time)`
- *Issue:* Result of `classify_or()` assigned to `or_data` but never read. Function
  always returns `True` unconditionally. Dead call wasted CPU on every scanner tick.
- *Fix:* Removed the dead `or_data = ...` line entirely.

**BUG-OR-2** ⚠️ → 🔧 **FIXED**
- *Location:* `detect_breakout_after_or()` — duplicate `from utils import config`
- *Issue:* `from utils import config` appeared once at the top of the function and
  again inside the `for` loop on every iteration. Redundant sys.modules lookup per bar.
- *Fix:* Removed the second `from utils import config` inside the loop.

---

### `app/signals/breakout_detector.py`
**SHA post-fix:** `cbfc26d` | **Status:** ✅ Fixed — 1 finding resolved

**BUG-BD-1** ⚠️ → 🔧 **FIXED**
- *Location:* `BreakoutDetector.__init__()` — `risk_reward_ratio: float = 2.0,`
- *Issue:* Annotated assignment with trailing comma — stored value was tuple `(2.0,)`
  not `2.0`. Variable never read anywhere. Latent confusion hazard.
- *Fix:* Removed the dead line entirely.

---

## Session SIG-1 — `app/signals/breakout_detector.py` + `app/signals/signal_analytics.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `cbfc26d` (BUG-BD-1 applied here)
**Files audited:** 2

---

### `app/signals/breakout_detector.py`
**SHA:** `eaa1062a` | **Size:** ~18 KB | **Status:** ✅ Fixed — see SIG-2 for BUG-BD-1

**Purpose:** Core pattern detector for `app/core/sniper.py`. Detects BULL BREAKOUT,
BEAR BREAKDOWN, and RETEST ENTRY signals using session-anchored S/R levels (Phase 1.17),
EMA volume confirmation, ATR-based dynamic stops, and T1/T2 split targets.

**Checks confirmed clean:** `calculate_atr()` bar-count cache, `get_pdh_pdl()` composite
cache key, `clear_pdh_pdl_cache()` / `clear_atr_cache()`, `calculate_support_resistance()`
rolling→session-anchor→PDH/PDL priority, `resistance_source`/`support_source` init,
`get_session_levels()` fail-silent import, EMA volume multiplier, `analyze_candle_strength()`
Marubozu/Hammer/Engulfing, `detect_breakout()` uses `bars[:-1]`, BULL/BEAR/RETEST
symmetric logic, `session_anchored` flag ✅

---

### `app/signals/signal_analytics.py`
**SHA:** `8722c950` | **Size:** ~17 KB | **Status:** ✅ Clean

**Purpose:** Full signal lifecycle tracker. Persists GENERATED→VALIDATED→ARMED→TRADED
events to `signal_events` table. Funnel stats, grade distribution, multiplier impact,
rejection breakdown, hourly patterns. Used by `eod_reporter.py`.

**Checks confirmed clean:** `get_conn()` try/finally, `_initialize_database()` guard,
table schema all lifecycle columns, 4 indexes, Postgres/SQLite dual-path, all stage guards,
ZeroDivisionError guards, `get_multiplier_impact()` fallback, singleton ✅

---

## Session DATA-4 — `app/data/ws_feed.py` + `app/data/ws_quote_feed.py`
**Date:** 2026-03-31 | **Commits:** `e77b5ba2`, `9ab785f6`
**Fixes:** BUG-WF-1, BUG-WQF-1, BUG-WQF-2 | **`app/data/` 100% complete (10/10)**

**BUG-WF-1** — `materialize_5m_bars()` moved inside `if count:` block
**BUG-WQF-1** — ask field: `or` → `is not None` (0.0 falsy trap)
**BUG-WQF-2** — bid field: `or` → `is not None` (0.0 falsy trap)

---

## Session DATA-3 — `app/data/data_manager.py`
**Date:** 2026-03-31 | **Commit:** `b0524d51`
**Fixes:** BUG-DM-1 (`cleanup_old_bars()` ET-naive cutoff), BUG-DM-2 (explicit WS/API counters)

---

## Session DATA-2 — `app/data/db_connection.py`
**Date:** 2026-03-31 | **Commit:** `b0524d51`
**Fixes:** BUG-DBC-1 (`datetime.now()` → `datetime.now(_ET)`), BUG-DBC-2 (logs → `logger.warning`)

---

## Session DATA-1 — `app/data/` Small & Medium Files
**Date:** 2026-03-31 | **Commit:** `a982d079`
**Fixes:** BUG-IAT-1, BUG-SS-1, BUG-SS-2, BUG-UOA-1

`app/data/__init__.py` ✅ · `database.py` ✅ 🔁 · `intraday_atr.py` ✅ Fixed ·
`sql_safe.py` ✅ Fixed · `candle_cache.py` ✅ · `unusual_options.py` ✅ Fixed

---

## Session CORE-6 — Pending Fix Clearance
**Date:** 2026-03-31 | **Commit:** `0c2290af`
**Fixes:** BUG-SC-1 (`signal_scorecard.py`), BUG-SP-3 (`sniper_pipeline.py`)

---

## Session CORE-5 — `app/core/scanner.py`
**Date:** 2026-03-31 | **Commit:** `7ece10fd`
**Fixes:** SC-A through SC-G (6 fixes). **`app/core/` 100% complete (15/15 files).**

---

## Session CORE-4 — `app/core/sniper.py`
**Date:** 2026-03-31 | **Commit:** `e25f3200`
**Fixes:** SN-4, SN-5, SN-6.

---

## Session CORE-3 — `app/core/arm_signal.py` + `analytics_integration.py`
**Date:** 2026-03-31 | Both ✅ Clean.

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31
`thread_safe_state.py` ✅ · `signal_scorecard.py` / `sniper_pipeline.py` — see CORE-6.

---

## Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31 | All 6 files ✅ Clean.

`app/__init__.py` · `app/core/__init__.py` · `app/core/__main__.py` ·
`logging_config.py` · `sniper_log.py` · `eod_reporter.py` · `health_server.py`

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31 | **Commit:** `5255863a`
`__init__.py` ✅ · `metrics_cache.py` ✅ · `ml_confidence_boost.py` ✅ Fixed ·
`ml_signal_scorer_v2.py` ✅ · `ml_trainer.py` ✅ Fixed

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31 | **SHA post-fix:** `7ea03339`
**Fixes:** ASS-1, ASS-2, ASS-3.

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e6481`
**Fixes:** WSS-1, WSS-2, WSS-3.

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | ✅ Clean audit — BUG-OR-1/2 fixed in SIG-2.

---

## Open Fix Queue

*No open items — queue is clear.*

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-OR-1 | `opening_range.py` | `cbfc26d` | `should_scan_now()` dead `or_data` variable removed |
| BUG-OR-2 | `opening_range.py` | `cbfc26d` | Duplicate `from utils import config` inside loop removed |
| BUG-BD-1 | `breakout_detector.py` | `cbfc26d` | Dead `risk_reward_ratio` tuple assignment removed |
| BUG-WF-1 | `ws_feed.py` | `e77b5ba2` | `materialize_5m_bars()` moved inside `if count:` |
| BUG-WQF-1 | `ws_quote_feed.py` | `9ab785f6` | ask parsing: `or` → `is not None` |
| BUG-WQF-2 | `ws_quote_feed.py` | `9ab785f6` | bid parsing: `or` → `is not None` |
| BUG-DM-1 | `data_manager.py` | `b0524d51` | `cleanup_old_bars()` cutoff ET-naive |
| BUG-DM-2 | `data_manager.py` | `b0524d51` | `bulk_fetch_live_snapshots()` explicit WS/API counters |
| BUG-DBC-1 | `db_connection.py` | `b0524d51` | `datetime.now()` → `datetime.now(_ET)` |
| BUG-DBC-2 | `db_connection.py` | `b0524d51` | `force_close_stale_connections()` logs → `logger.warning` |
| BUG-SC-1 | `signal_scorecard.py` | `0c2290af` | Blank line + removed unused `field` import |
| BUG-SP-3 | `sniper_pipeline.py` | `0c2290af` | `BEAR_SIGNALS_ENABLED` dead import removed |
| BUG-ASS-3 | `armed_signal_store.py` | `7ea03339` | `_persist_armed_signal()` reads `'validation_data'` |
| BUG-S16-1 | `arm_signal.py` | `d30cd3f5` | key `'validation'` → `'validation_data'` |
| BUG-UOA-1 | `unusual_options.py` | `a982d079` | `_cache_result()` stores `.isoformat()` |
| BUG-SS-2 | `sql_safe.py` | `a982d079` | `safe_insert/update_dict()` call `sanitize_table_name()` |
| BUG-SS-1 | `sql_safe.py` | `a982d079` | `build_insert/update/delete()` call `sanitize_table_name()` |
| BUG-IAT-1 | `intraday_atr.py` | `a982d079` | `logger.info` → `logger.warning` on compute exception |
| BUG-SC-A–G | `scanner.py` | `7ece10fd` | 6 fixes — version, dead var, `.get()` guards, constants |
| BUG-SN-4–6 | `sniper.py` | `e25f3200` | 3 fixes — dispatcher doc, import order, `.get()` guard |
| BUG-WSS-1–3 | `watch_signal_store.py` | in-file | info→warning, print→logger, empty `()` |
| BUG-ASS-1–2 | `armed_signal_store.py` | in-file | logging import order, redundant inner import |
| BUG-MCB-1–2 | `ml_confidence_boost.py` | `5255863a` | logging import order, 3× info→warning |
| BUG-MLT-1 | `ml_trainer.py` | `5255863a` | `df = df.copy()` CoW-safe |

---

## Next Session Queue

| Priority | Target | Files | Notes |
|----------|--------|-------|-------|
| 1 🔥 | `app/signals/` | Remaining ~7 files | `signal_validator.py`, `arm_trigger.py`, etc. |
| 2 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 3 | `app/notifications/` | All files | Discord alert system |
| 4 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 5 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 6 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 7 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
