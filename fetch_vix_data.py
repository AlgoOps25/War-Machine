#!/usr/bin/env python3
"""
Fetch VIX Data from EODHD and store in database

VIX (^VIX) is used as volatility filter for trading signals.
Only trade when VIX > 15 for better pattern reliability.
"""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3
import requests
import config

ET = ZoneInfo("America/New_York")

print("="*80)
print("VIX DATA FETCHER")
print("="*80)
print()

def fetch_vix_intraday(api_key: str, start_date: datetime, end_date: datetime):
    """
    Fetch VIX 1-minute intraday data from EODHD.
    
    Args:
        api_key: EODHD API key
        start_date: Start date
        end_date: End date
    
    Returns:
        List of dicts with datetime, open, high, low, close, volume
    """
    url = "https://eodhd.com/api/intraday/^VIX.INDX"
    
    params = {
        "api_token": api_key,
        "interval": "1m",
        "from": int(start_date.timestamp()),
        "to": int(end_date.timestamp()),
        "fmt": "json"
    }
    
    print(f"Fetching VIX data from {start_date.date()} to {end_date.date()}...")
    
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print("  No data returned from EODHD")
            return []
        
        bars = []
        for item in data:
            try:
                dt = datetime.fromtimestamp(item["timestamp"], tz=ET).replace(tzinfo=None)
                
                bars.append({
                    "datetime": dt,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": int(item.get("volume", 0))
                })
            except (KeyError, ValueError, TypeError) as e:
                continue
        
        print(f"  Fetched {len(bars)} VIX bars")
        return bars
    
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP Error: {e}")
        print(f"  Response: {response.text[:200]}")
        return []
    except Exception as e:
        print(f"  Error: {e}")
        return []


def store_vix_data(db_path: str, bars: list):
    """
    Store VIX data in intraday_bars table with ticker '^VIX'.
    
    Args:
        db_path: Path to SQLite database
        bars: List of bar dicts
    """
    if not bars:
        print("No bars to store")
        return
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Check if table exists
    cur.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='intraday_bars'
    """)
    
    if not cur.fetchone():
        print("  Creating intraday_bars table...")
        cur.execute("""
            CREATE TABLE intraday_bars (
                ticker TEXT NOT NULL,
                datetime TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER,
                PRIMARY KEY (ticker, datetime)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bars_ticker_dt ON intraday_bars(ticker, datetime)")
    
    # Delete existing VIX data for this date range
    if bars:
        min_dt = min(b["datetime"] for b in bars)
        max_dt = max(b["datetime"] for b in bars)
        cur.execute("""
            DELETE FROM intraday_bars 
            WHERE ticker = '^VIX'
              AND datetime >= ?
              AND datetime <= ?
        """, (min_dt, max_dt))
        deleted = cur.rowcount
        if deleted > 0:
            print(f"  Deleted {deleted} existing VIX bars")
    
    # Insert new data
    insert_query = """
        INSERT OR REPLACE INTO intraday_bars (ticker, datetime, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    
    for bar in bars:
        cur.execute(insert_query, (
            "^VIX",
            bar["datetime"],
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            bar["volume"]
        ))
    
    conn.commit()
    print(f"  Stored {len(bars)} VIX bars in database")
    
    # Verify
    cur.execute("SELECT COUNT(*) FROM intraday_bars WHERE ticker = '^VIX'")
    total = cur.fetchone()[0]
    print(f"  Total VIX bars in database: {total}")
    
    cur.close()
    conn.close()


def main():
    # Configuration
    api_key = config.EODHD_API_KEY
    db_path = "market_memory.db"
    
    # Fetch last 30 days of VIX data
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=30)
    
    print(f"Database: {db_path}")
    print(f"API Key: {api_key[:10]}...")
    print()
    
    # Fetch VIX data
    bars = fetch_vix_intraday(api_key, start_date, end_date)
    
    if not bars:
        print("\n❌ Failed to fetch VIX data")
        print("\nPossible issues:")
        print("  1. EODHD API key may not have access to ^VIX.INDX")
        print("  2. Try ^VIX instead of ^VIX.INDX")
        print("  3. VIX intraday may require higher subscription tier")
        print("\nYou can still run backtests without VIX filter.")
        return
    
    # Store in database
    print()
    print("Storing VIX data...")
    store_vix_data(db_path, bars)
    
    print()
    print("✅ VIX data fetch complete!")
    print()
    print("VIX levels over period:")
    vix_closes = [b["close"] for b in bars]
    print(f"  Min: {min(vix_closes):.2f}")
    print(f"  Max: {max(vix_closes):.2f}")
    print(f"  Avg: {sum(vix_closes)/len(vix_closes):.2f}")
    print()
    print("Now run: python advanced_mtf_backtest.py")


if __name__ == "__main__":
    main()
