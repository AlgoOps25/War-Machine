import os
import logging
from datetime import datetime, timedelta

import psycopg2
import pandas as pd

logger = logging.getLogger(__name__)

def get_ticker_win_rates(days: int = 30) -> dict:
    """
    Rolling per-ticker win rate over last `days`.
    Returns dict[ticker] = win_rate in [0,1].
    Falls back to empty dict on any DB error (e.g. missing column) so
    the scanner does not crash-loop on startup.
    """
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return {}

    since = datetime.utcnow() - timedelta(days=days)
    try:
        conn = psycopg2.connect(db_url)
        query = """
            SELECT ticker,
                   CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END AS win_flag
            FROM signals
            WHERE completed_at IS NOT NULL
              AND outcome IN ('WIN','LOSS')
              AND completed_at >= %s
        """
        df = pd.read_sql_query(query, conn, params=[since])
        conn.close()

        if df.empty:
            return {}

        grouped = df.groupby("ticker")["win_flag"].mean()
        return grouped.to_dict()

    except Exception as exc:
        logger.warning(
            f"[METRICS-CACHE] get_ticker_win_rates failed (returning empty dict): {exc}"
        )
        return {}
