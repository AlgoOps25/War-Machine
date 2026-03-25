import logging
from datetime import datetime, timedelta

import pandas as pd
from zoneinfo import ZoneInfo

from app.data.db_connection import get_conn, return_conn

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def get_ticker_win_rates(days: int = 30) -> dict:
    """
    Rolling per-ticker win rate over last `days`.
    Returns dict[ticker] = win_rate in [0,1].
    Falls back to empty dict on any DB error.
    """
    since = datetime.now(ET) - timedelta(days=days)
    conn = None
    try:
        conn = get_conn()
        df = pd.read_sql_query(
            """
            SELECT ticker,
                   CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END AS win_flag
            FROM signals
            WHERE completed_at IS NOT NULL
              AND outcome IN ('WIN','LOSS')
              AND completed_at >= %(since)s
            """,
            conn,
            params={"since": since},
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