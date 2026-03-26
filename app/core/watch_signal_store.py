# Watch Signal Store — DB persistence for watching signals
# Extracted from sniper.py (Phase 2 refactor)
# Owns: _ensure_watch_db, _persist_watch, _remove_watch_from_db,
#       _cleanup_stale_watches, _load_watches_from_db, _maybe_load_watches
#
# FIX I (2026-03-26): Added _watch_load_lock to _maybe_load_watches().
#   armed_signal_store.py correctly wraps _maybe_load_armed_signals() in a
#   threading.Lock() to prevent double-load on concurrent startup. This file
#   had no equivalent lock — two threads could both see is_watches_loaded()==False
#   simultaneously and both execute _load_watches_from_db(), duplicating watch
#   state in memory. Now matches the pattern used by armed_signal_store.py.

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.thread_safe_state import get_state
from app.data.sql_safe import safe_execute, safe_query, get_placeholder
import logging
logger = logging.getLogger(__name__)

_state = get_state()

MAX_WATCH_BARS = 12  # mirrored from sniper — watch window in bars (5m each)

# FIX I: lock mirrors _armed_load_lock in armed_signal_store.py
_watch_load_lock = __import__('threading').Lock()


def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def _strip_tz(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if hasattr(dt, "tzinfo") and dt.tzinfo else dt


def _ensure_watch_db():
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watching_signals_persist (
                ticker          TEXT PRIMARY KEY,
                direction       TEXT        NOT NULL,
                breakout_bar_dt TIMESTAMP   NOT NULL,
                or_high         REAL        NOT NULL,
                or_low          REAL        NOT NULL,
                signal_type     TEXT        NOT NULL,
                saved_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        logger.info(f"[WATCH-DB] Init error: {e}")
    finally:
        if conn:
            return_conn(conn)


def _persist_watch(ticker: str, data: dict):
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        query = f"""
            INSERT INTO watching_signals_persist
                (ticker, direction, breakout_bar_dt, or_high, or_low, signal_type, saved_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                direction       = EXCLUDED.direction,
                breakout_bar_dt = EXCLUDED.breakout_bar_dt,
                or_high         = EXCLUDED.or_high,
                or_low          = EXCLUDED.or_low,
                signal_type     = EXCLUDED.signal_type,
                saved_at        = CURRENT_TIMESTAMP
        """
        safe_execute(cursor, query, (
            ticker,
            data["direction"],
            data["breakout_bar_dt"],
            data["or_high"],
            data["or_low"],
            data["signal_type"],
        ))
        conn.commit()
    except Exception as e:
        logger.info(f"[WATCH-DB] Persist error for {ticker}: {e}")
    finally:
        if conn:
            return_conn(conn)


def _remove_watch_from_db(ticker: str):
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        safe_execute(cursor, f"DELETE FROM watching_signals_persist WHERE ticker = {p}", (ticker,))
        conn.commit()
    except Exception as e:
        logger.info(f"[WATCH-DB] Remove error for {ticker}: {e}")
    finally:
        if conn:
            return_conn(conn)


def _cleanup_stale_watches():
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        watch_window_minutes = MAX_WATCH_BARS * 5
        cutoff_time = _now_et() - timedelta(minutes=watch_window_minutes)
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        safe_execute(cursor,
                    f"DELETE FROM watching_signals_persist WHERE breakout_bar_dt < {p}",
                    (cutoff_time,))
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.info(f"[WATCH-DB] 🧹 Auto-cleaned {deleted_count} stale watch(es) (older than {watch_window_minutes}min)")
    except Exception as e:
        logger.info(f"[WATCH-DB] Cleanup error: {e}")
    finally:
        if conn:
            return_conn(conn)


def _load_watches_from_db() -> dict:
    from app.data.db_connection import get_conn, return_conn, dict_cursor as _dc, USE_POSTGRES as _USE_PG
    conn = None
    try:
        _cleanup_stale_watches()
        conn = get_conn()
        cursor = _dc(conn)
        p = get_placeholder(conn)
        today_et = _now_et().date()
        if _USE_PG:
            query = f"""
                SELECT ticker, direction, breakout_bar_dt, or_high, or_low, signal_type
                FROM   watching_signals_persist
                WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = {p}
            """
        else:
            query = f"""
                SELECT ticker, direction, breakout_bar_dt, or_high, or_low, signal_type
                FROM   watching_signals_persist
                WHERE  DATE(saved_at) = {p}
            """
        rows = safe_query(cursor, query, (today_et,))
        loaded = {}
        for row in rows:
            loaded[row["ticker"]] = {
                "direction":       row["direction"],
                "breakout_idx":    None,
                "breakout_bar_dt": _strip_tz(row["breakout_bar_dt"]),
                "or_high":         row["or_high"],
                "or_low":          row["or_low"],
                "signal_type":     row["signal_type"],
            }
        if loaded:
            print(
                f"[WATCH-DB] 📄 Reloaded {len(loaded)} watch state(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        logger.info(f"[WATCH-DB] Load error: {e}")
        return {}
    finally:
        if conn:
            return_conn(conn)


def _maybe_load_watches():
    # FIX I (2026-03-26): lock prevents double-load when two threads both see
    # is_watches_loaded()==False simultaneously at startup.
    with _watch_load_lock:
        if _state.is_watches_loaded():
            return
        _state.set_watches_loaded(True)
    _ensure_watch_db()
    loaded = _load_watches_from_db()
    if loaded:
        _state.update_watching_signals_bulk(loaded)


def send_bos_watch_alert(ticker, direction, bos_price, struct_high, struct_low,
                          signal_type="CFW6_INTRADAY"):
    """Send Discord alert when BOS is detected and we enter watch mode."""
    from app.notifications.discord_helpers import send_simple_message
    arrow = "🟢" if direction == "bull" else "🔴"
    level = f"${struct_high:.2f}" if direction == "bull" else f"${struct_low:.2f}"
    mode_tag = "[OR]" if signal_type == "CFW6_OR" else "[INTRADAY]"
    msg = (
        f"📡 **BOS ALERT {mode_tag}: {ticker}** — {arrow} {direction.upper()}\n"
        f"Break: **${bos_price:.2f}** | Level: {level}\n"
        f"⏳ Watching for FVG (up to {MAX_WATCH_BARS} min) | "
        f"🕐 {_now_et().strftime('%I:%M %p ET')}"
    )
    try:
        send_simple_message(msg)
        logger.info(f"[WATCH] 📡 {ticker} {direction.upper()} BOS @ ${bos_price:.2f}")
    except Exception as e:
        logger.info(f"[WATCH] Alert error: {e}")

def clear_watching_signals():
    """Clear all watching signals from memory and DB."""
    from app.data.db_connection import get_conn, return_conn
    from app.data.sql_safe import safe_execute
    _state.clear_watching_signals()
    conn = None
    try:
