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
- `close_db_connection(conn=None)` no-op guard (`if conn is not None`) is correct — legacy usage where old module held a singleton ✅
- `__all__` lists all 10 exported symbols — complete and accurate ✅
- No circular import risk — `database.py` imports from `db_connection.py`, not vice versa ✅
- No logic duplication — pure delegation ✅
- No stray prints, no dead imports ✅

**No findings.**

---

### `app/data/intraday_atr.py`
**SHA pre-fix:** `4cef275f` | **SHA post-fix:** `a982d079` | **Size:** ~3.9 KB
**Status:** ✅ Fixed — 1 finding resolved

**Purpose:** Provides `compute_intraday_atr()` and `get_atr_for_breakout()`.
Replaces the stale static `config.ATR_VALUE` constant with a true Wilder ATR
computed on the current session's 1-minute bars. Used by
`app/risk/dynamic_thresholds.py` for adaptive OR breakout thresholds.

**Architecture:**
- `DEFAULT_ATR_PERIOD = 14` — module-level constant
- `compute_intraday_atr(bars, period)` — pure math, no IO, no exception handling
- `get_atr_for_breakout(bars, ticker)` — wrapper with 3-tier fallback chain:
  1. Wilder ATR (≥15 session bars) → label `"INTRADAY"`
  2. Mean(high-low) proxy (<15 bars) → label `"DAILY_PROXY"`
  3. `config.ATR_VALUE` static constant → label `"FALLBACK"`

**BUG-IAT-1** ⚠️ → 🔧 **FIXED**
- *Location:* `get_atr_for_breakout()`, `except Exception as e:` clause
- *Issue:* `logger.info(f"[ATR] compute error for {ticker} (non-fatal): {e}")` —
  compute errors are abnormal conditions (e.g. malformed bar dict, missing key).
  Using `info` level buried these in Railway logs behind hundreds of normal ATR
  log lines, making it impossible to notice genuine data quality issues.
- *Fix:* Changed to `logger.warning(...)`. Fallback to `DAILY_PROXY` or `FALLBACK`
  still proceeds normally — non-fatal behavior unchanged.

**Checks confirmed clean:**
- `compute_intraday_atr()` Wilder smoothing formula correct: seed = `mean(TR[0:period])`, then `(atr*(p-1) + tr)/p` ✅
- First TR correctly uses `highs[0] - lows[0]` (no prev close) ✅
- High-low fallback: `if h > 0 and l > 0` guard prevents zero-bar pollution ✅
- `get_atr_for_breakout()` dual-branch correctly avoids double-computing: branch 1 (≥15 bars) → `compute_intraday_atr()` → Wilder path; branch 2 (<15 bars) → `compute_intraday_atr()` → triggers `hl_range fallback` internally ✅
- `from utils import config` deferred inside `except Exception` fallback — avoids import-time dependency ✅
- `getattr(config, "ATR_VALUE", 0.5)` safe fallback if config missing the attribute ✅
- No stray prints ✅

---

### `app/data/sql_safe.py`
**SHA pre-fix:** `909fdd49` | **SHA post-fix:** `a982d079` | **Size:** ~15.6 KB
**Status:** ✅ Fixed — 2 findings resolved

**Purpose:** SQL injection prevention module. Provides parameterized query helpers,
a fluent `SafeQueryBuilder`, and `sanitize_table_name()` / `sanitize_order_by()`
for cases where table/column names must be embedded in SQL strings (cannot be
parameterized). All callers in the codebase should use these instead of raw
f-string SQL.

**Architecture:**
- `ph()` — returns `"%s"` (Postgres) or `"?"` (SQLite) — reads `USE_POSTGRES` once at import
- `safe_execute()` / `safe_query()` — parameterized execute wrappers with error logging
- `build_insert()` / `build_update()` / `build_delete()` — SQL string builders
- `safe_insert_dict()` / `safe_update_dict()` — dict-based convenience wrappers
- `sanitize_table_name()` — whitelist validator (alphanum + `_` only, rejects SQL keywords)
- `sanitize_order_by()` — tokenized ORDER BY validator (Mar 26 fix)
- `safe_in_clause()` — builds `IN (?, ?, ?)` with params list
- `SafeQueryBuilder` — fluent builder; `__init__` calls `sanitize_table_name(table)`

**BUG-SS-1** 🐛 → 🔧 **FIXED**
- *Location:* `build_insert()`, `build_update()`, `build_delete()` — all three standalone builder functions
- *Issue:* All three embedded the `table` argument directly in an f-string SQL string
  without calling `sanitize_table_name(table)` first. `SafeQueryBuilder.__init__`
  already called `sanitize_table_name(self.table)` — the standalone functions were
  an inconsistency in the module's own security model and created a direct SQL
  injection path for any caller passing an unsanitized table name to these functions.
- *Fix:* Added `table = sanitize_table_name(table)` as the first line of each of the
  three functions. Raises `ValueError` on invalid input — callers fail loudly.

**BUG-SS-2** 🐛 → 🔧 **FIXED**
- *Location:* `safe_insert_dict()`, `safe_update_dict()` — dict-based convenience wrappers
- *Issue:* Both delegated to `build_insert()` / `build_update()` without pre-validating
  the `table` argument themselves. After BUG-SS-1 fix, `build_insert/update` now
  sanitize internally — but the validation now also needs to happen in these public
  wrappers for defense-in-depth and API clarity.
- *Fix:* Added `sanitize_table_name(table)` call (result discarded — validation only)
  at the start of each wrapper before delegating. `build_insert/update` still
  sanitize too — double validation is intentional and cheap.

**Checks confirmed clean:**
- `ph()` reads `_USE_POSTGRES` at module import — safe for pooled connections ✅
- `sanitize_table_name()` whitelist correct: `isalnum() or c == '_'` — no dots, dashes, spaces ✅
- SQL keyword blacklist covers 12 most dangerous keywords ✅
- `sanitize_order_by()` Mar 26 fix: tokenizes on comma, validates each part via `sanitize_table_name()` + direction whitelist `{"ASC", "DESC"}` ✅
- `SafeQueryBuilder.limit()` / `.offset()` cast via `int()` — no string injection ✅
- `SafeQueryBuilder.where_in()` calls `sanitize_table_name(column)` ✅
- `get_placeholder(conn)` delegates to `ph()` — backward compat shim ✅
- `__main__` block uses `logger.info` not `print()` ✅
- No dead imports ✅

---

### `app/data/candle_cache.py`
**SHA:** `004bb4f3` | **Size:** ~16.6 KB | **Status:** ✅ Clean

**Purpose:** `CandleCache` — PostgreSQL-backed historical candle cache. Wraps
`candle_cache` and `cache_metadata` tables with upsert, gap detection, freshness
checks, multi-timeframe aggregation, and pruning. Global singleton `candle_cache`
at module bottom.

**Architecture:**
- `_init_cache_tables()` — CREATE TABLE IF NOT EXISTS + indexes
- `load_cached_candles()` — parameterized SELECT → `_parse_cache_rows()`
- `cache_candles()` — atomic upsert: `executemany` on bars + `INSERT ... SELECT COUNT(*)` metadata update in one transaction; `rollback()` on error
- `get_cache_metadata()` — single row fetch, returns `None` if missing
- `detect_cache_gaps()` — compares `last_bar_time` against `now_et` minus 5 min
- `is_cache_fresh()` — FIX 14.H-6: treats naive datetime as UTC before comparing against `now(ET)`
- `aggregate_to_timeframe()` — bucket aggregation for 1m→5m→15m→1h→1d
- `cleanup_old_cache()` — prunes candles + orphaned metadata in one transaction (Phase 1.22)
- `get_cache_stats()` — total bars, unique tickers, date range, Postgres table size
- `_parse_cache_rows()` — FIX 14.H-7: converts naive UTC → ET-aware via `.astimezone(ET)`

**Prior fixes confirmed correctly implemented:**
- **C4:** `cache_candles()` upsert + metadata update is a single `conn.commit()` — atomic ✅
- **C4:** `bar_count` computed via `COUNT(*)` subquery, not additive ✅
- **1.22:** `cleanup_old_cache()` deletes orphaned `cache_metadata` rows in same transaction ✅
- **14.H-6:** `is_cache_fresh()` naive datetime → `replace(tzinfo=timezone.utc)` → `datetime.now(ET)` comparison correct ✅
- **14.H-7:** `_parse_cache_rows()` uses `.astimezone(ET)` not `.replace(tzinfo=None)` ✅

**Checks confirmed clean:**
- All DB calls use `get_conn()` / `return_conn()` in `try/finally` — no leaked connections ✅
- `cache_candles()` `rollback()` in `except` wrapped in nested try — safe against closed connection ✅
- `ph()` used throughout for dual-dialect compatibility ✅
- `dict_cursor()` used on all SELECT paths that read by column name ✅
- `aggregate_to_timeframe()` bucket keys use `replace()` — no mutation of source bars ✅
- `aggregate_to_timeframe()` correctly validates `target_mins % source_mins != 0` ✅
- `ET = ZoneInfo("America/New_York")` at module level — correct ✅
- Global singleton `candle_cache = CandleCache()` — single instance, no double init risk ✅
- No stray prints ✅
- No dead imports ✅

**No new findings.**

---

### `app/data/unusual_options.py`
**SHA pre-fix:** `579ba2ee` | **SHA post-fix:** `a982d079` | **Size:** ~16.2 KB
**Status:** ✅ Fixed — 1 finding resolved

**Purpose:** `UnusualOptionsDetector` — whale/institutional options flow detection.
Scores tickers 0-10 across 4 dimensions (whale orders, flow, sweeps, dark pool)
and returns a `confidence_boost` for the signal pipeline. All 4 scoring sub-methods
are currently stubs (returning `0.0`) pending Unusual Whales / EODHD API integration.
Global singleton `uoa_detector` + 3 module-level convenience functions.

**Architecture:**
- `check_whale_activity(ticker, direction)` — cache → score → result dict → cache store
- `_detect_large_orders()` / `_analyze_options_flow()` / `_detect_sweeps()` / `_check_dark_pool_activity()` — stub scorers, all return `0.0`, all wrapped in try/except
- `_generate_summary(overall, whale, flow, sweep)` — 5-tier string selector
- `_is_cached(ticker, direction)` — checks `(ticker, direction)` tuple key + TTL
- `_cache_result(ticker, direction, result)` — stores result in `self.cache`
- `clear_cache()` — EOD reset, logs count removed
- `get_whale_alerts(tickers, min_score)` — batch scan, returns sorted alert list
- `format_whale_alert(alert)` — Discord message formatter

**BUG-UOA-1** 🔴 → 🔧 **FIXED**
- *Location:* `_cache_result()` stores `'timestamp'`; `_is_cached()` reads and parses it
- *Issue:* `_cache_result()` stored `datetime.now(ET)` — a raw `datetime` object — under
  the `'timestamp'` key of the inner cache dict. `_is_cached()` then called
  `datetime.fromisoformat(self.cache[cache_key]['data']['timestamp'])` on that value.
  `datetime.fromisoformat()` accepts only `str`, not `datetime` — it raises `TypeError`
  on a datetime object. This caused every cache lookup after the very first store to
  raise, making the 5-minute TTL cache permanently non-functional. Every call to
  `check_whale_activity()` after the first would hit the TypeError, fall through
  (uncaught — `_is_cached` has no try/except), and re-execute all 4 stub scorers.
  In production with live API calls, this would cause unbounded API spam.
- *Fix:* `_cache_result()` now stores `datetime.now(ET).isoformat()` (a string), consistent
  with `check_whale_activity()` which already stored `result['timestamp']` as an ISO
  string. Cache TTL now works correctly.
- *Severity upgraded to 🔴:* Although all 4 scorers currently return `0.0` (stubs), the
  cache is the entire throttle mechanism for future live API calls. A broken cache
  would cause immediate rate-limit issues the moment real API integration lands.

**Checks confirmed clean:**
- `cache_ttl = 300` (5 min) — appropriate for intraday data ✅
- `_is_cached()` key format `(ticker, direction)` tuple — consistent with `_cache_result()` ✅
- `confidence_boost` tiers (0.10 / 0.05 / 0.02 / 0.0) — correctly computed ✅
- Weighted score: `whale×0.35 + flow×0.25 + sweep×0.25 + dark_pool×0.15` = 1.0 total ✅
- `get_whale_alerts()` iterates both CALL and PUT per ticker — correct dual-direction scan ✅
- All 4 stub scorers wrapped in `try/except` returning `0.0` — safe for production ✅
- `format_whale_alert()` uses only keys guaranteed present in result dict ✅
- `clear_cache()` logs count before clearing — useful for EOD diagnostics ✅
- Global singleton `uoa_detector` — single instance ✅
- No stray prints ✅
- No dead imports ✅

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
  collision). The aliasing was intentional but undocumented.
- *Fix:* Added explicit docstring note clarifying: `_pipeline` = implementation
  (sniper_pipeline), `_run_signal_pipeline` = public surface used by scanner.py.

**BUG-SN-5** ⚠️ (consistency) — **FIXED**
- *Location:* Secondary range fallback block inside `process_ticker`, ~line 290
- *Issue:* `get_secondary_range_levels` was imported via a deferred inline import
  inside a conditional block. All other `opening_range` symbols are at module top.
- *Fix:* Moved to top-level ORB_TRACKER_ENABLED try/except block with null stub.
  Secondary range fallback now guards with `if get_secondary_range_levels is not None:`.

**BUG-SN-6** ⚠️ (defensive) — **FIXED**
- *Location:* Intraday BOS+FVG path inside `process_ticker`, ~line 340
- *Issue:* `bos_signal["fvg_low"]`, `bos_signal["fvg_high"]`, `bos_signal["bos_price"]`
  used direct `[]` key access — silently swallowed on malformed return dict.
- *Fix:* All three replaced with `.get()` + `0.0` defaults. Added explicit guard
  with `logger.warning` on malformed dict.

**Checks confirmed clean:** (see CORE-5 section above for full list)

---

## Session CORE-3 — `app/core/` Pre-Big-Two Files
**Date:** 2026-03-31 | **Files:** `arm_signal.py`, `analytics_integration.py`
**Fixes applied:** None — both files are clean. 0 findings.

### `app/core/arm_signal.py`
**SHA:** `d30cd3f5` | **Size:** ~9 KB | **Status:** ✅ Clean

**Purpose:** `arm_ticker()` — final arming step after all pipeline gates pass.
All heavy imports deferred. 6 logical stages: stop check → log → open position → analytics → Discord → persist + cooldown.

**No findings.**

---

### `app/core/analytics_integration.py`
**SHA:** `3ebfcf2e` | **Size:** ~9.5 KB | **Status:** ✅ Clean

**Purpose:** `AnalyticsIntegration` — thin delegation wrapper over `SignalTracker`.
`_TRACKER_AVAILABLE` gate on every method. BUG-AI-1/2/3 all confirmed fixed.

**No findings.**

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31 | **Files:** `thread_safe_state.py`, `signal_scorecard.py`, `sniper_pipeline.py`
**Fixes applied:** None — 2 minor findings logged for fix-on-next-touch.

### `app/core/thread_safe_state.py`
**SHA:** `34ae63dc` | **Size:** ~12 KB | **Status:** ✅ Clean
- Double-checked locking singleton. 5 separate domain locks. BUG-TSS-1/2/3/4 all confirmed fixed.

### `app/core/signal_scorecard.py`
**SHA:** `57342678` | **Size:** ~12 KB | **Status:** ⚠️ BUG-SC-1 (style, non-crashing)
- **BUG-SC-1:** `import logging` and `logger =` consecutive with no blank line separator. Fix on next touch.

### `app/core/sniper_pipeline.py`
**SHA:** `cb87b539` | **Size:** ~14 KB | **Status:** ⚠️ BUG-SP-3 (dead import, non-crashing)
- **BUG-SP-3:** `BEAR_SIGNALS_ENABLED` imported at module scope but never used. Remove on next touch.

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
**Date:** 2026-03-31 | **SHA:** `6263afa7` | **Status:** ✅ Fixed in-file
- BUG-ASS-1: `import logging` moved to top. BUG-ASS-2: Redundant inner import removed.

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e6481` | **Status:** ✅ Fixed in-file
- BUG-WSS-1: 7× `logger.info` → `logger.warning`. BUG-WSS-2: stray `print()` → `logger.info()`. BUG-WSS-3: empty `()` removed from `safe_execute` DELETE.

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | **SHA:** `8c141c9a` | **Status:** ✅ Clean (2 minor findings pending)
- **BUG-OR-1:** `should_scan_now()` dead `or_data` computation. **BUG-OR-2:** `from utils import config` imported twice. Both fix on next `signals/` session.

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
| BUG-UOA-1 | `unusual_options.py` | `a982d079` | `_cache_result()` stores `.isoformat()` string — fixes TypeError in `_is_cached()` which called `fromisoformat()` on a raw datetime object; cache TTL now functional |
| BUG-SS-2 | `sql_safe.py` | `a982d079` | `safe_insert_dict` / `safe_update_dict` now call `sanitize_table_name(table)` before delegating — defense-in-depth |
| BUG-SS-1 | `sql_safe.py` | `a982d079` | `build_insert` / `build_update` / `build_delete` now call `sanitize_table_name(table)` — closes injection path in standalone builder functions |
| BUG-IAT-1 | `intraday_atr.py` | `a982d079` | `logger.info` → `logger.warning` on compute exception — abnormal condition now surfaces in Railway logs |
| BUG-SC-A | `scanner.py` | `7ece10fd` | Version bump v1.38d → v1.38e (sync with sniper.py) |
| BUG-SC-B | `scanner.py` | `7ece10fd` | Removed dead `metadata = watchlist_data['metadata']` in first-build block |
| BUG-SC-C | `scanner.py` | `7ece10fd` | `watchlist_data['watchlist']` → `.get('watchlist', [])` in both premarket blocks |
| BUG-SC-E | `scanner.py` | `7ece10fd` | Silent `except Exception` in `_get_stale_tickers` → `logger.warning` before return |
| BUG-SC-F | `scanner.py` | `7ece10fd` | `_REDEPLOY_RETRIES` / `_REDEPLOY_RETRY_WAIT` moved to module-level constants |
| BUG-SC-G | `scanner.py` | `7ece10fd` | `metadata['stage']`/`['stage_description']` → `.get()` with `'?'` fallbacks |
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
