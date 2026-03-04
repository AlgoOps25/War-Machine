"""
Production Helper Functions - Phase 3H

Safe wrappers for Discord, API, and database operations.
These prevent crashes from external service failures.
"""

import requests
import traceback


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
        print("[DISCORD] ⏱️  Alert timed out (continuing)")
        return False
    except requests.RequestException as e:
        print(f"[DISCORD] ❌ Request failed (continuing): {e}")
        return False
    except Exception as e:
        print(f"[DISCORD] ❌ Alert failed (continuing): {e}")
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
            print(f"[{ticker}] ⚠️  No {data_type} available")
            return None
        return data
    except Exception as e:
        print(f"[{ticker}] ❌ Failed to fetch {data_type}: {e}")
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
    
    Args:
        operation_func: Function that takes conn as argument and performs DB operation
        operation_name: Description for logging
    
    Returns:
        Result from operation_func, or None if failed
    """
    from db_connection import get_conn
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
                print(f"[DB] ↩️  Rolled back {operation_name}: {e}")
            except:
                print(f"[DB] ❌ Rollback failed for {operation_name}: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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
