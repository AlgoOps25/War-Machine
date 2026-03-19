"""
Candle Cache System - PostgreSQL-backed historical data cache

PHASE 1: Basic caching with startup optimization
PHASE 2: Smart incremental updates with gap detection
PHASE 3: Multi-timeframe aggregation

PHASE C4 FIX (MAR 10, 2026):
  - cache_candles() writes candles + metadata atomically.
  - bar_count computed via COUNT(*) subquery, not additive.

PHASE 1.22 FIX (MAR 10, 2026):
  - cleanup_old_cache() prunes to 30 days.
  - Orphaned cache_metadata rows deleted in same transaction.

FIX 14.H-7 (MAR 19, 2026): TZ stripping in _parse_cache_rows() caused
  naive UTC datetimes that broke _filter_session_bars() on Railway.
  Postgres returns TIMESTAMP columns as UTC-aware; stripping TZ then
  comparing against ET time() boundaries silently returned zero session
  bars. Fix: convert to ET-aware with .astimezone(ET) instead of
  stripping TZ.

FIX 14.H-6 (MAR 19, 2026): is_cache_fresh() used last_bar.replace(tzinfo=ET)
  on a naive datetime that is actually UTC from Postgres — stamping the
  wrong timezone made a UTC 14:30 bar appear as 14:30 ET (4-5 hours off)
  so stale cache appeared fresh all day. Fix: treat naive as UTC first
  (replace(tzinfo=timezone.utc)), then convert to ET before comparing
  against datetime.now(ET).
"""

import time
from datetime import datetime, timedelta, time as dtime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from utils import config
from app.data import db_connection
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class CandleCache:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self._init_cache_tables()

    # =============================================================
    # DATABASE SETUP
    # =============================================================

    def _init_cache_tables(self):
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS candle_cache (
                    id {db_connection.serial_pk()},
                    ticker VARCHAR(10) NOT NULL,
                    timeframe VARCHAR(5) NOT NULL,
                    datetime TIMESTAMP NOT NULL,
                    open NUMERIC(12,4) NOT NULL,
                    high NUMERIC(12,4) NOT NULL,
                    low NUMERIC(12,4) NOT NULL,
                    close NUMERIC(12,4) NOT NULL,
                    volume BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, timeframe, datetime)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_candle_lookup
                ON candle_cache(ticker, timeframe, datetime DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_candle_timeframe
                ON candle_cache(timeframe, datetime DESC)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    ticker VARCHAR(10) NOT NULL,
                    timeframe VARCHAR(5) NOT NULL,
                    first_bar_time TIMESTAMP,
                    last_bar_time TIMESTAMP,
                    bar_count INTEGER DEFAULT 0,
                    last_cache_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    cache_status VARCHAR(20) DEFAULT 'active',
                    PRIMARY KEY(ticker, timeframe)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_status
                ON cache_metadata(cache_status, last_cache_time)
            """)
            conn.commit()
            logger.info("[CACHE] ✅ Candle cache tables initialized")
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # PHASE 1: BASIC CACHE OPERATIONS
    # =============================================================

    def load_cached_candles(self, ticker: str, timeframe: str, days: int = 30) -> List[Dict]:
        cutoff = datetime.now(ET) - timedelta(days=days)
        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(
                f"SELECT datetime,open,high,low,close,volume FROM candle_cache"
                f" WHERE ticker={p} AND timeframe={p} AND datetime>={p}"
                f" ORDER BY datetime ASC",
                (ticker, timeframe, cutoff)
            )
            return self._parse_cache_rows(cursor.fetchall())
        finally:
            if conn:
                return_conn(conn)

    def cache_candles(self, ticker: str, timeframe: str, bars: List[Dict],
                      quiet: bool = False) -> int:
        """
        C4 FIX: candle upsert + metadata update in a single atomic transaction.
        """
        if not bars:
            return 0
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            upsert_sql = (
                f"INSERT INTO candle_cache"
                f" (ticker,timeframe,datetime,open,high,low,close,volume)"
                f" VALUES ({p},{p},{p},{p},{p},{p},{p},{p})"
                f" ON CONFLICT (ticker,timeframe,datetime) DO UPDATE SET"
                f"   open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,"
                f"   close=EXCLUDED.close, volume=EXCLUDED.volume,"
                f"   updated_at=CURRENT_TIMESTAMP"
            )
            cursor.executemany(
                upsert_sql,
                [(ticker, timeframe, b["datetime"], b["open"], b["high"],
                  b["low"], b["close"], b["volume"]) for b in bars]
            )
            p2 = ph()
            cursor.execute(
                f"INSERT INTO cache_metadata"
                f" (ticker,timeframe,first_bar_time,last_bar_time,bar_count,last_cache_time)"
                f" SELECT {p2},{p2},MIN(datetime),MAX(datetime),COUNT(*),CURRENT_TIMESTAMP"
                f" FROM candle_cache WHERE ticker={p2} AND timeframe={p2}"
                f" ON CONFLICT (ticker,timeframe) DO UPDATE SET"
                f"   first_bar_time=EXCLUDED.first_bar_time,"
                f"   last_bar_time=EXCLUDED.last_bar_time,"
                f"   bar_count=EXCLUDED.bar_count,"
                f"   last_cache_time=CURRENT_TIMESTAMP",
                (ticker, timeframe, ticker, timeframe)
            )
            conn.commit()
            last_bar = max(b["datetime"] for b in bars)
            if not quiet:
                print(f"[CACHE] Stored {len(bars)} {timeframe} bars for {ticker} "
                      f"(latest: {last_bar.strftime('%m/%d %H:%M ET')})")
            return len(bars)
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.info(f"[CACHE] Error caching {ticker} {timeframe}: {e}")
            return 0
        finally:
            if conn:
                return_conn(conn)

    def get_cache_metadata(self, ticker: str, timeframe: str) -> Optional[Dict]:
        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(
                f"SELECT first_bar_time,last_bar_time,bar_count,last_cache_time,cache_status"
                f" FROM cache_metadata WHERE ticker={p} AND timeframe={p}",
                (ticker, timeframe)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "first_bar_time":  row["first_bar_time"],
                "last_bar_time":   row["last_bar_time"],
                "bar_count":       row["bar_count"],
                "last_cache_time": row["last_cache_time"],
                "cache_status":    row["cache_status"]
            }
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # PHASE 2: SMART INCREMENTAL UPDATES
    # =============================================================

    def detect_cache_gaps(self, ticker: str, timeframe: str,
                          target_days: int = 30) -> List[Tuple[datetime, datetime]]:
        now_et = datetime.now(ET)
        target_start = now_et - timedelta(days=target_days)
        metadata = self.get_cache_metadata(ticker, timeframe)
        if not metadata:
            return [(target_start, now_et)]
        gaps = []
        last_bar = metadata["last_bar_time"]
        if last_bar < now_et - timedelta(minutes=5):
            gaps.append((last_bar + timedelta(minutes=1), now_et))
        return gaps

    def is_cache_fresh(self, ticker: str, timeframe: str,
                       max_age_minutes: int = 5) -> bool:
        """
        FIX 14.H-6: Naive datetimes from Postgres are UTC, not ET.
        Stamping tzinfo=ET directly on a UTC value produces a wrong
        timestamp (off by 4-5 hours), making stale cache appear fresh.
        Fix: treat naive as UTC first, then compare against now(ET).
        """
        metadata = self.get_cache_metadata(ticker, timeframe)
        if not metadata:
            return False
        last_bar = metadata["last_bar_time"]
        if isinstance(last_bar, str):
            last_bar = datetime.fromisoformat(last_bar)
        # Normalise to UTC-aware, then compare against now(ET)
        if last_bar.tzinfo is None:
            last_bar = last_bar.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(ET) - last_bar).total_seconds()
        return age_seconds / 60 <= max_age_minutes

    # =============================================================
    # PHASE 3: MULTI-TIMEFRAME AGGREGATION
    # =============================================================

    def aggregate_to_timeframe(self, ticker: str, source_tf: str,
                               target_tf: str, days: int = 30) -> List[Dict]:
        source_bars = self.load_cached_candles(ticker, source_tf, days)
        if not source_bars:
            return []
        intervals = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '1d': 1440}
        if source_tf not in intervals or target_tf not in intervals:
            logger.info(f"[CACHE] Unsupported aggregation: {source_tf} -> {target_tf}")
            return []
        source_mins = intervals[source_tf]
        target_mins = intervals[target_tf]
        if target_mins <= source_mins:
            logger.info(f"[CACHE] Cannot aggregate down: {source_tf} -> {target_tf}")
            return []
        if target_mins % source_mins != 0:
            logger.info(f"[CACHE] Incompatible timeframes: {source_tf} -> {target_tf}")
            return []
        buckets = defaultdict(list)
        for bar in source_bars:
            dt = bar["datetime"]
            if target_tf == '1h':
                bucket_dt = dt.replace(minute=0, second=0, microsecond=0)
            elif target_tf == '1d':
                bucket_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                minute_floor = (dt.minute // target_mins) * target_mins
                bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)
            buckets[bucket_dt].append(bar)
        agg_bars = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            agg_bars.append({
                "datetime": bucket_dt,
                "open":   bucket[0]["open"],
                "high":   max(b["high"] for b in bucket),
                "low":    min(b["low"]  for b in bucket),
                "close":  bucket[-1]["close"],
                "volume": sum(b["volume"] for b in bucket)
            })
        print(f"[CACHE] Aggregated {len(source_bars)} {source_tf} -> "
              f"{len(agg_bars)} {target_tf} bars for {ticker}")
        return agg_bars

    # =============================================================
    # CACHE MAINTENANCE
    # =============================================================

    def cleanup_old_cache(self, days_to_keep: int = 30):
        """
        Remove cached bars older than days_to_keep and prune orphaned
        cache_metadata rows (Phase 1.22).
        """
        cutoff = datetime.now(ET) - timedelta(days=days_to_keep)
        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM candle_cache WHERE datetime < {p}", (cutoff,))
            deleted = cursor.rowcount
            cursor.execute("""
                DELETE FROM cache_metadata
                WHERE (ticker, timeframe) NOT IN (
                    SELECT DISTINCT ticker, timeframe FROM candle_cache
                )
            """)
            orphans = cursor.rowcount
            conn.commit()
            print(f"[CLEANUP] Removed {deleted} candle cache bars older than {days_to_keep} days"
                  + (f" | {orphans} orphaned metadata rows pruned" if orphans > 0 else ""))
            return deleted
        finally:
            if conn:
                return_conn(conn)

    def get_cache_stats(self) -> Dict:
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute("SELECT COUNT(*) as cnt FROM candle_cache")
            total_bars = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(DISTINCT ticker) as cnt FROM candle_cache")
            unique_tickers = cursor.fetchone()["cnt"]
            cursor.execute(
                "SELECT MIN(datetime) as min_dt, MAX(datetime) as max_dt FROM candle_cache"
            )
            row = cursor.fetchone()
            date_range = (row["min_dt"], row["max_dt"]) if row["min_dt"] else (None, None)
            if db_connection.USE_POSTGRES:
                cursor.execute(
                    "SELECT pg_size_pretty(pg_total_relation_size('candle_cache')) as size"
                )
                cache_size = cursor.fetchone()["size"]
            else:
                cache_size = "N/A"
            cursor.execute(
                "SELECT timeframe, COUNT(*) as cnt FROM candle_cache GROUP BY timeframe ORDER BY timeframe"
            )
            tf_breakdown = {row["timeframe"]: row["cnt"] for row in cursor.fetchall()}
            return {
                "total_bars": total_bars, "unique_tickers": unique_tickers,
                "date_range": date_range, "cache_size": cache_size,
                "timeframe_breakdown": tf_breakdown
            }
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # UTILITIES
    # =============================================================

    def _parse_cache_rows(self, rows) -> List[Dict]:
        """
        FIX 14.H-7: Previously stripped TZ with dt.replace(tzinfo=None),
        producing naive UTC datetimes. _filter_session_bars() then compared
        these against ET time() boundaries — an ET 9:30 bar stored as
        13:30 UTC naive was never matched, returning zero session bars on
        Railway. Fix: convert to ET-aware with .astimezone(ET) so all
        downstream time comparisons use the correct local time.
        """
        bars = []
        for row in rows:
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            # Normalise: treat naive as UTC, then convert to ET
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(ET)
            bars.append({
                "datetime": dt,
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": int(row["volume"])
            })
        return bars


# Global singleton
candle_cache = CandleCache()
