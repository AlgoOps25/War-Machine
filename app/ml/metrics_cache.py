#!/usr/bin/env python3
"""
Metrics Cache — app.ml.metrics_cache
=====================================
Rolling per-ticker win-rate cache consumed by MLConfidenceBooster and
ml_trainer.py to supply the `ticker_win_rate` feature at inference time.

Called by:
    sniper.py / ml_confidence_boost.py  → get_ticker_win_rates(days=30)

Returns:
    dict[ticker: str] = win_rate: float  in [0.0, 1.0]
    Falls back to {} on any DB error — callers must handle missing keys
    gracefully (treat as 0.5 neutral, not 0.0 losing).

FIX BUG-ML-2 (Mar 27 2026 — Session 11):
    pd.read_sql_query was using %(since)s named-param syntax which is
    psycopg2-only. On SQLite fallback (dev/CI) this raised
    sqlite3.ProgrammingError, was swallowed by except, and returned {}
    silently — every ticker got ticker_win_rate=0.0 (worst-case loss signal)
    poisoning the ML feature vector.
    Fix: use db_connection.ph() abstraction for the placeholder and pass
    params as a positional tuple so both psycopg2 (%s) and sqlite3 (?)
    work correctly.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
from zoneinfo import ZoneInfo

from app.data.db_connection import get_conn, return_conn, ph as _ph

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def get_ticker_win_rates(days: int = 30) -> dict:
    """
    Rolling per-ticker win rate over last `days`.
    Returns dict[ticker] = win_rate in [0, 1].
    Falls back to empty dict on any DB error.

    NOTE: callers should treat a missing key as 0.5 (neutral),
    NOT as 0.0 — absence of data is not evidence of losing.
    """
    since = datetime.now(ET) - timedelta(days=days)
    conn = None
    try:
        conn = get_conn()
        p = _ph()
        # FIX BUG-ML-2: use ph() positional placeholder + tuple params
        # so this works on both psycopg2 (Railway/Postgres) and sqlite3 (dev/CI).
        df = pd.read_sql_query(
            f"""
            SELECT ticker,
                   CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END AS win_flag
            FROM signals
            WHERE completed_at IS NOT NULL
              AND outcome IN ('WIN','LOSS')
              AND completed_at >= {p}
            """,
            conn,
            params=(since,),
        )
        if df.empty:
            return {}
        return df.groupby("ticker")["win_flag"].mean().to_dict()
    except Exception as exc:
        logger.warning(
            f"[METRICS-CACHE] get_ticker_win_rates failed (returning empty dict): {exc}"
        )
        return {}
    finally:
        if conn:
            return_conn(conn)
