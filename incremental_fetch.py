"""
Incremental Fetch - Updates bar cache for tickers
Fetches only today's intraday data to avoid excessive storage
"""

from datetime import datetime, timedelta
from scanner_helpers import fetch_intraday_bars, insert_bars_to_memory, get_recent_bars_from_memory


def update_ticker(ticker: str):
    """
    Update bars for a ticker.
    Fetches latest intraday data and stores in cache.
    Only keeps today's bars to prevent database bloat.
    """
    try:
        # Fetch latest intraday bars from EODHD
        new_bars = fetch_intraday_bars(ticker, interval="1m")
        
        if not new_bars:
            # print(f"[FETCH] {ticker}: No new bars available")
            return
        
        # Filter to only today's bars (avoid historical data bloat)
        today = datetime.now().date()
        today_bars = [b for b in new_bars if b["datetime"].date() == today]
        
        if not today_bars:
            # print(f"[FETCH] {ticker}: No bars for today")
            return
        
        # Insert into cache (SQLite or PostgreSQL)
        insert_bars_to_memory(ticker, today_bars)
        
        # Log summary
        if len(today_bars) != len(new_bars):
            print(f"[FETCH] {ticker}: Stored {len(today_bars)} today's bars (filtered from {len(new_bars)} total)")
        # else:
            # print(f"[FETCH] {ticker}: Stored {len(today_bars)} bars")
    
    except Exception as e:
        print(f"[FETCH] Error updating {ticker}: {e}")
        import traceback
        traceback.print_exc()


def cleanup_old_bars(days_to_keep: int = 7):
    """
    Clean up bars older than N days to prevent database bloat.
    Call this once per day during after-hours.
    """
    try:
        import sqlite3
        
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
        
        conn = sqlite3.connect("market_memory.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM bars 
            WHERE datetime < ?
        """, (cutoff_date,))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            print(f"[CLEANUP] Deleted {deleted} old bars (older than {days_to_keep} days)")
    
    except Exception as e:
        print(f"[CLEANUP] Error cleaning old bars: {e}")
