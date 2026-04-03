# Armed Signal Store — DB persistence for armed signals
# Extracted from sniper.py (Phase 2 refactor)
# Owns: _ensure_armed_db, _persist_armed_signal, _remove_armed_from_db,
#       _cleanup_stale_armed_signals, _load_armed_signals_from_db, _maybe_load_armed_signals
#
# AUDIT 2026-03-27:
#   - Promoted logger.info → logger.warning on all error paths so they surface
#     visibly in Railway logs.
#   - Replaced stray print() in _load_armed_signals_from_db() with logger.info().
#
# AUDIT 2026-03-31 (Session 15):
#   BUG-ASS-1: Moved `import logging` / `logger =` to top of import block (before app imports)
#              so standard-library imports appear before third-party/app imports per convention.
#   BUG-ASS-2: Removed redundant `from app.data.sql_safe import safe_execute` inside
#              clear_armed_signals() — safe_execute is already imported at module scope.
#
# AUDIT 2026-03-31 (Session 18):
#   BUG-ASS-3 (REAL BUG): _persist_armed_signal() read data.get('validation') but
#              arm_signal.py sends 'validation_data' after BUG-S16-1 renamed the key.
#              Validation payload was always None in DB on every arm. Fixed: read
#              'validation_data' to match the key arm_signal.py actually sends.
#
# AUDIT 2026-04-02:
#   BUG-ASS-4: _ensure_armed_db() contained an inline CREATE TABLE with SQLite-style types
#              (TEXT, REAL, INTEGER) that diverged from migration 002 which uses the correct
#              PostgreSQL types (VARCHAR, NUMERIC, TIMESTAMPTZ, SERIAL). Schema ownership
#              belongs exclusively to migrations/. Function gutted to a no-op log — if the
#              table is missing it means migration 002 has not been run, which is the real fix.
#
# AUDIT 2026-04-03:
#   BUG-ASS-5 (REAL BUG): _cleanup_stale_armed_signals() evaluated
#              `pos_id not in open_position_ids` for every row. FUTURES_ORB signals
#              are persisted with position_id = None (no auto-execution path yet).
#              None is never in open_position_ids so every futures signal was deleted
#              on the very next cleanup cycle, making futures persistence a no-op.
#              Fix: skip rows where position_id IS NULL — treat them as manually-managed
#              signals. Equity signals always have a non-None position_id so the existing
#              cleanup logic is completely unchanged for that path.
#
#   BUG-ARM-3 (REAL BUG): be_price was stored in-memory (arm_signal.py) and passed
#              to position_manager, but never included in the DB INSERT. After a Railway
#              restart _load_armed_signals_from_db() reloaded signals without be_price,
#              silently dropping the break-even trigger. Fixed: be_price added to INSERT
#              column list, ON CONFLICT DO UPDATE, SELECT, and loaded dict.
#              Requires migration 007 (migrations/007_armed_signals_be_price.sql).

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.thread_safe_state import get_state
from app.data.sql_safe import safe_execute, safe_query, safe_in_clause, get_placeholder
from app.risk.position_manager import position_manager

logger = logging.getLogger(__name__)

_state = get_state()


def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def _ensure_armed_db():
    # BUG-ASS-4 FIX (2026-04-02): Schema is owned by migrations/002_signal_persist_tables.sql.
    # The old inline CREATE TABLE used SQLite-style types (TEXT/REAL/INTEGER) that diverged
    # from the correct PostgreSQL schema in migration 002. Gutted to a no-op.
    # If armed_signals_persist is missing, run: psql < migrations/002_signal_persist_tables.sql
    logger.debug("[ARMED-DB] _ensure_armed_db() skipped — schema owned by migration 002")


def _persist_armed_signal(ticker: str, data: dict):
    from app.data.db_connection import get_conn, return_conn
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        validation_json = None
        # BUG-ASS-3 FIX: was data.get('validation') but arm_signal.py sends 'validation_data'
        # after BUG-S16-1. Both keys now consistent: arm_signal → store → DB.
        if data.get("validation_data"):
            try:
                validation_json = json.dumps(data["validation_data"])
            except Exception:
                validation_json = None
        # BUG-ARM-3 FIX: be_price added to INSERT and ON CONFLICT DO UPDATE.
        # Requires migration 007 to have added the column.
        query = f"""
            INSERT INTO armed_signals_persist
                (ticker, position_id, direction, entry_price, stop_price, t1, t2,
                 be_price, confidence, grade, signal_type, validation_data, saved_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                position_id     = EXCLUDED.position_id,
                direction       = EXCLUDED.direction,
                entry_price     = EXCLUDED.entry_price,
                stop_price      = EXCLUDED.stop_price,
                t1              = EXCLUDED.t1,
                t2              = EXCLUDED.t2,
                be_price        = EXCLUDED.be_price,
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
            data.get("be_price"),   # BUG-ARM-3: None-safe; old signals lack this key
            data["confidence"],
            data["grade"],
            data["signal_type"],
            validation_json
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"[ARMED-DB] Persist error for {ticker}: {e}")
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
        logger.warning(f"[ARMED-DB] Remove error for {ticker}: {e}")
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
            # BUG-ASS-5 FIX (2026-04-03): skip rows with no position_id.
            # FUTURES_ORB signals are persisted with position_id = None because
            # there is no auto-execution path yet. None is never in
            # open_position_ids, so without this guard every futures signal was
            # silently deleted on the first cleanup cycle after being written.
            # Equity signals always carry a non-None position_id, so this guard
            # leaves the equity cleanup path completely unchanged.
            if pos_id is None:
                continue
            if pos_id not in open_position_ids:
                stale_tickers.append(ticker)
        if stale_tickers:
            placeholders, params = safe_in_clause(stale_tickers, p)
            safe_execute(cursor,
                        f"DELETE FROM armed_signals_persist WHERE ticker IN ({placeholders})",
                        tuple(params))
            conn.commit()
            logger.info(f"[ARMED-DB] \U0001f9f9 Auto-cleaned {len(stale_tickers)} closed position(s): {', '.join(stale_tickers)}")
    except Exception as e:
        logger.warning(f"[ARMED-DB] Cleanup error: {e}")
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
                       be_price, confidence, grade, signal_type, validation_data
                FROM   armed_signals_persist
                WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = {p}
            """
        else:
            query = f"""
                SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                       be_price, confidence, grade, signal_type, validation_data
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
                "position_id":     row["position_id"],
                "direction":       row["direction"],
                "entry_price":     row["entry_price"],
                "stop_price":      row["stop_price"],
                "t1":              row["t1"],
                "t2":              row["t2"],
                "be_price":        row.get("be_price"),  # BUG-ARM-3: None-safe for rows pre-migration 007
                "confidence":      row["confidence"],
                "grade":           row["grade"],
                "signal_type":     row["signal_type"],
                "validation_data": validation
            }
        if loaded:
            logger.info(
                f"[ARMED-DB] \U0001f4c4 Reloaded {len(loaded)} armed signal(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        logger.warning(f"[ARMED-DB] Load error: {e}")
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
    _state.clear_armed_signals()
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        safe_execute(cursor, "DELETE FROM armed_signals_persist")
        conn.commit()
    except Exception as e:
        logger.warning(f"[ARMED-DB] Clear error: {e}")
    finally:
        if conn:
            return_conn(conn)
    logger.info("[ARMED] Cleared")
