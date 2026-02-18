"""
Data Manager - Consolidated Data Fetching, Storage, and Database Management
Replaces: incremental_fetch.py, historical_loader.py, database_setup.py
Handles all data operations for War Machine
"""
import sqlite3
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import config

class DataManager:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.api_key = config.EODHD_API_KEY
        self.initialize_database()
    
    def initialize_database(self):
        """Create all necessary database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Intraday bars table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intraday_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        
        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_datetime 
            ON intraday_bars(ticker, datetime DESC)
        """)
        
        # Metadata table to track last update times
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_metadata (
                ticker TEXT PRIMARY KEY,
                last_fetch TIMESTAMP,
                last_bar_time TIMESTAMP,
                bar_count INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
        
        print(f"[DATA] Database initialized: {self.db_path}")
    
    def fetch_intraday_bars(self, ticker: str, interval: str = "1m", 
                           from_date: Optional[str] = None,
                           to_date: Optional[str] = None) -> List[Dict]:
        """
        Fetch intraday bars from EODHD API
        
        Args:
            ticker: Stock symbol
            interval: "1m", "5m", "1h" etc.
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
        """
        # Default to today if not specified
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        
        if not from_date:
            from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": self.api_key,
            "interval": interval,
            "from": from_date,
            "to": to_date,
            "fmt": "json"
        }
        
        try:
            print(f"[DATA] Fetching {ticker} {interval} bars from {from_date} to {to_date}...")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                print(f"[DATA] No data returned for {ticker}")
                return []
            
            bars = []
            for bar in data:
                bars.append({
                    "datetime": datetime.fromtimestamp(bar["timestamp"]),
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"]
                })
            
            print(f"[DATA] ✅ Fetched {len(bars)} bars for {ticker}")
            return bars
            
        except requests.exceptions.RequestException as e:
            print(f"[DATA] ❌ API Error for {ticker}: {e}")
            return []
        except Exception as e:
            print(f"[DATA] ❌ Unexpected error for {ticker}: {e}")
            return []
    
    def store_bars(self, ticker: str, bars: List[Dict]):
        """Store bars in database (upsert to avoid duplicates)"""
        if not bars:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        inserted = 0
        for bar in bars:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO intraday_bars 
                    (ticker, datetime, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker,
                    bar["datetime"],
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar["volume"]
                ))
                inserted += 1
            except Exception as e:
                print(f"[DATA] Error inserting bar: {e}")
                continue
        
        # Update metadata
        cursor.execute("""
            INSERT OR REPLACE INTO fetch_metadata 
            (ticker, last_fetch, last_bar_time, bar_count)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?)
        """, (ticker, bars[-1]["datetime"], len(bars)))
        
        conn.commit()
        conn.close()
        
        print(f"[DATA] Stored {inserted} bars for {ticker}")
    
    def get_bars_from_memory(self, ticker: str, limit: int = 300) -> List[Dict]:
        """Retrieve bars from local database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = ?
            ORDER BY datetime DESC
            LIMIT ?
        """, (ticker, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        # Convert to dict format (reverse to chronological order)
        bars = []
        for row in reversed(rows):
            bars.append({
                "datetime": datetime.fromisoformat(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5]
            })
        
        return bars
    
    def update_ticker(self, ticker: str, force: bool = False):
        """
        Incremental update: Fetch only new bars since last update
        
        Args:
            ticker: Stock symbol
            force: If True, fetch full 5 days regardless of last update
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check last fetch time
        cursor.execute("""
            SELECT last_fetch, last_bar_time 
            FROM fetch_metadata 
            WHERE ticker = ?
        """, (ticker,))
        
        result = cursor.fetchone()
        conn.close()
        
        # Determine fetch window
        if force or not result:
            # Full fetch: last 5 days
            from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            print(f"[DATA] Full fetch for {ticker} (5 days)")
        else:
            last_fetch = datetime.fromisoformat(result[0])
            
            # Only fetch if last update was > 2 minutes ago
            if (datetime.now() - last_fetch).total_seconds() < 120:
                print(f"[DATA] {ticker} recently updated, skipping...")
                return
            
            # Incremental: fetch from last bar time
            from_date = datetime.fromisoformat(result[1]).strftime("%Y-%m-%d")
            print(f"[DATA] Incremental fetch for {ticker} from {from_date}")
        
        # Fetch and store
        bars = self.fetch_intraday_bars(ticker, interval="1m", from_date=from_date)
        if bars:
            self.store_bars(ticker, bars)
    
    def cleanup_old_bars(self, days_to_keep: int = 7):
        """Remove bars older than specified days to save space"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM intraday_bars 
            WHERE datetime < ?
        """, (cutoff_date,))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"[CLEANUP] Removed {deleted} old bars (keeping last {days_to_keep} days)")
    
    def get_database_stats(self) -> Dict:
        """Get database statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total bars
        cursor.execute("SELECT COUNT(*) FROM intraday_bars")
        total_bars = cursor.fetchone()[0]
        
        # Unique tickers
        cursor.execute("SELECT COUNT(DISTINCT ticker) FROM intraday_bars")
        unique_tickers = cursor.fetchone()[0]
        
        # Date range
        cursor.execute("SELECT MIN(datetime), MAX(datetime) FROM intraday_bars")
        date_range = cursor.fetchone()
        
        # Database size
        db_size = os.path.getsize(self.db_path) / (1024 * 1024)  # MB
        
        conn.close()
        
        return {
            "total_bars": total_bars,
            "unique_tickers": unique_tickers,
            "date_range": date_range,
            "size_mb": db_size
        }
    
    def load_historical_data(self, ticker: str, days: int = 30) -> List[Dict]:
        """
        Load historical data for backtesting
        
        Args:
            ticker: Stock symbol
            days: Number of days to load
        """
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        
        print(f"[HISTORICAL] Loading {days} days for {ticker}...")
        
        bars = self.fetch_intraday_bars(ticker, interval="1m", 
                                        from_date=from_date, 
                                        to_date=to_date)
        
        if bars:
            self.store_bars(ticker, bars)
        
        return bars
    
    def bulk_update(self, tickers: List[str]):
        """Update multiple tickers efficiently"""
        print(f"[BULK] Updating {len(tickers)} tickers...")
        
        for idx, ticker in enumerate(tickers, 1):
            print(f"[{idx}/{len(tickers)}] {ticker}")
            try:
                self.update_ticker(ticker)
            except Exception as e:
                print(f"[BULK] Error updating {ticker}: {e}")
                continue
        
        print(f"[BULK] ✅ Update complete")

# Global instance
data_manager = DataManager()

# Helper functions for backward compatibility
def update_ticker(ticker: str):
    """Legacy function - calls DataManager"""
    data_manager.update_ticker(ticker)

def cleanup_old_bars(days_to_keep: int = 7):
    """Legacy function - calls DataManager"""
    data_manager.cleanup_old_bars(days_to_keep)
