import logging

logger = logging.getLogger(__name__)

"""
Data Manager - Consolidated Data Fetching, Storage, and Database Management

Design principles:
  - Postgres (or SQLite locally) is the SINGLE source of truth for all bars.
  - NO in-memory live bar accumulator — every bar is persisted to DB immediately.
  - TODAY's bars are supplied by ws_feed.py (EODHD WebSocket real-time feed).
    startup_backfill_today() fetches 30 days of HISTORICAL data (up to yesterday)
    so OR and prior-day context are available even after a midday restart.
    startup_intraday_backfill_today() makes a best-effort REST fetch of today's
    bars (04:00 ET -> now) to fill the 9:30-now gap on mid-session restarts;
    silent no-op if EODHD doesn't serve same-day intraday on the current plan.
  - Each scan cycle, update_ticker() skips today's fetch when WS is connected
    (the WS feed owns today). For prior days, incremental fetches still run.
  - 1m bars  -> intraday_bars table.
  - Materialized 5m bars -> intraday_bars_5m table (rebuilt from 1m after each store).
  - get_today_session_bars() queries strictly by today's ET date. It NEVER falls
    back to a prior date. If today has no bars, it returns [] and the scanner skips.
  - Historical data accumulates over time for future backtesting.
  - WEBSOCKET-FIRST OPTIMIZATION: Live data queries check WebSocket feed before DB/API.

EODHD endpoint rules:
  - /api/intraday/ : primary bar source — prior-day data is always available;
    same-day data availability depends on plan (All-In-One may serve it sooner).
  - /api/eod/ : end-of-day OHLCV historical data — used by get_daily_ohlc().
  - /api/real-time/ : live price snapshot — used by bulk_fetch_live_snapshots().
  - WebSocket (ws_feed.py): real-time tick stream — the primary source for today's bars.
  - from/to MUST be Unix timestamps (int) — date strings cause 422 errors.
  - Returns ET-naive datetimes (extended hours 4 AM - 8 PM ET, ~960 bars/day).

FIX #4: CONNECTION LIFECYCLE MANAGEMENT
  - All database operations now use try/finally to guarantee connection return
  - Prevents connection pool exhaustion from leaked connections
  - Better error handling with connection cleanup

FIX 15.C-1 (MAR 19, 2026): DESTRUCTIVE MIGRATION GUARD
  - initialize_database() ran `DELETE FROM intraday_bars` whenever db_version
    row was unreadable (transient DB error → current_version defaults to 0 →
    condition `< 2` fires → all bar history wiped mid-session).
  - Fix: migration DELETEs now require FORCE_MIGRATION=true env flag.
  - If version row is missing/unreadable without the flag, we stamp v2 and log
    a warning instead of deleting — the data is already ET-naive on Railway.
  - One-time use: set FORCE_MIGRATION=true only on a fresh DB before first run.

FIX 15.C-2 (MAR 19, 2026): INVERTED TZ LOGIC IN startup_backfill_with_cache()
  - age_minutes calculation used `.replace(tzinfo=ET if last_cached.tzinfo is None
    else None)` — the condition is inverted: naive datetimes got ET attached
    (correct), but tz-aware datetimes had tzinfo stripped to None, making them
    naive while now_et remained tz-aware → TypeError on subtraction → exception
    swallowed by outer except → fell through to full 30-day API backfill on
    every restart, completely bypassing the cache on Railway/Postgres.
  - Fix: if naive, attach ET; if already tz-aware, leave as-is. Both branches
    result in a tz-aware datetime that subtracts cleanly against now_et.
  - Same bug patched in background_cache_sync().

AUDIT 2026-03-27:
  - Replaced all print() calls with logger.info() — logging is configured before
    DataManager() is instantiated, so logger is always ready.
  - Promoted logger.info → logger.warning on all error/exception paths.
  - NOTE: _UPDATE_TTL / _last_update are declared at module level but never
    read or written in update_ticker(). Dead code — flagged for future cleanup.

DATA-2 AUDIT (MAR 31, 2026):
  - Removed dead module-level constants _last_update / UPDATE_TTL (never used).
  - Moved module docstring after logger declaration so logger is defined before
    any module-level code that could reference it.
  - Fixed ZeroDivisionError in startup_backfill_with_cache() stats block:
    cache_hits/len(tickers) now guards len(tickers) > 0 before dividing.
  - Fixed ws_feed import path in _get_ws_bar() / _is_ws_connected():
    `from ws_feed import ...` → `from app.data.ws_feed import ...` to match
    the package structure; ImportError fallback still returns None/False safely.

DATA-3 AUDIT (MAR 31, 2026):
  - BUG-DM-1: cleanup_old_bars() cutoff now uses ET-naive now
    (`datetime.now(ET).replace(tzinfo=None)`) so retention is aligned with the
    ET-naive bar timestamps stored throughout the DB. Prevents Railway UTC from
    deleting 4-5 extra hours of valid bars.
  - BUG-DM-2: bulk_fetch_live_snapshots() WS/API counts now tracked explicitly
    instead of deriving WS count from the final mixed result dict.
"""
import time
import os
import requests
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime, date as date_type
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
from utils import config
from app.data import db_connection
from app.data.db_connection import (
    get_conn, return_conn, ph, dict_cursor, serial_pk,
    upsert_bar_sql, upsert_bar_5m_sql, upsert_metadata_sql
)

ET = ZoneInfo("America/New_York")

_logged_skip = set()  # Track tickers we've logged skip messages for


def _to_aware_et(dt: datetime) -> datetime:
    """
    Normalize a datetime to tz-aware ET regardless of input state.

    FIX 15.C-2: Replaces the inverted `.replace(tzinfo=ET if dt.tzinfo is None
    else None)` pattern that stripped tzinfo from already-aware datetimes and
    then failed to subtract against tz-aware now_et.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


class DataManager:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.api_key = config.EODHD_API_KEY
        self.initialize_database()

    # =============================================================
    # WEBSOCKET INTEGRATION HELPERS
    # =============================================================

    def _get_ws_bar(self, ticker: str) -> Optional[Dict]:
        """
        Get current bar from WebSocket feed if connected and available.
        Returns None if WS not connected or no data for ticker.
        Import path: app.data.ws_feed (DATA-2 fix — was bare `ws_feed`).
        """
        if not config.ENABLE_WEBSOCKET_FEED:
            return None

        try:
            from app.data.ws_feed import is_connected, get_current_bar
            if is_connected():
                return get_current_bar(ticker)
        except ImportError:
            pass
        except Exception:
            pass

        return None

    def _is_ws_connected(self) -> bool:
        """
        Check if WebSocket feed is active.
        Import path: app.data.ws_feed (DATA-2 fix — was bare `ws_feed`).
        """
        if not config.ENABLE_WEBSOCKET_FEED:
            return False

        try:
            from app.data.ws_feed import is_connected
            return is_connected()
        except (ImportError, Exception):
            return False

    # =============================================================
    # DATABASE SETUP
    # =============================================================

    def initialize_database(self):
        """Create all necessary database tables."""
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = conn.cursor()

            # 1m bars — primary store
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS intraday_bars (
                    id          {serial_pk()},
                    ticker      TEXT      NOT NULL,
                    datetime    TIMESTAMP NOT NULL,
                    open        REAL      NOT NULL,
                    high        REAL      NOT NULL,
                    low         REAL      NOT NULL,
                    close       REAL      NOT NULL,
                    volume      INTEGER   NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, datetime)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ticker_datetime
                ON intraday_bars(ticker, datetime DESC)
            """)

            # Materialized 5m bars
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS intraday_bars_5m (
                    id          {serial_pk()},
                    ticker      TEXT      NOT NULL,
                    datetime    TIMESTAMP NOT NULL,
                    open        REAL      NOT NULL,
                    high        REAL      NOT NULL,
                    low         REAL      NOT NULL,
                    close       REAL      NOT NULL,
                    volume      INTEGER   NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, datetime)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ticker_datetime_5m
                ON intraday_bars_5m(ticker, datetime DESC)
            """)

            # Fetch state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fetch_metadata (
                    ticker        TEXT PRIMARY KEY,
                    last_fetch    TIMESTAMP,
                    last_bar_time TIMESTAMP,
                    bar_count     INTEGER DEFAULT 0
                )
            """)

            # DB version
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS db_version (version INTEGER UNIQUE)
            """)
            cursor.execute("SELECT version FROM db_version LIMIT 1")
            row = cursor.fetchone()
            current_version = (
                row[0] if isinstance(row, (list, tuple)) else row["version"]
            ) if row else 0

            if current_version < 2:
                force_migration = os.getenv("FORCE_MIGRATION", "").strip().lower() == "true"
                if force_migration:
                    cursor.execute("DELETE FROM intraday_bars")
                    cursor.execute("DELETE FROM intraday_bars_5m")
                    cursor.execute("DELETE FROM fetch_metadata")
                    cursor.execute("DELETE FROM db_version")
                    cursor.execute("INSERT INTO db_version (version) VALUES (2)")
                    logger.info("[DATA] Migration v2: Cleared UTC bars — switching to ET-naive storage")
                else:
                    cursor.execute("DELETE FROM db_version")
                    cursor.execute("INSERT INTO db_version (version) VALUES (2)")
                    logger.warning(
                        "[DATA] db_version was <2 but FORCE_MIGRATION not set — "
                        "stamped v2 without deleting bars. "
                        "Set FORCE_MIGRATION=true only on a brand-new empty DB."
                    )

            conn.commit()

            db_type = "PostgreSQL" if db_connection.USE_POSTGRES else self.db_path
            logger.info(f"[DATA] Database initialized: {db_type}")

        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # EODHD FETCH
    # =============================================================

    def _fetch_range(self, ticker: str, from_ts: int, to_ts: int,
                     interval: str = "1m") -> List[Dict]:
        """
        Core EODHD intraday fetch.
        from_ts / to_ts are UTC Unix timestamps (int).
        """
        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": self.api_key,
            "interval":  interval,
            "from":      from_ts,
            "to":        to_ts,
            "fmt":       "json"
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            if not data:
                return []

            bars = []
            for bar in data:
                try:
                    required = ["timestamp", "open", "high", "low", "close", "volume"]
                    missing = [k for k in required if k not in bar or bar[k] is None]

                    if missing:
                        logger.warning(f"[DATA] {ticker}: Skipping bar with missing fields: {missing}")
                        continue

                    dt_et = datetime.fromtimestamp(
                        bar["timestamp"], tz=ET
                    ).replace(tzinfo=None)

                    bars.append({
                        "datetime": dt_et,
                        "open":     float(bar["open"]),
                        "high":     float(bar["high"]),
                        "low":      float(bar["low"]),
                        "close":    float(bar["close"]),
                        "volume":   int(bar["volume"])
                    })
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning(f"[DATA] Bar parse error for {ticker}: {e}")
                    continue

            return bars

        except requests.exceptions.HTTPError as e:
            logger.warning(f"[DATA] API Error for {ticker}: {e}")
            return []
        except Exception as e:
            logger.warning(f"[DATA] Unexpected error for {ticker}: {e}")
            return []

    # =============================================================
    # STARTUP BACKFILL
    # =============================================================

    def startup_backfill_today(self, tickers: List[str]):
        """
        Fetch 30 days of historical bars (up to yesterday's close) for every ticker.
        """
        now_et = datetime.now(ET)
        today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        from_ts = int((today_midnight - timedelta(days=30)).timestamp())
        to_ts   = int((today_midnight - timedelta(seconds=1)).timestamp())

        logger.info(f"[DATA] Startup backfill: {len(tickers)} tickers | "
                    f"30 days history -> yesterday (WebSocket handles today's bars)")

        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    self.store_bars(ticker, bars)
                    self.materialize_5m_bars(ticker)
                    logger.info(f"[DATA] [{idx}/{len(tickers)}] {ticker}: "
                                f"{len(bars)} historical bars stored")
                else:
                    logger.info(f"[DATA] [{idx}/{len(tickers)}] {ticker}: "
                                f"no historical bars returned")
            except Exception as e:
                logger.warning(f"[DATA] [{idx}/{len(tickers)}] {ticker} backfill error: {e}")

        logger.info("[DATA] Startup backfill complete — WebSocket feed handles today's bars")

    def startup_intraday_backfill_today(self, tickers: List[str]):
        """
        Best-effort REST fetch of today's intraday bars for mid-session restarts.
        """
        now_et   = datetime.now(ET)
        today_et = now_et.date()
        from_dt  = datetime.combine(today_et, dtime(4, 0, 0))
        from_ts  = int(from_dt.replace(tzinfo=ET).timestamp())
        to_ts    = int(now_et.timestamp())

        logger.info(f"[DATA] Today's REST backfill: {len(tickers)} tickers | "
                    f"04:00 ET -> {now_et.strftime('%H:%M ET')} (best-effort, WS is primary)")

        filled = 0
        for ticker in tickers:
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                bars = [b for b in bars if b["datetime"].date() == today_et]
                if bars:
                    self.store_bars(ticker, bars)
                    self.materialize_5m_bars(ticker)
                    filled += 1
            except Exception as e:
                logger.warning(f"[DATA] Today REST backfill error for {ticker}: {e}")

        if filled:
            logger.info(f"[DATA] Today REST backfill complete: {filled}/{len(tickers)} tickers")
        else:
            logger.info(f"[DATA] Today REST backfill: no same-day data from EODHD — WS-only session")

    # =============================================================
    # CACHE-AWARE STARTUP & SYNC
    # =============================================================

    def startup_backfill_with_cache(self, tickers: List[str], days: int = 30):
        """
        Smart startup backfill using candle_cache.

        Workflow:
        1. Check cache for each ticker
        2. If cache exists and fresh: Load from cache (INSTANT)
        3. If cache missing/stale: Fetch from API and cache
        4. Only fetch gaps (new data since last cache)

        This reduces:
        - API calls from ~160,000 to <500 per deploy
        - Startup time from 5-10 min to 10-30 seconds
        """
        from app.data.candle_cache import candle_cache

        now_et = datetime.now(ET)
        timeframe = '1m'

        logger.info(f"[CACHE] Smart startup backfill: {len(tickers)} tickers | {days} days")

        cache_hits = 0
        cache_misses = 0
        gap_fills = 0
        total_api_bars = 0
        total_cached_bars = 0

        for idx, ticker in enumerate(tickers, 1):
            try:
                metadata = candle_cache.get_cache_metadata(ticker, timeframe)

                if metadata and metadata["bar_count"] > 0:
                    last_cached = metadata["last_bar_time"]
                    if isinstance(last_cached, str):
                        last_cached = datetime.fromisoformat(last_cached)

                    cached_bars = candle_cache.load_cached_candles(ticker, timeframe, days)

                    if cached_bars:
                        self.store_bars(ticker, cached_bars, quiet=True)
                        self.materialize_5m_bars(ticker)
                        total_cached_bars += len(cached_bars)

                        age_minutes = (
                            now_et - _to_aware_et(last_cached)
                        ).total_seconds() / 60

                        if age_minutes > 60:
                            from_ts = int(_to_aware_et(last_cached).timestamp())
                            to_ts = int(now_et.timestamp())

                            new_bars = self._fetch_range(ticker, from_ts, to_ts)
                            if new_bars:
                                candle_cache.cache_candles(ticker, timeframe, new_bars, quiet=True)
                                self.store_bars(ticker, new_bars, quiet=True)
                                self.materialize_5m_bars(ticker)
                                total_api_bars += len(new_bars)
                                gap_fills += 1
                                logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                            f"{len(cached_bars)} from cache + {len(new_bars)} new bars")
                            else:
                                logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                            f"{len(cached_bars)} bars from cache (up-to-date)")
                        else:
                            logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                        f"{len(cached_bars)} bars from cache (fresh)")

                        cache_hits += 1
                        continue

                # Cache miss — full backfill from API
                cache_misses += 1
                today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ts = int((today_midnight - timedelta(days=days)).timestamp())
                to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())

                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    candle_cache.cache_candles(ticker, timeframe, bars, quiet=True)
                    self.store_bars(ticker, bars, quiet=True)
                    self.materialize_5m_bars(ticker)
                    total_api_bars += len(bars)
                    logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                f"{len(bars)} bars fetched and cached")
                else:
                    logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data returned")

            except Exception as e:
                logger.warning(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")

        n = len(tickers)
        logger.info(f"[CACHE] Startup complete!")
        logger.info(f"[CACHE] Stats:")
        logger.info(f"[CACHE]   - Cache hits: {cache_hits}/{n} ({cache_hits / n * 100:.1f}%)" if n > 0 else "[CACHE]   - Cache hits: 0/0")
        logger.info(f"[CACHE]   - Cache misses: {cache_misses}")
        logger.info(f"[CACHE]   - Gap fills: {gap_fills}")
        logger.info(f"[CACHE]   - Bars from cache: {total_cached_bars:,}")
        logger.info(f"[CACHE]   - Bars from API: {total_api_bars:,}")

        total_bars = total_cached_bars + total_api_bars
        if cache_hits > 0 and total_bars > 0:
            api_reduction = (1 - total_api_bars / total_bars) * 100
            logger.info(f"[CACHE]   - API reduction: {api_reduction:.1f}%")
        logger.info("")

    def store_bars_with_cache(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """
        Enhanced store_bars that auto-caches to candle_cache.
        """
        if not bars:
            return 0

        result = self.store_bars(ticker, bars, quiet)

        if result > 0:
            try:
                from app.data.candle_cache import candle_cache
                candle_cache.cache_candles(ticker, '1m', bars, quiet=True)
            except Exception as e:
                logger.warning(f"[CACHE] Auto-cache failed for {ticker}: {e}")

        return result

    def background_cache_sync(self, tickers: List[str]):
        """
        Hourly background task to sync cache with latest data.
        """
        from app.data.candle_cache import candle_cache

        now_et = datetime.now(ET)

        if not (config.MARKET_OPEN <= now_et.time() <= dtime(17, 0)):
            return

        logger.info(f"[CACHE] Background sync: {len(tickers)} tickers")

        synced = 0
        for ticker in tickers:
            try:
                metadata = candle_cache.get_cache_metadata(ticker, '1m')
                if not metadata:
                    continue

                last_cached = metadata["last_bar_time"]
                if isinstance(last_cached, str):
                    last_cached = datetime.fromisoformat(last_cached)

                age_minutes = (
                    now_et - _to_aware_et(last_cached)
                ).total_seconds() / 60

                if age_minutes > 10:
                    from_ts = int(_to_aware_et(last_cached).timestamp())
                    to_ts = int(now_et.timestamp())

                    new_bars = self._fetch_range(ticker, from_ts, to_ts)
                    if new_bars:
                        candle_cache.cache_candles(ticker, '1m', new_bars, quiet=True)
                        synced += 1

            except Exception as e:
                logger.warning(f"[CACHE] Background sync error for {ticker}: {e}")

        if synced > 0:
            logger.info(f"[CACHE] Background sync complete: {synced}/{len(tickers)} updated")

    def warmup_cache(self, tickers: List[str], days: int = 60):
        """
        One-time cache warmup with extended history.
        """
        from app.data.candle_cache import candle_cache

        logger.info(f"[CACHE] Cache warmup: {len(tickers)} tickers | {days} days")

        now_et = datetime.now(ET)
        today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        from_ts = int((today_midnight - timedelta(days=days)).timestamp())
        to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())

        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    candle_cache.cache_candles(ticker, '1m', bars)
                    logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: {len(bars)} bars cached")
                else:
                    logger.info(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data")
            except Exception as e:
                logger.warning(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")

        logger.info(f"[CACHE] Warmup complete!")

    # =============================================================
    # INCREMENTAL UPDATE
    # =============================================================

    def _get_last_bar_ts(self, ticker: str) -> Optional[datetime]:
        """FIX #4: Ensure connection is returned."""
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(
                f"SELECT last_bar_time FROM fetch_metadata WHERE ticker = {p}",
                (ticker,)
            )
            row = cursor.fetchone()
            if not row or not row["last_bar_time"]:
                return None
            ts = row["last_bar_time"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            return ts
        finally:
            if conn:
                return_conn(conn)

    def update_ticker(self, ticker: str):
        """
        Smart incremental updates:
        - During market hours: SKIP (WebSocket owns today)
        - After hours: Fetch ONLY missing ranges
        - Daily close: Fetch ONLY yesterday's bars
        """
        now_et = datetime.now(ET)
        today_et = now_et.date()

        if config.MARKET_OPEN <= now_et.time() <= config.MARKET_CLOSE:
            if self._is_ws_connected():
                return

        last_bar = self._get_last_bar_ts(ticker)

        if not last_bar:
            from_ts = int((now_et - timedelta(days=30)).timestamp())
            to_ts = int(now_et.timestamp())
            label = "initial 30-day seed"
        else:
            last_bar_date = last_bar.date()

            if last_bar_date < today_et:
                yesterday = today_et - timedelta(days=1)
                from_ts = int(datetime.combine(yesterday, dtime(4, 0)).replace(tzinfo=ET).timestamp())
                to_ts = int(datetime.combine(yesterday, dtime(20, 0)).replace(tzinfo=ET).timestamp())
                label = f"yesterday's bars ({yesterday})"
            else:
                fetch_from = last_bar + timedelta(minutes=1)
                from_ts = int(fetch_from.replace(tzinfo=ET).timestamp())
                to_ts = int(now_et.timestamp())
                label = f"gap fill from {fetch_from.strftime('%H:%M ET')}"

        logger.info(f"[DATA] {ticker} -> {label}")
        bars = self._fetch_range(ticker, from_ts, to_ts)

        if bars:
            self.store_bars(ticker, bars)
            self.materialize_5m_bars(ticker)
        else:
            logger.info(f"[DATA] {ticker}: no new bars returned")

    # =============================================================
    # STORAGE (FIX #4: GUARANTEED CONNECTION RETURN)
    # =============================================================

    def store_bars(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """
        Upsert 1m bars into intraday_bars and update fetch_metadata.
        FIX #4: Ensures connection is returned even on error.
        """
        if not bars:
            return 0

        max_retries = 3
        for attempt in range(max_retries):
            conn = None
            try:
                conn = get_conn(self.db_path)
                cursor = dict_cursor(conn)
                data = [
                    (ticker, b["datetime"], b["open"], b["high"],
                     b["low"], b["close"], b["volume"])
                    for b in bars
                ]
                cursor.executemany(upsert_bar_sql(), data)
                latest_bar_dt = max(b["datetime"] for b in bars)
                cursor.execute(upsert_metadata_sql(),
                               (ticker, latest_bar_dt, len(bars)))
                conn.commit()
                if not quiet:
                    logger.info(f"[DATA] Stored {len(bars)} bars for {ticker} "
                                f"(latest: {latest_bar_dt.strftime('%m/%d %H:%M')} ET)")
                return len(bars)
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                logger.warning(f"[DATA] Store attempt {attempt+1}/{max_retries} "
                               f"failed for {ticker}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            finally:
                if conn:
                    return_conn(conn)

        logger.warning(f"[DATA] All {max_retries} store attempts failed for {ticker}")
        return 0

    def materialize_5m_bars(self, ticker: str):
        """
        Compute 5m OHLCV from today's 1m bars and upsert into intraday_bars_5m.
        FIX #4: Ensures connection is returned even on error.
        """
        bars_1m = self.get_today_session_bars(ticker)
        if not bars_1m:
            return

        buckets: Dict[datetime, List[Dict]] = defaultdict(list)
        for bar in bars_1m:
            dt = bar["datetime"]
            minute_floor = (dt.minute // 5) * 5
            bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)
            buckets[bucket_dt].append(bar)

        bars_5m = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            bars_5m.append({
                "datetime": bucket_dt,
                "open":     bucket[0]["open"],
                "high":     max(b["high"]   for b in bucket),
                "low":      min(b["low"]    for b in bucket),
                "close":    bucket[-1]["close"],
                "volume":   sum(b["volume"] for b in bucket)
            })

        if not bars_5m:
            return

        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            data = [
                (ticker, b["datetime"], b["open"], b["high"],
                 b["low"], b["close"], b["volume"])
                for b in bars_5m
            ]
            cursor.executemany(upsert_bar_5m_sql(), data)
            conn.commit()
        except Exception as e:
            logger.warning(f"[DATA] 5m materialization error for {ticker}: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn:
                return_conn(conn)

    # =============================================================
    # SESSION QUERIES (WEBSOCKET-OPTIMIZED) (FIX #4)
    # =============================================================

    def _parse_bar_rows(self, rows) -> List[Dict]:
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

    def get_today_session_bars(self, ticker: str) -> List[Dict]:
        """
        Return today's 1m bars (04:00-20:00 ET).
        NEVER falls back to a prior date.
        FIX #4: Ensures connection is returned.
        """
        today_et  = datetime.now(ET).date()
        day_start = datetime.combine(today_et, dtime(4, 0, 0))
        day_end   = datetime.combine(today_et, dtime(20, 0, 0))

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT datetime, open, high, low, close, volume
                FROM intraday_bars
                WHERE ticker   = {p}
                  AND datetime >= {p}
                  AND datetime <= {p}
                ORDER BY datetime ASC
            """, (ticker, day_start, day_end))
            rows = cursor.fetchall()
            return self._parse_bar_rows(rows)
        finally:
            if conn:
                return_conn(conn)

    def get_today_5m_bars(self, ticker: str) -> List[Dict]:
        """
        Return today's materialized 5m bars.
        FIX #4: Ensures connection is returned.
        """
        today_et  = datetime.now(ET).date()
        day_start = datetime.combine(today_et, dtime(4, 0, 0))
        day_end   = datetime.combine(today_et, dtime(20, 0, 0))

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT datetime, open, high, low, close, volume
                FROM intraday_bars_5m
                WHERE ticker   = {p}
                  AND datetime >= {p}
                  AND datetime <= {p}
                ORDER BY datetime ASC
            """, (ticker, day_start, day_end))
            rows = cursor.fetchall()
            return self._parse_bar_rows(rows)
        finally:
            if conn:
                return_conn(conn)

    def get_latest_bar(self, ticker: str) -> Optional[Dict]:
        """
        Get the most recent bar for a ticker.
        Checks WebSocket feed first if connected, falls back to database.
        FIX #4: Ensures connection is returned.
        """
        ws_bar = self._get_ws_bar(ticker)
        if ws_bar:
            return ws_bar

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT datetime, open, high, low, close, volume
                FROM intraday_bars
                WHERE ticker = {p}
                ORDER BY datetime DESC
                LIMIT 1
            """, (ticker,))
            row = cursor.fetchone()

            if not row:
                return None

            bars = self._parse_bar_rows([row])
            return bars[0] if bars else None
        finally:
            if conn:
                return_conn(conn)

    def get_latest_price(self, ticker: str) -> Optional[float]:
        """Get the most recent close price for a ticker."""
        bar = self.get_latest_bar(ticker)
        return bar["close"] if bar else None

    # =============================================================
    # DAILY OHLC (EODHD /eod/ endpoint)
    # =============================================================

    def get_daily_ohlc(self, ticker: str, target_date: date_type) -> Optional[Dict]:
        """
        Fetch full OHLCV for a specific date via EODHD /eod/ endpoint.
        Returns dict: {"open", "high", "low", "close", "volume"} or None.
        """
        url = f"https://eodhd.com/api/eod/{ticker}.US"
        params = {
            "api_token": self.api_key,
            "from": target_date.isoformat(),
            "to": target_date.isoformat(),
            "fmt": "json"
        }
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if not data or len(data) == 0:
                return None

            bar = data[0]
            return {
                "open":   float(bar["open"]),
                "high":   float(bar["high"]),
                "low":    float(bar["low"]),
                "close":  float(bar["close"]),
                "volume": int(bar["volume"])
            }
        except Exception as e:
            logger.warning(f"[DATA] Error fetching daily OHLC for {ticker} on {target_date}: {e}")
            return None

    def get_previous_day_ohlc(self, ticker: str, as_of_date=None) -> Optional[Dict]:
        """
        Fetch previous trading day's OHLC. Walks back up to 5 days to skip weekends/holidays.
        Returns dict: {"open", "high", "low", "close", "volume"} or None.

        as_of_date: date or datetime to use as "today". Defaults to datetime.now(ET).date().
                    Pass session_date in backtests so each fold fetches its own prior-day OHLC.
        """
        if as_of_date is None:
            as_of_date = datetime.now(ET).date()
        elif isinstance(as_of_date, datetime):
            as_of_date = as_of_date.date()

        for days_back in range(1, 6):
            target_date = as_of_date - timedelta(days=days_back)
            ohlc = self.get_daily_ohlc(ticker, target_date)
            if ohlc:
                return ohlc

        return None

    # =============================================================
    # LIVE PRICE SNAPSHOTS
    # =============================================================

    def bulk_fetch_live_snapshots(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetch real-time price snapshots for up to 50 tickers in one call.
        For tickers with WS data, returns WS bars immediately.
        Only fetches REST API snapshots for tickers without WS coverage.
        """
        if not tickers:
            return {}

        result = {}
        tickers_needing_api = []
        ws_count = 0
        api_count = 0

        if self._is_ws_connected():
            for ticker in tickers:
                ws_bar = self._get_ws_bar(ticker)
                if ws_bar:
                    result[ticker] = ws_bar
                    ws_count += 1
                else:
                    tickers_needing_api.append(ticker)
        else:
            tickers_needing_api = tickers

        if not tickers_needing_api:
            return result

        primary = f"{tickers_needing_api[0]}.US"
        extras  = ",".join(f"{t}.US" for t in tickers_needing_api[1:])
        url     = f"https://eodhd.com/api/real-time/{primary}"
        params  = {"api_token": self.api_key, "fmt": "json"}
        if extras:
            params["s"] = extras

        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                data = [data]

            for d in data:
                code  = d.get("code", "").replace(".US", "")
                ts    = d.get("timestamp")
                close = d.get("close") or d.get("last")
                if code and ts and close:
                    dt_et = datetime.fromtimestamp(
                        int(ts), tz=ET
                    ).replace(tzinfo=None)
                    result[code] = {
                        "datetime": dt_et,
                        "close":    float(close),
                        "volume":   int(d.get("volume", 0))
                    }
                    api_count += 1

            logger.info(f"[LIVE] Bulk snapshot: {len(result)}/{len(tickers)} tickers "
                        f"(WS: {ws_count}, API: {api_count})")
            return result

        except Exception as e:
            logger.warning(f"[LIVE] Bulk snapshot error: {e}")
            return result

    # =============================================================
    # CACHE MANAGEMENT
    # =============================================================

    def clear_prev_day_cache(self) -> None:
        """
        DEPRECATED: signal_generator.py is deprecated. This cache clear is no longer needed
        since sniper.py doesn't maintain a PDH/PDL cache that needs clearing.
        """
        pass

    # =============================================================
    # UTILITIES (FIX #4)
    # =============================================================

    def cleanup_old_bars(self, days_to_keep: int = 60):
        """
        Remove bars older than days_to_keep from 1m and 5m tables.
        FIX #4: Ensures connection is returned.
        """
        cutoff = datetime.now(ET).replace(tzinfo=None) - timedelta(days=days_to_keep)
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM intraday_bars WHERE datetime < {p}", (cutoff,)
            )
            cursor.execute(
                f"DELETE FROM intraday_bars_5m WHERE datetime < {p}", (cutoff,)
            )
            conn.commit()
            logger.info(f"[CLEANUP] Removed bars older than {days_to_keep} days")
        finally:
            if conn:
                return_conn(conn)

    def get_bars_from_memory(self, ticker: str, limit: int = 390) -> List[Dict]:
        """
        Return N most recent bars. Prefer get_today_session_bars() for live scanning.
        FIX #4: Ensures connection is returned.
        """
        if limit == 1:
            ws_bar = self._get_ws_bar(ticker)
            if ws_bar:
                return [ws_bar]

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT datetime, open, high, low, close, volume
                FROM intraday_bars
                WHERE ticker = {p}
                ORDER BY datetime DESC
                LIMIT {p}
            """, (ticker, limit))
            rows = cursor.fetchall()
            return list(reversed(self._parse_bar_rows(rows)))
        finally:
            if conn:
                return_conn(conn)

    def get_database_stats(self) -> Dict:
        """
        Get database statistics for the startup banner.
        FIX #4: Ensures connection is returned.
        """
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute("SELECT COUNT(*) AS cnt FROM intraday_bars")
            total_bars = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(DISTINCT ticker) AS cnt FROM intraday_bars")
            unique_tickers = cursor.fetchone()["cnt"]

            cursor.execute(
                "SELECT MIN(datetime) AS mn, MAX(datetime) AS mx FROM intraday_bars"
            )
            row = cursor.fetchone()
            date_range = (row["mn"], row["mx"])

            if db_connection.USE_POSTGRES:
                cursor.execute(
                    "SELECT pg_size_pretty(pg_database_size(current_database())) AS sz"
                )
                db_size = cursor.fetchone()["sz"]
            else:
                db_size = (
                    f"{os.path.getsize(self.db_path) / (1024 * 1024):.1f} MB"
                    if os.path.exists(self.db_path) else "0 MB"
                )

            return {
                "total_bars":     total_bars,
                "unique_tickers": unique_tickers,
                "date_range":     date_range,
                "size":           db_size
            }
        finally:
            if conn:
                return_conn(conn)

    def get_vix_level(self) -> Optional[float]:
        """
        Get current VIX level for volatility-based threshold adjustments.
        Returns VIX close price as float, or None if unavailable.
        """
        try:
            bars = self.get_bars_from_memory("VIX", limit=1)
            if bars:
                return bars[-1]["close"]

            bar = self.get_latest_bar("VIX")
            if bar:
                return bar["close"]

            url = "https://eodhd.com/api/real-time/VIX.INDX"
            params = {
                "api_token": config.EODHD_API_KEY,
                "fmt": "json"
            }

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data.get("close", 0))

            return None

        except Exception as e:
            logger.warning(f"[DATA-MGR] VIX fetch error: {e}")
            return None


# ───────────────────────────────────────────────────────────────
# Global singleton
# ───────────────────────────────────────────────────────────────
data_manager = DataManager()
