Full Batch 38 audit below.

File: docs/signal_logic_audit_batch38.md
text
# Signal Logic Audit — Batch 38

**Date:** 2026-03-18
**Scope:** `app/core/thread_safe_state.py` (10.8 KB)
           `app/core/scanner.py` (39 KB)
**Total Findings:** 24 (0 Critical, 5 High, 11 Medium, 8 Low)

---

## `thread_safe_state.py`

The double-checked locking singleton pattern is correct Python — the
outer `if cls._instance is None` check avoids lock contention on every
instantiation attempt after first init. All public methods acquire their
respective granular locks before touching shared state. Returning
`.copy()` from all getters is the right defensive pattern. Zero criticals
and zero highs — this is one of the best-implemented files in the codebase.

---

## 🔴 Criticals (0)

---

## 🟡 Highs (0) — `thread_safe_state.py`

---

## 🟠 Mediums (3) — `thread_safe_state.py`

| ID | Issue |
|----|-------|
| 38.M-1 | `_last_dashboard_check` and `_last_alert_check` are initialized as `datetime.now()` (tz-naive, local machine time). On Railway (UTC), these timestamps are UTC-naive. Any comparison like `(datetime.now(ET) - self._last_dashboard_check).total_seconds()` mixes tz-aware and tz-naive datetimes and raises `TypeError`. Should initialize as `datetime.now(ET)` and store tz-aware datetimes. Matches the same tz-naive bug found in 37.H-1. |
| 38.M-2 | `_validation_call_tracker` grows unbounded during the session — every unique `signal_id` checked in via `track_validation_call()` is stored forever. With 50 tickers × 12 cycles/hour × 6 trading hours = 3,600 potential entries per day, plus signal IDs that may not be tickers (e.g., `f"{ticker}_{timestamp}"`), this dict can accumulate tens of thousands of entries. `clear_validation_call_tracker()` exists but there is no scheduled call to it. Should be cleared in the EOD reset path (alongside `clear_session_cache()`). |
| 38.M-3 | `_validator_stats` only tracks 5 hardcoded keys: `['tested', 'passed', 'filtered', 'boosted', 'penalized']`. `increment_validator_stat()` silently ignores any `stat_name` not in this set: `if stat_name in self._validator_stats`. If a new stat is added in a future phase (e.g., `'timeout'`), the call succeeds but increments nothing. Should either use `defaultdict(int)` to auto-add new keys, or log a warning when an unknown key is passed. |

---

## 🟢 Lows (3) — `thread_safe_state.py`

| ID | Issue |
|----|-------|
| 38.L-4 | Module-level `print("[THREAD-SAFE-STATE] ✅ Module initialized ...")` fires on every import. Should be `logger.debug`. |
| 38.L-5 | The convenience functions at the bottom (`get_armed_signal`, `set_armed_signal`, etc.) are thin one-liners that duplicate the `ThreadSafeState` method signatures exactly. Any future signature change on the class method requires a matching update to the convenience function. Should explicitly test that both signatures stay in sync, or remove the convenience layer and have callers use `get_state().method()` directly. |
| 38.L-6 | `update_watching_signal_field()` acquires `_watching_lock`, checks `if ticker in self._watching_signals`, updates one field, then releases. No equivalent method exists for `armed_signals`. Any caller that needs to update a single field on an armed signal must call `get_armed_signal()` (acquires lock, copies dict, releases), mutate locally, then call `set_armed_signal()` (acquires lock again). This is a double-lock pattern and a TOCTOU race window between the two calls. Should add `update_armed_signal_field()` for consistency. |

---

## `scanner.py`

The Phase history (1.16–1.33 in 9 days) shows rapid iteration and
disciplined fix tracking. Phase 1.29's single-`get_session_status()`
per cycle fix is exactly right. Phase 1.27 (health server at module
load) is the right call for Railway startup sequencing. The
`_run_ticker_with_timeout()` watchdog is a well-designed safety net.

---

## 🔴 Criticals (0)

---

## 🟡 Highs (5) — `scanner.py`

---

### 38.H-1 — **`analytics_conn` is a raw `psycopg2` connection managed entirely outside the connection pool.** At module load, `scanner.py` opens `analytics_conn = psycopg2.connect(DATABASE_URL, ...)` independently of `app.data.db_connection`'s pool. The `_get_analytics_conn()` reconnect helper manages it with a 3-attempt retry. This means the codebase now has **two independent Postgres connection managers**: the `db_connection` pool (used by everything else) and this raw connection used only by `scanner.py`'s `analytics` object. With Railway Postgres's connection limit, this raw connection consumes one slot permanently and does not participate in pool eviction. After 37.H-1 is fixed and `check_scheduled_tasks()` uses `datetime.now(ET)`, this connection is passed to `AnalyticsIntegration()` which ignores `db_connection` entirely (see 37.M comment — it manages its own). The `analytics_conn` / `ANALYTICS_AVAILABLE` / `_get_analytics_conn()` infrastructure is orphaned legacy code from before the pool was established. Should be removed; `AnalyticsIntegration` constructs fine with `db_connection=None`.

---

### 38.H-2 — **`_run_ticker_with_timeout()` uses a `ThreadPoolExecutor` with `max_workers=1`.** `process_ticker()` is submitted sequentially per ticker, blocking until it completes or times out. If `process_ticker(NVDA)` takes 44.9 seconds (just under timeout), the entire watchlist of 50 tickers takes a minimum of 50 × 44.9s = 37+ minutes per cycle — catastrophically longer than any scan interval. The timeout only protects against a single ticker hanging **indefinitely**, not against slow execution across all tickers. The intent (preventing a single ticker from blocking the loop forever) is correct but the `max_workers=1` makes it serial. With `max_workers=1`, the executor processes tickers one at a time — you get one watchdog worker but lose all concurrency. To get true concurrent processing with individual timeout guards, should use `max_workers=len(watchlist)` (or a capped value like 8–10), submit all tickers at once, and collect results with per-future `timeout`. Or keep the current serial model but set `TICKER_TIMEOUT_SECONDS = 5` (matching the OR window scan interval) during the OR window, and `15` otherwise.

---

### 38.H-3 — **`start_health_server()` is called at module-level** (`scanner.py` line ~60, before `start_scanner_loop()`). This means the health server starts on every `import scanner` — including during test runs, CI, and `__main__` checks. More critically, if `scanner.py` is imported by any other module (e.g., a route handler), the health HTTP server binds to `PORT` immediately. On Railway, only one process should bind the health port. A second import in a thread or subprocess would cause `OSError: [Errno 98] Address already in use`. The fix from Phase 1.27 (`start_health_server()` at module load) solves the Railway startup sequencing problem but introduces port-bind-on-import. Should be moved inside `start_scanner_loop()` with a module-level `_health_started = False` guard.

---

### 38.H-4 — **EOD reset block at `last_report_day != current_day` imports `_bos_watch_alerted` directly from `sniper.py`:**

```python
from app.core.sniper import process_ticker, clear_armed_signals, \
    clear_watching_signals, _bos_watch_alerted
_bos_watch_alerted.clear()
_bos_watch_alerted is a module-level set in sniper.py, accessed here by direct reference. This is a cross-module mutation of a private variable (_ prefix convention = internal). If sniper.py is ever refactored to move _bos_watch_alerted into thread_safe_state (the right architecture), this import silently breaks with ImportError. More immediately: the from app.core.sniper import ... _bos_watch_alerted import is inside the start_scanner_loop() function body — it runs once at startup and caches the reference. If sniper.py replaces _bos_watch_alerted with a new set object at some point, scanner.py still holds a reference to the old set and .clear() has no effect. Should be exposed as a clear_bos_watch_alerts() function in sniper.py or moved into thread_safe_state.

38.H-5 — _has_loss_streak check has a logic error:
python
_has_loss_streak = (
    daily_stats.get("losses", 0) >= 3
    and daily_stats.get("wins", 0) == 0
    or _pm.has_loss_streak(max_consecutive_losses=3)
)
Due to Python's operator precedence, and binds tighter than or. This evaluates as:

python
(losses >= 3 AND wins == 0) OR (has_loss_streak)
The intended logic is likely: losses >= 3 AND (wins == 0 OR consecutive_losses >= 3). But what's written means: if _pm.has_loss_streak() returns True at any point (even with 0 total losses), the circuit breaker fires. If has_loss_streak() has a bug that returns True spuriously (e.g., before any trades), all scanning halts immediately at session open with no losses recorded. Should add explicit parentheses: (losses >= 3 and wins == 0) or _pm.has_loss_streak(...).

🟠 Mediums (8) — scanner.py
ID	Issue
38.M-6	get_screener_tickers() at the bottom of scanner.py is a standalone HTTP function that hits the EODHD screener API. It is not called anywhere in scanner.py itself and does not appear to be called from any imported module visible in this audit. Dead code in the main scanner module. If needed, should live in app/screening/ not scanner.py.
38.M-7	subscribe_and_prefetch_tickers() launches two fire-and-forget background threads: startup_backfill_with_cache(combined, days=30) and startup_intraday_backfill_today(combined). The lambda captures combined by reference at the time the thread starts — correct since combined is a local variable. However, if subscribe_and_prefetch_tickers() is called multiple times in quick succession (e.g., watchlist refreshes during pre-market), multiple backfill threads pile up for overlapping ticker sets. There is no deduplication — if NVDA appears in 3 consecutive watchlist refreshes, 3 separate backfill threads each download 30 days of NVDA bars simultaneously. Should check if a backfill is already running for a ticker before submitting another.
38.M-8	The startup banner prints 30+ print(..., flush=True) lines at startup. On Railway, these are captured in the log stream but have no timestamps, no log levels, and no filtering capability. They inflate the startup log to 50+ lines. Should be replaced with structured logger.info() calls after startup completes, or consolidated into a single multi-line logger.info() block.
38.M-9	monitor_open_positions() calls data_manager.get_bars_from_memory(ticker, limit=1) as a fallback when both WS and REST bar fetches fail. With 50 open positions (worst case), this is 50 DB queries in the monitoring path on top of the 50 ticker scan queries — all within a single scan cycle. Should cache the "last known bar" per ticker in thread_safe_state and use the cache as the final fallback rather than hitting the DB.
38.M-10	_get_stale_tickers() calls candle_cache.get_bars(ticker, limit=1) for every ticker in startup_watchlist. With a 50-ticker watchlist at startup, this is 50 cache reads to build the stale list. If candle_cache is backed by disk parquet files, this is 50 file reads at startup. Should use a bulk get_all_cached_tickers() call if available, or batch the reads.
38.M-11	_extract_premarket_metrics() divides sum / len(all_tickers) for avg_rvol and avg_score without guarding against len(all_tickers) == 0. The early return if not all_tickers: return None guards against the empty case correctly — but only if all_tickers is falsy. An all_tickers = [{}] (one empty dict) passes the guard and then sum(t.get('rvol', 0) for t in all_tickers) / 1 is fine. However all_tickers[:3] in top_3_summary accesses items with .get('ticker') and .get('rvol') — if the first 3 items have neither key, the summary is 'N/A'. Low risk but should validate t.get('ticker') is not None before inclusion.
38.M-12	In the main loop EOD block, clear_armed_signals() and clear_watching_signals() are imported from sniper.py. But these functions live in armed_signal_store.py and watch_signal_store.py respectively — they're re-exported from sniper.py. The import path from app.core.sniper import clear_armed_signals creates an indirect dependency on sniper.py even when the intent is to clear persistence stores. Should import directly from the store modules to reduce coupling.
38.M-13	_fire_and_forget() creates a new threading.Thread on every call with no thread limit. At premarket watchlist refresh (potentially every 60 seconds) combined with new-ticker backfills, multiple threads can accumulate. With no cap, 20+ background threads could be active simultaneously during active premarket scanning. Should use a ThreadPoolExecutor with a bounded pool for background tasks.
🟢 Lows (8)
ID	Issue
38.L-14	thread_safe_state.py: _initialize() is called in __new__ with double-checked locking — correct. But _initialize() itself is a regular method, not protected against a second call. If somehow called twice (e.g., subclass in a test), all state dicts would be silently reset. Should guard: if hasattr(self, '_armed_signals'): return.
38.L-15	scanner.py: from app.core.sniper import _bos_watch_alerted imports a private symbol. This is a code smell surfaced as a Low given it's also H-4. The underscore convention should be respected; expose via a public function.
38.L-16	scanner.py: LEGACY_ANALYTICS_ENABLED flag and signal_tracker are imported at module level but LEGACY_ANALYTICS_ENABLED is never read after being set. Dead flag alongside the orphaned analytics_conn infrastructure (38.H-1).
38.L-17	scanner.py: The analytics object (from AnalyticsIntegration) is only used for monitor_active_signals() (which is a pass) and check_scheduled_tasks(). Given monitor_active_signals() is a no-op and check_scheduled_tasks() has the tz bug (37.H-1), the entire analytics construction path in scanner.py currently does nothing useful on Railway. Both issues need fixes before this code path has any effect.
38.L-18	scanner.py: Version string "CFW6 v1.33" is hardcoded in two places: the startup banner print and the Discord online message. Should be a module-level constant SCANNER_VERSION = "1.33" to avoid desync.
38.L-19	scanner.py: for ticker in watchlist: try: _run_ticker_with_timeout(...) catches Exception and calls traceback.print_exc(). The traceback is printed with print() rather than logger.error(). Railway captures print() but it lacks log-level metadata. Should be logger.error(..., exc_info=True).
38.L-20	scanner.py: get_adaptive_scan_interval() uses a global _last_logged_interval to suppress duplicate logs. This is a module-level mutable global shared across all calls, including potential concurrent calls from multiple threads. Since get_adaptive_scan_interval() is called in the main loop (single thread), the race is theoretical but the global pattern is fragile. Should be an instance variable or moved inside start_scanner_loop() as a closure variable.
38.L-21	scanner.py: should_scan_now() function is defined at module level and also named identically to the function in opening_range.py (34.M-7). Having two should_scan_now() functions in the codebase (one in scanner.py, one in opening_range.py) with different signatures and different behavior is a naming collision that creates confusion in logs and stack traces. One should be renamed — scanner.py's version is the authoritative one for the scan loop; the OR version (which always returns True) should be removed per 34.M-7.
Priority Fix Order (Batch 38)
Rank	ID	Fix
1	38.H-5	Add parentheses to _has_loss_streak — prevents spurious circuit breaker firing at session open
2	38.H-2	max_workers=1 in ticker executor — serial processing makes 50-ticker scan take 37+ min if tickers are slow
3	38.H-1	Remove analytics_conn raw connection; pass db_connection=None to AnalyticsIntegration
4	38.H-4	Replace _bos_watch_alerted.clear() with a clear_bos_watch_alerts() function in sniper.py
5	38.M-11 / 38.M-7	Deduplicate concurrent backfill threads per ticker
6	38.M-1	thread_safe_state monitoring timestamps → datetime.now(ET)
7	38.M-2	Schedule clear_validation_call_tracker() in EOD reset
8	38.H-3	Guard start_health_server() with _health_started flag to prevent port-bind-on-import

**38.H-5 is the most immediately dangerous finding** — the `and`/`or` precedence bug means `_pm.has_loss_streak()` alone can trigger the circuit breaker with zero losses recorded. If `position_manager.has_loss_streak()` returns `True` at startup for any reason (stale DB state from yesterday, empty positions counted as losses), all scanning halts at market open with no trades ever taken. It's a two-character fix: add parentheses.

**38.H-2** is the most performance-impactful — `max_workers=1` means the ticker watchdog processes all 50 tickers serially. The timeout only prevents a single stuck ticker from hanging forever, not slow aggregate processing. During the 9:30-9:40 OR window where the scan interval is 5 seconds, serial processing of 50 tickers almost certainly overshoots the interval on most cycles.
