"""
Dynamic Stock Screener
Replaces static watchlist with EODHD screener API to find best tickers daily.

EODHD Screener API:
  GET https://eodhd.com/api/screener?api_token=KEY&filters=...
  
  Included in: EOD+Intraday — All World Extended (your current plan)
  
Features:
  - Find top volume movers automatically each morning
  - Filter by market cap, price change, sector
  - Adaptive criteria based on market conditions
  - Cache results to avoid redundant API calls

Integration:
  - Called by premarket_scanner.py before gap scanner
  - Replaces SCAN_UNIVERSE static list with dynamic results
"""
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import config

# Cache to avoid redundant API calls
_screener_cache = {}  # {"date": datetime, "results": [...]}
_CACHE_TTL_HOURS = 6  # Cache expires after 6 hours

# Default screening criteria
DEFAULT_FILTERS = [
    ["market_capitalization", ">", 1000000000],    # Market cap > $1B
    ["volume", ">", 500000],                       # Volume > 500K shares
    ["close", ">", 5],                             # Price > $5
    ["close", "<", 1000],                          # Price < $1000 (exclude extreme)
]

# High-volume day filters (when market is very active)
HIGH_VOLUME_FILTERS = [
    ["market_capitalization", ">", 1000000000],
    ["volume", ">", 1000000],                      # Higher volume threshold
    ["percent_change", ">", 1],                    # Moving > 1% today
    ["close", ">", 5],
]

# Core tickers always included (SPY, QQQ, major names)
CORE_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA",                    # Major ETFs
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",      # Mega caps
    "TSLA", "META", "AMD",                         # High volatility tech
]


def _is_cache_valid() -> bool:
    """Check if screener cache is still fresh."""
    if not _screener_cache:
        return False
    
    cached_time = _screener_cache.get("date")
    if not cached_time:
        return False
    
    age = datetime.now() - cached_time
    return age < timedelta(hours=_CACHE_TTL_HOURS)


def run_screener(
    filters: Optional[List] = None,
    limit: int = 50,
    sort_by: str = "volume.desc"
) -> List[str]:
    """
    Run EODHD stock screener with custom filters.
    
    Args:
        filters: List of filter conditions. Format:
                 [["field", "operator", value], ...]
                 Example: [["volume", ">", 1000000], ["close", ">", 10]]
        limit: Max results to return (default 50)
        sort_by: Sort field with direction (default "volume.desc")
                 Options: "volume.desc", "market_cap.desc", 
                         "percent_change.desc", "close.desc"
    
    Returns:
        List of ticker symbols that passed the screen
    
    EODHD Screener Docs:
        https://eodhd.com/financial-apis/stock-market-screener-api
    """
    # Use default filters if none provided
    if filters is None:
        filters = DEFAULT_FILTERS
    
    # Build filter JSON for API
    filter_json = json.dumps(filters)
    
    url = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": filter_json,
        "limit": limit,
        "sort": sort_by,
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, dict) or "data" not in data:
            print(f"[SCREENER] Unexpected response format: {type(data)}")
            return []
        
        results = data.get("data", [])
        tickers = []
        
        for item in results:
            # Extract ticker from code (format: "AAPL.US")
            code = item.get("code", "")
            if not code:
                continue
            
            # Remove .US suffix
            ticker = code.replace(".US", "").replace(".NYSE", "").replace(".NASDAQ", "")
            if ticker and ticker not in tickers:
                tickers.append(ticker)
        
        return tickers[:limit]
    
    except Exception as e:
        print(f"[SCREENER] Error running screener: {e}")
        return []


def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50
) -> List[str]:
    """
    Generate dynamic watchlist using EODHD screener.
    This is the main function called by premarket_scanner.py.
    
    Args:
        include_core: Always include core tickers (SPY, QQQ, AAPL, etc.)
        max_tickers: Maximum watchlist size
    
    Returns:
        List of ticker symbols for today's watchlist
    
    Strategy:
        1. Check cache - if valid, return cached results
        2. Run volume screener to find most active stocks
        3. Add core tickers (SPY, QQQ, etc.) if include_core=True
        4. Deduplicate and limit to max_tickers
        5. Cache results for 6 hours
    """
    # Check cache first
    if _is_cache_valid():
        cached_results = _screener_cache.get("results", [])
        print(f"[SCREENER] Using cached results ({len(cached_results)} tickers)")
        return cached_results
    
    print(f"[SCREENER] Running dynamic screener...")
    
    # Start with core tickers if requested
    watchlist = list(CORE_TICKERS) if include_core else []
    
    # Run volume-based screener
    volume_movers = run_screener(
        filters=DEFAULT_FILTERS,
        limit=max_tickers,
        sort_by="volume.desc"
    )
    
    # Run price change screener (top % movers)
    price_movers = run_screener(
        filters=[
            ["market_capitalization", ">", 1000000000],
            ["volume", ">", 500000],
            ["percent_change", ">", 2],  # Moving > 2% today
            ["close", ">", 5],
        ],
        limit=20,
        sort_by="percent_change.desc"
    )
    
    # Merge results
    for ticker in volume_movers:
        if ticker not in watchlist:
            watchlist.append(ticker)
    
    for ticker in price_movers:
        if ticker not in watchlist:
            watchlist.append(ticker)
    
    # Limit to max size
    final_watchlist = watchlist[:max_tickers]
    
    # Cache results
    _screener_cache["date"] = datetime.now()
    _screener_cache["results"] = final_watchlist
    
    print(f"[SCREENER] Generated watchlist: {len(final_watchlist)} tickers")
    print(f"[SCREENER] Top 10: {', '.join(final_watchlist[:10])}")
    
    return final_watchlist


def get_sector_screener(sector: str, limit: int = 20) -> List[str]:
    """
    Screen for stocks in a specific sector.
    
    Args:
        sector: Sector name (e.g., "Technology", "Healthcare", "Financial")
        limit: Max results
    
    Returns:
        List of tickers in that sector
    """
    filters = [
        ["market_capitalization", ">", 1000000000],
        ["volume", ">", 500000],
        ["sector", "=", sector],
        ["close", ">", 5],
    ]
    
    return run_screener(
        filters=filters,
        limit=limit,
        sort_by="volume.desc"
    )


def get_gap_candidates(min_gap_pct: float = 3.0, limit: int = 30) -> List[str]:
    """
    Find stocks with significant gaps (pre-market or at open).
    
    Args:
        min_gap_pct: Minimum gap percentage (default 3%)
        limit: Max results
    
    Returns:
        List of gapping tickers
    """
    filters = [
        ["market_capitalization", ">", 500000000],  # $500M+ market cap
        ["volume", ">", 300000],
        ["percent_change", ">", min_gap_pct],       # Gap > threshold
        ["close", ">", 3],
    ]
    
    return run_screener(
        filters=filters,
        limit=limit,
        sort_by="percent_change.desc"
    )


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    """
    Generate watchlist for high-volume trading days (FOMC, earnings season, etc.).
    Uses stricter volume criteria to find only the most liquid names.
    
    Args:
        limit: Max watchlist size
    
    Returns:
        List of highly liquid tickers
    """
    return run_screener(
        filters=HIGH_VOLUME_FILTERS,
        limit=limit,
        sort_by="volume.desc"
    )


def clear_screener_cache():
    """Clear screener cache. Called at EOD in main.py."""
    global _screener_cache
    _screener_cache = {}
    print("[SCREENER] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    if not _screener_cache:
        return {"cached": False}
    
    cached_time = _screener_cache.get("date")
    results_count = len(_screener_cache.get("results", []))
    
    return {
        "cached": True,
        "timestamp": cached_time.isoformat() if cached_time else None,
        "tickers_count": results_count,
        "age_hours": (datetime.now() - cached_time).total_seconds() / 3600 if cached_time else None
    }
