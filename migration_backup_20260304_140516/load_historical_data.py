"""
Load Historical Data from EODHD API

Fetches 90 days of intraday 1-minute bars for specified tickers
and caches them in market_memory.db for backtesting.

Usage:
    python load_historical_data.py
    
Requires:
    - EODHD_API_KEY in environment or .env file
"""

import sys
sys.path.append('.')

import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict
import time

from app.data.data_manager import data_manager

ET = ZoneInfo("America/New_York")

# Get API key
EODHD_API_KEY = os.getenv('EODHD_API_KEY')

if not EODHD_API_KEY:
    print("❌ ERROR: EODHD_API_KEY not found in environment")
    print("   Set it with: export EODHD_API_KEY='your_key_here'")
    print("   Or add to .env file")
    sys.exit(1)

# Tickers to fetch
TICKERS = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META', 'GOOGL', 'AMD']

# EODHD API endpoint
EODHD_BASE_URL = "https://eodhd.com/api/intraday"


def fetch_intraday_bars(ticker: str, from_date: str, to_date: str) -> List[Dict]:
    """
    Fetch 1-minute intraday bars from EODHD.
    
    Args:
        ticker: Stock symbol
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
    
    Returns:
        List of bar dictionaries
    """
    url = f"{EODHD_BASE_URL}/{ticker}.US"
    
    params = {
        'api_token': EODHD_API_KEY,
        'interval': '1m',
        'from': from_date,
        'to': to_date,
        'fmt': 'json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and 'error' in data:
            print(f"  ⚠️  API Error for {ticker}: {data['error']}")
            return []
        
        return data if isinstance(data, list) else []
    
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request failed for {ticker}: {e}")
        return []
    except Exception as e:
        print(f"  ❌ Error processing {ticker}: {e}")
        return []


def convert_to_storage_format(ticker: str, bars: List[Dict]) -> List[Dict]:
    """
    Convert EODHD format to War Machine storage format.
    
    EODHD format:
    {
        "datetime": "2024-12-03 09:30:00",
        "open": 100.5,
        "high": 101.0,
        "low": 100.3,
        "close": 100.8,
        "volume": 50000
    }
    
    War Machine format:
    {
        "ticker": "AAPL",
        "timestamp": datetime_object,
        "open": 100.5,
        "high": 101.0,
        "low": 100.3,
        "close": 100.8,
        "volume": 50000
    }
    """
    converted = []
    
    for bar in bars:
        try:
            # Parse datetime string
            dt_str = bar.get('datetime', '')
            if not dt_str:
                continue
            
            # Convert to datetime object (assume ET timezone)
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=ET)
            
            converted.append({
                'ticker': ticker,
                'timestamp': dt,
                'open': float(bar['open']),
                'high': float(bar['high']),
                'low': float(bar['low']),
                'close': float(bar['close']),
                'volume': int(bar['volume']) if bar.get('volume') else 0
            })
        except Exception as e:
            print(f"  ⚠️  Skipping malformed bar for {ticker}: {e}")
            continue
    
    return converted


def cache_bars_to_database(ticker: str, bars: List[Dict]):
    """
    Store bars in market_memory.db using data_manager.
    """
    if not bars:
        return
    
    # Store each bar individually
    for bar in bars:
        data_manager.cache_bar(ticker, bar)
    
    print(f"  ✅ Cached {len(bars)} bars for {ticker}")


def main():
    """
    Main workflow: Fetch and cache historical data.
    """
    print("="*80)
    print("LOAD HISTORICAL DATA FROM EODHD")
    print("="*80)
    print(f"Start time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    # Calculate date range (90 days back)
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=90)
    
    from_date_str = start_date.strftime('%Y-%m-%d')
    to_date_str = end_date.strftime('%Y-%m-%d')
    
    print(f"Fetching data from {from_date_str} to {to_date_str}")
    print(f"Tickers: {', '.join(TICKERS)}")
    print()
    
    total_bars = 0
    
    for i, ticker in enumerate(TICKERS, 1):
        print(f"[{i}/{len(TICKERS)}] Fetching {ticker}...")
        
        # Fetch bars from EODHD
        bars = fetch_intraday_bars(ticker, from_date_str, to_date_str)
        
        if not bars:
            print(f"  ⚠️  No data returned for {ticker}")
            continue
        
        print(f"  📥 Downloaded {len(bars)} bars")
        
        # Convert to storage format
        converted = convert_to_storage_format(ticker, bars)
        
        if not converted:
            print(f"  ⚠️  No valid bars after conversion")
            continue
        
        # Cache to database
        cache_bars_to_database(ticker, converted)
        total_bars += len(converted)
        
        # Rate limiting (EODHD allows 20 requests/min for basic plans)
        if i < len(TICKERS):
            print(f"  ⏳ Rate limiting (3 seconds)...")
            time.sleep(3)
        
        print()
    
    print("="*80)
    print("LOAD COMPLETE")
    print("="*80)
    print(f"Total bars cached: {total_bars:,}")
    print()
    print("✅ You can now run backtest_optimized_params.py")
    print()
    print(f"End time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}")


if __name__ == "__main__":
    main()
