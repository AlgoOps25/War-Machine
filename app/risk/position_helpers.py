"""
position_helpers.py — Module-level helpers for position_manager.py

Extracted from position_manager.py to reduce file size and improve testability.
All symbols here are re-imported by position_manager.py so existing callers
that import from position_manager are unaffected.

Contents:
  - SECTOR_GROUPS         : ticker → sector mapping for concentration limits
  - _STATS_CACHE_TTL      : get_daily_stats() cache TTL constant
  - _POSITIONS_CACHE_TTL  : get_open_positions() cache TTL constant
  - _date_eq_today()      : Postgres / SQLite-compatible "= today" SQL fragment
  - _date_lt_today()      : Postgres / SQLite-compatible "< today" SQL fragment
  - _date_col()           : Raw date-extract fragment (no implied comparator).
                            Use this for range / >= queries such as get_win_rate().
                            FIX #13 (2026-03-26): get_win_rate() previously called
                            _date_eq_today() in a >= clause — the name implied
                            equality but the fragment is structurally a date extractor.
                            Added _date_col() as a semantically-correct alias so
                            range comparisons read clearly at the call site.
  - _write_completed_at() : Write completed_at / outcome / exit_price to ml_signals
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor, USE_POSTGRES

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


# ── Sector / ticker concentration mapping ───────────────────────────────────────────────────────
SECTOR_GROUPS = {
    "TECH":       ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM"],
    "FINANCE":    ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "ENERGY":     ["XOM", "CVX", "COP", "SLB", "EOG"],
    "HEALTHCARE": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO"],
    "INDICES":    ["SPY", "QQQ", "IWM", "DIA"],
    "VOLATILITY": ["VIX", "UVXY", "SVXY", "VXX"],
}


# ── Cache TTL constants ────────────────────────────────────────────────────────────────────────
SECTOR_GROUPS = {
    "TECH":       ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM"],
    "FINANCE":    ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "ENERGY":     ["XOM", "CVX", "COP", "SLB", "EOG"],
    "HEALTHCARE": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO"],
    "INDICES":    ["SPY", "QQQ", "IWM", "DIA"],
    "VOLATILITY": ["VIX", "UVXY", "SVXY", "VXX"],
}

_STATS_CACHE_TTL     = 10  # get_daily_stats()     — re-query at most every 10s
_POSITIONS_CACHE_TTL =  5  # get_open_positions()  — re-query at most every 5s


# ── FIX #11: SQLite-compatible date-filter helpers ────────────────────────────────────────────

def _date_col(col: str) -> str:
    """
    FIX #13 (2026-03-26): Semantically-correct alias for date extraction.

    Returns a SQL fragment that extracts the date part from a TIMESTAMP column
    with NO implied comparator.  Use this for range queries (>=, <=, BETWEEN)
    where _date_eq_today() would be misleading.

    Examples:
        WHERE {_date_col('exit_time')} >= {p}   -- lookback range in get_win_rate()
        WHERE {_date_col('entry_time')} BETWEEN {p} AND {p}

    Postgres:  DATE(col AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
    SQLite:    date(col)
    """
    if USE_POSTGRES:
        return f"DATE({col} AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')"
    return f"date({col})"


def _date_eq_today(col: str) -> str:
    """
    Return a SQL fragment that compares `col` (TIMESTAMP) to today's ET date.

    Intended for: WHERE {_date_eq_today('exit_time')} = {p}  -- p bound to today's date string

    Postgres:  DATE(col AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
    SQLite:    date(col)
    """
    if USE_POSTGRES:
        return f"DATE({col} AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')"
    return f"date({col})"


def _date_lt_today(col: str) -> str:
    """
    Return a SQL fragment that checks `col` is strictly before today's ET date.

    Intended for: WHERE {_date_lt_today('entry_time')} < {p}  -- p bound to today's date string

    Postgres:  DATE(col AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
    SQLite:    date(col)
    """
    if USE_POSTGRES:
        return f"DATE({col} AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')"
    return f"date({col})"


# ── FIX #4: completed_at write-back helper ────────────────────────────────────────────────────

def _write_completed_at(
    ticker:     str,
    direction:  str,
    outcome:    str,   # 'WIN' | 'LOSS'
    exit_price: float,
    exit_time:  datetime,
) -> None:
    """
    Write completed_at, outcome, and exit_price back to the ml_signals table
    for the most-recent PENDING signal matching (ticker, direction).

    Safe no-op if:
      - ml_signals table does not exist
      - no matching PENDING row is found
      - any DB error occurs

    Called from close_position() for every real close (STOP LOSS, TARGET 1/2,
    EOD CLOSE) so the live EOD retrain loop can detect resolved signals.
    """
    conn = None
    try:
        conn   = get_conn()
        cursor = dict_cursor(conn)
        p      = ph()

        cursor.execute(
            f"""
            SELECT id FROM ml_signals
            WHERE  ticker    = {p}
              AND  direction = {p}
              AND  status    = 'PENDING'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticker, direction),
        )
        row = cursor.fetchone()
        if row is None:
            return

        signal_id = row["id"]

        cursor.execute(
            f"""
            UPDATE ml_signals
            SET  outcome      = {p},
                 exit_price   = {p},
                 completed_at = {p},
                 status       = 'COMPLETED'
            WHERE id = {p}
            """,
            (outcome, exit_price, exit_time, signal_id),
        )
        conn.commit()
        logger.info(
            f"[ML-SIGNALS] \u2705 completed_at written: {ticker} {direction.upper()} "
            f"{outcome} @ ${exit_price:.2f} (signal_id={signal_id})"
        )

    except Exception as exc:
        logger.info(f"[ML-SIGNALS] \u26a0\ufe0f  completed_at write skipped ({ticker}): {exc}")
    finally:
        if conn:
            return_conn(conn)
