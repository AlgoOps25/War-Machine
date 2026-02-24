"""
Bulk Historical Data Downloader
Efficiently downloads historical OHLCV data using EODHD bulk endpoints.

EODHD Bulk Download API:
  GET https://eodhd.com/api/eod-bulk-last-day/US?api_token=KEY&fmt=json
  
  Advantages over individual ticker API calls:
  - Single API call fetches ALL US stocks (6000+ tickers)
  - Much faster than looping through individual /eod/{TICKER}.US calls
  - Lower API usage count
  - Perfect for end-of-day data backfills

Use Cases:
  - Initial database population (seed historical data)
  - Daily EOD backfill (catch up any missed bars)
  - Gap detection (compare yesterday close to today open)
  - Support/resistance level calculation

Integration:
  - Called during system initialization if database is empty
  - Optional: scheduled daily at 4:30 PM ET for EOD backfill
"""
import requests
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import config


def download_bulk_eod_data(
    exchange: str = "US",
    date: Optional[str] = None,
    symbols_filter: Optional[List[str]] = None
) -> List[Dict]:
    """
    Download bulk end-of-day data for an entire exchange.
    
    Args:
        exchange: Exchange code (default "US" for US stocks)
        date: Specific date in YYYY-MM-DD format (default: last trading day)
        symbols_filter: Optional list of tickers to filter (None = all tickers)
    
    Returns:
        List of OHLCV dicts:
        [{
            "code": "AAPL.US",
            "date": "2026-02-21",
            "open": 184.50,
            "high": 186.20,
            "low": 183.90,
            "close": 185.75,
            "volume": 52340000
        }, ...]
    
    EODHD Docs:
        https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends
    """
    if date:
        url = f"https://eodhd.com/api/eod-bulk-last-day/{exchange}"
        params = {
            "api_token": config.EODHD_API_KEY,
            "date": date,
            "fmt": "json"
        }
    else:
        # Latest trading day
        url = f"https://eodhd.com/api/eod-bulk-last-day/{exchange}"
        params = {
            "api_token": config.EODHD_API_KEY,
            "fmt": "json"
        }
    
    try:
        print(f"[BULK] Downloading {exchange} EOD data" + (f" for {date}" if date else " (latest)"))
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, list):
            print(f"[BULK] Unexpected response format: {type(data)}")
            return []
        
        # Filter by symbols if provided
        if symbols_filter:
            symbols_upper = [s.upper() for s in symbols_filter]
            filtered = []
            for item in data:
                code = item.get("code", "")
                ticker = code.replace(".US", "").replace(".NASDAQ", "").replace(".NYSE", "")
                if ticker.upper() in symbols_upper:
                    filtered.append(item)
            data = filtered
        
        print(f"[BULK] Downloaded {len(data)} ticker records")
        return data
    
    except Exception as e:
        print(f"[BULK] Error downloading bulk data: {e}")
        return []


def backfill_historical_data(
    tickers: List[str],
    days_back: int = 30,
    force_refresh: bool = False
) -> Dict:
    """
    Backfill historical daily data for a list of tickers.
    Uses individual EOD endpoint (not bulk) for multi-day ranges.
    
    Args:
        tickers: List of ticker symbols
        days_back: Number of days to backfill (default 30)
        force_refresh: If True, overwrites existing data
    
    Returns:
        Dict with backfill statistics:
        {
            "tickers_processed": 25,
            "total_bars": 750,
            "errors": ["INVALID", ...]
        }
    
    Note: For initial large backfills (>100 tickers), use download_bulk_eod_data()
          in a loop for each day. This function is better for targeted updates.
    """
    from data_manager import data_manager
    
    stats = {
        "tickers_processed": 0,
        "total_bars": 0,
        "errors": []
    }
    
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"[BULK] Backfilling {len(tickers)} tickers | {days_back} days | {from_date} to {to_date}")
    
    for ticker in tickers:
        try:
            url = f"https://eodhd.com/api/eod/{ticker}.US"
            params = {
                "api_token": config.EODHD_API_KEY,
                "from": from_date,
                "to": to_date,
                "period": "d",  # Daily bars
                "fmt": "json"
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if not isinstance(data, list):
                stats["errors"].append(ticker)
                continue
            
            # Convert to data_manager format
            bars = []
            for item in data:
                bar_date = item.get("date")
                if not bar_date:
                    continue
                
                bars.append({
                    "datetime": datetime.strptime(bar_date, "%Y-%m-%d"),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": int(item.get("volume", 0))
                })
            
            if bars:
                # Store as daily bars (separate table from intraday)
                data_manager.store_daily_bars(ticker, bars)
                stats["tickers_processed"] += 1
                stats["total_bars"] += len(bars)
                
                if stats["tickers_processed"] % 10 == 0:
                    print(f"[BULK] Progress: {stats['tickers_processed']}/{len(tickers)} tickers")
        
        except Exception as e:
            print(f"[BULK] Error backfilling {ticker}: {e}")
            stats["errors"].append(ticker)
    
    print(f"[BULK] Backfill complete: {stats['tickers_processed']} tickers, {stats['total_bars']} bars")
    if stats["errors"]:
        print(f"[BULK] Errors: {len(stats['errors'])} tickers failed: {', '.join(stats['errors'][:5])}")
    
    return stats


def seed_database_with_bulk_data(
    tickers: List[str],
    days_back: int = 60
):
    """
    Seed database with historical data using bulk downloads.
    Call this once during initial setup or after database wipe.
    
    Strategy:
      1. Download bulk EOD data for the last 60 days (one call per day)
      2. Filter to watchlist tickers
      3. Store in data_manager daily bars table
    
    Args:
        tickers: List of tickers to seed
        days_back: Number of days to download (default 60)
    """
    print(f"\n[BULK SEED] Initializing database with {days_back} days of data for {len(tickers)} tickers")
    print(f"[BULK SEED] This may take 2-3 minutes...\n")
    
    from data_manager import data_manager
    
    total_bars = 0
    
    # Download day-by-day using bulk endpoint
    for i in range(days_back, -1, -1):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        
        # Skip weekends (basic check - doesn't account for holidays)
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        if date_obj.weekday() >= 5:  # Saturday = 5, Sunday = 6
            continue
        
        bulk_data = download_bulk_eod_data(
            exchange="US",
            date=target_date,
            symbols_filter=tickers
        )
        
        # Store bars for each ticker
        ticker_bars = {}
        for item in bulk_data:
            code = item.get("code", "")
            ticker = code.replace(".US", "").replace(".NASDAQ", "").replace(".NYSE", "")
            
            if ticker not in ticker_bars:
                ticker_bars[ticker] = []
            
            bar_date = item.get("date")
            if not bar_date:
                continue
            
            ticker_bars[ticker].append({
                "datetime": datetime.strptime(bar_date, "%Y-%m-%d"),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(item.get("volume", 0))
            })
        
        # Store all tickers for this date
        for ticker, bars in ticker_bars.items():
            if bars:
                data_manager.store_daily_bars(ticker, bars)
                total_bars += len(bars)
        
        if (days_back - i) % 10 == 0:
            print(f"[BULK SEED] Progress: {days_back - i}/{days_back} days processed")
    
    print(f"\n[BULK SEED] Complete: {total_bars} daily bars stored")


def get_previous_close_bulk(tickers: List[str]) -> Dict[str, float]:
    """
    Get previous day's closing prices for multiple tickers in one API call.
    Much more efficient than individual requests.
    
    Args:
        tickers: List of ticker symbols
    
    Returns:
        Dict mapping ticker to previous close:
        {"AAPL": 185.75, "TSLA": 201.30, ...}
    """
    bulk_data = download_bulk_eod_data(exchange="US", symbols_filter=tickers)
    
    prev_closes = {}
    for item in bulk_data:
        code = item.get("code", "")
        ticker = code.replace(".US", "").replace(".NASDAQ", "").replace(".NYSE", "")
        close = float(item.get("close", 0))
        
        if ticker and close > 0:
            prev_closes[ticker] = close
    
    return prev_closes


def run_daily_eod_backfill(watchlist: List[str]):
    """
    Run at 4:30 PM ET daily to backfill any missed EOD data.
    Uses bulk download for efficiency.
    
    Args:
        watchlist: Current watchlist tickers to backfill
    """
    print("\n[EOD BACKFILL] Starting daily EOD data refresh...")
    
    # Download today's EOD data
    bulk_data = download_bulk_eod_data(exchange="US", symbols_filter=watchlist)
    
    if not bulk_data:
        print("[EOD BACKFILL] No data received")
        return
    
    from data_manager import data_manager
    
    bars_stored = 0
    for item in bulk_data:
        code = item.get("code", "")
        ticker = code.replace(".US", "").replace(".NASDAQ", "").replace(".NYSE", "")
        
        bar_date = item.get("date")
        if not bar_date:
            continue
        
        bar = {
            "datetime": datetime.strptime(bar_date, "%Y-%m-%d"),
            "open": float(item.get("open", 0)),
            "high": float(item.get("high", 0)),
            "low": float(item.get("low", 0)),
            "close": float(item.get("close", 0)),
            "volume": int(item.get("volume", 0))
        }
        
        if bar["close"] > 0:
            data_manager.store_daily_bars(ticker, [bar])
            bars_stored += 1
    
    print(f"[EOD BACKFILL] Stored {bars_stored} EOD bars")
