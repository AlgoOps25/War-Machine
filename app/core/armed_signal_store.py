# Armed Signal Store — DB persistence for armed signals
# Extracted from sniper.py (Phase 2 refactor)
# Owns: _ensure_armed_db, _persist_armed_signal, _remove_armed_from_db,
#       _cleanup_stale_armed_signals, _load_armed_signals_from_db, _maybe_load_armed_signals

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.thread_safe_state import get_state
from app.data.sql_safe import safe_execute, safe_query, safe_in_clause, get_placeholder
from app.risk.position_manager import position_manager
import logging
logger = logging.getLogger(__name__)

_state = get_state()


def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def _ensure_armed_db():
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS armed_signals_persist (
                ticker          TEXT PRIMARY KEY,
                position_id     INTEGER     NOT NULL,
                direction       TEXT        NOT NULL,
                entry_price     REAL        NOT NULL,
                stop_price      REAL        NOT NULL,
                t1              REAL        NOT NULL,
                t2              REAL        NOT NULL,
                confidence      REAL        NOT NULL,
                grade           TEXT        NOT NULL,
                signal_type     TEXT        NOT NULL,
                validation_data TEXT,
                saved_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        logger.info(f"[ARMED-DB] Init error: {e}")
    finally:
        if conn:
            return_conn(conn)


def _persist_armed_signal(ticker: str, data: dict):
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        validation_json = None
        if data.get("validation"):
            try:
                validation_json = json.dumps(data["validation"])
            except Exception:
                validation_json = None
        query = f"""
            INSERT INTO armed_signals_persist
                (ticker, position_id, direction, entry_price, stop_price, t1, t2,
                 confidence, grade, signal_type, validation_data, saved_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                position_id     = EXCLUDED.position_id,
                direction       = EXCLUDED.direction,
                entry_price     = EXCLUDED.entry_price,
                stop_price      = EXCLUDED.stop_price,
                t1              = EXCLUDED.t1,
                t2              = EXCLUDED.t2,
                confidence      = EXCLUDED.confidence,
                grade           = EXCLUDED.grade,
                signal_type     = EXCLUDED.signal_type,
                validation_data = EXCLUDED.validation_data,
                saved_at        = CURRENT_TIMESTAMP
        """
        safe_execute(cursor, query, (
            ticker,
            data["position_id"],
            data["direction"],
            data["entry_price"],
            data["stop_price"],
            data["t1"],
            data["t2"],
            data["confidence"],
            data["grade"],
            data["signal_type"],
            validation_json
        ))
        conn.commit()
    except Exception as e:
        logger.info(f"[ARMED-DB] Persist error for {ticker}: {e}")
    finally:
        if conn:
            return_conn(conn)


def _remove_armed_from_db(ticker: str):
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        safe_execute(cursor, f"DELETE FROM armed_signals_persist WHERE ticker = {p}", (ticker,))
        conn.commit()
    except Exception as e:
        logger.info(f"[ARMED-DB] Remove error for {ticker}: {e}")
    finally:
        if conn:
            return_conn(conn)


def _cleanup_stale_armed_signals():
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        open_positions = position_manager.get_open_positions()
        open_position_ids = {pos["id"] for pos in open_positions}
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        rows = safe_query(cursor, "SELECT ticker, position_id FROM armed_signals_persist")
        stale_tickers = []
        for row in rows:
            ticker = row[0] if isinstance(row, tuple) else row["ticker"]
            pos_id = row[1] if isinstance(row, tuple) else row["position_id"]
            if pos_id not in open_position_ids:
                stale_tickers.append(ticker)
        if stale_tickers:
            placeholders, params = safe_in_clause(stale_tickers, p)
            safe_execute(cursor,
                        f"DELETE FROM armed_signals_persist WHERE ticker IN ({placeholders})",
                        tuple(params))
            conn.commit()
            logger.info(f"[ARMED-DB] 🧹 Auto-cleaned {len(stale_tickers)} closed position(s): {', '.join(stale_tickers)}")
    except Exception as e:
        logger.info(f"[ARMED-DB] Cleanup error: {e}")
    finally:
        if conn:
            return_conn(conn)


def _load_armed_signals_from_db() -> dict:
    from app.data.db_connection import get_conn, return_conn, dict_cursor as _dc, USE_POSTGRES as _USE_PG
    conn = None
    try:
        _cleanup_stale_armed_signals()
        conn = get_conn()
        cursor = _dc(conn)
        p = get_placeholder(conn)
        today_et = _now_et().date()
        if _USE_PG:
            query = f"""
                SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                       confidence, grade, signal_type, validation_data
                FROM   armed_signals_persist
                WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = {p}
            """
        else:
            query = f"""
                SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                       confidence, grade, signal_type, validation_data
                FROM   armed_signals_persist
                WHERE  DATE(saved_at) = {p}
            """
        rows = safe_query(cursor, query, (today_et,))
        loaded = {}
        for row in rows:
            validation = None
            if row.get("validation_data"):
                try:
                    validation = json.loads(row["validation_data"])
                except Exception:
                    validation = None
            loaded[row["ticker"]] = {
                "position_id":  row["position_id"],
                "direction":    row["direction"],
                "entry_price":  row["entry_price"],
                "stop_price":   row["stop_price"],
                "t1":           row["t1"],
                "t2":           row["t2"],
                "confidence":   row["confidence"],
                "grade":        row["grade"],
                "signal_type":  row["signal_type"],
                "validation":   validation
            }
        if loaded:
            print(
                f"[ARMED-DB] 📄 Reloaded {len(loaded)} armed signal(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        logger.info(f"[ARMED-DB] Load error: {e}")
        return {}
    finally:
        if conn:
            return_conn(conn)


_armed_load_lock = __import__('threading').Lock()

def _maybe_load_armed_signals():
    with _armed_load_lock:
        if _state.is_armed_loaded():
            return
        _state.set_armed_loaded(True)
    _ensure_armed_db()
    loaded = _load_armed_signals_from_db()
    if loaded:
        _state.update_armed_signals_bulk(loaded)

def clear_armed_signals():
    """Clear all armed signals from memory and DB."""
    from app.data.db_connection import get_conn, return_conn
    from app.data.sql_safe import safe_execute
    _state.clear_armed_signals()
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        safe_execute(cursor, "DELETE FROM armed_signals_persist")
        conn.commit()
    except Exception as e:
        logger.info(f"[ARMED-DB] Clear error: {e}")
    finally:
        if conn:
            return_conn(conn)
    logger.info("[ARMED] Cleared")
