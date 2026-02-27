"""
db_connection.py — Dual-mode database utility
Automatically uses PostgreSQL on Railway (when DATABASE_URL is set),
falls back to SQLite for local development.

NOTE: Railway provides DATABASE_URL as postgres:// — psycopg2 requires
postgresql:// — we normalize it automatically here.

FIXED: Added connection timeout to prevent startup hangs.
FIXED: dict_cursor now returns usable cursor for both PostgreSQL and SQLite

PHASE 2B: Moved to utils/ folder for better organization.
"""
import os
import sqlite3

# Strip whitespace/newlines, then normalize postgres:// → postgresql://
_raw_url = os.getenv("DATABASE_URL", "").strip()
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
USE_POSTGRES  = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql://"))

# Test the connection at startup with timeout — fall back to SQLite if it fails
if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        
        print("[DB] Testing PostgreSQL connection...")
        
        # Add connection timeout to prevent startup hang
        _test = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        _test.close()
        
        print("[DB] ✅ PostgreSQL mode active")
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
    Return an open connection for the current environment.
    
    Args:
        sqlite_path: Path to SQLite database file (used only if not PostgreSQL)
    
    Returns:
        Database connection object
    """
    if USE_POSTGRES:
        # Add timeout for runtime connections too
        return psycopg2.connect(DATABASE_URL, connect_timeout=10)
    
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def ph() -> str:
    """Single parameter placeholder: %s (Postgres) or ? (SQLite)."""
    return "%s" if USE_POSTGRES else "?"


def dict_cursor(conn):
    """
    Return a dictionary-capable cursor for either engine.
    
    FIXED: SQLite cursors don't support context manager protocol (no __enter__/__exit__).
    Instead of returning a bare cursor that fails with `with dict_cursor(conn):`,
    we ensure row_factory is set so cursor.fetchone()/fetchall() return dict-like objects.
    
    For SQLite: Returns regular cursor (row_factory already makes rows dict-like via Row objects)
    For PostgreSQL: Returns RealDictCursor (native dict support)
    """
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # SQLite: Ensure row_factory is set (should already be from get_conn)
    if not hasattr(conn, 'row_factory') or conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    
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
