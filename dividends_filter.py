"""
Dividends & Splits Filter
Blocks trades on ex-dividend dates and around stock splits.

EODHD API Endpoint:
  GET https://eodhd.com/api/div/{TICKER}.US?api_token=KEY&from=DATE
  
  Returns: [{"date": "2026-02-24", "value": 0.25, "declarationDate": "...", ...}]
  
Integration:
  - Called by premarket_scanner.py before adding ticker to watchlist
  - Called by sniper.py before arming signals (double-check)
"""
import requests
from datetime import datetime, timedelta
from typing import Tuple, Optional
import config

# Cache to avoid redundant API calls
_dividend_cache = {}  # {ticker: {"date": datetime, "data": [...]}}
_CACHE_TTL_HOURS = 24


def _is_cache_valid(ticker: str) -> bool:
    """Check if cached dividend data is still fresh."""
    if ticker not in _dividend_cache:
        return False
    cached_time = _dividend_cache[ticker]["date"]
    age = datetime.now() - cached_time
    return age < timedelta(hours=_CACHE_TTL_HOURS)


def get_upcoming_dividends(ticker: str, days_ahead: int = 7) -> list:
    """
    Fetch upcoming dividend events for a ticker.
    
    Args:
        ticker: Stock symbol (e.g., "AAPL")
        days_ahead: Look ahead window (default 7 days)
    
    Returns:
        List of dividend dicts within the window:
        [{"date": "2026-02-24", "value": 0.25, "type": "dividend"}, ...]
    """
    # Check cache first
    if _is_cache_valid(ticker):
        return _dividend_cache[ticker]["data"]
    
    today = datetime.now().date()
    from_date = today - timedelta(days=2)  # Look back 2 days for today's ex-div
    to_date = today + timedelta(days=days_ahead)
    
    url = f"https://eodhd.com/api/div/{ticker}.US"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from": from_date.strftime("%Y-%m-%d"),
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, list):
            return []
        
        # Filter to events within our window
        upcoming = []
        for event in data:
            event_date_str = event.get("date", "")
            if not event_date_str:
                continue
            
            try:
                event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
                if from_date <= event_date <= to_date:
                    upcoming.append({
                        "date": event_date_str,
                        "value": float(event.get("value", 0)),
                        "type": "dividend",
                        "declaration_date": event.get("declarationDate", ""),
                        "record_date": event.get("recordDate", ""),
                        "payment_date": event.get("paymentDate", "")
                    })
            except (ValueError, TypeError):
                continue
        
        # Cache the results
        _dividend_cache[ticker] = {
            "date": datetime.now(),
            "data": upcoming
        }
        
        return upcoming
    
    except Exception as e:
        print(f"[DIV] Error fetching dividends for {ticker}: {e}")
        return []


def get_upcoming_splits(ticker: str, days_ahead: int = 7) -> list:
    """
    Fetch upcoming stock split events.
    
    EODHD Endpoint: /api/splits/{TICKER}.US
    Returns: [{"date": "2026-02-24", "split": "2/1"}, ...]
    
    Args:
        ticker: Stock symbol
        days_ahead: Look ahead window (default 7 days)
    
    Returns:
        List of split dicts within the window
    """
    today = datetime.now().date()
    from_date = today - timedelta(days=2)
    to_date = today + timedelta(days=days_ahead)
    
    url = f"https://eodhd.com/api/splits/{ticker}.US"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from": from_date.strftime("%Y-%m-%d"),
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, list):
            return []
        
        upcoming = []
        for event in data:
            event_date_str = event.get("date", "")
            if not event_date_str:
                continue
            
            try:
                event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
                if from_date <= event_date <= to_date:
                    upcoming.append({
                        "date": event_date_str,
                        "split": event.get("split", ""),
                        "type": "split"
                    })
            except (ValueError, TypeError):
                continue
        
        return upcoming
    
    except Exception as e:
        print(f"[SPLIT] Error fetching splits for {ticker}: {e}")
        return []


def has_dividend_or_split_soon(ticker: str, days_ahead: int = 2) -> Tuple[bool, Optional[dict]]:
    """
    Check if ticker has a dividend or split within the guard window.
    
    Args:
        ticker: Stock symbol
        days_ahead: Guard window (default 2 days)
    
    Returns:
        (has_event, event_details)
        - has_event: True if dividend/split detected
        - event_details: Dict with event info or None
    
    Example:
        has_event, details = has_dividend_or_split_soon("AAPL")
        if has_event:
            print(f"Ex-div date: {details['date']}, amount: ${details['value']}")
    """
    # Check dividends
    dividends = get_upcoming_dividends(ticker, days_ahead=days_ahead)
    if dividends:
        return True, dividends[0]  # Return the nearest dividend
    
    # Check splits
    splits = get_upcoming_splits(ticker, days_ahead=days_ahead)
    if splits:
        return True, splits[0]  # Return the nearest split
    
    return False, None


def clear_dividend_cache():
    """Clear the dividend cache (called at EOD in main.py)."""
    global _dividend_cache
    _dividend_cache = {}
    print("[DIV] Cache cleared")


def get_cache_stats() -> dict:
    """Return cache statistics for monitoring."""
    return {
        "cached_tickers": len(_dividend_cache),
        "tickers": list(_dividend_cache.keys())
    }
