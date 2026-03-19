#!/usr/bin/env python3
"""
db_connection.py — Dual-mode database utility with CONNECTION POOLING

Automatically uses PostgreSQL on Railway (when DATABASE_URL is set),
falls back to SQLite for local development.

FIX #2: CONNECTION POOLING
- PostgreSQL: Uses psycopg2.pool.ThreadedConnectionPool (min/max connections)
- SQLite: Direct connections (pooling not needed for single-user)
- Thread-safe connection checkout/return

FIX #4: CONNECTION LIFECYCLE MANAGEMENT
- Added connection leak detection and monitoring
- Added pool health checks and auto-recovery
- Added connection timeout tracking
- Fixed ensure-close patterns throughout codebase

FIX #5: POOL EXHAUSTION PREVENTION
- Upgraded SimpleConnectionPool → ThreadedConnectionPool (thread-safe internally)
- Added retry logic with exponential backoff (up to 10 attempts, max 2s delay)
- Removed redundant _pool_lock on getconn/putconn
- Added retries stat counter for observability

FIX #6: SEMAPHORE GATE (thundering-herd prevention)
- Added threading.Semaphore wrapping all get_conn() calls
- Prevents startup burst from exceeding pool capacity
- Semaphore is acquired BEFORE getconn() and released in return_conn() / error paths

FIX #7 (MAR 16, 2026): RAILWAY POSTGRES LIMIT ALIGNMENT
- Railway hobby plan caps at ~20 connections total (shared with system connections)
- POOL_MAX reduced 50 → 15 (leaves headroom for Railway internal connections)
- DB_SEMAPHORE_LIMIT reduced 40 → 12 (below POOL_MAX, leaves headroom)
- POOL_MIN reduced 10 → 3 (faster startup, less idle waste)
- Pool exhaustion was crashing scanner at 9:30 open (backfill + monitor + scan burst)

FIX #8 (MAR 16, 2026): DOUBLE SEMAPHORE RELEASE ON POOL EXHAUSTION
- When all POOL_RETRY_ATTEMPTS failed, the retry-exhaustion path released the
  semaphore then raised RuntimeError. The raise caused the outer except block
  to fire with semaphore_acquired still True, releasing the semaphore a second
  time and inflating its internal counter above DB_SEMAPHORE_LIMIT.
- Over time the gate stopped enforcing the cap, allowing >12 concurrent holders
  to pile up — causing the 30s timeout crash in monitor_open_positions().
- Fix: set semaphore_acquired = False immediately after release in the
  retry-exhaustion path so the outer except skips the redundant release.

FIX 14.C-1 (MAR 19, 2026): LAZY POOL INIT — RAILWAY COLD-START CRASH
- Pool was initialized at module import time via top-level if USE_POSTGRES block.
- If Railway's DB wasn't ready yet, the import-time psycopg2.connect() call
  raised OperationalError, crashing the entire process before main() ran.
- Fix: moved pool init into _init_pool(), called lazily on first get_conn().
  The module now imports cleanly regardless of DB availability.

FIX 14.C-2 (MAR 19, 2026): STALE SSL CONNECTION — SSL SYSCALL EOF
- Railway's Postgres TCP proxy silently drops idle connections after ~5 min.
  psycopg2's ThreadedConnectionPool keeps the dead socket in the pool and
  returns it on the next getconn() — the caller's first query then raises
  `psycopg2.OperationalError: SSL SYSCALL error: EOF detected`.
- Fix: _validate_conn() pings each checked-out connection with a lightweight
  SELECT 1 query.  If the ping raises OperationalError the connection is
  discarded (putconn + closed) and a fresh one is requested from the pool.
  A single reconnect attempt is made; if that also fails the error propagates
  normally so the scanner loop's existing error handler can restart cleanly.
- This is deliberately minimal — no infinite loop, no silent swallowing.

FIX 14.C-3 (MAR 19, 2026): TRANSIENT DB BLIP — DOUBLE-VALIDATION RETRY
- When both the stale connection AND the fresh reconnect failed _validate_conn(),
  the code immediately raised RuntimeError("Reconnected connection also failed
  validation — DB may be down"), crashing the scanner + triggering a Railway
  container restart.
- Root cause: Railway's Postgres proxy occasionally blips for <5s during
  intraday (observed at 10:19 AM EDT). The instant-fail path treated a
  transient blip the same as a true DB outage.
- Fix: replace the immediate raise with a retry loop (DB_RECONNECT_RETRIES=3,
  delays: 1s / 2s / 3s). Each attempt discards dead connections and requests
  a fresh one from the pool. Only if all retries are exhausted does the error
  propagate, at which point a true outage is a reasonable conclusion.
- Added db_reconnect_failures counter to _pool_stats for observability.

NOTE: Railway provides DATABASE_URL as postgres:// — psycopg2 requires
postgresql:// — we normalize it automatically here.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional
from datetime import datetime, timedelta


# Strip whitespace/newlines, then normalize postgres:// → postgresql://
_raw_url = os.getenv("DATABASE_URL", "").strip()
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql://"))


# ==============================================================================
# POOL CONFIGURATION
# ==============================================================================

# FIX #7: Railway hobby Postgres caps at ~20 connections (shared with pg system
# connections). Previous values (POOL_MAX=50, SEMAPHORE=40) caused pool exhaustion
# at 9:30 AM when backfill threads + monitor_open_positions + scan burst all hit
# the DB simultaneously.
POOL_MIN = 3           # Keep 3 warm connections at all times
POOL_MAX = 15          # Hard cap well below Railway's ~20 limit
POOL_RETRY_ATTEMPTS = 10
POOL_RETRY_BASE_DELAY = 0.1   # seconds; doubles each attempt, capped at 2.0s
CONNECTION_TIMEOUT_SECONDS = 300  # 5 minutes

# FIX 14.C-3: retry budget when BOTH the stale conn and the first fresh conn
# fail validation (transient Railway proxy blip).
DB_RECONNECT_RETRIES = 3          # max additional fresh-connection attempts
DB_RECONNECT_DELAYS  = [1, 2, 3]  # seconds to wait before each retry

# Semaphore gate — caps concurrent DB checkouts below POOL_MAX so that
# startup bursts never exhaust the pool even when many threads call get_conn().
DB_SEMAPHORE_LIMIT = 12   # Must be <= POOL_MAX; leaves headroom for health queries
_db_semaphore = threading.Semaphore(DB_SEMAPHORE_LIMIT)

_connection_pool = None
_pool_lock = threading.Lock()  # Only used for close_pool() shutdown guard
_pool_stats = {
    "checkouts": 0,
    "returns": 0,
    "errors": 0,
    "timeouts": 0,
    "retries": 0,
    "semaphore_waiters": 0,
    "stale_reconnects": 0,          # FIX 14.C-2
    "db_reconnect_failures": 0,     # FIX 14.C-3
    "last_health_check": None
}
_checked_out_connections = {}  # conn_id -> checkout epoch time
_stats_lock = threading.Lock()

if not USE_POSTGRES:
    print("[DB] SQLite fallback mode (DATABASE_URL not set)")


# ==============================================================================
# LAZY POOL INIT (FIX 14.C-1)
# ==============================================================================

_pool_init_lock = threading.Lock()  # Prevents double-init on concurrent first calls

def _init_pool():
    """
    Lazy pool initializer — called on first get_conn(), not at module import.

    FIX 14.C-1: Previously the pool was created at module import time inside a
    top-level `if USE_POSTGRES:` block. If Railway's DB wasn't ready at import
    time, psycopg2.connect() raised OperationalError and crashed the process
    before main() ever ran. Now the pool is created on first actual DB access,
    by which time Railway guarantees the DB is reachable.
    """
    global _connection_pool, USE_POSTGRES

    if _connection_pool is not None:
        return  # Already initialized — fast path, no lock needed
    if not USE_POSTGRES:
        return

    with _pool_init_lock:
        # Double-checked locking: another thread may have init'd while we waited
        if _connection_pool is not None:
            return

        try:
            import psycopg2
            import psycopg2.extras
            from psycopg2 import pool as pg_pool

            print("[DB] Testing PostgreSQL connection...")
            _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            _test.close()

            print("[DB] Initializing connection pool...")
            _connection_pool = pg_pool.ThreadedConnectionPool(
                minconn=POOL_MIN,
                maxconn=POOL_MAX,
                dsn=DATABASE_URL,
                connect_timeout=10
            )
            print(f"[DB] PostgreSQL pool active ({POOL_MIN}-{POOL_MAX} connections)")
            print(f"[DB] Semaphore gate active (max {DB_SEMAPHORE_LIMIT} concurrent checkouts)")

        except psycopg2.OperationalError as e:
            print(f"[DB] PostgreSQL connection timeout or refused: {e}")
            print("[DB] Falling back to SQLite (database may not be ready)")
            USE_POSTGRES = False
        except Exception as e:
            print(f"[DB] PostgreSQL connection failed: {e}")
            print("[DB] Falling back to SQLite")
            USE_POSTGRES = False


# ==============================================================================
# FIX 14.C-2: STALE CONNECTION VALIDATOR
# ==============================================================================

def _validate_conn(conn) -> bool:
    """
    Ping conn with a lightweight SELECT 1.  Returns True if the connection is
    alive, False if the Railway proxy has dropped the SSL socket.

    On failure the connection's internal state is rolled back so it can be
    safely putconn()'d back into the pool before being replaced.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        # Discard any open transaction started by the ping
        conn.rollback()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def _discard_conn(conn) -> None:
    """Safely return a known-dead connection to the pool and close the socket."""
    try:
        _connection_pool.putconn(conn, close=True)
    except Exception:
        pass


# ==============================================================================
# CONNECTION MANAGEMENT
# ==============================================================================

def get_conn(sqlite_path: str = "war_machine.db"):
    """
    Get a connection from the pool (PostgreSQL) or create new (SQLite).

    FIX #5: Retries up to POOL_RETRY_ATTEMPTS times with exponential backoff
    when pool is exhausted, instead of raising immediately.

    FIX #6: Acquires a semaphore slot BEFORE calling pool.getconn() to prevent
    thundering-herd exhaustion during startup when many threads hit the DB
    simultaneously (scanner backfill burst).

    FIX #8: semaphore_acquired is set to False immediately after any release
    inside the retry loop or retry-exhaustion path, so the outer except block
    never performs a double-release that would inflate the semaphore counter
    above DB_SEMAPHORE_LIMIT.

    FIX 14.C-1: _init_pool() called here (lazy) instead of at module import.

    FIX 14.C-2: After getconn() succeeds, _validate_conn() pings the socket.
    If the ping fails (SSL SYSCALL EOF), the dead connection is returned to the
    pool and discarded, then one fresh connection is requested.  This handles
    the Railway TCP proxy silently dropping idle connections after ~5 min.

    FIX 14.C-3: If the first fresh reconnect also fails validation (transient
    Railway proxy blip), retry up to DB_RECONNECT_RETRIES more times with
    increasing delays (1s / 2s / 3s) before propagating the error.  This
    prevents a <5s Railway blip from crashing the scanner.

    IMPORTANT: Caller must close the connection when done!
    Better to use `with get_connection() as conn:` context manager.
    """
    _init_pool()  # FIX 14.C-1 — lazy init, safe on Railway cold start

    if USE_POSTGRES:
        if _connection_pool is None:
            raise RuntimeError("Connection pool not initialized")

        semaphore_acquired = False
        try:
            if not _db_semaphore.acquire(blocking=True, timeout=30):
                with _stats_lock:
                    _pool_stats["errors"] += 1
                raise RuntimeError(
                    f"DB semaphore timeout after 30s — "
                    f"{DB_SEMAPHORE_LIMIT} concurrent connections already active"
                )
            semaphore_acquired = True
            with _stats_lock:
                _pool_stats["semaphore_waiters"] += 1

            last_error = None

            for attempt in range(POOL_RETRY_ATTEMPTS):
                try:
                    conn = _connection_pool.getconn()

                    if conn is None:
                        raise RuntimeError("Pool returned None connection")

                    # FIX 14.C-2: validate the socket before handing it to caller
                    if not _validate_conn(conn):
                        print("[DB] \u26a0\ufe0f  Stale connection detected (SSL EOF) — discarding and reconnecting")
                        _discard_conn(conn)
                        with _stats_lock:
                            _pool_stats["stale_reconnects"] += 1

                        # FIX 14.C-3: retry fresh connection up to DB_RECONNECT_RETRIES
                        # times before giving up — handles transient Railway proxy blips.
                        reconnected = False
                        for r_attempt, r_delay in enumerate(DB_RECONNECT_DELAYS, start=1):
                            conn = _connection_pool.getconn()
                            if conn is None:
                                print(f"[DB] \u26a0\ufe0f  Reconnect attempt {r_attempt}/{DB_RECONNECT_RETRIES}: pool returned None")
                                time.sleep(r_delay)
                                continue
                            if _validate_conn(conn):
                                reconnected = True
                                break
                            # This fresh conn is also dead
                            print(
                                f"[DB] \u26a0\ufe0f  Reconnect attempt {r_attempt}/{DB_RECONNECT_RETRIES} "
                                f"failed validation — waiting {r_delay}s before retry"
                            )
                            _discard_conn(conn)
                            with _stats_lock:
                                _pool_stats["db_reconnect_failures"] += 1
                            time.sleep(r_delay)

                        if not reconnected:
                            raise RuntimeError(
                                f"DB unavailable after {DB_RECONNECT_RETRIES} reconnect attempts "
                                f"— Railway proxy may be down"
                            )

                    conn_id = id(conn)
                    with _stats_lock:
                        _pool_stats["checkouts"] += 1
                        _checked_out_connections[conn_id] = time.time()
                        if attempt > 0:
                            _pool_stats["retries"] += 1

                    return conn

                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()

                    if any(k in error_str for k in ("exhausted", "pool", "none")):
                        if attempt < POOL_RETRY_ATTEMPTS - 1:
                            delay = min(POOL_RETRY_BASE_DELAY * (2 ** attempt), 2.0)
                            with _stats_lock:
                                _pool_stats["errors"] += 1
                            if attempt == 0:
                                print(
                                    f"[DB] Pool busy, retrying... "
                                    f"(attempt {attempt + 1}/{POOL_RETRY_ATTEMPTS})"
                                )
                            time.sleep(delay)
                            continue

                    with _stats_lock:
                        _pool_stats["errors"] += 1
                    print(f"[DB] Connection checkout failed after {attempt + 1} attempts: {e}")
                    if semaphore_acquired:
                        _db_semaphore.release()
                        semaphore_acquired = False  # FIX #8: prevent double-release in outer except
                    raise

            # FIX #8: clear flag before raise so outer except skips the redundant release
            if semaphore_acquired:
                _db_semaphore.release()
                semaphore_acquired = False
            raise RuntimeError(
                f"Connection pool exhausted after {POOL_RETRY_ATTEMPTS} retries: {last_error}"
            )

        except Exception:
            if semaphore_acquired:
                try:
                    _db_semaphore.release()
                except Exception:
                    pass
            raise

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def return_conn(conn):
    """
    Return a connection to the pool (PostgreSQL) or close it (SQLite).
    Releases the semaphore slot so another waiting thread can proceed.
    """
    if conn is None:
        return

    if USE_POSTGRES:
        if _connection_pool is None:
            try:
                conn.close()
            except Exception:
                pass
        else:
            try:
                conn_id = id(conn)
                checkout_duration = None

                with _stats_lock:
                    if conn_id in _checked_out_connections:
                        checkout_time = _checked_out_connections.pop(conn_id)
                        checkout_duration = time.time() - checkout_time
                    _pool_stats["returns"] += 1

                if checkout_duration and checkout_duration > CONNECTION_TIMEOUT_SECONDS:
                    print(
                        f"[DB] Connection held for {checkout_duration:.1f}s "
                        f"(>{CONNECTION_TIMEOUT_SECONDS}s timeout) — possible leak!"
                    )
                    with _stats_lock:
                        _pool_stats["timeouts"] += 1

                _connection_pool.putconn(conn)

            except Exception as e:
                print(f"[DB] Error returning connection to pool: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
            finally:
                try:
                    _db_semaphore.release()
                except Exception:
                    pass
    else:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_connection(sqlite_path: str = "war_machine.db"):
    """
    Context manager for safe connection handling.
    Always returns the connection to the pool on exit, even on exceptions.

    Usage:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM table")
            conn.commit()
    """
    conn = get_conn(sqlite_path)
    try:
        yield conn
    finally:
        return_conn(conn)


def check_pool_health() -> dict:
    """Check connection pool health and detect potential leaks."""
    if not USE_POSTGRES or _connection_pool is None:
        return {"healthy": True, "mode": "SQLite", "pooling": False}

    with _stats_lock:
        stats_copy = _pool_stats.copy()
        checked_out_copy = _checked_out_connections.copy()

    checkouts = stats_copy["checkouts"]
    returns = stats_copy["returns"]
    leaked = checkouts - returns

    now = time.time()
    stale_connections = [
        (conn_id, now - checkout_time)
        for conn_id, checkout_time in checked_out_copy.items()
        if (now - checkout_time) > CONNECTION_TIMEOUT_SECONDS
    ]

    semaphore_available = _db_semaphore._value

    health = {
        "healthy": leaked < 5 and len(stale_connections) == 0,
        "mode": "PostgreSQL",
        "pooling": True,
        "pool_size": {"min": POOL_MIN, "max": POOL_MAX},
        "semaphore_limit": DB_SEMAPHORE_LIMIT,
        "semaphore_available": semaphore_available,
        "checkouts": checkouts,
        "returns": returns,
        "currently_checked_out": leaked,
        "errors": stats_copy["errors"],
        "retries": stats_copy["retries"],
        "timeouts": stats_copy["timeouts"],
        "semaphore_waiters": stats_copy["semaphore_waiters"],
        "stale_reconnects": stats_copy["stale_reconnects"],        # FIX 14.C-2
        "db_reconnect_failures": stats_copy["db_reconnect_failures"],  # FIX 14.C-3
        "stale_connections": len(stale_connections),
        "last_check": datetime.now().isoformat()
    }

    with _stats_lock:
        _pool_stats["last_health_check"] = time.time()

    if leaked > 5:
        print(f"[DB] Pool health warning: {leaked} connections not returned (possible leak)")

    if stale_connections:
        print(f"[DB] {len(stale_connections)} stale connection(s) detected:")
        for conn_id, duration in stale_connections[:3]:
            print(f"[DB]   \u2022 Connection {conn_id}: held for {duration:.1f}s")

    return health


def print_pool_stats():
    """Print connection pool statistics for debugging."""
    health = check_pool_health()

    if not health["pooling"]:
        print(f"[DB] Mode: {health['mode']} (no pooling)")
        return

    print("\n" + "=" * 60)
    print("CONNECTION POOL STATISTICS")
    print("=" * 60)
    print(f"Status:              {'HEALTHY' if health['healthy'] else 'WARNING'}")
    print(f"Pool Size:           {health['pool_size']['min']}-{health['pool_size']['max']} connections")
    print(f"Semaphore Gate:      {health['semaphore_limit']} max concurrent ({health['semaphore_available']} available)")
    print(f"Total Checkouts:     {health['checkouts']}")
    print(f"Total Returns:       {health['returns']}")
    print(f"Currently Out:       {health['currently_checked_out']}")
    print(f"Retry Events:        {health['retries']}")
    print(f"Errors:              {health['errors']}")
    print(f"Timeout Warnings:    {health['timeouts']}")
    print(f"Semaphore Waiters:   {health['semaphore_waiters']}")
    print(f"Stale Reconnects:    {health['stale_reconnects']}")
    print(f"Reconnect Failures:  {health['db_reconnect_failures']}")
    print(f"Stale Connections:   {health['stale_connections']}")
    print("=" * 60 + "\n")


def force_close_stale_connections():
    """
    Emergency function to remove stale connection tracking entries.
    WARNING: Clears tracking dict only — does not forcibly close sockets.
    """
    if not USE_POSTGRES or _connection_pool is None:
        return 0

    now = time.time()
    with _stats_lock:
        stale = [
            conn_id for conn_id, t in _checked_out_connections.items()
            if (now - t) > CONNECTION_TIMEOUT_SECONDS
        ]

    if not stale:
        return 0

    print(f"[DB] Force-clearing {len(stale)} stale tracking entries...")
    for conn_id in stale:
        with _stats_lock:
            _checked_out_connections.pop(conn_id, None)
        try:
            _db_semaphore.release()
        except Exception:
            pass

    print(f"[DB] Cleared {len(stale)} stale entries")
    return len(stale)


def close_pool():
    """Close all connections in the pool. Call this on application shutdown."""
    global _connection_pool

    if USE_POSTGRES and _connection_pool is not None:
        print("\n[DB] Shutting down connection pool...")
        print_pool_stats()

        with _pool_lock:
            _connection_pool.closeall()
            _connection_pool = None

        print("[DB] Connection pool closed")


def get_pool_stats() -> dict:
    """Get connection pool statistics."""
    return check_pool_health()


# ==============================================================================
# DATABASE UTILITY FUNCTIONS (UNCHANGED)
# ==============================================================================

def ph() -> str:
    """Single parameter placeholder: %s (Postgres) or ? (SQLite)."""
    return "%s" if USE_POSTGRES else "?"


def dict_cursor(conn):
    """Return a dictionary-capable cursor for either engine."""
    if USE_POSTGRES:
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()   # row_factory already set on SQLite conn


def serial_pk() -> str:
    """Auto-increment primary key definition."""
    return "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def upsert_bar_sql() -> str:
    """INSERT/UPSERT SQL for intraday_bars (1m)."""
    if USE_POSTGRES:
        return """
            INSERT INTO intraday_bars
                (ticker, datetime, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, datetime) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
        """
    return """
        INSERT OR REPLACE INTO intraday_bars
            (ticker, datetime, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """


def upsert_bar_5m_sql() -> str:
    """INSERT/UPSERT SQL for intraday_bars_5m (materialized 5m)."""
    if USE_POSTGRES:
        return """
            INSERT INTO intraday_bars_5m
                (ticker, datetime, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, datetime) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
        """
    return """
        INSERT OR REPLACE INTO intraday_bars_5m
            (ticker, datetime, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """


def upsert_metadata_sql() -> str:
    """INSERT/UPSERT SQL for fetch_metadata."""
    p = ph()
    if USE_POSTGRES:
        return f"""
            INSERT INTO fetch_metadata (ticker, last_fetch, last_bar_time, bar_count)
            VALUES ({p}, CURRENT_TIMESTAMP, {p}, {p})
            ON CONFLICT (ticker) DO UPDATE SET
                last_fetch    = CURRENT_TIMESTAMP,
                last_bar_time = EXCLUDED.last_bar_time,
                bar_count     = EXCLUDED.bar_count
        """
    return f"""
        INSERT OR REPLACE INTO fetch_metadata
            (ticker, last_fetch, last_bar_time, bar_count)
        VALUES ({p}, CURRENT_TIMESTAMP, {p}, {p})
    """
