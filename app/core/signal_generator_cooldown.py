#!/usr/bin/env python3
"""
Signal Generator Cooldown - Issue #19

Prevents duplicate signals after Railway restarts by persisting cooldown state to DB.
Completes the persistence trilogy: watch state, armed signals, and now cooldown tracking.

Cooldown Rules:
- Same ticker + same direction: 30 minutes minimum between signals
- Same ticker + opposite direction: 15 minutes minimum (allows reversal setups)
- Cooldown survives restarts and is auto-cleaned after expiration

Public API:
    is_on_cooldown(ticker, direction)  -> (bool, reason|None)
    set_cooldown(ticker, direction, signal_type)
    clear_cooldown(ticker)
    clear_all_cooldowns()
    get_active_cooldowns()             -> dict
    print_cooldown_summary()

Compat shim (for legacy callers using the old CooldownTracker class):
    CooldownTracker  - delegates to module-level functions above
    cooldown_tracker - singleton instance of CooldownTracker
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════
COOLDOWN_SAME_DIRECTION_MINUTES = 30  # Same ticker + same direction
COOLDOWN_OPPOSITE_DIRECTION_MINUTES = 15  # Same ticker + opposite direction

# Module state
_cooldowns_loaded = False
_cooldown_cache: Dict[str, Dict] = {}  # {ticker: {direction, expires_at}}


# ══════════════════════════════════════════════════════════════════════════════
# Database Persistence
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_cooldown_table():
    """Create signal_cooldowns table if it doesn't exist."""
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_cooldowns (
                ticker      TEXT PRIMARY KEY,
                direction   TEXT        NOT NULL,
                signal_type TEXT        NOT NULL,
                expires_at  TIMESTAMP   NOT NULL,
                created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Init error: {e}")
    finally:
        return_conn(conn)


def _persist_cooldown(ticker: str, direction: str, signal_type: str, expires_at: datetime):
    """Upsert a cooldown entry to the DB."""
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"""
            INSERT INTO signal_cooldowns (ticker, direction, signal_type, expires_at, created_at)
            VALUES ({p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                direction   = EXCLUDED.direction,
                signal_type = EXCLUDED.signal_type,
                expires_at  = EXCLUDED.expires_at,
                created_at  = CURRENT_TIMESTAMP
            """,
            (ticker, direction, signal_type, expires_at)
        )
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Persist error for {ticker}: {e}")
    finally:
        return_conn(conn)


def _remove_cooldown_from_db(ticker: str):
    """Delete a cooldown entry from the DB."""
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"DELETE FROM signal_cooldowns WHERE ticker = {p}", (ticker,)
        )
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Remove error for {ticker}: {e}")
    finally:
        return_conn(conn)


def _cleanup_expired_cooldowns():
    """
    Remove cooldown entries from DB that have expired.
    Runs on startup and periodically during the trading session.
    """
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        now = datetime.now(ZoneInfo("America/New_York"))
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"DELETE FROM signal_cooldowns WHERE expires_at < {p}",
            (now,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            print(f"[COOLDOWN-DB] 🧹 Auto-cleaned {deleted_count} expired cooldown(s)")
    except Exception as e:
        print(f"[COOLDOWN-DB] Cleanup error: {e}")
    finally:
        return_conn(conn)


def _load_cooldowns_from_db() -> Dict[str, Dict]:
    """
    Load all active cooldowns from the DB.
    Returns dict of ticker -> {direction, signal_type, expires_at}.
    Expired cooldowns are auto-cleaned before loading.
    """
    from app.data.db_connection import get_conn, return_conn, dict_cursor as _dc
    conn = None
    try:
        _cleanup_expired_cooldowns()

        conn = get_conn()
        cursor = _dc(conn)
        cursor.execute("""
            SELECT ticker, direction, signal_type, expires_at
            FROM signal_cooldowns
        """)
        rows = cursor.fetchall()

        loaded = {}
        for row in rows:
            loaded[row["ticker"]] = {
                "direction": row["direction"],
                "signal_type": row["signal_type"],
                "expires_at": row["expires_at"] if isinstance(row["expires_at"], datetime)
                             else datetime.fromisoformat(str(row["expires_at"]))
            }

        if loaded:
            print(
                f"[COOLDOWN-DB] 📄 Reloaded {len(loaded)} cooldown(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        print(f"[COOLDOWN-DB] Load error: {e}")
        return {}
    finally:
        return_conn(conn)


def _maybe_load_cooldowns():
    """
    Called once per session on the first check_cooldown() invocation.
    Initializes the DB table and loads any surviving cooldown state into memory.
    """
    global _cooldowns_loaded, _cooldown_cache
    if _cooldowns_loaded:
        return
    _cooldowns_loaded = True
    _ensure_cooldown_table()
    loaded = _load_cooldowns_from_db()
    if loaded:
        _cooldown_cache.update(loaded)


# ══════════════════════════════════════════════════════════════════════════════
# Cooldown Logic
# ══════════════════════════════════════════════════════════════════════════════

def is_on_cooldown(ticker: str, direction: str) -> tuple[bool, Optional[str]]:
    """
    Check if a ticker is on cooldown for the given direction.

    Args:
        ticker: Stock symbol
        direction: 'bull' or 'bear'

    Returns:
        Tuple of (is_blocked: bool, reason: Optional[str])
    """
    _maybe_load_cooldowns()

    if ticker not in _cooldown_cache:
        return False, None

    cooldown = _cooldown_cache[ticker]
    now = datetime.now(ZoneInfo("America/New_York"))

    if now >= cooldown["expires_at"]:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        return False, None

    prev_direction = cooldown["direction"]
    time_left = int((cooldown["expires_at"] - now).total_seconds() / 60)

    if prev_direction == direction:
        reason = (
            f"Same-direction cooldown active ({time_left}m remaining from last {prev_direction.upper()} signal)"
        )
        return True, reason
    else:
        if time_left > COOLDOWN_OPPOSITE_DIRECTION_MINUTES:
            reason = (
                f"Reversal cooldown active ({time_left}m remaining, "
                f"minimum {COOLDOWN_OPPOSITE_DIRECTION_MINUTES}m for {direction.upper()} after {prev_direction.upper()})"
            )
            return True, reason
        else:
            del _cooldown_cache[ticker]
            _remove_cooldown_from_db(ticker)
            return False, None


def set_cooldown(ticker: str, direction: str, signal_type: str = "CFW6"):
    """
    Set a cooldown for a ticker after generating a signal.

    Args:
        ticker: Stock symbol
        direction: 'bull' or 'bear'
        signal_type: e.g. 'CFW6_OR' or 'CFW6_INTRADAY'
    """
    _maybe_load_cooldowns()

    now = datetime.now(ZoneInfo("America/New_York"))
    expires_at = now + timedelta(minutes=COOLDOWN_SAME_DIRECTION_MINUTES)

    _cooldown_cache[ticker] = {
        "direction": direction,
        "signal_type": signal_type,
        "expires_at": expires_at
    }

    _persist_cooldown(ticker, direction, signal_type, expires_at)

    print(
        f"[COOLDOWN] {ticker} {direction.upper()} on cooldown until "
        f"{expires_at.strftime('%I:%M %p ET')} ({COOLDOWN_SAME_DIRECTION_MINUTES}m)"
    )


def clear_cooldown(ticker: str):
    """Manually clear cooldown for a ticker (e.g., after manual intervention)."""
    if ticker in _cooldown_cache:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        print(f"[COOLDOWN] {ticker} cooldown cleared")


def clear_all_cooldowns():
    """Clear all cooldowns (e.g., at EOD or for testing)."""
    global _cooldowns_loaded, _cooldown_cache
    _cooldown_cache.clear()
    _cooldowns_loaded = False

    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM signal_cooldowns")
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Clear all error: {e}")
    finally:
        return_conn(conn)

    print("[COOLDOWN] All cooldowns cleared")


def get_active_cooldowns() -> Dict[str, Dict]:
    """Get all active cooldowns for monitoring/debugging."""
    _maybe_load_cooldowns()

    now = datetime.now(ZoneInfo("America/New_York"))
    active = {}

    for ticker, cooldown in _cooldown_cache.items():
        if now < cooldown["expires_at"]:
            time_left_min = int((cooldown["expires_at"] - now).total_seconds() / 60)
            active[ticker] = {
                "direction": cooldown["direction"],
                "signal_type": cooldown["signal_type"],
                "expires_at": cooldown["expires_at"],
                "minutes_remaining": time_left_min
            }

    return active


def print_cooldown_summary():
    """Print end-of-day cooldown summary."""
    active = get_active_cooldowns()

    if not active:
        return

    print("\n" + "="*80)
    print("SIGNAL COOLDOWN SUMMARY")
    print("="*80)
    print(f"Active Cooldowns: {len(active)}")
    print("\nTicker  Direction  Signal Type      Expires At        Time Left")
    print("-" * 80)

    for ticker, data in sorted(active.items(), key=lambda x: x[1]['expires_at']):
        print(
            f"{ticker:<8} {data['direction']:<10} {data['signal_type']:<16} "
            f"{data['expires_at'].strftime('%I:%M %p ET'):<17} {data['minutes_remaining']}m"
        )

    print("="*80 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# CooldownTracker compat shim
# Legacy callers (sniper.py, arm_signal.py) that imported
# `from app.analytics.cooldown_tracker import CooldownTracker, cooldown_tracker`
# can now import from this module instead and get identical behaviour.
# ══════════════════════════════════════════════════════════════════════════════

class CooldownTracker:
    """
    Compatibility shim wrapping the module-level cooldown functions.
    Provides the same API as the old app.analytics.cooldown_tracker.CooldownTracker.
    """

    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown_minutes = cooldown_minutes

    def set_cooldown(self, ticker: str, direction: str = "bull", signal_type: str = "CFW6") -> None:
        set_cooldown(ticker, direction, signal_type)

    def is_in_cooldown(self, ticker: str, direction: str = "bull") -> bool:
        blocked, _ = is_on_cooldown(ticker, direction)
        return blocked

    def get_cooldown_remaining(self, ticker: str) -> float:
        active = get_active_cooldowns()
        entry = active.get(ticker)
        if not entry:
            return 0.0
        return entry["minutes_remaining"] * 60.0

    def clear_cooldown(self, ticker: str) -> None:
        clear_cooldown(ticker)

    def clear_all_cooldowns(self) -> None:
        clear_all_cooldowns()

    def get_active_cooldowns(self) -> Dict:
        return get_active_cooldowns()

    def print_eod_report(self) -> None:
        print_cooldown_summary()


# Singleton instance for legacy `cooldown_tracker.cooldown_tracker` imports
cooldown_tracker = CooldownTracker(cooldown_minutes=COOLDOWN_SAME_DIRECTION_MINUTES)
