"""
Data Manager - Consolidated Data Fetching, Storage, and Database Management

Design principles:
  - Postgres (or SQLite locally) is the SINGLE source of truth for all bars.
  - NO in-memory live bar accumulator — every bar is persisted to DB immediately.
  - On startup, call startup_backfill_today(watchlist) to fetch today's full
    session (04:00 ET → now) so OR bars are available even after a midday restart.
  - Each scan cycle, update_ticker() fetches only bars since last_bar_time
    (incremental) — no full 5-day refetch every cycle.
  - 1m bars → intraday_bars table.
  - Materialized 5m bars → intraday_bars_5m table (rebuilt from 1m after each store).
  - get_today_session_bars() queries strictly by today's ET date. It NEVER falls
    back to a prior date. If today has no bars, it returns [] and the scanner skips.
  - Historical data accumulates over time for future backtesting.

EODHD intraday endpoint rules:
  - URL:  /api/intraday/{TICKER}.US
  - from/to MUST be Unix timestamps (int) — date strings cause 422 errors.
  - Returns ET-naive datetimes (extended hours 4 AM – 8 PM ET, ~960 bars/day).
"""
import time
import os
import requests
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime, date as date_type
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
import config
import db_connection
from db_connection import (
    get_conn, ph, dict_cursor, serial_pk,
    upsert_bar_sql, upsert_bar_5m_sql, upsert_metadata_sql
)

ET = ZoneInfo("America/New_York")

# Per-ticker update TTL — prevents hammering EODHD during rapid scan cycles.
# 2 minutes is fine since we fetch 1m bars; each incremental call is tiny.
_last_update: Dict[str, datetime] = {}
UPDATE_TTL = timedelta(minutes=2)


class DataManager:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.api_key = config.EODHD_API_KEY
        self.initialize_database()

    # ═════════════════════════════════════════════════════════════
    # DATABASE SETUP
    # ═════════════════════════════════════════════════════════════

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

        # Materialized 5m bars — rebuilt from 1m after each store
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

        # Fetch state — tracks last stored bar per ticker for incremental fetches
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_metadata (
                ticker        TEXT PRIMARY KEY,
                last_fetch    TIMESTAMP,
                last_bar_time TIMESTAMP,
                bar_count     INTEGER DEFAULT 0
            )
        """)

        # DB version — triggers migration if schema changed
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

    # ═════════════════════════════════════════════════════════════
    # EODHD FETCH  (Unix timestamps only — never date strings)
    # ═════════════════════════════════════════════════════════════

    def _fetch_range(self, ticker: str, from_ts: int, to_ts: int,
                     interval: str = "1m") -> List[Dict]:
        """
        Core EODHD intraday fetch.
        from_ts / to_ts are UTC Unix timestamps (int).
        Returns bars with ET-naive datetimes stored as local ET.
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
                    # Convert UTC Unix timestamp → ET-naive datetime
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
                except Exception as e:
                    print(f"[DATA] Bar parse error for {ticker}: {e}")
                    continue
            return bars

        except requests.exceptions.HTTPError as e:
            print(f"[DATA] ❌ API Error for {ticker}: {e}")
            return []
        except Exception as e:
            print(f"[DATA] ❌ Unexpected error for {ticker}: {e}")
            return []

    # ═════════════════════════════════════════════════════════════
    # STARTUP BACKFILL  (call once before the scanner loop starts)
    # ═════════════════════════════════════════════════════════════

    def startup_backfill_today(self, tickers: List[str]):
        """
        Fetch today's full session (04:00 ET → now) for every ticker.

        Must be called ONCE at startup before the scanner loop begins.
        This guarantees 9:30-9:40 OR bars are in DB regardless of what
        time the container started or restarted.

        After this runs, update_ticker() handles incremental updates each cycle.
        """
        now_et      = datetime.now(ET)
        today_start = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
        from_ts     = int(today_start.timestamp())
        to_ts       = int(now_et.timestamp())

        print(f"\n[DATA] 🔄 Startup backfill: {len(tickers)} tickers | "
              f"04:00 ET → {now_et.strftime('%I:%M %p ET')}")

        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    self.store_bars(ticker, bars)
                    self.materialize_5m_bars(ticker)
                    or_count = sum(
                        1 for b in bars
                        if dtime(9, 30) <= b["datetime"].time() < dtime(9, 40)
                    )
                    print(f"[DATA] ✅ [{idx}/{len(tickers)}] {ticker}: "
                          f"{len(bars)} bars stored ({or_count} OR bars)")
                else:
                    print(f"[DATA] ⚠️  [{idx}/{len(tickers)}] {ticker}: "
                          f"no bars returned for today")
            except Exception as e:
                print(f"[DATA] ❌ [{idx}/{len(tickers)}] {ticker} backfill error: {e}")

        print("[DATA] ✅ Startup backfill complete\n")

    # ═════════════════════════════════════════════════════════════
    # INCREMENTAL UPDATE  (called each scan cycle per ticker)
    # ═════════════════════════════════════════════════════════════

    def _get_last_bar_ts(self, ticker: str) -> Optional[datetime]:
        """Read the last stored bar timestamp from fetch_metadata."""
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

    def update_ticker(self, ticker: str):
        """
        Fetch only new bars since last_bar_time (incremental).
        Three cases:
          1. last_bar is today  → fetch last 10 min overlap → now  (fast, ~1-5 bars)
          2. last_bar is prior day → fetch today 04:00 ET → now    (today catch-up)
          3. No data at all     → seed 30 days for backtest history (one-time)
        """
        # TTL guard — don't hammer EODHD more than once per 2 minutes per ticker
        now_utc = datetime.utcnow()
        last_called = _last_update.get(ticker)
        if last_called and (now_utc - last_called) < UPDATE_TTL:
            return
        _last_update[ticker] = now_utc

        now_et    = datetime.now(ET)
        today_et  = now_et.date()
        last_bar  = self._get_last_bar_ts(ticker)

        if last_bar:
            last_bar_date = last_bar.date()
            if last_bar_date < today_et:
                # Last bar is from a prior day — fetch today's full session
                today_start = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
                from_ts = int(today_start.timestamp())
                label = f"today catch-up (last bar was {last_bar_date})"
            else:
                # Last bar is today — incremental, 10-min overlap for revisions
                fetch_from = last_bar - timedelta(minutes=10)
                from_ts = int(fetch_from.replace(tzinfo=ET).timestamp())
                label = f"incremental from {fetch_from.strftime('%H:%M ET')}"
        else:
            # No data at all — seed 30 days for backtesting
            from_dt = datetime.utcnow() - timedelta(days=30)
            from_ts = int(from_dt.timestamp())
            label = "full seed (30 days)"

        to_ts = int(now_et.timestamp())
        print(f"[DATA] {ticker} → {label}")

        bars = self._fetch_range(ticker, from_ts, to_ts)
        if bars:
            self.store_bars(ticker, bars)
            self.materialize_5m_bars(ticker)
        else:
            print(f"[DATA] ⚠️  {ticker}: no new bars returned")

    # ═════════════════════════════════════════════════════════════
    # STORAGE
    # ═════════════════════════════════════════════════════════════

    def store_bars(self, ticker: str, bars: List[Dict]) -> int:
        """Upsert 1m bars into intraday_bars and update fetch_metadata."""
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

        print(f"[DATA] ❌ All {max_retries} store attempts failed for {ticker}")
        return 0

    def materialize_5m_bars(self, ticker: str):
        """
        Compute 5m OHLCV from today's 1m bars and upsert into intraday_bars_5m.
        Only processes today to keep the operation fast.
        Called automatically after every store_bars().
        """
        bars_1m = self.get_today_session_bars(ticker)
        if not bars_1m:
            return

        # Group bars into 5-minute buckets (floor to 5m boundary)
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
            print(f"[DATA] ❌ 5m materialization error for {ticker}: {e}")
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

    # ═════════════════════════════════════════════════════════════
    # SESSION QUERIES — today only, no fallback
    # ═════════════════════════════════════════════════════════════

    def _parse_bar_rows(self, rows) -> List[Dict]:
        """Shared row → dict parser for all session queries."""
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
        Return today's 1m bars from DB (04:00–20:00 ET today).

        NEVER falls back to a prior date. If today has no bars, returns [].
        The scanner and sniper both handle [] by logging and skipping cleanly.

        This is the ONLY data source used by the live scanner. No yesterday,
        no synthetic data, no made-up ranges.
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
        """
        Return today's materialized 5m bars from intraday_bars_5m.
        Used for multi-timeframe confirmation in CFW6.
        """
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

    # ═════════════════════════════════════════════════════════════
    # BACKTESTING QUERIES — multi-day, specific dates
    # ═════════════════════════════════════════════════════════════

    def get_bars_by_date(self, ticker: str, session_date: date_type) -> List[Dict]:
        """
        Return all 1m bars for a specific calendar date (ET-naive).
        FOR BACKTESTING ONLY — not used by the live scanner.
        """
        day_start = datetime.combine(session_date, dtime(4, 0, 0))
        day_end   = datetime.combine(session_date, dtime(20, 0, 0))

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

    def get_available_dates(self, ticker: str) -> List[date_type]:
        """
        Return sorted list of all dates with stored bars for a ticker.
        Used to enumerate backtest sessions.
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        if db_connection.USE_POSTGRES:
            cursor.execute(f"""
                SELECT DISTINCT DATE(datetime) AS d
                FROM intraday_bars
                WHERE ticker = {p}
                ORDER BY d ASC
            """, (ticker,))
        else:
            cursor.execute(f"""
                SELECT DISTINCT date(datetime) AS d
                FROM intraday_bars
                WHERE ticker = {p}
                ORDER BY d ASC
            """, (ticker,))
        rows = cursor.fetchall()
        conn.close()
        dates = []
        for row in rows:
            d = row["d"]
            if isinstance(d, str):
                from datetime import date as _date
                d = _date.fromisoformat(d)
            dates.append(d)
        return dates

    # ═════════════════════════════════════════════════════════════
    # LIVE PRICE SNAPSHOTS  (position monitoring — not strategy input)
    # ═════════════════════════════════════════════════════════════

    def bulk_fetch_live_snapshots(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetch real-time price snapshots for up to 50 tickers in ONE API call.
        Used only for position stop/target monitoring, not for strategy bars.
        """
        if not tickers:
            return {}

        primary = f"{tickers[0]}.US"
        extras  = ",".join(f"{t}.US" for t in tickers[1:])
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

            result = {}
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

            print(f"[LIVE] ✅ Bulk snapshot: {len(result)}/{len(tickers)} tickers")
            return result

        except Exception as e:
            print(f"[LIVE] ❌ Bulk snapshot error: {e}")
            return {}

    def bulk_update_live_bars(self, tickers: List[str]) -> int:
        """
        Backward-compat stub kept for scanner.py.
        The in-memory accumulator is removed — bars are now persisted to DB.
        This just fetches a live snapshot (for the position monitor / log banner)
        without accumulating anything in memory.
        """
        snapshots = self.bulk_fetch_live_snapshots(tickers)
        return len(snapshots)

    # ═════════════════════════════════════════════════════════════
    # UTILITIES
    # ═════════════════════════════════════════════════════════════

    def cleanup_old_bars(self, days_to_keep: int = 60):
        """
        Remove bars older than days_to_keep from both 1m and 5m tables.
        Default 60 days retains enough history for backtesting.
        """
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
        Return the N most recent bars. Backward-compat alias.
        Prefer get_today_session_bars() for live scanning.
        """
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


# ─────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────
data_manager = DataManager()


# Legacy compatibility shims
def update_ticker(ticker: str):
    data_manager.update_ticker(ticker)

def cleanup_old_bars(days_to_keep: int = 60):
    data_manager.cleanup_old_bars(days_to_keep)
