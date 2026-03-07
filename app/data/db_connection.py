#!/usr/bin/env python3
"""
db_connection.py — Dual-mode database utility with CONNECTION POOLING

Automatically uses PostgreSQL on Railway (when DATABASE_URL is set),
falls back to SQLite for local development.

FIX #2: CONNECTION POOLING
- PostgreSQL: Uses psycopg2.pool.SimpleConnectionPool (2-10 connections)
- SQLite: Direct connections (pooling not needed for single-user)
- Thread-safe connection checkout/return
- Context manager for automatic cleanup

NOTE: Railway provides DATABASE_URL as postgres:// — psycopg2 requires
postgresql:// — we normalize it automatically here.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional

# Strip whitespace/newlines, then normalize postgres:// → postgresql://
_raw_url = os.getenv("DATABASE_URL", "").strip()
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql://"))

# ==============================================================================
# CONNECTION POOL (FIX #2)
# ==============================================================================

_connection_pool = None
_pool_lock = threading.Lock()

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool
        
        print("[DB] Testing PostgreSQL connection...")
        
        # Test connection with timeout
        _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        _test.close()
        
        # Initialize connection pool
        print("[DB] Initializing connection pool...")
        _connection_pool = pool.SimpleConnectionPool(
            minconn=2,  # Minimum connections to keep open
            maxconn=10,  # Maximum connections allowed
            dsn=DATABASE_URL,
            connect_timeout=10
        )
        
        print("[DB] ✅ PostgreSQL mode active with connection pooling (2-10 connections)")
    except psycopg2.OperationalError as e:
        print(f"[DB] ❌ PostgreSQL connection timeout or refused: {e}")
        print("[DB] ⚠️  Falling back to SQLite (database may not be ready)")
        USE_POSTGRES = False
    except Exception as e:
        print(f"[DB] ❌ PostgreSQL connection failed: {e}")
        print("[DB] ⚠️  Falling back to SQLite")
        USE_POSTGRES = False
else:
    print("[DB] SQLite fallback mode (DATABASE_URL not set)")


def get_conn(sqlite_path: str = "war_machine.db"):
    """
    Get a connection from the pool (PostgreSQL) or create new (SQLite).
    
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
        
        # Thread-safe connection checkout
        with _pool_lock:
            conn = _connection_pool.getconn()
        
        if conn is None:
            raise RuntimeError("Failed to get connection from pool")
        
        return conn
    
    # SQLite: Create new connection (no pooling needed)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def return_conn(conn):
    """
    Return a connection to the pool (PostgreSQL) or close it (SQLite).
    
    Args:
        conn: Database connection to return/close
    """
    if conn is None:
        return
    
    if USE_POSTGRES:
        if _connection_pool is None:
            conn.close()
        else:
            # Thread-safe connection return
            with _pool_lock:
                _connection_pool.putconn(conn)
    else:
        # SQLite: Just close
        conn.close()


@contextmanager
def get_connection(sqlite_path: str = "war_machine.db"):
    """
    Context manager for safe connection handling.
    Automatically returns connection to pool on exit.
    
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


def close_pool():
    """
    Close all connections in the pool.
    Call this on application shutdown.
    """
    global _connection_pool
    
    if USE_POSTGRES and _connection_pool is not None:
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
    if not USE_POSTGRES or _connection_pool is None:
        return {"pooling": False, "mode": "SQLite"}
    
    # Note: psycopg2.pool doesn't expose detailed stats
    # We'd need to track this ourselves if needed
    return {
        "pooling": True,
        "mode": "PostgreSQL",
        "minconn": 2,
        "maxconn": 10,
        "note": "Pool stats not available in SimpleConnectionPool"
    }


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
