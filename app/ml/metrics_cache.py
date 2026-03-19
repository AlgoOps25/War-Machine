import os
import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def _get_engine():
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return create_engine(db_url)
    except Exception as exc:
        logger.warning(f"[METRICS-CACHE] Could not create SQLAlchemy engine: {exc}")
        return None


def get_ticker_win_rates(days: int = 30) -> dict:
    """
    Rolling per-ticker win rate over last `days`.
    Returns dict[ticker] = win_rate in [0,1].
    Falls back to empty dict on any DB error.
    """
    engine = _get_engine()
    if engine is None:
        return {}

    since = datetime.utcnow() - timedelta(days=days)
    try:
        from sqlalchemy import text
        query = text("""
            SELECT ticker,
                   CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END AS win_flag
            FROM signals
            WHERE completed_at IS NOT NULL
              AND outcome IN ('WIN','LOSS')
              AND completed_at >= :since
        """)
        with engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params={"since": since})

        if df.empty:
            return {}

        grouped = df.groupby("ticker")["win_flag"].mean()
        return grouped.to_dict()

    except Exception as exc:
        logger.warning(
            f"[METRICS-CACHE] get_ticker_win_rates failed (returning empty dict): {exc}"
        )
        return {}
