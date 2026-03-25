"""
Production Helper Functions - Phase 3H

Safe wrappers for Discord, API, and database operations.
These prevent crashes from external service failures.

FIX (MAR 25, 2026): SEMAPHORE LEAK IN _db_operation_safe()
  - _db_operation_safe() called conn.close() in its finally block instead of
    return_conn(). conn.close() only closes the TCP socket — it does NOT call
    _db_semaphore.release(). Every analytics cycle permanently consumed one
    semaphore slot. After 12 cycles the semaphore hit 0, all subsequent
    get_conn() calls timed out at 30s, and the scanner entered a crash loop.
  - Fix: replace conn.close() with return_conn(conn) so the semaphore slot is
    always released back to the pool on every call.
"""

import requests
import traceback
import logging
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════
# SAFE DISCORD WRAPPER - Phase 3H Production Hardening
# ════════════════════════════════════════════════════════════════════════════════

def _send_alert_safe(alert_func, *args, **kwargs):
    """
    Send Discord alert without blocking on failure.
    Trading continues even if Discord is down.
    
    Args:
        alert_func: The Discord alert function to call
        *args, **kwargs: Arguments to pass to alert_func
    
    Returns:
        bool: True if successful, False if failed
    """
    try:
        alert_func(*args, **kwargs)
        return True
    except requests.Timeout:
        logger.info("[DISCORD] ⏱️  Alert timed out (continuing)")
        return False
    except requests.RequestException as e:
        logger.info(f"[DISCORD] ❌ Request failed (continuing): {e}")
        return False
    except Exception as e:
        logger.info(f"[DISCORD] ❌ Alert failed (continuing): {e}")
        return False

# Usage:
# OLD: send_options_signal_alert(ticker=ticker, ...)
# NEW: _send_alert_safe(send_options_signal_alert, ticker=ticker, ...)


# ════════════════════════════════════════════════════════════════════════════════
# SAFE API WRAPPER - Phase 3H Production Hardening
# ════════════════════════════════════════════════════════════════════════════════

def _fetch_data_safe(ticker, data_func, data_type="data"):
    """
    Safely fetch data from data_manager with error handling.
    
    Args:
        ticker: Stock ticker symbol
        data_func: Function to call (e.g., data_manager.get_today_session_bars)
        data_type: Description of data being fetched (for logging)
    
    Returns:
        Data from data_func, or None if failed
    """
    try:
        data = data_func(ticker)
        if not data:
            logger.info(f"[{ticker}] ⚠️  No {data_type} available")
            return None
        return data
    except Exception as e:
        logger.info(f"[{ticker}] ❌ Failed to fetch {data_type}: {e}")
        import traceback
        traceback.print_exc()
        return None

# Usage:
# OLD: bars_session = data_manager.get_today_session_bars(ticker)
# NEW: bars_session = _fetch_data_safe(ticker, lambda t: data_manager.get_today_session_bars(t), "session bars")
#      if bars_session is None:
#          return


# ════════════════════════════════════════════════════════════════════════════════
# SAFE DATABASE WRAPPER - Phase 3H Production Hardening
# ════════════════════════════════════════════════════════════════════════════════

def _db_operation_safe(operation_func, operation_name="DB operation"):
    """
    Execute database operation with automatic rollback on error.

    FIX (MAR 25, 2026): Use return_conn() instead of conn.close().
    conn.close() only shuts the TCP socket — it never calls
    _db_semaphore.release(). Every call was permanently leaking one semaphore
    slot, exhausting the gate (limit=12) after ~12 analytics cycles and
    causing the 30s timeout crash loop in get_conn().

    Args:
        operation_func: Function that takes conn as argument and performs DB operation
        operation_name: Description for logging
    
    Returns:
        Result from operation_func, or None if failed
    """
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        result = operation_func(conn)
        conn.commit()
        return result
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                logger.info(f"[DB] ↩️  Rolled back {operation_name}: {e}")
            except Exception:
                logger.info(f"[DB] ❌ Rollback failed for {operation_name}: {e}")
        raise
    finally:
        if conn:
            return_conn(conn)   # ← releases semaphore slot correctly

# Usage example:
# def _persist_operation(conn):
#     cursor = conn.cursor()
#     cursor.execute("INSERT INTO ...")
#     return cursor.lastrowid
# 
# try:
#     result = _db_operation_safe(_persist_operation, "persist armed signal")
# except Exception as e:
#     print(f"[{ticker}] ⚠️  Failed to persist (memory only)")
