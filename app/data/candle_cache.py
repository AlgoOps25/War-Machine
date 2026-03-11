"""
Candle Cache System - PostgreSQL-backed historical data cache

PHASE 1: Basic caching with startup optimization
PHASE 2: Smart incremental updates with gap detection
PHASE 3: Multi-timeframe aggregation

Purpose:
- Reduce API calls by 95%+ on Railway redeploys
- Instant startup (load from DB instead of EODHD API)
- Persist data across redeploys
- Smart gap-filling for missing data

PHASE C4 FIX (MAR 10, 2026):
  - FIXED: cache_candles() now writes candles + metadata in a single atomic
    transaction. Previously a crash between the two execute() calls left
    metadata stale while bars were already committed, causing startup
    cache-hit logic to trust wrong last_bar_time / bar_count values.
  - FIXED: bar_count now computed via COUNT(*) subquery instead of additive
    accumulation. Re-caching overlapping ranges no longer inflates the count.

PHASE 1.22 FIX (MAR 10, 2026):
  - FIXED: cleanup_old_cache() now prunes to 30 days (matching the 30-day
    startup backfill window) instead of 60 days.
  - FIXED: orphaned cache_metadata rows (tickers with zero remaining bars
    after a prune) are now deleted in the same transaction, preventing stale
    metadata from tricking startup cache-hit logic into skipping a full
    backfill for a ticker whose cache was fully evicted.
"""

import time
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from utils import config
from app.data import db_connection
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")


class CandleCache:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self._init_cache_tables()

    # =============================================================
    # DATABASE SETUP
    # =============================================================

    def _init_cache_tables(self):
        """Initialize cache tables if they don't exist."""
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = conn.cursor()

            # Main cache table
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

            # Metadata tracking
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
            print("[CACHE] \u2705 Candle cache tables initialized")
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # PHASE 1: BASIC CACHE OPERATIONS
    # =============================================================

    def load_cached_candles(
        self,
        ticker: str,
        timeframe: str,
        days: int = 30
    ) -> List[Dict]:
        """
        Load candles from cache for the specified time range.

        Args:
            ticker: Stock symbol
            timeframe: '1m', '5m', '15m', '1h', '1d'
            days: Number of days to load

        Returns:
            List of bar dicts sorted by datetime ASC
        """
        cutoff = datetime.now(ET) - timedelta(days=days)

        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT datetime, open, high, low, close, volume
                FROM candle_cache
                WHERE ticker = {p}
                  AND timeframe = {p}
                  AND datetime >= {p}
                ORDER BY datetime ASC
            """, (ticker, timeframe, cutoff))

            rows = cursor.fetchall()
            return self._parse_cache_rows(rows)
        finally:
            if conn:
                return_conn(conn)

    def cache_candles(
        self,
        ticker: str,
        timeframe: str,
        bars: List[Dict],
        quiet: bool = False
    ) -> int:
        """
        Store/update candles in cache.

        C4 FIX: candle upsert + metadata update execute inside a single
        transaction.  A crash (or Railway restart) mid-write will roll back
        both operations together, so metadata never drifts from the actual
        candle rows.  bar_count is computed via COUNT(*) after the upsert
        so overlapping re-cache calls never inflate the stored count.

        Args:
            ticker: Stock symbol
            timeframe: '1m', '5m', etc.
            bars: List of bar dicts
            quiet: Suppress log output

        Returns:
            Number of bars cached
        """
        if not bars:
            return 0

        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            p = ph()

            # ── Step 1: upsert candle rows ────────────────────────────────────
            upsert_sql = f"""
                INSERT INTO candle_cache
                (ticker, timeframe, datetime, open, high, low, close, volume)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT (ticker, timeframe, datetime)
                DO UPDATE SET
                    open       = EXCLUDED.open,
                    high       = EXCLUDED.high,
                    low        = EXCLUDED.low,
                    close      = EXCLUDED.close,
                    volume     = EXCLUDED.volume,
                    updated_at = CURRENT_TIMESTAMP
            """

            data = [
                (ticker, timeframe, b["datetime"], b["open"], b["high"],
                 b["low"], b["close"], b["volume"])
                for b in bars
            ]
            cursor.executemany(upsert_sql, data)

            # ── Step 2: recompute true bar_count from DB (not additive) ───────
            p2 = ph()
            cursor.execute(f"""
                INSERT INTO cache_metadata
                (ticker, timeframe, first_bar_time, last_bar_time, bar_count, last_cache_time)
                SELECT
                    {p2} AS ticker,
                    {p2} AS timeframe,
                    MIN(datetime)              AS first_bar_time,
                    MAX(datetime)              AS last_bar_time,
                    COUNT(*)                   AS bar_count,
                    CURRENT_TIMESTAMP          AS last_cache_time
                FROM candle_cache
                WHERE ticker = {p2} AND timeframe = {p2}
                ON CONFLICT (ticker, timeframe) DO UPDATE SET
                    first_bar_time = EXCLUDED.first_bar_time,
                    last_bar_time  = EXCLUDED.last_bar_time,
                    bar_count      = EXCLUDED.bar_count,
                    last_cache_time = CURRENT_TIMESTAMP
            """, (ticker, timeframe, ticker, timeframe))

            # ── Step 3: commit both operations together ────────────────────────
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
            print(f"[CACHE] Error caching {ticker} {timeframe}: {e}")
            return 0
        finally:
            if conn:
                return_conn(conn)

    def get_cache_metadata(
        self,
        ticker: str,
        timeframe: str
    ) -> Optional[Dict]:
        """
        Get cache metadata for a ticker/timeframe.

        Returns:
            Dict with first_bar_time, last_bar_time, bar_count, last_cache_time
            or None if not cached
        """
        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT first_bar_time, last_bar_time, bar_count, last_cache_time, cache_status
                FROM cache_metadata
                WHERE ticker = {p} AND timeframe = {p}
            """, (ticker, timeframe))

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

    def detect_cache_gaps(
        self,
        ticker: str,
        timeframe: str,
        target_days: int = 30
    ) -> List[Tuple[datetime, datetime]]:
        """
        Detect missing time ranges in cache.

        Returns:
            List of (from_datetime, to_datetime) tuples representing gaps
        """
        now_et = datetime.now(ET)
        target_start = now_et - timedelta(days=target_days)

        metadata = self.get_cache_metadata(ticker, timeframe)

        # No cache at all - full backfill needed
        if not metadata:
            return [(target_start, now_et)]

        gaps = []
        last_bar = metadata["last_bar_time"]

        # Gap at the end (new data available)
        if last_bar < now_et - timedelta(minutes=5):
            gaps.append((last_bar + timedelta(minutes=1), now_et))

        return gaps

    def is_cache_fresh(
        self,
        ticker: str,
        timeframe: str,
        max_age_minutes: int = 5
    ) -> bool:
        """
        Check if cache is fresh enough for use.

        Returns:
            True if cache exists and last bar is within max_age_minutes
        """
        metadata = self.get_cache_metadata(ticker, timeframe)
        if not metadata:
            return False

        last_bar = metadata["last_bar_time"]
        if isinstance(last_bar, str):
            last_bar = datetime.fromisoformat(last_bar)

        age = datetime.now(ET) - last_bar.replace(tzinfo=ET) if last_bar.tzinfo is None else datetime.now(ET) - last_bar
        return age.total_seconds() / 60 <= max_age_minutes

    # =============================================================
    # PHASE 3: MULTI-TIMEFRAME AGGREGATION
    # =============================================================

    def aggregate_to_timeframe(
        self,
        ticker: str,
        source_tf: str,
        target_tf: str,
        days: int = 30
    ) -> List[Dict]:
        """
        Aggregate cached bars from source timeframe to target timeframe.

        Example: aggregate_to_timeframe('SPY', '1m', '5m', 30)

        Supported aggregations:
        - 1m -> 5m, 15m, 1h
        - 5m -> 15m, 1h

        Returns:
            List of aggregated bars
        """
        # Load source bars
        source_bars = self.load_cached_candles(ticker, source_tf, days)
        if not source_bars:
            return []

        # Determine aggregation interval
        intervals = {
            '1m': 1,
            '5m': 5,
            '15m': 15,
            '1h': 60,
            '1d': 1440
        }

        if source_tf not in intervals or target_tf not in intervals:
            print(f"[CACHE] Unsupported aggregation: {source_tf} -> {target_tf}")
            return []

        source_mins = intervals[source_tf]
        target_mins = intervals[target_tf]

        if target_mins <= source_mins:
            print(f"[CACHE] Cannot aggregate down: {source_tf} -> {target_tf}")
            return []

        if target_mins % source_mins != 0:
            print(f"[CACHE] Incompatible timeframes: {source_tf} -> {target_tf}")
            return []

        # Aggregate bars
        buckets = defaultdict(list)

        for bar in source_bars:
            dt = bar["datetime"]

            # Calculate bucket start time
            if target_tf == '1h':
                bucket_dt = dt.replace(minute=0, second=0, microsecond=0)
            elif target_tf == '1d':
                bucket_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                # For minute-based timeframes (5m, 15m)
                minute_floor = (dt.minute // target_mins) * target_mins
                bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)

            buckets[bucket_dt].append(bar)

        # Build aggregated bars
        agg_bars = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            agg_bars.append({
                "datetime": bucket_dt,
                "open":     bucket[0]["open"],
                "high":     max(b["high"] for b in bucket),
                "low":      min(b["low"]  for b in bucket),
                "close":    bucket[-1]["close"],
                "volume":   sum(b["volume"] for b in bucket)
            })

        print(f"[CACHE] Aggregated {len(source_bars)} {source_tf} bars -> "
              f"{len(agg_bars)} {target_tf} bars for {ticker}")

        return agg_bars

    # =============================================================
    # CACHE MAINTENANCE
    # =============================================================

    def cleanup_old_cache(self, days_to_keep: int = 30):
        """
        Remove cached bars older than days_to_keep and prune orphaned
        cache_metadata rows for tickers with no remaining bars.

        Phase 1.22 changes:
          - Default changed from 60 to 30 days (matches startup_backfill_with_cache).
          - After the bar DELETE, any cache_metadata row whose ticker+timeframe
            has zero bars remaining is also deleted in the same transaction.
            This prevents stale metadata from tricking the cache-hit logic into
            skipping a full backfill for a ticker whose cache was fully evicted.
        """
        cutoff = datetime.now(ET) - timedelta(days=days_to_keep)

        conn = None
        try:
            p = ph()
            conn = get_conn(self.db_path)
            cursor = conn.cursor()

            # Step 1: delete old bars
            cursor.execute(f"""
                DELETE FROM candle_cache
                WHERE datetime < {p}
            """, (cutoff,))
            deleted = cursor.rowcount

            # Step 2: prune orphaned metadata rows
            # A metadata row is orphaned when no candle_cache rows remain for
            # that (ticker, timeframe) pair after the prune above.
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
        """Get cache statistics."""
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            # Total bars
            cursor.execute("SELECT COUNT(*) as cnt FROM candle_cache")
            total_bars = cursor.fetchone()["cnt"]

            # Unique tickers
            cursor.execute("SELECT COUNT(DISTINCT ticker) as cnt FROM candle_cache")
            unique_tickers = cursor.fetchone()["cnt"]

            # Date range
            cursor.execute("""
                SELECT MIN(datetime) as min_dt, MAX(datetime) as max_dt
                FROM candle_cache
            """)
            row = cursor.fetchone()
            date_range = (row["min_dt"], row["max_dt"]) if row["min_dt"] else (None, None)

            # Cache size
            if db_connection.USE_POSTGRES:
                cursor.execute("""
                    SELECT pg_size_pretty(pg_total_relation_size('candle_cache')) as size
                """)
                cache_size = cursor.fetchone()["size"]
            else:
                cache_size = "N/A"

            # Per-timeframe breakdown
            cursor.execute("""
                SELECT timeframe, COUNT(*) as cnt
                FROM candle_cache
                GROUP BY timeframe
                ORDER BY timeframe
            """)
            tf_breakdown = {row["timeframe"]: row["cnt"] for row in cursor.fetchall()}

            return {
                "total_bars":          total_bars,
                "unique_tickers":      unique_tickers,
                "date_range":          date_range,
                "cache_size":          cache_size,
                "timeframe_breakdown": tf_breakdown
            }
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # UTILITIES
    # =============================================================

    def _parse_cache_rows(self, rows) -> List[Dict]:
        """Parse database rows into bar dicts."""
        bars = []
        for row in rows:
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)

            bars.append({
                "datetime": dt,
                "open":     float(row["open"]),
                "high":     float(row["high"]),
                "low":      float(row["low"]),
                "close":    float(row["close"]),
                "volume":   int(row["volume"])
            })
        return bars


# Global singleton
candle_cache = CandleCache()
