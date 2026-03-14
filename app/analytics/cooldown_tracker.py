#!/usr/bin/env python3
"""
Signal Cooldown Tracker  (app.analytics.cooldown_tracker)  ← canonical
======================================================================
Prevents duplicate signals after Railway restarts by persisting cooldown
state to DB. Cooldown survives restarts and is auto-cleaned after expiration.

Cooldown Rules:
- Same ticker + same direction : 30 min minimum between signals
- Same ticker + opposite direction : 15 min minimum (allows reversal setups)

Public API:
    is_on_cooldown(ticker, direction)  -> (bool, reason|None)
    set_cooldown(ticker, direction, signal_type)
    clear_cooldown(ticker)
    clear_all_cooldowns()
    get_active_cooldowns()             -> dict
    print_cooldown_summary()

Legacy class API (for old callers using CooldownTracker):
    CooldownTracker  - delegates to module-level functions
    cooldown_tracker - singleton instance
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict

COOLDOWN_SAME_DIRECTION_MINUTES     = 30
COOLDOWN_OPPOSITE_DIRECTION_MINUTES = 15

_cooldowns_loaded = False
_cooldown_cache: Dict[str, Dict] = {}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_cooldown_table():
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        conn.cursor().execute("""
            CREATE TABLE IF NOT EXISTS signal_cooldowns (
                ticker      TEXT PRIMARY KEY,
                direction   TEXT      NOT NULL,
                signal_type TEXT      NOT NULL,
                expires_at  TIMESTAMP NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Init error: {e}")
    finally:
        return_conn(conn)


def _persist_cooldown(ticker, direction, signal_type, expires_at):
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        conn = get_conn()
        p = _ph()
        conn.cursor().execute(
            f"INSERT INTO signal_cooldowns (ticker,direction,signal_type,expires_at,created_at) "
            f"VALUES ({p},{p},{p},{p},CURRENT_TIMESTAMP) "
            f"ON CONFLICT (ticker) DO UPDATE SET "
            f"direction=EXCLUDED.direction, signal_type=EXCLUDED.signal_type, "
            f"expires_at=EXCLUDED.expires_at, created_at=CURRENT_TIMESTAMP",
            (ticker, direction, signal_type, expires_at)
        )
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Persist error {ticker}: {e}")
    finally:
        return_conn(conn)


def _remove_cooldown_from_db(ticker):
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        conn = get_conn()
        p = _ph()
        conn.cursor().execute(f"DELETE FROM signal_cooldowns WHERE ticker={p}", (ticker,))
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Remove error {ticker}: {e}")
    finally:
        return_conn(conn)


def _cleanup_expired_cooldowns():
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        now = datetime.now(ZoneInfo("America/New_York"))
        conn = get_conn()
        p = _ph()
        cur = conn.cursor()
        cur.execute(f"DELETE FROM signal_cooldowns WHERE expires_at < {p}", (now,))
        if cur.rowcount > 0:
            print(f"[COOLDOWN-DB] 🧹 Auto-cleaned {cur.rowcount} expired cooldown(s)")
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Cleanup error: {e}")
    finally:
        return_conn(conn)


def _load_cooldowns_from_db() -> Dict[str, Dict]:
    from app.data.db_connection import get_conn, return_conn, dict_cursor as _dc
    conn = None
    try:
        _cleanup_expired_cooldowns()
        conn = get_conn()
        cur = _dc(conn)
        cur.execute("SELECT ticker,direction,signal_type,expires_at FROM signal_cooldowns")
        loaded = {}
        for row in cur.fetchall():
            loaded[row["ticker"]] = {
                "direction":   row["direction"],
                "signal_type": row["signal_type"],
                "expires_at":  row["expires_at"] if isinstance(row["expires_at"], datetime)
                               else datetime.fromisoformat(str(row["expires_at"]))
            }
        if loaded:
            print(f"[COOLDOWN-DB] 📄 Reloaded {len(loaded)} cooldown(s): {', '.join(loaded.keys())}")
        return loaded
    except Exception as e:
        print(f"[COOLDOWN-DB] Load error: {e}")
        return {}
    finally:
        return_conn(conn)


def _maybe_load_cooldowns():
    global _cooldowns_loaded, _cooldown_cache
    if _cooldowns_loaded:
        return
    _cooldowns_loaded = True
    _ensure_cooldown_table()
    _cooldown_cache.update(_load_cooldowns_from_db())


# ── Public API ────────────────────────────────────────────────────────────────

def is_on_cooldown(ticker: str, direction: str) -> tuple[bool, Optional[str]]:
    _maybe_load_cooldowns()
    if ticker not in _cooldown_cache:
        return False, None
    cooldown = _cooldown_cache[ticker]
    now = datetime.now(ZoneInfo("America/New_York"))
    if now >= cooldown["expires_at"]:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        return False, None
    prev_dir   = cooldown["direction"]
    time_left  = int((cooldown["expires_at"] - now).total_seconds() / 60)
    if prev_dir == direction:
        return True, f"Same-direction cooldown active ({time_left}m remaining from last {prev_dir.upper()} signal)"
    if time_left > COOLDOWN_OPPOSITE_DIRECTION_MINUTES:
        return True, (
            f"Reversal cooldown active ({time_left}m remaining, "
            f"min {COOLDOWN_OPPOSITE_DIRECTION_MINUTES}m for {direction.upper()} after {prev_dir.upper()})"
        )
    del _cooldown_cache[ticker]
    _remove_cooldown_from_db(ticker)
    return False, None


def set_cooldown(ticker: str, direction: str, signal_type: str = "CFW6"):
    _maybe_load_cooldowns()
    now = datetime.now(ZoneInfo("America/New_York"))
    expires_at = now + timedelta(minutes=COOLDOWN_SAME_DIRECTION_MINUTES)
    _cooldown_cache[ticker] = {"direction": direction, "signal_type": signal_type, "expires_at": expires_at}
    _persist_cooldown(ticker, direction, signal_type, expires_at)
    print(f"[COOLDOWN] {ticker} {direction.upper()} cooldown until {expires_at.strftime('%I:%M %p ET')} ({COOLDOWN_SAME_DIRECTION_MINUTES}m)")


def clear_cooldown(ticker: str):
    if ticker in _cooldown_cache:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        print(f"[COOLDOWN] {ticker} cooldown cleared")


def clear_all_cooldowns():
    global _cooldowns_loaded, _cooldown_cache
    _cooldown_cache.clear()
    _cooldowns_loaded = False
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        conn.cursor().execute("DELETE FROM signal_cooldowns")
        conn.commit()
    except Exception as e:
        print(f"[COOLDOWN-DB] Clear all error: {e}")
    finally:
        return_conn(conn)
    print("[COOLDOWN] All cooldowns cleared")


def get_active_cooldowns() -> Dict[str, Dict]:
    _maybe_load_cooldowns()
    now = datetime.now(ZoneInfo("America/New_York"))
    return {
        ticker: {
            "direction":       c["direction"],
            "signal_type":     c["signal_type"],
            "expires_at":      c["expires_at"],
            "minutes_remaining": int((c["expires_at"] - now).total_seconds() / 60)
        }
        for ticker, c in _cooldown_cache.items() if now < c["expires_at"]
    }


def print_cooldown_summary():
    active = get_active_cooldowns()
    if not active:
        return
    print("\n" + "="*80)
    print("SIGNAL COOLDOWN SUMMARY")
    print("="*80)
    print(f"Active Cooldowns: {len(active)}")
    print("Ticker   Direction  Signal Type      Expires At        Time Left")
    print("-"*80)
    for ticker, d in sorted(active.items(), key=lambda x: x[1]['expires_at']):
        print(
            f"{ticker:<8} {d['direction']:<10} {d['signal_type']:<16} "
            f"{d['expires_at'].strftime('%I:%M %p ET'):<17} {d['minutes_remaining']}m"
        )
    print("="*80 + "\n")


# ── Legacy class shim ─────────────────────────────────────────────────────────

class CooldownTracker:
    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown_minutes = cooldown_minutes

    def set_cooldown(self, ticker, direction="bull", signal_type="CFW6"):
        set_cooldown(ticker, direction, signal_type)

    def is_in_cooldown(self, ticker, direction="bull") -> bool:
        blocked, _ = is_on_cooldown(ticker, direction)
        return blocked

    def get_cooldown_remaining(self, ticker) -> float:
        entry = get_active_cooldowns().get(ticker)
        return entry["minutes_remaining"] * 60.0 if entry else 0.0

    def clear_cooldown(self, ticker): clear_cooldown(ticker)
    def clear_all_cooldowns(self): clear_all_cooldowns()
    def get_active_cooldowns(self): return get_active_cooldowns()
    def print_eod_report(self): print_cooldown_summary()


cooldown_tracker = CooldownTracker(cooldown_minutes=COOLDOWN_SAME_DIRECTION_MINUTES)
