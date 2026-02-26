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
"""
import time
import os
import requests
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime, date as date_type
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import config
import db_connection
from db_connection import (
    get_conn, ph, dict_cursor, serial_pk,
    upsert_bar_sql, upsert_bar_5m_sql, upsert_metadata_sql
)

ET = ZoneInfo("America/New_York")

_logged_skip = set()  # Track tickers we've logged skip messages for

# Per-ticker update TTL — prevents hammering EODHD during rapid scan cycles.
_last_update: Dict[str, datetime] = {}
UPDATE_TTL = timedelta(minutes=2)


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
        """
        if not config.ENABLE_WEBSOCKET_FEED:
            return None
        
        try:
            from ws_feed import is_connected, get_current_bar
            if is_connected():
                return get_current_bar(ticker)
        except ImportError:
            pass
        except Exception as e:
            # Silently fail - WS is optional optimization
            pass
        
        return None

    def _is_ws_connected(self) -> bool:
        """Check if WebSocket feed is active."""
        if not config.ENABLE_WEBSOCKET_FEED:
            return False
        
        try:
            from ws_feed import is_connected
            return is_connected()
        except (ImportError, Exception):
            return False

    # =============================================================
    # DATABASE SETUP
    # =============================================================

    def initialize_database(self):
        """Create all necessary database tables."""
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
            cursor.execute("DELETE FROM intraday_bars")
            cursor.execute("DELETE FROM intraday_bars_5m")
            cursor.execute("DELETE FROM fetch_metadata")
            cursor.execute("DELETE FROM db_version")
            cursor.execute("INSERT INTO db_version (version) VALUES (2)")
            print("[DATA] Migration v2: Cleared UTC bars — switching to ET-naive storage")

        conn.commit()
        conn.close()
        db_type = "PostgreSQL" if db_connection.USE_POSTGRES else self.db_path
        print(f"[DATA] Database initialized: {db_type}")

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
                    # Check for required fields
                    required = ["timestamp", "open", "high", "low", "close", "volume"]
                    missing = [k for k in required if k not in bar or bar[k] is None]
                    
                    if missing:
                        print(f"[DATA] {ticker}: Skipping bar with missing fields: {missing}")
                        continue
                    
                    dt_et = datetime.fromtimestamp(
                        bar["timestamp"], tz=ET
                    ).replace(tzinfo=None)
                    
                    # Legitimate zero volume is fine - we already validated it exists
                    bars.append({
                        "datetime": dt_et,
                        "open":     float(bar["open"]),
                        "high":     float(bar["high"]),
                        "low":      float(bar["low"]),
                        "close":    float(bar["close"]),
                        "volume":   int(bar["volume"])  # Can be 0 legitimately
                    })
                except (ValueError, TypeError, KeyError) as e:
                    print(f"[DATA] Bar parse error for {ticker}: {e}")
                    continue

            return bars

        except requests.exceptions.HTTPError as e:
            print(f"[DATA] API Error for {ticker}: {e}")
            return []
        except Exception as e:
            print(f"[DATA] Unexpected error for {ticker}: {e}")
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

        print(f"\n[DATA] Startup backfill: {len(tickers)} tickers | "
              f"30 days history -> yesterday (WebSocket handles today's bars)")

        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    self.store_bars(ticker, bars)
                    self.materialize_5m_bars(ticker)
                    print(f"[DATA] [{idx}/{len(tickers)}] {ticker}: "
                          f"{len(bars)} historical bars stored")
                else:
                    print(f"[DATA] [{idx}/{len(tickers)}] {ticker}: "
                          f"no historical bars returned")
            except Exception as e:
                print(f"[DATA] [{idx}/{len(tickers)}] {ticker} backfill error: {e}")

        print("[DATA] Startup backfill complete — WebSocket feed handles today's bars\n")

    def startup_intraday_backfill_today(self, tickers: List[str]):
        """
        Best-effort REST fetch of today's intraday bars for mid-session restarts.
        """
        now_et   = datetime.now(ET)
        today_et = now_et.date()
        from_dt  = datetime.combine(today_et, dtime(4, 0, 0))
        from_ts  = int(from_dt.replace(tzinfo=ET).timestamp())
        to_ts    = int(now_et.timestamp())

        print(f"[DATA] Today's REST backfill: {len(tickers)} tickers | "
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
                print(f"[DATA] Today REST backfill error for {ticker}: {e}")

        if filled:
            print(f"[DATA] Today REST backfill complete: {filled}/{len(tickers)} tickers\n")
        else:
            print(f"[DATA] Today REST backfill: no same-day data from EODHD — WS-only session\n")

    # =============================================================
    # CACHE-AWARE STARTUP & SYNC (Phase 2: Merged from cache_integration)
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
        from candle_cache import candle_cache
        
        now_et = datetime.now(ET)
        timeframe = '1m'
        
        print(f"\n[CACHE] 🚀 Smart startup backfill: {len(tickers)} tickers | {days} days")
        
        cache_hits = 0
        cache_misses = 0
        gap_fills = 0
        total_api_bars = 0
        total_cached_bars = 0
        
        for idx, ticker in enumerate(tickers, 1):
            try:
                # Step 1: Check cache status
                metadata = candle_cache.get_cache_metadata(ticker, timeframe)
                
                if metadata and metadata["bar_count"] > 0:
                    # Cache exists - check if we need updates
                    last_cached = metadata["last_bar_time"]
                    if isinstance(last_cached, str):
                        last_cached = datetime.fromisoformat(last_cached)
                    
                    # Load from cache
                    cached_bars = candle_cache.load_cached_candles(ticker, timeframe, days)
                    
                    if cached_bars:
                        # Store cached bars to intraday_bars (for compatibility)
                        self.store_bars(ticker, cached_bars, quiet=True)
                        self.materialize_5m_bars(ticker)
                        total_cached_bars += len(cached_bars)
                        
                        # Check if we need to fetch new data
                        age_minutes = (now_et - last_cached.replace(tzinfo=ET if last_cached.tzinfo is None else None)).total_seconds() / 60
                        
                        if age_minutes > 60:  # Cache older than 1 hour
                            # Fetch only new data since last cache
                            from_ts = int(last_cached.replace(tzinfo=ET).timestamp())
                            to_ts = int(now_et.timestamp())
                            
                            new_bars = self._fetch_range(ticker, from_ts, to_ts)
                            if new_bars:
                                # Cache new bars
                                candle_cache.cache_candles(ticker, timeframe, new_bars, quiet=True)
                                # Also store to intraday_bars
                                self.store_bars(ticker, new_bars, quiet=True)
                                self.materialize_5m_bars(ticker)
                                total_api_bars += len(new_bars)
                                gap_fills += 1
                                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                      f"{len(cached_bars)} from cache + {len(new_bars)} new bars")
                            else:
                                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                      f"{len(cached_bars)} bars from cache (up-to-date)")
                        else:
                            print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                  f"{len(cached_bars)} bars from cache (fresh)")
                        
                        cache_hits += 1
                        continue
                
                # Step 2: Cache miss - full backfill from API
                cache_misses += 1
                today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ts = int((today_midnight - timedelta(days=days)).timestamp())
                to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())
                
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    # Cache the bars
                    candle_cache.cache_candles(ticker, timeframe, bars, quiet=True)
                    # Store to intraday_bars
                    self.store_bars(ticker, bars, quiet=True)
                    self.materialize_5m_bars(ticker)
                    total_api_bars += len(bars)
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                          f"{len(bars)} bars fetched and cached")
                else:
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data returned")
            
            except Exception as e:
                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")
        
        # Print summary
        print(f"\n[CACHE] ✅ Startup complete!")
        print(f"[CACHE] 📊 Stats:")
        print(f"[CACHE]   - Cache hits: {cache_hits}/{len(tickers)} ({cache_hits/len(tickers)*100:.1f}%)")
        print(f"[CACHE]   - Cache misses: {cache_misses}")
        print(f"[CACHE]   - Gap fills: {gap_fills}")
        print(f"[CACHE]   - Bars from cache: {total_cached_bars:,}")
        print(f"[CACHE]   - Bars from API: {total_api_bars:,}")
        
        if cache_hits > 0:
            api_reduction = (1 - total_api_bars / (total_cached_bars + total_api_bars)) * 100 if (total_cached_bars + total_api_bars) > 0 else 0
            print(f"[CACHE]   - API reduction: {api_reduction:.1f}%")
        print()

    def store_bars_with_cache(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """
        Enhanced store_bars that auto-caches to candle_cache.
        
        This is a wrapper around store_bars() that also caches to candle_cache.
        Use this when you want automatic caching behavior.
        """
        if not bars:
            return 0
        
        # Store to intraday_bars (original behavior)
        result = self.store_bars(ticker, bars, quiet)
        
        # Also cache to candle_cache
        if result > 0:
            try:
                from candle_cache import candle_cache
                candle_cache.cache_candles(ticker, '1m', bars, quiet=True)
            except Exception as e:
                print(f"[CACHE] Auto-cache failed for {ticker}: {e}")
        
        return result

    def background_cache_sync(self, tickers: List[str]):
        """
        Hourly background task to sync cache with latest data.
        
        Run this every 60 minutes to keep cache fresh without
        impacting real-time scanning performance.
        """
        from candle_cache import candle_cache
        
        now_et = datetime.now(ET)
        
        # Only sync during market hours + 1 hour after close
        if not (config.MARKET_OPEN <= now_et.time() <= dtime(17, 0)):
            return
        
        print(f"[CACHE] 🔄 Background sync: {len(tickers)} tickers")
        
        synced = 0
        for ticker in tickers:
            try:
                metadata = candle_cache.get_cache_metadata(ticker, '1m')
                if not metadata:
                    continue
                
                last_cached = metadata["last_bar_time"]
                if isinstance(last_cached, str):
                    last_cached = datetime.fromisoformat(last_cached)
                
                # Sync if cache is > 10 minutes old
                age_minutes = (now_et - last_cached.replace(tzinfo=ET if last_cached.tzinfo is None else None)).total_seconds() / 60
                
                if age_minutes > 10:
                    from_ts = int(last_cached.replace(tzinfo=ET).timestamp())
                    to_ts = int(now_et.timestamp())
                    
                    new_bars = self._fetch_range(ticker, from_ts, to_ts)
                    if new_bars:
                        candle_cache.cache_candles(ticker, '1m', new_bars, quiet=True)
                        synced += 1
            
            except Exception as e:
                print(f"[CACHE] Background sync error for {ticker}: {e}")
        
        if synced > 0:
            print(f"[CACHE] ✅ Background sync complete: {synced}/{len(tickers)} updated")

    def warmup_cache(self, tickers: List[str], days: int = 60):
        """
        One-time cache warmup with extended history.
        
        Use this to pre-populate cache with 60 days of data
        for better backtesting capabilities.
        """
        from candle_cache import candle_cache
        
        print(f"[CACHE] 🔥 Cache warmup: {len(tickers)} tickers | {days} days")
        
        now_et = datetime.now(ET)
        today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        from_ts = int((today_midnight - timedelta(days=days)).timestamp())
        to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())
        
        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    candle_cache.cache_candles(ticker, '1m', bars)
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: {len(bars)} bars cached")
                else:
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data")
            except Exception as e:
                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")
        
        print(f"[CACHE] ✅ Warmup complete!\n")

    # =============================================================
    # INCREMENTAL UPDATE (module-level legacy shim calls this)
    # =============================================================

    def _get_last_bar_ts(self, ticker: str) -> Optional[datetime]:
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        cursor.execute(
            f"SELECT last_bar_time FROM fetch_metadata WHERE ticker = {p}",
            (ticker,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row or not row["last_bar_time"]:
            return None
        ts = row["last_bar_time"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        return ts

    def _update_ticker_internal(self, ticker: str):
        """
        Smart incremental updates:
        - During market hours: SKIP (WebSocket owns today)
        - After hours: Fetch ONLY missing ranges
        - Daily close: Fetch ONLY yesterday's bars
        """
        now_et = datetime.now(ET)
        today_et = now_et.date()
        
        # CRITICAL OPTIMIZATION: Skip during market hours if WebSocket is connected
        if config.MARKET_OPEN <= now_et.time() <= config.MARKET_CLOSE:
            if self._is_ws_connected():
                return  # WebSocket owns today - no API calls needed
        
        last_bar = self._get_last_bar_ts(ticker)
        
        # If no data at all, fetch 30 days
        if not last_bar:
            from_ts = int((now_et - timedelta(days=30)).timestamp())
            to_ts = int(now_et.timestamp())
            label = "initial 30-day seed"
        else:
            # Gap detection: fetch from last bar to now
            last_bar_date = last_bar.date()
            
            # If last bar is from prior day, fetch yesterday only (not full range)
            if last_bar_date < today_et:
                # Fetch yesterday's bars only
                yesterday = today_et - timedelta(days=1)
                from_ts = int(datetime.combine(yesterday, dtime(4, 0)).replace(tzinfo=ET).timestamp())
                to_ts = int(datetime.combine(yesterday, dtime(20, 0)).replace(tzinfo=ET).timestamp())
                label = f"yesterday's bars ({yesterday})"
            else:
                # Same-day gap fill (after hours)
                fetch_from = last_bar + timedelta(minutes=1)
                from_ts = int(fetch_from.replace(tzinfo=ET).timestamp())
                to_ts = int(now_et.timestamp())
                label = f"gap fill from {fetch_from.strftime('%H:%M ET')}"
        
        print(f"[DATA] {ticker} -> {label}")
        bars = self._fetch_range(ticker, from_ts, to_ts)
        
        if bars:
            self.store_bars(ticker, bars)
            self.materialize_5m_bars(ticker)
        else:
            print(f"[DATA] {ticker}: no new bars returned")

    # =============================================================
    # STORAGE
    # =============================================================

    def store_bars(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """
        Upsert 1m bars into intraday_bars and update fetch_metadata.

        Args:
            ticker: Stock symbol.
            bars:   List of bar dicts (datetime, open, high, low, close, volume).
            quiet:  When True, suppress the per-call log line. Used by ws_feed
                    during the startup backfill window to avoid console spam.
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
                    print(f"[DATA] Stored {len(bars)} bars for {ticker} "
                          f"(latest: {latest_bar_dt.strftime('%m/%d %H:%M')} ET)")
                return len(bars)
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                print(f"[DATA] Store attempt {attempt+1}/{max_retries} "
                      f"failed for {ticker}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        print(f"[DATA] All {max_retries} store attempts failed for {ticker}")
        return 0

    def materialize_5m_bars(self, ticker: str):
        """
        Compute 5m OHLCV from today's 1m bars and upsert into intraday_bars_5m.
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
            print(f"[DATA] 5m materialization error for {ticker}: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # =============================================================
    # SESSION QUERIES (WEBSOCKET-OPTIMIZED)
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
        """
        today_et  = datetime.now(ET).date()
        day_start = datetime.combine(today_et, dtime(4, 0, 0))
        day_end   = datetime.combine(today_et, dtime(20, 0, 0))

        p = ph()
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
        conn.close()
        return self._parse_bar_rows(rows)

    def get_today_5m_bars(self, ticker: str) -> List[Dict]:
        """Return today's materialized 5m bars."""
        today_et  = datetime.now(ET).date()
        day_start = datetime.combine(today_et, dtime(4, 0, 0))
        day_end   = datetime.combine(today_et, dtime(20, 0, 0))

        p = ph()
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
        conn.close()
        return self._parse_bar_rows(rows)

    def get_latest_bar(self, ticker: str) -> Optional[Dict]:
        """
        Get the most recent bar for a ticker.
        
        WEBSOCKET-OPTIMIZED: Checks WebSocket feed FIRST if connected,
        falls back to database query only if WS unavailable.
        
        This reduces API quota consumption and provides fresher data.
        
        Returns:
            Bar dict with datetime, open, high, low, close, volume or None
        """
        # OPTIMIZATION: Try WebSocket first
        ws_bar = self._get_ws_bar(ticker)
        if ws_bar:
            return ws_bar
        
        # Fallback: Query database for latest bar
        p = ph()
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
        conn.close()
        
        if not row:
            return None
        
        bars = self._parse_bar_rows([row])
        return bars[0] if bars else None

    def get_latest_price(self, ticker: str) -> Optional[float]:
        """
        Get the most recent close price for a ticker.
        
        WEBSOCKET-OPTIMIZED: Checks WebSocket feed FIRST.
        
        Returns:
            Close price as float or None
        """
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
            print(f"[DATA] Error fetching daily OHLC for {ticker} on {target_date}: {e}")
            return None

    def get_previous_day_ohlc(self, ticker: str) -> Optional[Dict]:
        """
        Fetch previous trading day's OHLC via get_daily_ohlc().
        Returns dict: {"open", "high", "low", "close", "volume"} or None.
        """
        now_et = datetime.now(ET)
        yesterday = now_et.date() - timedelta(days=1)
        
        # Walk back up to 5 days to skip weekends/holidays
        for days_back in range(1, 6):
            target_date = now_et.date() - timedelta(days=days_back)
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
        
        WEBSOCKET-OPTIMIZED: For tickers with WS data, returns WS bars immediately.
        Only fetches REST API snapshots for tickers without WS coverage.
        """
        if not tickers:
            return {}

        result = {}
        tickers_needing_api = []
        
        # First pass: Try to get data from WebSocket
        if self._is_ws_connected():
            for ticker in tickers:
                ws_bar = self._get_ws_bar(ticker)
                if ws_bar:
                    result[ticker] = ws_bar
                else:
                    tickers_needing_api.append(ticker)
        else:
            tickers_needing_api = tickers
        
        # Second pass: Fetch remaining tickers via REST API
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

            ws_count = len(result) - len([t for t in tickers_needing_api if t in result])
            api_count = len([t for t in tickers_needing_api if t in result])
            print(f"[LIVE] Bulk snapshot: {len(result)}/{len(tickers)} tickers "
                  f"(WS: {ws_count}, API: {api_count})")
            return result

        except Exception as e:
            print(f"[LIVE] Bulk snapshot error: {e}")
            return result

    # =============================================================
    # CACHE MANAGEMENT
    # =============================================================

    def clear_prev_day_cache(self) -> None:
        """
        Clear previous day OHLC cache and PDH/PDL cache in breakout detector.
        Called at EOD to prepare for new trading day.
        """
        try:
            from signal_generator import signal_generator
            signal_generator.detector.clear_pdh_pdl_cache()
            print("[DATA] PDH/PDL cache cleared for new session")
        except Exception as e:
            print(f"[DATA] PDH/PDL cache clear error: {e}")

    # =============================================================
    # UTILITIES
    # =============================================================

    def _cleanup_old_bars_internal(self, days_to_keep: int = 60):
        """Remove bars older than days_to_keep from 1m and 5m tables."""
        cutoff = datetime.now() - timedelta(days=days_to_keep)
        p = ph()
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM intraday_bars WHERE datetime < {p}", (cutoff,)
        )
        cursor.execute(
            f"DELETE FROM intraday_bars_5m WHERE datetime < {p}", (cutoff,)
        )
        conn.commit()
        conn.close()
        print(f"[CLEANUP] Removed bars older than {days_to_keep} days")

    def get_bars_from_memory(self, ticker: str, limit: int = 390) -> List[Dict]:
        """
        Return N most recent bars. Prefer get_today_session_bars() for live scanning.
        
        WEBSOCKET-OPTIMIZED: If requesting only 1 bar and WS is connected,
        returns WS bar immediately.
        """
        # Optimization: Single bar request during live session
        if limit == 1:
            ws_bar = self._get_ws_bar(ticker)
            if ws_bar:
                return [ws_bar]
        
        p = ph()
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
        conn.close()
        return list(reversed(self._parse_bar_rows(rows)))

    def get_database_stats(self) -> Dict:
        """Get database statistics for the startup banner."""
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

        conn.close()
        return {
            "total_bars":     total_bars,
            "unique_tickers": unique_tickers,
            "date_range":     date_range,
            "size":           db_size
        }

    def get_vix_level(self) -> Optional[float]:
        """
        Get current VIX level for volatility-based threshold adjustments.

        Returns:
            VIX close price as float, or None if unavailable
        """
        try:
            # Method 1: Try to get VIX from memory first (fastest)
            bars = self.get_bars_from_memory("VIX", limit=1)
            if bars:
                return bars[-1]["close"]
            
            # Method 2: Try latest bar
            bar = self.get_latest_bar("VIX")
            if bar:
                return bar["close"]

            # Method 3: Fall back to fetching latest VIX data via REST
            url = f"https://eodhd.com/api/real-time/VIX.INDX"
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
            print(f"[DATA-MGR] VIX fetch error: {e}")
            return None

# ─────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────
data_manager = DataManager()


# Legacy compatibility shims (keep for existing callers)
def update_ticker(ticker: str):
    """Module-level shim — calls DataManager internal method."""
    data_manager._update_ticker_internal(ticker)

def cleanup_old_bars(days_to_keep: int = 60):
    """Module-level shim — calls DataManager internal method."""
    data_manager._cleanup_old_bars_internal(days_to_keep)
