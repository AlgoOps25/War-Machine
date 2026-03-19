# Signal Logic Audit — Batch 9

**Date:** 2026-03-18
**Scope:** `app/core/scanner.py`, `app/core/thread_safe_state.py`, `app/core/armed_signal_store.py`, `app/core/watch_signal_store.py`
**Total Findings:** 23 (5 Critical, 7 High, 7 Medium, 4 Low)

---

## 🔴 Criticals (5)

---

### 9.C-1 — `_ticker_executor` is a single-worker pool — scan loop serializes all tickers, OR window is functionally broken
**File:** `scanner.py`, module-level

```python
_ticker_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")
max_workers=1 means only one ticker runs in the pool at a time. The watchdog future.result(timeout=45) blocks the main scan thread for up to 45s per ticker. With a 30-ticker watchlist at OR open (5-second scan interval), one cycle takes up to 30×45 = 1,350 seconds. The TICKER_TIMEOUT_SECONDS = 45 hard timeout is functionally meaningless. Additionally, future.cancel() does not interrupt a running task in Python's ThreadPoolExecutor — the next future queues behind it anyway.

Fix: Increase max_workers to at least min(len(watchlist), 8). Use as_completed() with a timeout. Or remove the executor entirely and use a per-ticker daemon thread with join(timeout=45).

9.C-2 — _has_loss_streak boolean has wrong operator precedence — circuit breaker fires incorrectly
File: scanner.py, main loop

python
_has_loss_streak = (
    daily_stats.get("losses", 0) >= 3
    and daily_stats.get("wins", 0) == 0
    or _pm.has_loss_streak(max_consecutive_losses=3)
)
Python evaluates and before or. This reads as (losses>=3 AND wins==0) OR pm.has_loss_streak(). If _pm.has_loss_streak() returns True for any reason — including consecutive losses from a previous session if position_manager doesn't reset — the circuit breaker fires even though the daily_stats condition was never met.

Fix:

python
_has_loss_streak = (
    (daily_stats.get("losses", 0) >= 3 and daily_stats.get("wins", 0) == 0)
    or _pm.has_loss_streak(max_consecutive_losses=3)
)
Also verify _pm.has_loss_streak() resets at session start (Batch 10 scope).

9.C-3 — start_health_server() called at module import time — crashes Railway before env vars are validated
File: scanner.py, top of file

python
from app.core.health_server import start_health_server, health_heartbeat
start_health_server()   # executes at import time
start_health_server() runs before validate_required_env_vars() (which is inside start_scanner_loop()). If health_server.py reads env vars or binds a socket, a misconfigured Railway env raises at import — before the clear error table from Phase 1.28 is ever printed. Also: any test or script that imports scanner will bind a port on import, causing port conflicts.

Fix: Move start_health_server() into start_scanner_loop() after validate_required_env_vars(). Use a guard flag to prevent double-start.

9.C-4 — analytics_conn is a bare psycopg2 connection at module scope — not thread-safe
File: scanner.py, module-level

python
analytics_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
analytics_conn.autocommit = True
psycopg2 connections are not thread-safe. analytics_conn is shared between the main loop's analytics.monitor_active_signals(), background threads from _fire_and_forget(), and _get_analytics_conn() (which re-assigns the global without a lock). Two simultaneous reconnect attempts leak the first connection. Two concurrent users of the connection raise ProgrammingError or silently corrupt state.

Fix: Wrap all analytics_conn access with a threading.Lock(), or switch to psycopg2.pool.ThreadedConnectionPool / db_connection.get_conn().

9.C-5 — _maybe_load_armed_signals() has a TOCTOU race — flag set before DB load completes
File: armed_signal_store.py

python
def _maybe_load_armed_signals():
    if _state.is_armed_loaded():
        return
    _state.set_armed_loaded(True)   # flag set BEFORE load
    _ensure_armed_db()
    loaded = _load_armed_signals_from_db()
    if loaded:
        _state.update_armed_signals_bulk(loaded)
Thread A sets the flag to True and begins loading. Thread B sees is_armed_loaded() == True and returns immediately — but Thread A hasn't finished populating the store. Thread B processes tickers against an empty armed signal store, potentially re-arming already-active signals. Same pattern exists in watch_signal_store.py's _maybe_load_watches().

Fix:

python
_load_lock = threading.Lock()

def _maybe_load_armed_signals():
    with _load_lock:
        if _state.is_armed_loaded():
            return
        _ensure_armed_db()
        loaded = _load_armed_signals_from_db()
        if loaded:
            _state.update_armed_signals_bulk(loaded)
        _state.set_armed_loaded(True)  # set AFTER load completes
🟡 Highs (7)
9.H-6 — _cleanup_stale_watches() uses tz-aware datetime against naive DB column — mismatch on SQLite and Postgres
File: watch_signal_store.py

_now_et() returns a tz-aware datetime. SQLite stores timestamps as naive strings; comparing a tz-aware cutoff_time against them either raises TypeError or uses string comparison — stale watches are never cleaned. On Postgres, TIMESTAMP (no TZ) vs tz-aware Python datetime raises an offset-naive/offset-aware error. _strip_tz() is defined but only applied on read, not on write.

Fix: Strip timezone before writing: _strip_tz(data["breakout_bar_dt"]) in _persist_watch(). Use _now_et().replace(tzinfo=None) for the cutoff comparison.

9.H-7 — _cleanup_stale_armed_signals() issues a redundant DB checkout on top of its own connection
File: armed_signal_store.py

_cleanup_stale_armed_signals() calls position_manager.get_open_positions() (likely another get_conn()) then opens its own get_conn() — two pooled connections for one housekeeping function. Called during every startup load. In the OR window at 5-second cycle intervals, this double-checkout can exhaust the pool.

Fix: Accept open_positions as an optional parameter, defaulting to position_manager.get_open_positions() only if not provided. Allow callers to pass the already-fetched session["open_positions"].

9.H-8 — subscribe_and_prefetch_tickers() packs two calls into one tuple-lambda — closure captures list by reference
File: scanner.py

python
_fire_and_forget(
    lambda: (
        data_manager.startup_backfill_with_cache(combined, days=30),
        data_manager.startup_intraday_backfill_today(combined),
    ),
    label=f"prefetch-{','.join(new_tickers[:3])}"
)
If startup_backfill_with_cache() raises, startup_intraday_backfill_today() is silently skipped. combined is captured by reference — if subscribe_and_prefetch_tickers() is called again before the thread runs, both jobs use the new list.

Fix: Split into two separate _fire_and_forget calls. Snapshot the list: tickers_snapshot = list(combined).

9.H-9 — _get_stale_tickers() silently returns all tickers on any exception — defeats smart backfill
File: scanner.py

python
except Exception:
    return list(tickers)
Any candle_cache error causes all tickers to be treated as stale, triggering a full EODHD backfill on every redeploy. The Phase 1.24 "Smart Backfill" feature is silently disabled with no log entry.

Fix: logger.warning(f"[STALE-CHECK] candle_cache error — assuming all stale: {e}") before the return.

9.H-10 — ThreadSafeState class-level _lock is not reentrant — can deadlock if _initialize() triggers re-import
File: thread_safe_state.py

_initialize() is called while _lock (a non-reentrant threading.Lock()) is held. If any code path in _initialize() or its imports ever calls ThreadSafeState() again, it deadlocks.

Fix: Use threading.RLock() for the class-level singleton lock.

9.H-11 — _validation_call_tracker grows unbounded within a session — never pruned
File: thread_safe_state.py

_validation_call_tracker only clears at EOD. On a full session: ~520 cycles × 50 tickers = ~26,000 entries accumulate. Stale keys from early in the session persist all day, potentially suppressing re-validation of the same ticker+bar combo in a later cycle.

Fix: Add TTL pruning in track_validation_call() — remove entries older than a configurable session window (e.g., 60 minutes).

9.H-12 — _bos_watch_alerted.clear() reaches into a private sniper attribute — fragile EOD reset
File: scanner.py, EOD block

python
from app.core.sniper import _bos_watch_alerted; _bos_watch_alerted.clear()
_bos_watch_alerted is a private module-level set in sniper.py. If it is ever renamed, removed, or migrated into ThreadSafeState, this import raises ImportError at EOD — silently breaking the daily reset. A missed .clear() means stale BOS alerts carry over to the next trading day.

Fix: Expose reset_daily_state() from sniper.py. Call sniper.reset_daily_state() from scanner.py instead.

🟠 Mediums (7)
ID	File	Issue
9.M-13	scanner.py	get_adaptive_scan_interval() returns interval=5 for 9:30–9:40, but this sleep only runs after the per-ticker loop. At 5–10s/ticker × 30 tickers = 150–300s per cycle, the 5-second OR window interval is aspirational, not functional.
9.M-14	scanner.py	loss_streak_alerted is never reset mid-session when the streak clears. After 3 losses, the scanner is permanently halted for the rest of the session even if subsequent trades win. Should reset loss_streak_alerted = False when _has_loss_streak transitions to False.
9.M-15	scanner.py	get_screener_tickers() is defined at module level but never called internally — it's an orphan. It uses config.EODHD_API_KEY instead of the module-level cached API_KEY, creating two separate key-read paths.
9.M-16	armed_signal_store.py	_persist_armed_signal() accesses data["position_id"], data["direction"], etc. by bare key — no .get(). If the caller passes an incomplete signal dict, KeyError is silently swallowed by the outer except Exception, losing data with only a print.
9.M-17	watch_signal_store.py	cursor.rowcount after DELETE is unreliable — always -1 in SQLite, unreliable in psycopg2 without RETURNING. The "Auto-cleaned N stale watch(es)" log may always print 0.
9.M-18	scanner.py	premarket_built = True is set even when the funnel raises and the fallback list is used. The watchlist is permanently stuck on the emergency fallback for the rest of pre-market — get_funnel().should_update() will never re-trigger a real build.
9.M-19	watch_signal_store.py	breakout_idx is always None on DB reload. sniper.py uses breakout_idx to count elapsed bars in the watch window. After a redeploy, all reloaded watches start at None — the sniper must handle this or NoneType-error when computing bars_elapsed. Should reconstruct from breakout_bar_dt vs current time on load.
🟢 Lows (4)
ID	File	Issue
9.L-20	scanner.py	Startup banner prints "✓ REGIME-FILTER VIX/SPY regime detection active" twice — once hardcoded in the checklist block and once from the dynamic try/except import check.
9.L-21	scanner.py	data_update_counter, data_update_symbols, and last_data_summary_time are defined at module scope but never read or written anywhere in the file. Dead code — remove.
9.L-22	armed_signal_store.py	All DB functions use print() instead of logger.* — breaks structured log parsing (same pattern flagged in 8.L-19).
9.L-23	thread_safe_state.py	get_last_dashboard_check() / update_last_dashboard_check() use naive datetime.now() (no timezone). All other time functions in the system use ET. Cross-comparison will be offset by the server's UTC offset.
Priority Fix Order
9.C-5 — TOCTOU race in _maybe_load_armed_signals() — active signals missed on restart during OR window

9.C-2 — Circuit breaker operator precedence bug — scanner may halt when it shouldn't

9.C-4 — analytics_conn shared across threads without a lock — connection corruption under load

9.C-1 — Single-worker watchdog executor — OR window scan loop serializes all tickers

9.C-3 — Health server starts at module import before env validation — obscures boot errors

9.H-12 — Private sniper attribute accessed directly from scanner — fragile EOD reset

9.M-19 — breakout_idx = None on watch reload — sniper needs to reconstruct from breakout_bar_dt

9.M-14 — loss_streak_alerted never resets — permanent scanner halt after 3 losses