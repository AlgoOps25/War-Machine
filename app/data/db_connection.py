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
            print(f"[DB]   • Connection {conn_id}: held for {duration:.1f}s")

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
