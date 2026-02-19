"""
Data Manager - Consolidated Data Fetching, Storage, and Database Management
Replaces: incremental_fetch.py, historical_loader.py, database_setup.py
"""
import time
import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import config
import db_connection
from db_connection import get_conn, ph, dict_cursor, serial_pk, upsert_bar_sql, upsert_metadata_sql

ET = ZoneInfo("America/New_York")


class DataManager:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.api_key = config.EODHD_API_KEY
        self.initialize_database()

    def initialize_database(self):
        """Create all necessary database tables."""
        conn = get_conn(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS intraday_bars (
                id {serial_pk()},
                ticker TEXT NOT NULL,
                datetime TIMESTAMP NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, datetime)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_datetime
            ON intraday_bars(ticker, datetime DESC)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_metadata (
                ticker TEXT PRIMARY KEY,
                last_fetch TIMESTAMP,
                last_bar_time TIMESTAMP,
                bar_count INTEGER DEFAULT 0
            )
        """)

        # ── Migration v2: clear UTC-stored bars, switch to ET storage ──────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS db_version (version INTEGER UNIQUE)
        """)
        cursor.execute("SELECT version FROM db_version LIMIT 1")
        row = cursor.fetchone()
        current_version = (row[0] if isinstance(row, (list, tuple)) else row["version"]) if row else 0
        if current_version < 2:
            cursor.execute("DELETE FROM intraday_bars")
            cursor.execute("DELETE FROM fetch_metadata")
            cursor.execute("DELETE FROM db_version")
            cursor.execute("INSERT INTO db_version (version) VALUES (2)")
            print("[DATA] Migration v2: Cleared UTC bars — switching to ET-naive storage")
        # ──────────────────────────────────────────────────────────────────────

        conn.commit()
        conn.close()
        db_type = "PostgreSQL" if db_connection.USE_POSTGRES else self.db_path
        print(f"[DATA] Database initialized: {db_type}")

    def fetch_intraday_bars(self, ticker: str, interval: str = "1m",
                            from_date: str = None, to_date: str = None) -> List[Dict]:
        """
        Fetch intraday bars from EODHD API.
        Bars are stored as ET-naive datetimes so time comparisons in sniper.py work correctly.
        """
        now_dt  = datetime.utcnow()
        from_dt = now_dt - timedelta(days=5)
        from_ts = int(from_dt.timestamp())
        to_ts   = int(now_dt.timestamp())

        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": self.api_key,
            "interval":  interval,
            "from":      from_ts,
            "to":        to_ts,
            "fmt":       "json"
        }

        try:
            print(f"[DATA] Fetching {ticker} {interval} bars (last 5 days)...")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data:
                print(f"[DATA] No data returned for {ticker}")
                return []

            bars = []
            for bar in data:
                try:
                    # Convert Unix timestamp → ET-aware → strip tz → ET-naive
                    # This ensures bar times (9:30, 9:31 ...) match ET time comparisons in sniper.py
                    dt_et = datetime.fromtimestamp(bar["timestamp"], tz=ET).replace(tzinfo=None)
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

            print(f"[DATA] \u2705 {ticker}: {len(bars)} bars fetched")
            return bars

        except requests.exceptions.HTTPError as e:
            print(f"[DATA] \u274c API Error for {ticker}: {e}")
            return []
        except Exception as e:
            print(f"[DATA] \u274c Unexpected error for {ticker}: {e}")
            return []

    def store_bars(self, ticker: str, bars: List[Dict]):
        """Bulk insert bars with retry on connection drop."""
        if not bars:
            return

        max_retries = 3
        for attempt in range(max_retries):
            conn = None
            try:
                conn = get_conn(self.db_path)
                cursor = dict_cursor(conn)

                data = [
                    (ticker, bar['datetime'], bar['open'], bar['high'],
                     bar['low'], bar['close'], bar['volume'])
                    for bar in bars
                ]
                cursor.executemany(upsert_bar_sql(), data)
                cursor.execute(upsert_metadata_sql(),
                               (ticker, bars[-1]['datetime'], len(bars)))
                conn.commit()
                print(f"[DATA] Stored {len(bars)} bars for {ticker}")
                return

            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                print(f"[DATA] Store attempt {attempt + 1}/{max_retries} failed for {ticker}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)

            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        print(f"[DATA] \u274c All {max_retries} store attempts failed for {ticker}")

    def update_ticker(self, ticker: str):
        """Fetch latest bars and store in database. Called by sniper.py."""
        try:
            existing = self.get_bars_from_memory(ticker, limit=1)

            if not existing:
                print(f"[DATA] Full fetch for {ticker} (5 days)")
            else:
                print(f"[DATA] Incremental fetch for {ticker}")

            bars = self.fetch_intraday_bars(ticker)

            if bars:
                self.store_bars(ticker, bars)
            else:
                print(f"[DATA] \u26a0\ufe0f No bars returned for {ticker}")

        except Exception as e:
            print(f"[DATA] \u274c Error updating {ticker}: {e}")

    def get_bars_from_memory(self, ticker: str, limit: int = 300) -> List[Dict]:
        """Retrieve bars from database."""
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

        if not rows:
            return []

        bars = []
        for row in reversed(rows):
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            # Strip any timezone info so comparisons stay ET-naive
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            bars.append({
                "datetime": dt,
                "open":     row["open"],
                "high":     row["high"],
                "low":      row["low"],
                "close":    row["close"],
                "volume":   row["volume"]
            })
        return bars

    def cleanup_old_bars(self, days_to_keep: int = 7):
        """Remove bars older than specified days."""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        p = ph()
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM intraday_bars WHERE datetime < {p}", (cutoff_date,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"[CLEANUP] Removed {deleted} old bars (keeping last {days_to_keep} days)")

    def get_database_stats(self) -> Dict:
        """Get database statistics."""
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)

        cursor.execute("SELECT COUNT(*) as cnt FROM intraday_bars")
        total_bars = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(DISTINCT ticker) as cnt FROM intraday_bars")
        unique_tickers = cursor.fetchone()["cnt"]

        cursor.execute("SELECT MIN(datetime) as mn, MAX(datetime) as mx FROM intraday_bars")
        row = cursor.fetchone()
        date_range = (row["mn"], row["mx"])

        if db_connection.USE_POSTGRES:
            cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database())) as sz")
            db_size = cursor.fetchone()["sz"]
        else:
            db_size = f"{os.path.getsize(self.db_path) / (1024 * 1024):.1f} MB"

        conn.close()
        return {
            "total_bars":     total_bars,
            "unique_tickers": unique_tickers,
            "date_range":     date_range,
            "size":           db_size
        }

    def load_historical_data(self, ticker: str, days: int = 30) -> List[Dict]:
        """Load historical data for backtesting."""
        print(f"[HISTORICAL] Loading {days} days for {ticker}...")
        bars = self.fetch_intraday_bars(ticker, interval="1m")
        if bars:
            self.store_bars(ticker, bars)
        return bars

    def bulk_update(self, tickers: List[str]):
        """Update multiple tickers efficiently."""
        print(f"[BULK] Updating {len(tickers)} tickers...")
        for idx, ticker in enumerate(tickers, 1):
            print(f"[{idx}/{len(tickers)}] {ticker}")
            try:
                self.update_ticker(ticker)
            except Exception as e:
                print(f"[BULK] Error updating {ticker}: {e}")
                continue
        print(f"[BULK] \u2705 Update complete")


# Global singleton
data_manager = DataManager()


# Legacy compatibility shims
def update_ticker(ticker: str):
    data_manager.update_ticker(ticker)

def cleanup_old_bars(days_to_keep: int = 7):
    data_manager.cleanup_old_bars(days_to_keep)
