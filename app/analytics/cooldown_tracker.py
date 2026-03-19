#!/usr/bin/env python3
"""
Signal Cooldown Tracker  (app.analytics.cooldown_tracker)  ← canonical
======================================================================
Prevents duplicate signals after Railway restarts by persisting cooldown
state to DB. Cooldown survives restarts and is auto-cleaned after expiration.

Cooldown Rules:
- Same ticker + same direction : 30 min minimum between signals
- Same ticker + opposite direction : 15 min minimum (allows reversal setups)

FIX 12.C-2 (Mar 19 2026): tz-aware vs naive timestamp comparison
  On Postgres, expires_at is returned as UTC-aware. When SQLite fallback
  or older psycopg2 returns a naive string, datetime.fromisoformat() produces
  a naive datetime. Comparing ET-aware `now` against a naive `expires_at`
  raises TypeError. Fix: ensure expires_at is always UTC-aware after load.

FIX 43.M-9 (Mar 19 2026): DELETE-on-read in hot path
  _cleanup_expired_cooldowns() was called inside _load_cooldowns_from_db()
  which is called on every is_on_cooldown() invocation (hot scanner path).
  That is a DELETE write on every read. Fix: removed from _load_cooldowns_from_db().
  Cleanup is now called only from set_cooldown() (natural write point) and
  exposed as a standalone function for EOD scheduler.

FIX 43.M-12 (Mar 19 2026): expires_at uses datetime.now(timezone.utc)
  instead of datetime.now(ZoneInfo("America/New_York")) for DB writes.
  Both are TZ-aware and psycopg2 handles either correctly, but UTC is the
  explicit convention that matches how Postgres stores/returns TIMESTAMPTZ,
  eliminating any ambiguity.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict
import logging
logger = logging.getLogger(__name__)

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
        logger.info(f"[COOLDOWN-DB] Init error: {e}")
    finally:
        if conn:
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
        logger.info(f"[COOLDOWN-DB] Persist error {ticker}: {e}")
    finally:
        if conn:
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
        logger.info(f"[COOLDOWN-DB] Remove error {ticker}: {e}")
    finally:
        if conn:
            return_conn(conn)


def cleanup_expired_cooldowns():
    """
    Delete expired cooldown rows from DB and evict them from the in-memory cache.

    FIX 43.M-9: Previously called inside _load_cooldowns_from_db() which runs
    on every is_on_cooldown() call (hot path). Moved here as a standalone
    function — called from set_cooldown() and available for EOD scheduler.
    """
    from app.data.db_connection import get_conn, return_conn, ph as _ph
    conn = None
    try:
        now = datetime.now(timezone.utc)
        conn = get_conn()
        p = _ph()
        cur = conn.cursor()
        cur.execute(f"DELETE FROM signal_cooldowns WHERE expires_at < {p}", (now,))
        if cur.rowcount > 0:
            logger.info(f"[COOLDOWN-DB] 🧹 Auto-cleaned {cur.rowcount} expired cooldown(s)")
        conn.commit()
        # Also evict from in-memory cache
        expired_keys = [t for t, c in _cooldown_cache.items() if now >= c["expires_at"]]
        for k in expired_keys:
            del _cooldown_cache[k]
    except Exception as e:
        logger.info(f"[COOLDOWN-DB] Cleanup error: {e}")
    finally:
        if conn:
            return_conn(conn)


# Keep internal alias for any legacy internal callers
_cleanup_expired_cooldowns = cleanup_expired_cooldowns


def _load_cooldowns_from_db() -> Dict[str, Dict]:
    """
    FIX 43.M-9: cleanup_expired_cooldowns() removed from here.
    FIX 12.C-2: expires_at normalised to UTC-aware after load.
    """
    from app.data.db_connection import get_conn, return_conn, dict_cursor as _dc
    conn = None
    try:
        conn = get_conn()
        cur = _dc(conn)
        cur.execute("SELECT ticker,direction,signal_type,expires_at FROM signal_cooldowns")
        loaded = {}
        now_utc = datetime.now(timezone.utc)
        for row in cur.fetchall():
            raw_exp = row["expires_at"]
            # FIX 12.C-2: normalise to UTC-aware
            if isinstance(raw_exp, str):
                raw_exp = datetime.fromisoformat(raw_exp)
            if raw_exp.tzinfo is None:
                raw_exp = raw_exp.replace(tzinfo=timezone.utc)
            # Skip already-expired rows (no write needed — cleanup_expired_cooldowns handles bulk)
            if now_utc >= raw_exp:
                continue
            loaded[row["ticker"]] = {
                "direction":   row["direction"],
                "signal_type": row["signal_type"],
                "expires_at":  raw_exp,
            }
        if loaded:
            logger.info(f"[COOLDOWN-DB] 📄 Reloaded {len(loaded)} cooldown(s): {', '.join(loaded.keys())}")
        return loaded
    except Exception as e:
        logger.info(f"[COOLDOWN-DB] Load error: {e}")
        return {}
    finally:
        if conn:
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
    now = datetime.now(timezone.utc)  # FIX 43.M-12: UTC for consistent comparison
    expires = cooldown["expires_at"]
    # FIX 12.C-2: ensure expires is UTC-aware before comparison
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now >= expires:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        return False, None
    prev_dir  = cooldown["direction"]
    time_left = int((expires - now).total_seconds() / 60)
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
    # FIX 43.M-12: use UTC for expires_at — matches TIMESTAMPTZ convention
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=COOLDOWN_SAME_DIRECTION_MINUTES)
    _cooldown_cache[ticker] = {"direction": direction, "signal_type": signal_type, "expires_at": expires_at}
    _persist_cooldown(ticker, direction, signal_type, expires_at)
    # FIX 43.M-9: natural write point — run cleanup here instead of on every read
    try:
        cleanup_expired_cooldowns()
    except Exception:
        pass
    et_exp = expires_at.astimezone(ZoneInfo("America/New_York"))
    logger.info(f"[COOLDOWN] {ticker} {direction.upper()} cooldown until {et_exp.strftime('%I:%M %p ET')} ({COOLDOWN_SAME_DIRECTION_MINUTES}m)")


def clear_cooldown(ticker: str):
    if ticker in _cooldown_cache:
        del _cooldown_cache[ticker]
        _remove_cooldown_from_db(ticker)
        logger.info(f"[COOLDOWN] {ticker} cooldown cleared")


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
        logger.info(f"[COOLDOWN-DB] Clear all error: {e}")
    finally:
        if conn:
            return_conn(conn)
    logger.info("[COOLDOWN] All cooldowns cleared")


def get_active_cooldowns() -> Dict[str, Dict]:
    _maybe_load_cooldowns()
    now = datetime.now(timezone.utc)
    return {
        ticker: {
            "direction":         c["direction"],
            "signal_type":       c["signal_type"],
            "expires_at":        c["expires_at"],
            "minutes_remaining": int((c["expires_at"] - now).total_seconds() / 60)
        }
        for ticker, c in _cooldown_cache.items() if now < c["expires_at"]
    }


def print_cooldown_summary():
    active = get_active_cooldowns()
    if not active:
        return
    logger.info("\n" + "="*80)
    logger.info("SIGNAL COOLDOWN SUMMARY")
    logger.info("="*80)
    logger.info(f"Active Cooldowns: {len(active)}")
    logger.info("Ticker   Direction  Signal Type      Expires At        Time Left")
    logger.info("-"*80)
    for ticker, d in sorted(active.items(), key=lambda x: x[1]['expires_at']):
        exp_et = d['expires_at'].astimezone(ZoneInfo("America/New_York"))
        print(
            f"{ticker:<8} {d['direction']:<10} {d['signal_type']:<16} "
            f"{exp_et.strftime('%I:%M %p ET'):<17} {d['minutes_remaining']}m"
        )
    logger.info("="*80 + "\n")


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
