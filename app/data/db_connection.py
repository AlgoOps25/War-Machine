#!/usr/bin/env python3
"""
db_connection.py — Dual-mode database utility with CONNECTION POOLING

Automatically uses PostgreSQL on Railway (when DATABASE_URL is set),
falls back to SQLite for local development.

FIX #2: CONNECTION POOLING
- PostgreSQL: Uses psycopg2.pool.ThreadedConnectionPool (10-50 connections)
- SQLite: Direct connections (pooling not needed for single-user)
- Thread-safe connection checkout/return
- Context manager for automatic cleanup

FIX #4: CONNECTION LIFECYCLE MANAGEMENT
- Added connection leak detection and monitoring
- Added pool health checks and auto-recovery
- Added connection timeout tracking
- Fixed ensure-close patterns throughout codebase

FIX #5: POOL EXHAUSTION PREVENTION
- Upgraded SimpleConnectionPool → ThreadedConnectionPool (thread-safe internally)
- Increased pool size from 5-20 to 10-50 connections
- Added retry logic with exponential backoff (up to 10 attempts, max 2s delay)
- Removed redundant _pool_lock on getconn/putconn (ThreadedConnectionPool handles this)
- Added retries stat counter for observability

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
# POOL CONFIGURATION (FIX #5)
# ==============================================================================

POOL_MIN = 10          # Increased from 5 (FIX #5)
POOL_MAX = 50          # Increased from 20 (FIX #5)
POOL_RETRY_ATTEMPTS = 10
POOL_RETRY_BASE_DELAY = 0.1   # seconds; doubles each attempt, capped at 2.0s
CONNECTION_TIMEOUT_SECONDS = 300  # 5 minutes

_connection_pool = None
_pool_lock = threading.Lock()  # Only used for close_pool() shutdown guard
_pool_stats = {
    "checkouts": 0,
    "returns": 0,
    "errors": 0,
    "timeouts": 0,
    "retries": 0,
    "last_health_check": None
}
_checked_out_connections = {}  # conn_id -> checkout epoch time
_stats_lock = threading.Lock()

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool

        print("[DB] Testing PostgreSQL connection...")

        # Test connection with timeout
        _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        _test.close()

        # FIX #5: ThreadedConnectionPool replaces SimpleConnectionPool
        # ThreadedConnectionPool is internally thread-safe — no external lock needed
        # on getconn/putconn calls.
        print("[DB] Initializing connection pool...")
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=POOL_MIN,
            maxconn=POOL_MAX,
            dsn=DATABASE_URL,
            connect_timeout=10
        )

        print(f"[DB] PostgreSQL mode active with connection pooling ({POOL_MIN}-{POOL_MAX} connections)")
        print("[DB] FIX #4: Enhanced pool size + lifecycle monitoring")
        print("[DB] FIX #5: ThreadedConnectionPool + retry backoff + pool size 10-50")

    except psycopg2.OperationalError as e:
        print(f"[DB] PostgreSQL connection timeout or refused: {e}")
        print("[DB] Falling back to SQLite (database may not be ready)")
        USE_POSTGRES = False
    except Exception as e:
        print(f"[DB] PostgreSQL connection failed: {e}")
        print("[DB] Falling back to SQLite")
        USE_POSTGRES = False
else:
    print("[DB] SQLite fallback mode (DATABASE_URL not set)")


def get_conn(sqlite_path: str = "war_machine.db"):
    """
    Get a connection from the pool (PostgreSQL) or create new (SQLite).

    FIX #5: Retries up to POOL_RETRY_ATTEMPTS times with exponential backoff
    when pool is exhausted, instead of raising immediately. This prevents
    thundering-herd failures when 40+ tickers hit the DB simultaneously.

    IMPORTANT: Caller must close the connection when done!
    Better to use `with get_connection() as conn:` context manager.

    Args:
        sqlite_path: Path to SQLite database file (used only if not PostgreSQL)

    Returns:
        Database connection object
    """
    if USE_POSTGRES:
        if _connection_pool is None:
            raise RuntimeError("Connection pool not initialized")

        last_error = None

        for attempt in range(POOL_RETRY_ATTEMPTS):
            try:
                # FIX #5: ThreadedConnectionPool handles its own locking internally —
                # no _pool_lock wrapper needed here.
                conn = _connection_pool.getconn()

                if conn is None:
                    raise RuntimeError("Pool returned None connection")

                # Track checkout time (FIX #4)
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

                # Only retry on pool exhaustion — not on auth/network errors
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

                # Non-recoverable error
                with _stats_lock:
                    _pool_stats["errors"] += 1
                print(f"[DB] Connection checkout failed after {attempt + 1} attempts: {e}")
                raise

        raise RuntimeError(
            f"Connection pool exhausted after {POOL_RETRY_ATTEMPTS} retries: {last_error}"
        )

    # SQLite: Create new connection (no pooling needed)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def return_conn(conn):
    """
    Return a connection to the pool (PostgreSQL) or close it (SQLite).

    FIX #4/#5: Tracks checkout duration and warns on connection leaks.
    ThreadedConnectionPool handles its own locking — no _pool_lock needed.

    Args:
        conn: Database connection to return/close
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

                # Warn about long-held connections (FIX #4)
                if checkout_duration and checkout_duration > CONNECTION_TIMEOUT_SECONDS:
                    print(
                        f"[DB] Connection held for {checkout_duration:.1f}s "
                        f"(>{CONNECTION_TIMEOUT_SECONDS}s timeout) — possible leak!"
                    )
                    with _stats_lock:
                        _pool_stats["timeouts"] += 1

                # FIX #5: No _pool_lock needed — ThreadedConnectionPool is thread-safe
                _connection_pool.putconn(conn)

            except Exception as e:
                print(f"[DB] Error returning connection to pool: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
    else:
        # SQLite: Just close
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

    Args:
        sqlite_path: Path to SQLite database file (used only if not PostgreSQL)

    Yields:
        Database connection object
    """
    conn = get_conn(sqlite_path)
    try:
        yield conn
    finally:
        return_conn(conn)


def check_pool_health() -> dict:
    """
    Check connection pool health and detect potential leaks.

    Returns:
        Dictionary with pool health metrics
    """
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

    health = {
        "healthy": leaked < 5 and len(stale_connections) == 0,
        "mode": "PostgreSQL",
        "pooling": True,
        "pool_size": {"min": POOL_MIN, "max": POOL_MAX},
        "checkouts": checkouts,
        "returns": returns,
        "currently_checked_out": leaked,
        "errors": stats_copy["errors"],
        "retries": stats_copy["retries"],
        "timeouts": stats_copy["timeouts"],
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
    print(f"Total Checkouts:     {health['checkouts']}")
    print(f"Total Returns:       {health['returns']}")
    print(f"Currently Out:       {health['currently_checked_out']}")
    print(f"Retry Events:        {health['retries']}")
    print(f"Errors:              {health['errors']}")
    print(f"Timeout Warnings:    {health['timeouts']}")
    print(f"Stale Connections:   {health['stale_connections']}")
    print("=" * 60 + "\n")


def force_close_stale_connections():
    """
    Emergency function to remove stale connection tracking entries.

    WARNING: This clears the tracking dict only — it does not forcibly
    close underlying sockets. Use only as a last resort.
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

    print(f"[DB] Cleared {len(stale)} stale entries")
    return len(stale)


def close_pool():
    """
    Close all connections in the pool.
    Call this on application shutdown.
    """
    global _connection_pool

    if USE_POSTGRES and _connection_pool is not None:
        print("\n[DB] Shutting down connection pool...")
        print_pool_stats()

        with _pool_lock:
            _connection_pool.closeall()
            _connection_pool = None

        print("[DB] Connection pool closed")


def get_pool_stats() -> dict:
    """
    Get connection pool statistics.

    Returns:
        Dictionary with pool info (PostgreSQL) or empty dict (SQLite)
    """
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
