"""
Incremental Fetch - Updates bar cache for tickers
"""

from datetime import datetime, timedelta
from scanner_helpers import fetch_intraday_bars, insert_bars_to_memory, get_recent_bars_from_memory


def update_ticker(ticker: str):
    """
    Update bars for a ticker.
    Fetches latest data and stores in memory cache.
    """
    try:
        # Check last bar in cache
        existing_bars = get_recent_bars_from_memory(ticker, limit=1)
        
        # Fetch fresh data
        new_bars = fetch_intraday_bars(ticker, interval="1m")
        
        if new_bars:
            # Insert into cache
            insert_bars_to_memory(ticker, new_bars)
            # print(f"[FETCH] {ticker}: Updated {len(new_bars)} bars")
    
    except Exception as e:
        print(f"[FETCH] Error updating {ticker}: {e}")
