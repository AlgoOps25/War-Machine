"""
Scanner Helpers - Data Fetching and Caching
"""

import requests
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict
import config


# Initialize SQLite memory cache
DB_PATH = "market_memory.db"
EODHD_API_KEY = os.getenv("EODHD_API_KEY")


def init_memory_db():
    """Initialize SQLite database for bar caching."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            datetime TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            timeframe TEXT DEFAULT '1m',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, datetime, timeframe)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticker_datetime 
        ON bars(ticker, datetime DESC)
    """)
    
    conn.commit()
    conn.close()


# Initialize on module load
init_memory_db()


def insert_bars_to_memory(ticker: str, bars: List[Dict]):
    """Insert bars into SQLite memory cache."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for bar in bars:
        try:
            dt = bar["datetime"]
            if isinstance(dt, datetime):
                dt_str = dt.isoformat()
            else:
                dt_str = dt
                
            cursor.execute("""
                INSERT OR IGNORE INTO bars (ticker, datetime, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                dt_str,
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
                bar["volume"]
            ))
        except Exception as e:
            print(f"Error inserting bar: {e}")
            continue
    
    conn.commit()
    conn.close()


def get_recent_bars_from_memory(ticker: str, limit: int = 300) -> List[Dict]:
    """
    Retrieve recent bars from SQLite memory cache.
    Returns list of bar dictionaries.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT datetime, open, high, low, close, volume
        FROM bars
        WHERE ticker = ?
        ORDER BY datetime DESC
        LIMIT ?
    """, (ticker, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    bars = []
    for row in rows:
        try:
            bars.append({
                "datetime": datetime.fromisoformat(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5])
            })
        except Exception as e:
            print(f"Error parsing bar: {e}")
            continue
    
    # Return in chronological order (oldest first)
    return list(reversed(bars))


def fetch_intraday_bars(ticker: str, interval: str = "1m") -> List[Dict]:
    """Fetch intraday bars from EODHD API."""
    url = f"https://eodhd.com/api/intraday/{ticker}.US"
    
    params = {
        "api_token": EODHD_API_KEY,
        "interval": interval,
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
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
        
        return bars
    
    except Exception as e:
        print(f"[FETCH] Error fetching {ticker}: {e}")
        return []


def get_darkpool_trades(ticker: str, limit: int = 50) -> List[Dict]:
    """Fetch dark pool trades from EODHD."""
    try:
        url = f"https://eodhd.com/api/dark-pool/{ticker}.US"
        params = {
            "api_token": EODHD_API_KEY,
            "limit": limit,
            "fmt": "json"
        }
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        
        # EODHD returns list of trades
        if isinstance(data, list):
            return data
        
        return []
    
    except Exception as e:
        print(f"[DARKPOOL] Error fetching {ticker}: {e}")
        return []


def analyze_darkpool(ticker: str) -> Dict:
    """Analyze dark pool activity for a ticker."""
    trades = get_darkpool_trades(ticker)
    
    if not trades:
        return None
    
    total_volume = 0
    total_value = 0
    big_prints = 0
    
    for trade in trades[:50]:
        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            value = size * price
            
            total_volume += size
            total_value += value
            
            if value > 200000:  # $200K+ block
                big_prints += 1
        
        except Exception:
            continue
    
    return {
        "total_volume": total_volume,
        "total_volume_usd": total_value,
        "trade_count": len(trades),
        "big_prints": big_prints,
        "accumulation": (total_value / 1_000_000 > 2) or (big_prints >= 3)
    }


def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> List[str]:
    """Fetch top tickers from EODHD screener."""
    url = "https://eodhd.com/api/screener"
    
    params = {
        "api_token": EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume", ">=", 1000000],
            ["exchange", "=", "US"]
        ]),
        "limit": limit,
        "sort": "volume.desc"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        tickers = []
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                code = item.get("code", "").replace(".US", "")
                if code:
                    tickers.append(code)
        
        return tickers[:limit]
    
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []


def get_realtime_quote(ticker: str) -> Dict:
    """Get real-time quote for ticker."""
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US"
        params = {"api_token": EODHD_API_KEY, "fmt": "json"}
        
        response = requests.get(url, params=params, timeout=6)
        response.raise_for_status()
        
        return response.json()
    
    except Exception as e:
        print(f"[QUOTE] Error fetching {ticker}: {e}")
        return None
