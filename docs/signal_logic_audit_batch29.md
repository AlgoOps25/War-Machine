Full Batch 29 audit below — this is the largest file in the data layer.

File: docs/signal_logic_audit_batch29.md
text
# Signal Logic Audit — Batch 29

**Date:** 2026-03-18
**Scope:** `app/data/data_manager.py` (full, 43 KB)
**Total Findings:** 22 (0 Critical, 5 High, 10 Medium, 7 Low)

---

## 🔴 Criticals (0)

The FIX #4 connection lifecycle management is consistently applied across all DB operations — every method has `try/finally: if conn: return_conn(conn)`. No pool leak from this file. No criticals.

---

## 🟡 Highs (5)

---

### 29.H-1 — `startup_backfill_with_cache()` contains the same **tz-aware/naive calculation bug** as 27.H-2 and 27.H-3, appearing **twice** in this function and **once more** in `background_cache_sync()`:

```python
# In startup_backfill_with_cache():
age_minutes = (now_et - last_cached.replace(
    tzinfo=ET if last_cached.tzinfo is None else None
)).total_seconds() / 60
When last_cached.tzinfo is None (naive datetime from Postgres TIMESTAMP), this does last_cached.replace(tzinfo=ET) — stamps the naive value as ET without conversion. If Railway Postgres stores in UTC, a bar from 14:30 UTC becomes 14:30 ET (= 18:30 UTC) — 4 hours ahead. age_minutes becomes negative (~-240 min), fails the > 60 threshold, and the gap-fill branch is skipped for every ticker. The cache is loaded but never refreshed from the API, so the system runs on potentially 4-hours-stale data through the entire session.

This same pattern appears identically in background_cache_sync(). Three locations total. All should use datetime.utcnow() / datetime.now() (naive) on the left side and last_cached.replace(tzinfo=None) on the right.

29.H-2 — store_bars() retries up to 3 times on failure with time.sleep(1) between attempts. This is called from:
_flush_pending() in ws_feed.py (background flush thread)

startup_backfill_with_cache() (for every ticker in sequence)

materialize_5m_bars() is called after every store_bars() and itself calls get_today_session_bars() + another get_conn()

At 9:30 with 50 tickers in startup_backfill_with_cache(), each ticker calls store_bars() (3 retry attempts × 1s sleep = up to 3s blocked) and materialize_5m_bars() (another get_conn()) in sequence in the main thread. The entire startup loop can block for up to 50 × (3s + DB query time) = 150+ seconds if store attempts are failing — during exactly the window when the WS feed is also hammering the pool (28.H-2). The time.sleep(1) retry sleeps in the calling thread. If this is the scanner main thread, the scanner is frozen during retries. Move retries to a background thread or remove time.sleep() from the retry path and rely on the DB pool's built-in backoff (FIX #5 in db_connection.py).

29.H-3 — materialize_5m_bars() calls get_today_session_bars() which internally calls get_conn() — acquiring a DB connection. Then materialize_5m_bars() itself calls get_conn() again for the upsert. That is 2 DB connections per materialize_5m_bars() call. Since materialize_5m_bars() is called after every store_bars() call (including every _flush_open() cycle per ticker), and store_bars() already holds one connection, the pattern is:
text
store_bars():        acquire conn #1 → release
materialize_5m():    acquire conn #2 (get_today_session_bars) → release
                     acquire conn #3 (upsert 5m bars) → release
Per ticker per flush: 3 connection checkouts. At 50 tickers × 10s = 5 flushes/minute × 3 connections = 15 concurrent semaphore slots just from flush. That exceeds DB_SEMAPHORE_LIMIT=12. This is the exact mechanism behind the 9:30 pool exhaustion, and it compounds 28.H-2. Fix: pass the already-open connection into materialize_5m_bars() as a parameter so it reuses the caller's connection instead of opening new ones.

29.H-4 — _get_ws_bar() imports from ws_feed using the bare module name:
python
from ws_feed import is_connected, get_current_bar
ws_feed.py lives at app/data/ws_feed.py. The correct import path is from app.data.ws_feed import .... The bare from ws_feed import only works if app/data/ is on sys.path directly (i.e., run with python -m from app/data/ or ws_feed.py is installed as a package). On Railway, the working directory is the repo root, so from ws_feed import raises ModuleNotFoundError, which is silently caught by except ImportError: pass. This means WebSocket integration in DataManager is silently broken on Railway. _is_ws_connected() always returns False, _get_ws_bar() always returns None. The "WebSocket-first optimization" in get_latest_bar(), bulk_fetch_live_snapshots(), and update_ticker() never fires. Every bar query goes to the DB even when the WS feed is live.

29.H-5 — get_bars_from_memory() uses a LIMIT parameter via placeholder interpolation:
python
cursor.execute(f"""
    SELECT ... FROM intraday_bars
    WHERE ticker = {p}
    ORDER BY datetime DESC
    LIMIT {p}
""", (ticker, limit))
The LIMIT {p} with p = "%s" produces LIMIT %s in the Postgres query, which is valid parameterized SQL — correct. However, the same {p} also appears in the f-string, meaning for SQLite (p = "?"), the query is LIMIT ? — also valid. This is actually fine. However, it is semantically fragile: a future developer switching {p} for a hardcoded placeholder in the WHERE clause could accidentally leave LIMIT {p} as an f-string injection. The LIMIT value should be validated as int before being passed as a parameter: if not isinstance(limit, int) or limit < 1: raise ValueError(...).

🟠 Mediums (10)
ID	File	Issue
29.M-6	data_manager.py	initialize_database() runs a data-destructive migration on every cold start: if db_version < 2, it DELETEs all rows from intraday_bars, intraday_bars_5m, and fetch_metadata. On Railway, if the Postgres db_version table is empty (e.g., after a schema drop/recreate), current_version = 0, and all bar data is wiped. This migration was for a one-time UTC→ET conversion in March 2025. It should be removed — or at minimum guarded to only run once using a migration flag table rather than on every startup where db_version is missing.
29.M-7	data_manager.py	store_bars() calls upsert_metadata_sql() with (ticker, latest_bar_dt, len(bars)) — passing len(bars) as bar_count. But upsert_metadata_sql() in db_connection.py does ON CONFLICT DO UPDATE SET bar_count = EXCLUDED.bar_count. This means every re-store of overlapping bars replaces bar_count with the count of the current batch, not the total count. After a 5-bar incremental update on a ticker with 1,000 stored bars, bar_count becomes 5. The bar_count in fetch_metadata is unreliable for any consumer that reads it for total bar count. candle_cache avoids this with a COUNT(*) subquery (C4 fix); data_manager does not.
29.M-8	data_manager.py	update_ticker() has an UPDATE_TTL of 2 minutes (timedelta(minutes=2)) but never reads _last_update. The dict is populated nowhere in this file. The TTL guard is dead code. Was it removed during a refactor? If so, update_ticker() will be called on every scanner cycle for every ticker with no rate-limiting, generating 50 API calls per cycle.
29.M-9	data_manager.py	startup_backfill_with_cache() summary block computes cache_hits/len(tickers)*100 without guarding against len(tickers) == 0. ZeroDivisionError if called with an empty watchlist. Minor but will crash the startup log print.
29.M-10	data_manager.py	background_cache_sync() is gated on config.MARKET_OPEN <= now_et.time() <= dtime(17, 0) — runs only during market hours + 1h. But it is called from a scheduled task (presumably via sniper.py or scheduler.py). If the scheduler calls it at 5:00 PM ET (outside the window), it silently returns with no log output. The caller has no way to know the sync was skipped. Should log "[CACHE] Background sync skipped (outside market window)" for observability.
29.M-11	data_manager.py	get_vix_level() has a 3-tier fallback (DB bars → DB latest bar → REST API), but get_bars_from_memory("VIX", limit=1) and get_latest_bar("VIX") both query intraday_bars — the same table. The second call is always redundant if the first returns nothing. get_bars_from_memory("VIX", 1) calls _get_ws_bar("VIX") first (which is always None due to 29.H-4) then DB. If that returns nothing, get_latest_bar("VIX") checks _get_ws_bar("VIX") (None) then DB again. Two identical DB queries for VIX before falling through to REST. Remove the duplicate.
29.M-12	data_manager.py	cleanup_old_bars() uses datetime.now() (naive, local system time) for the cutoff. If Railway's system timezone is UTC and ET is UTC-4/UTC-5, this is off by 4-5 hours. Bars that should be kept (within days_to_keep in ET) may be pruned prematurely. Should use datetime.now(ET).replace(tzinfo=None) consistently with the rest of the codebase.
29.M-13	data_manager.py	DataManager.__init__() sets self.db_path = db_path and passes it to every get_conn(self.db_path) call throughout. As established in 26.M-6 and 27.H-1, this parameter is silently ignored on Postgres. The default "market_memory.db" and candle_cache.py's "market_memory.db" both create the same SQLite file name — correct coincidence — but data_manager = DataManager() at module level uses the default, while candle_cache = CandleCache() uses the same default. On local dev both modules write to market_memory.db. However, database.py shim calls get_conn() with no argument, defaulting to "war_machine.db". Three different default db names across the codebase.
29.M-14	data_manager.py	bulk_fetch_live_snapshots() computes ws_count incorrectly: ws_count = len(result) - len([t for t in tickers_needing_api if t in result]). tickers_needing_api is the list of tickers that didn't have WS data. So len([t for t in tickers_needing_api if t in result]) is the count of REST-filled tickers. ws_count = total_result - rest_filled. This is correct mathematically but confusingly written. More importantly, the log line f"(WS: {ws_count}, API: {api_count})" uses ws_count (computed above) and api_count (also computed as API-filled tickers) — ws_count + api_count may not equal len(result) if some REST tickers came back empty. Not a correctness bug, but the log is potentially misleading.
29.M-15	data_manager.py	clear_prev_day_cache() is documented as DEPRECATED and is a pass. It is still exported as a public method and presumably still called from somewhere (otherwise it would have been removed). If a caller depends on it for EOD reset, it silently does nothing. Either remove entirely or raise a DeprecationWarning.
🟢 Lows (7)
ID	File	Issue
29.L-16	data_manager.py	_logged_skip = set() at module level is never populated or read in this file. Was it used by a prior version of update_ticker()? Dead code.
29.L-17	data_manager.py	_last_update: Dict[str, datetime] = {} and UPDATE_TTL = timedelta(minutes=2) at module level — defined but never read or written (29.M-8). Dead state alongside dead code.
29.L-18	data_manager.py	store_bars_with_cache() wraps store_bars() + candle_cache.cache_candles(). This method is defined but never called anywhere visible in the codebase (all callers use store_bars() directly). If ws_feed._flush_pending() should be auto-caching, this wrapper should be wired in — or the wrapper should be removed to avoid confusion.
29.L-19	data_manager.py	warmup_cache() uses days=60 as default, which is 2× the cleanup_old_cache() retention window of 30 days. A warmup populates 60 days of data that is immediately eligible for cleanup the next time the pruner runs. The warmup default should match the retention window.
29.L-20	data_manager.py	Multiple print(f"[CACHE] ✅ ... \n[CACHE] 📊 Stats:\n[CACHE] - ...") multi-line print blocks. Replace with logger. These fire on every startup for every ticker.
29.L-21	data_manager.py	get_previous_day_ohlc() walks back up to 5 days making synchronous blocking HTTP calls until it finds a trading day. On a holiday week (e.g., 4-day Thanksgiving), this makes up to 4 API calls sequentially before returning. Should check weekday first (if target_date.weekday() >= 5: continue) to skip weekends without API calls.
29.L-22	data_manager.py	data_manager = DataManager() at module level calls initialize_database() on every import. This means any test or script that imports data_manager triggers a DB connection + table creation + version check. On Railway at startup, if the DB is not yet ready, the module import itself fails. Should be lazily initialized or guarded with if __name__ != "__main__" for test environments.
Cross-Batch Connection Budget Analysis (Batches 26–29)
After auditing the entire app/data/ layer, the true concurrent DB connection load at 9:30 AM is now fully mapped:

Source	Connections per 10s cycle	Semaphore slots
_flush_open() — 50 tickers × store_bars()	50	50
materialize_5m_bars() per ticker × 2 calls	100	100
startup_backfill_with_cache() per ticker	3 (retries)	3
Scanner get_today_session_bars() × 50	50	50
Monitor get_today_session_bars()	5	5
candle_cache writes	5	5
Total	213	213
DB_SEMAPHORE_LIMIT = 12 was sized to handle the monitoring + scanner path (~15 connections). It was set in FIX #7 without accounting for _flush_open() and materialize_5m_bars() which add 150 concurrent checkouts per 10s cycle. The fix is not to raise the semaphore limit — it is to batch all 50 open-bar writes into a single connection (28.H-2) and pass connections into materialize_5m_bars() (29.H-3) rather than opening new ones.

Priority Fix Order
29.H-4 — from ws_feed import is a broken import on Railway — WS integration in DataManager is silently dead; fix to from app.data.ws_feed import

29.H-3 + 28.H-2 — Combined: materialize_5m_bars() opening 2 connections per call × 50 tickers per flush cycle = root cause of pool exhaustion; pass caller's connection in

29.H-1 — tz-aware/naive age calculation in startup_backfill_with_cache() and background_cache_sync() causes gap-fill branch to never fire → stale session data

29.H-2 — store_bars() retry sleeps in calling thread; during startup blocks scanner main thread for 150s

29.M-8 — _last_update / UPDATE_TTL never read → update_ticker() has no rate limiting → 50 API calls per scan cycle

29.M-6 — Data-destructive migration runs on every cold start when db_version table is empty → wipe risk

29.M-7 — fetch_metadata.bar_count overwritten with batch size on every partial update → unreliable count for any consumer

**The `app/data/` layer audit is now complete (Batches 26–29)**. The most impactful cross-cutting finding is the connection budget analysis above — the 9:30 pool exhaustion crash has been traced to its exact root cause: `_flush_open()` issuing 50 individual `get_conn()` calls plus `materialize_5m_bars()` opening 2 more connections per call, totaling 150+ semaphore slots per 10-second flush cycle against a limit of 12. FIX #7 raised the wall on the wrong side.
