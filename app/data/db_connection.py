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
  the code immediately raised RuntimeError, crashing the scanner.
- Fix: replace the immediate raise with a retry loop (DB_RECONNECT_RETRIES=3,
  delays: 1s / 2s / 3s). Only if all retries are exhausted does the error
  propagate.
- Added db_reconnect_failures counter to _pool_stats for observability.

FIX 14.C-4 (MAR 19, 2026): DOUBLE-INIT RACE — USE_POSTGRES FLIPPED TO FALSE
- Two threads could both pass the pre-lock `_connection_pool is not None` check
  simultaneously (neither had set it yet). Both entered _init_pool(), both ran
  psycopg2.connect() test pings. The first succeeded and built the pool. The
  second ran its test ping 20 s later when Railway had already dropped that
  transient test socket, got OperationalError, and hit the except branch which
  sets USE_POSTGRES = False — destroying the working pool mid-startup and
  causing all subsequent get_conn() calls to fall back to SQLite.
- Fix: the double-checked `_connection_pool is not None` guard is now INSIDE
  the lock body (it was only outside before). Once the lock is held, the thread
  re-checks the pool; if it's already been built it returns immediately without
  running the test ping. The OperationalError fallback path is also guarded: it
  only sets USE_POSTGRES = False when _connection_pool is still None (i.e. we
  truly failed to build one), never when a working pool already exists.

FIX (MAR 25, 2026): SEMAPHORE LIMIT INCREASE 12 → 14
- Root cause of the 30s timeout crash loop was a semaphore leak in
  production_helpers._db_operation_safe() (conn.close() instead of return_conn()).
  That leak is fixed in production_helpers.py. This change raises the limit from
  12 to 14 as a defensive buffer: the OR-window burst (analytics + monitor +
  ticker loop) can briefly need 13 slots, and the extra headroom prevents a
  single leaked slot from triggering the crash again.
- Still well below POOL_MAX=15 and Railway's ~20 connection cap.

FIX (MAR 26, 2026): ROLLBACK BEFORE PUTCONN IN return_conn()
- Any caller whose query raised an exception left the connection in Postgres'
  InFailedSqlTransaction state before calling return_conn(). putconn() returned
  the dirty connection to the pool, and the next caller to check it out received
  a connection that failed every query with:
    InFailedSqlTransaction: current transaction is aborted,
    commands ignored until end of transaction block
  The _validate_conn() SELECT 1 on checkout catches stale SSL sockets but does
  NOT catch aborted-transaction state (SELECT 1 can succeed in aborted state on
  some psycopg2 versions, and even when it fails the reconnect path only handles
  SSL EOF, not transaction state).
- Fix: call conn.rollback() inside return_conn() before putconn(). This is
  standard psycopg2 pool practice — always rollback on return to guarantee a
  clean idle state for the next borrower. rollback() on a clean (non-aborted)
  connection is a no-op, so there is zero cost when no error occurred.

DATA-2 AUDIT (MAR 31, 2026): print() → logger
- 4 residual print() calls replaced with logger.warning() / logger.info().
  Locations: get_conn() reconnect loop, get_conn() pool-busy path,
  return_conn() timeout warning. All Railway-visible logging now routes
  through the configured logger — no silent stdout leakage.

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
import logging

logger = logging.getLogger(__name__)


# Strip whitespace/newlines, then normalize postgres:// → postgresql://
_raw_url = os.getenv("DATABASE_URL", "").strip()
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql://"))


# ==============================================================================
# POOL CONFIGURATION
# ==============================================================================

POOL_MIN = 3
POOL_MAX = 15
POOL_RETRY_ATTEMPTS = 10
POOL_RETRY_BASE_DELAY = 0.1
CONNECTION_TIMEOUT_SECONDS = 300

# FIX 14.C-3
DB_RECONNECT_RETRIES = 3
DB_RECONNECT_DELAYS  = [1, 2, 3]

# FIX MAR 25, 2026: Raised 12 -> 14 as defensive buffer after semaphore leak
# fix in production_helpers.py. Still below POOL_MAX=15 and Railway's ~20 cap.
DB_SEMAPHORE_LIMIT = 14
_db_semaphore = threading.Semaphore(DB_SEMAPHORE_LIMIT)

_connection_pool = None
_pool_lock = threading.Lock()
_pool_stats = {
    "checkouts": 0,
    "returns": 0,
    "errors": 0,
    "timeouts": 0,
    "retries": 0,
    "semaphore_waiters": 0,
    "stale_reconnects": 0,
    "db_reconnect_failures": 0,
    "last_health_check": None
}
_checked_out_connections = {}
_stats_lock = threading.Lock()

if not USE_POSTGRES:
    logger.info("[DB] SQLite fallback mode (DATABASE_URL not set)")


# ==============================================================================
# LAZY POOL INIT (FIX 14.C-1, hardened by FIX 14.C-4)
# ==============================================================================

_pool_init_lock = threading.Lock()

def _init_pool():
    """
    Lazy pool initializer — called on first get_conn(), not at module import.

    FIX 14.C-1: Lazy init so module imports cleanly on Railway cold start.

    FIX 14.C-4: The pre-lock fast-path check is retained as a performance
    optimisation for the hot path (pool already up), but the authoritative
    guard is the identical check INSIDE the lock.  This prevents a second
    thread that passed the pre-lock check from re-running the test ping after
    the first thread already built the pool — which previously caused
    USE_POSTGRES to be flipped to False when the transient test socket was
    dropped by Railway's proxy ~20 s later.

    The OperationalError fallback only sets USE_POSTGRES = False when
    _connection_pool is still None, i.e. we genuinely failed to build a pool.
    It never tears down a pool that is already healthy.
    """
    global _connection_pool, USE_POSTGRES

    # Fast path — no lock needed when pool is already up
    if _connection_pool is not None:
        return
    if not USE_POSTGRES:
        return

    with _pool_init_lock:
        # --- Authoritative guard (FIX 14.C-4) ---
        # Re-check inside the lock. Any thread that was waiting here while
        # another thread built the pool will now see _connection_pool is not
        # None and return immediately, skipping the test ping entirely.
        if _connection_pool is not None:
            return
        if not USE_POSTGRES:
            return

        try:
            import psycopg2
            import psycopg2.extras
            from psycopg2 import pool as pg_pool

            logger.info("[DB] Testing PostgreSQL connection...")
            _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            _test.close()

            logger.info("[DB] Initializing connection pool...")
            _connection_pool = pg_pool.ThreadedConnectionPool(
                minconn=POOL_MIN,
                maxconn=POOL_MAX,
                dsn=DATABASE_URL,
                connect_timeout=10
            )
            logger.info(f"[DB] PostgreSQL pool active ({POOL_MIN}-{POOL_MAX} connections)")
            logger.info(f"[DB] Semaphore gate active (max {DB_SEMAPHORE_LIMIT} concurrent checkouts)")

        except Exception as e:
            # FIX 14.C-4: Only fall back to SQLite if we have not yet built a
            # pool. If _connection_pool is already set (built by a concurrent
            # thread that got here first) we do NOT touch USE_POSTGRES — the
            # working pool must not be destroyed.
            if _connection_pool is None:
                logger.info(f"[DB] PostgreSQL connection failed: {e}")
                logger.info("[DB] Falling back to SQLite")
                USE_POSTGRES = False
            else:
                # Pool was built by another thread; this exception came from
                # the redundant test ping — safe to ignore.
                logger.info(f"[DB] _init_pool() secondary test ping failed (pool already active, ignoring): {e}")


# ==============================================================================
# STALE CONNECTION VALIDATOR (FIX 14.C-2)
# ==============================================================================

def _validate_conn(conn) -> bool:
    """
    Ping conn with SELECT 1. Returns True if alive, False if socket is dead.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
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

    FIX #5: Retries with exponential backoff on pool exhaustion.
    FIX #6: Semaphore gate prevents thundering-herd on startup burst.
    FIX #8: semaphore_acquired flag prevents double-release.
    FIX 14.C-1: Lazy _init_pool() called here.
    FIX 14.C-2: _validate_conn() detects stale SSL sockets.
    FIX 14.C-3: Retry loop on double-validation failure (transient blip).
    FIX 14.C-4: _init_pool() no longer flips USE_POSTGRES=False on race.
    DATA-2: All print() calls replaced with logger.*.
    """
    _init_pool()

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

                    # FIX 14.C-2: validate socket before handing to caller
                    if not _validate_conn(conn):
                        logger.warning("[DB] Stale connection detected (SSL EOF) — discarding and reconnecting")
                        _discard_conn(conn)
                        with _stats_lock:
                            _pool_stats["stale_reconnects"] += 1

                        # FIX 14.C-3: retry fresh connection up to DB_RECONNECT_RETRIES
                        reconnected = False
                        for r_attempt, r_delay in enumerate(DB_RECONNECT_DELAYS, start=1):
                            conn = _connection_pool.getconn()
                            if conn is None:
                                logger.warning(f"[DB] Reconnect attempt {r_attempt}/{DB_RECONNECT_RETRIES}: pool returned None")
                                time.sleep(r_delay)
                                continue
                            if _validate_conn(conn):
                                reconnected = True
                                break
                            logger.warning(
                                f"[DB] Reconnect attempt {r_attempt}/{DB_RECONNECT_RETRIES} "
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
                                logger.warning(
                                    f"[DB] Pool busy, retrying... "
                                    f"(attempt {attempt + 1}/{POOL_RETRY_ATTEMPTS})"
                                )
                            time.sleep(delay)
                            continue

                    with _stats_lock:
                        _pool_stats["errors"] += 1
                    logger.warning(f"[DB] Connection checkout failed after {attempt + 1} attempts: {e}")
                    if semaphore_acquired:
                        _db_semaphore.release()
                        semaphore_acquired = False
                    raise

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
    Releases the semaphore slot.

    FIX MAR 26, 2026: rollback before putconn so any aborted transaction
    state is cleared before the connection is recycled to the pool.
    Without this, a caller whose query raised an exception would return
    a dirty connection, and the next borrower would immediately hit:
      InFailedSqlTransaction: current transaction is aborted,
      commands ignored until end of transaction block
    rollback() on a clean connection is a no-op — zero cost when no
    error occurred.
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
                    logger.warning(
                        f"[DB] Connection held for {checkout_duration:.1f}s "
                        f"(>{CONNECTION_TIMEOUT_SECONDS}s timeout) — possible leak!"
                    )
                    with _stats_lock:
                        _pool_stats["timeouts"] += 1

                # FIX MAR 26, 2026: always rollback before returning to pool
                # to clear any aborted transaction state left by a failed query.
                try:
                    conn.rollback()
                except Exception:
                    pass

                _connection_pool.putconn(conn)

            except Exception as e:
                logger.warning(f"[DB] Error returning connection to pool: {e}")
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
        "stale_reconnects": stats_copy["stale_reconnects"],
        "db_reconnect_failures": stats_copy["db_reconnect_failures"],
        "stale_connections": len(stale_connections),
        "last_check": datetime.now().isoformat()
    }

    with _stats_lock:
        _pool_stats["last_health_check"] = time.time()

    if leaked > 5:
        logger.warning(f"[DB] Pool health warning: {leaked} connections not returned (possible leak)")

    if stale_connections:
        logger.warning(f"[DB] {len(stale_connections)} stale connection(s) detected:")
        for conn_id, duration in stale_connections[:3]:
            logger.warning(f"[DB]   • Connection {conn_id}: held for {duration:.1f}s")

    return health


def print_pool_stats():
    """Print connection pool statistics for debugging."""
    health = check_pool_health()

    if not health["pooling"]:
        logger.info(f"[DB] Mode: {health['mode']} (no pooling)")
        return

    logger.info("\n" + "=" * 60)
    logger.info("CONNECTION POOL STATISTICS")
    logger.info("=" * 60)
    logger.info(f"Status:              {'HEALTHY' if health['healthy'] else 'WARNING'}")
    logger.info(f"Pool Size:           {health['pool_size']['min']}-{health['pool_size']['max']} connections")
    logger.info(f"Semaphore Gate:      {health['semaphore_limit']} max concurrent ({health['semaphore_available']} available)")
    logger.info(f"Total Checkouts:     {health['checkouts']}")
    logger.info(f"Total Returns:       {health['returns']}")
    logger.info(f"Currently Out:       {health['currently_checked_out']}")
    logger.info(f"Retry Events:        {health['retries']}")
    logger.info(f"Errors:              {health['errors']}")
    logger.info(f"Timeout Warnings:    {health['timeouts']}")
    logger.info(f"Semaphore Waiters:   {health['semaphore_waiters']}")
    logger.info(f"Stale Reconnects:    {health['stale_reconnects']}")
    logger.info(f"Reconnect Failures:  {health['db_reconnect_failures']}")
    logger.info(f"Stale Connections:   {health['stale_connections']}")
    logger.info("=" * 60 + "\n")


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

    logger.info(f"[DB] Force-clearing {len(stale)} stale tracking entries...")
    for conn_id in stale:
        with _stats_lock:
            _checked_out_connections.pop(conn_id, None)
        try:
            _db_semaphore.release()
        except Exception:
            pass

    logger.info(f"[DB] Cleared {len(stale)} stale entries")
    return len(stale)


def close_pool():
    """Close all connections in the pool. Call this on application shutdown."""
    global _connection_pool

    if USE_POSTGRES and _connection_pool is not None:
        logger.info("\n[DB] Shutting down connection pool...")
        print_pool_stats()

        with _pool_lock:
            _connection_pool.closeall()
            _connection_pool = None

        logger.info("[DB] Connection pool closed")


def get_pool_stats() -> dict:
    """Get connection pool statistics."""
    return check_pool_health()


# ==============================================================================
# DATABASE UTILITY FUNCTIONS
# ==============================================================================

def ph() -> str:
    """Single parameter placeholder: %s (Postgres) or ? (SQLite)."""
    return "%s" if USE_POSTGRES else "?"


def dict_cursor(conn):
    """Return a dictionary-capable cursor for either engine."""
    if USE_POSTGRES:
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


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
