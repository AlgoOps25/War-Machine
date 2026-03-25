Here is the full Batch 14 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch14.md
text
# Signal Logic Audit — Batch 14

**Date:** 2026-03-18
**Scope:** `app/data/db_connection.py`, `app/data/candle_cache.py`
**Total Findings:** 16 (2 Critical, 5 High, 5 Medium, 4 Low)

---

## 🔴 Criticals (2)

---

### 14.C-1 — Pool initialization fires at module import — crashes ALL modules on Railway if `DATABASE_URL` is missing or DB is briefly unavailable
**File:** `db_connection.py`

```python
# Module-level code — runs at import time
if USE_POSTGRES:
    _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    _test.close()
    _connection_pool = pool.ThreadedConnectionPool(...)
The test connection and pool initialization execute unconditionally at import time. On Railway, if the Postgres instance is momentarily unavailable during a cold start (happens during Railway deploys — the Postgres add-on starts separately from the web service), the import raises OperationalError and crashes the entire process before any code runs. Because db_connection is imported by nearly every module in the codebase, a transient 2-second DB unavailability during startup takes down the entire scanner. The fix should implement startup retry logic at the pool-init level, not just at get_conn().

Fix: Wrap pool initialization in a retry loop with exponential backoff (reuse POOL_RETRY_ATTEMPTS/POOL_RETRY_BASE_DELAY):

python
for attempt in range(POOL_RETRY_ATTEMPTS):
    try:
        _connection_pool = pool.ThreadedConnectionPool(...)
        break
    except psycopg2.OperationalError:
        if attempt < POOL_RETRY_ATTEMPTS - 1:
            time.sleep(min(POOL_RETRY_BASE_DELAY * (2 ** attempt), 5.0))
        else:
            USE_POSTGRES = False  # graceful SQLite fallback
14.C-2 — get_conn() docstring says "use get_connection() context manager" but most callers use raw get_conn() / return_conn() — leaked connections on exception paths throughout codebase
File: db_connection.py

python
def get_conn(sqlite_path: str = "war_machine.db"):
    """
    ...
    IMPORTANT: Caller must close the connection when done!
    Better to use `with get_connection() as conn:` context manager.
    """
The get_connection() context manager exists and is correct. However, across 11 audited modules (Batches 8–13), not a single call site uses get_connection() — every module uses the raw get_conn() / return_conn() pattern with hand-written try/finally. When finally blocks are missing (e.g., 13.C-1 in explosive_mover_tracker), connections leak. The correct pattern is already built — it just isn't being enforced.

This is a systemic architectural finding, not a single-file bug. Every module that uses get_conn() should be migrated to with get_connection() as conn:. This eliminates an entire class of connection leak bugs (13.C-1, 12.C-2 root cause, etc.).

Recommended migration:

python
# Before (in every module):
conn = None
try:
    conn = get_conn()
    cursor = conn.cursor()
    ...
    conn.commit()
finally:
    return_conn(conn)

# After:
with get_connection() as conn:
    cursor = conn.cursor()
    ...
    conn.commit()
🟡 Highs (5)
14.H-3 — force_close_stale_connections() releases the semaphore for each stale entry but does NOT putconn() the connection back to the pool — pool permanently shrinks
File: db_connection.py

python
def force_close_stale_connections():
    for conn_id in stale:
        with _stats_lock:
            _checked_out_connections.pop(conn_id, None)
        try:
            _db_semaphore.release()   # ← releases gate
        except Exception:
            pass
    # No putconn() — pool slot is permanently lost
force_close_stale_connections() removes the stale entry from _checked_out_connections and releases the semaphore — but the actual psycopg2 connection object is no longer accessible (we only stored its id(), not the object itself). This means the pool's internal slot for that connection is never returned via putconn(). After calling this function, the pool believes N fewer connections are available. Over a session with repeated stale connection cleanup, POOL_MAX effectively decreases toward 0. The function's own docstring says "does not forcibly close sockets" but doesn't warn that it also permanently shrinks the pool.

Fix: Either store the actual connection object in _checked_out_connections (not just id()), allowing true putconn() recovery, or document clearly that this function should only be called at startup (before any active work) and the pool should be restarted afterward.

14.H-4 — check_pool_health() reads _db_semaphore._value — accessing a private attribute of threading.Semaphore
File: db_connection.py

python
semaphore_available = _db_semaphore._value
threading.Semaphore._value is a CPython implementation detail, not part of the public API. It works in CPython 3.x but is not guaranteed across Python implementations or future versions. More importantly, reading _value without the semaphore's internal lock is not thread-safe — the value can change between the read and any downstream use.

Fix: Track available slots manually with an _semaphore_held counter under _stats_lock, or use _db_semaphore._value with a comment acknowledging it is a CPython internal and acceptable for monitoring-only use (not control flow).

14.H-5 — CandleCache.__init__() passes db_path to get_conn() — same bug as 13.C-2
File: candle_cache.py

python
class CandleCache:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self._init_cache_tables()

    def load_cached_candles(self, ...):
        conn = get_conn(self.db_path)   # ← get_conn() takes no arguments
Every get_conn() call in candle_cache.py passes self.db_path. On Postgres (Railway), get_conn() ignores the argument entirely — the connection always goes to DATABASE_URL. The db_path parameter is a SQLite legacy artifact. However, unlike 13.C-2, get_conn() accepts sqlite_path as a keyword argument with a default — so this does not raise TypeError. On Postgres the argument is silently ignored, meaning the db_path="market_memory.db" default has no effect on Railway. The CandleCache("market_memory.db") singleton at module level works fine on Railway but creates a misleading API.

Fix: Remove db_path parameter from CandleCache.__init__() and all get_conn(self.db_path) calls. Document that on Railway, all data goes to DATABASE_URL.

14.H-6 — is_cache_fresh() compares naive and tz-aware datetimes — raises TypeError on Postgres
File: candle_cache.py

python
def is_cache_fresh(self, ticker, timeframe, max_age_minutes=5):
    last_bar = metadata["last_bar_time"]
    if isinstance(last_bar, str):
        last_bar = datetime.fromisoformat(last_bar)

    age = (
        datetime.now(ET) - last_bar.replace(tzinfo=ET)
        if last_bar.tzinfo is None
        else datetime.now(ET) - last_bar
    )
On Postgres, last_bar_time is returned as a tz-aware datetime (psycopg2 attaches UTC tzinfo to TIMESTAMP WITH TIME ZONE columns, or naive for TIMESTAMP). The candle_cache table uses TIMESTAMP (without TZ). psycopg2 returns these as naive datetimes. So last_bar.tzinfo is None is True, and the code does last_bar.replace(tzinfo=ET) — this stamps ET onto a UTC-stored value, producing an incorrect age calculation. If the last bar was stored at 14:30 UTC (10:30 ET), the code treats it as 14:30 ET, computing an age 4 hours shorter than reality. A stale cache appears fresh.

Fix: Store and retrieve all timestamps in UTC consistently:

python
if last_bar.tzinfo is None:
    last_bar = last_bar.replace(tzinfo=ZoneInfo("UTC"))
age = datetime.now(ET) - last_bar.astimezone(ET)
14.H-7 — _parse_cache_rows() strips timezone from all returned datetimes — downstream consumers receive naive datetimes inconsistently
File: candle_cache.py

python
def _parse_cache_rows(self, rows):
    for row in rows:
        dt = row["datetime"]
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)   # ← strips TZ unconditionally
All bars returned by load_cached_candles() have their timezone stripped. The rest of the codebase (_filter_session_bars() in trade_calculator.py, candle_processor in ws_feed.py) compares these naive datetimes against dtime(9, 30) using dt.time(). This works correctly only if Railway's system clock is ET — which it is not (Railway uses UTC). A naive UTC datetime at 13:35 has dt.time() = 13:35, which is outside the SESSION_START=09:30 / SESSION_END=16:00 window, causing session-hour bar filtering to exclude all intraday bars from the cache. In effect, _filter_session_bars() in trade_calculator.py may see zero bars from the candle cache on Railway when bars stored as UTC are returned as naive UTC datetimes and compared to ET session boundaries.

Fix: Return tz-aware datetimes from _parse_cache_rows() with ET attached:

python
from zoneinfo import ZoneInfo
_ET = ZoneInfo("America/New_York")
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_ET)
🟠 Mediums (5)
ID	File	Issue
14.M-8	candle_cache.py	detect_cache_gaps() only checks for a trailing gap (new data available since last_bar_time). It does not check for leading gaps (data before first_bar_time within the target_days window). If the cache was populated from day 20 onward but target_days=30, the 10-day gap at the start is never detected. The scanner operates as though 30 days of data are present when only 10 are.
14.M-9	candle_cache.py	aggregate_to_timeframe() creates bucket keys using dt.replace(minute=minute_floor) without zeroing second and microsecond. A 1m bar timestamped at 09:35:30.000 would produce bucket key 09:35:30 instead of 09:35:00, creating a different bucket from 09:35:00.000. Result: some 5m buckets contain 1 bar instead of 5, producing incorrect OHLCV aggregations silently.
14.M-10	db_connection.py	_pool_stats["semaphore_waiters"] is incremented on every successful semaphore acquire (after acquiring). This counter accumulates without bound over the session and is labeled "waiters" — but it counts total acquirers, not currently-waiting threads. The name is misleading for the health dashboard. Rename to semaphore_total_acquires or reset it periodically.
14.M-11	candle_cache.py	cleanup_old_cache() uses DELETE FROM cache_metadata WHERE (ticker, timeframe) NOT IN (SELECT DISTINCT ticker, timeframe FROM candle_cache). The NOT IN with a multi-column tuple subquery is a SQLite extension. On Postgres the correct syntax is NOT EXISTS or a LEFT JOIN ... WHERE ... IS NULL. This query raises SyntaxError on Railway, meaning orphaned metadata rows are never cleaned up on Postgres.
14.M-12	db_connection.py	CONNECTION_TIMEOUT_SECONDS = 300 (5 minutes). Any connection held longer than 5 minutes logs a warning. Scanner cycles run every 5 seconds — a connection held through 60 cycles (5 minutes) is almost certainly leaked. The timeout is too generous; 60 seconds would catch real leaks while allowing slow queries.
🟢 Lows (4)
ID	File	Issue
14.L-13	candle_cache.py	candle_cache = CandleCache() singleton at module scope calls _init_cache_tables() at import time — same pattern as 10.H-10, 12.H-7, 13.H-3. Runs DDL before env validation.
14.L-14	db_connection.py	check_pool_health() uses datetime.now().isoformat() (naive) for last_check. Should use datetime.now(tz=ET).isoformat() for consistency with the rest of the codebase.
14.L-15	candle_cache.py	_parse_cache_rows() calls hasattr(dt, "tzinfo") — all Python datetime objects always have tzinfo (it may be None). The hasattr check is redundant; use dt.tzinfo is not None directly.
14.L-16	All files	All print() calls should be logger.*. Same pattern flagged in batches 8–13.
Priority Fix Order
14.H-7 — _parse_cache_rows() strips TZ → naive UTC datetimes compared to ET session boundaries → _filter_session_bars() may return zero bars from cache on Railway

14.H-6 — is_cache_fresh() stamps ET onto UTC-stored last_bar_time → stale cache appears fresh → stale bar data used for signal generation

14.C-1 — Pool init at import with no retry → transient DB unavailability during Railway deploy crashes entire process

14.M-11 — NOT IN multi-column subquery is SQLite syntax — orphaned metadata never pruned on Postgres

14.M-9 — aggregate_to_timeframe() bucket keys not zeroing seconds — incorrect OHLCV aggregations

14.C-2 — Systemic: migrate all get_conn()/return_conn() callers to with get_connection() as conn: to eliminate connection leak class

14.H-3 — force_close_stale_connections() permanently shrinks pool — avoid calling in production




