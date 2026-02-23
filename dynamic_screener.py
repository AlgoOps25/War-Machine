"""
Dynamic Stock Screener
Replaces static watchlist with EODHD screener API to find best tickers daily.

EODHD Screener API:
  GET https://eodhd.com/api/screener?api_token=KEY&filters=...

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
# NOTE: percent_change uses whole numbers (e.g. 2 = 2%), volume uses integers
DEFAULT_FILTERS = [
    ["market_capitalization", ">", 1000000000],    # Market cap > $1B
    ["volume", ">", 500000],                       # Volume > 500K shares
    ["close", ">", 5],                             # Price > $5
    ["close", "<", 1000],                          # Price < $1000
]

# High-volume day filters
HIGH_VOLUME_FILTERS = [
    ["market_capitalization", ">", 1000000000],
    ["volume", ">", 1000000],
    ["percent_change", ">", 1],
    ["close", ">", 5],
]

# Core tickers always included (SPY, QQQ, major names)
CORE_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "TSLA", "META", "AMD",
]

# Expanded fallback watchlist — used when EODHD screener returns no results
# (weekend, API issue, plan limitation, etc.)
FALLBACK_WATCHLIST = [
    # ETFs
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV",
    # Mega caps
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    # High beta / volatile tech
    "AMD", "NFLX", "ADBE", "CRM", "ORCL", "SNOW", "PLTR", "COIN",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC",
    # Healthcare
    "UNH", "JNJ", "PFE", "ABBV", "MRK",
    # Consumer
    "WMT", "HD", "COST", "NKE", "MCD",
    # Energy
    "XOM", "CVX", "OXY",
    # Semis
    "QCOM", "MU", "INTC", "AMAT", "LRCX",
    # Additional active names
    "UBER", "MSTR", "SMCI", "ARM", "MRVL",
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

    IMPORTANT: filters must be serialized with separators=(',',':')
    so there are NO spaces in the JSON string. Spaces get URL-encoded
    as '+' signs which EODHD rejects with a 422 error.

    Args:
        filters: List of filter conditions [["field", "op", value], ...]
        limit: Max results to return (default 50)
        sort_by: Sort field with direction (default "volume.desc")

    Returns:
        List of ticker symbols, or [] on failure.

    EODHD Screener Docs:
        https://eodhd.com/financial-apis/stock-market-screener-api
    """
    if filters is None:
        filters = DEFAULT_FILTERS

    # CRITICAL FIX: separators=(',',':') produces compact JSON with NO spaces.
    # json.dumps default adds spaces after ',' and ':' which URL-encode to '+'
    # causing EODHD to return 422 Unprocessable Content.
    # Bad:  [["market_capitalization", ">", 1000000000], ["volume", ">", 500000]]
    # Good: [["market_capitalization",">",1000000000],["volume",">",500000]]
    filter_json = json.dumps(filters, separators=(',', ':'))

    url = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": filter_json,
        "limit": limit,
        "sort": sort_by,
        "fmt": "json"
    }

    try:
        print(f"[SCREENER] Calling API: filters={filter_json[:80]}... limit={limit} sort={sort_by}")
        response = requests.get(url, params=params, timeout=15)

        print(f"[SCREENER] HTTP {response.status_code}")

        if response.status_code == 422:
            print(f"[SCREENER] ❌ 422 Unprocessable — filter format rejected. Raw: {filter_json}")
            return []
        if response.status_code == 403:
            print("[SCREENER] ❌ 403 Forbidden — screener not in your EODHD plan")
            return []
        if response.status_code == 401:
            print("[SCREENER] ❌ 401 Unauthorized — check EODHD_API_KEY")
            return []

        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            print(f"[SCREENER] Response keys: {list(data.keys())}")
            total = data.get("total", "?")
            print(f"[SCREENER] Total results from API: {total}")
        else:
            print(f"[SCREENER] Unexpected response type: {type(data)} | preview: {str(data)[:200]}")
            return []

        results = data.get("data", [])
        if not results:
            print("[SCREENER] ⚠️  API returned 0 results — filters may be too strict")
            return []

        tickers = []
        for item in results:
            code = item.get("code", "")
            if not code:
                continue
            ticker = code.split(".")[0]
            if ticker and ticker not in tickers:
                tickers.append(ticker)

        print(f"[SCREENER] ✅ {len(tickers)} tickers returned")
        return tickers[:limit]

    except requests.exceptions.HTTPError as e:
        print(f"[SCREENER] HTTP error: {e}")
        return []
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50,
    force_refresh: bool = False
) -> List[str]:
    """
    Generate dynamic watchlist using EODHD screener.
    Falls back to FALLBACK_WATCHLIST if API returns no results.

    Args:
        include_core: Always include core tickers (SPY, QQQ, AAPL, etc.)
        max_tickers: Maximum watchlist size
        force_refresh: Bypass cache and re-run screener immediately

    Returns:
        List of ticker symbols for today's watchlist
    """
    if not force_refresh and _is_cache_valid():
        cached_results = _screener_cache.get("results", [])
        print(f"[SCREENER] Using cached results ({len(cached_results)} tickers)")
        return cached_results

    print("[SCREENER] Running dynamic screener...")

    watchlist = list(CORE_TICKERS) if include_core else []
    screener_success = False

    # Run 1: Volume movers
    volume_movers = run_screener(
        filters=DEFAULT_FILTERS,
        limit=max_tickers,
        sort_by="volume.desc"
    )
    if volume_movers:
        screener_success = True
        for ticker in volume_movers:
            if ticker not in watchlist:
                watchlist.append(ticker)

    # Run 2: % movers (best during/after market open)
    price_movers = run_screener(
        filters=[
            ["market_capitalization", ">", 1000000000],
            ["volume", ">", 500000],
            ["percent_change", ">", 2],
            ["close", ">", 5],
        ],
        limit=20,
        sort_by="percent_change.desc"
    )
    if price_movers:
        screener_success = True
        for ticker in price_movers:
            if ticker not in watchlist:
                watchlist.append(ticker)

    # Fallback: API returned nothing — use expanded static list, skip cache
    if not screener_success:
        print("[SCREENER] ⚠️  Screener returned no live data — using FALLBACK_WATCHLIST")
        print("[SCREENER] ⚠️  Cache NOT saved (will retry on next call)")
        fallback = list(dict.fromkeys(FALLBACK_WATCHLIST))  # deduplicate, preserve order
        return fallback[:max_tickers]

    final_watchlist = watchlist[:max_tickers]

    _screener_cache["date"] = datetime.now()
    _screener_cache["results"] = final_watchlist

    print(f"[SCREENER] ✅ Watchlist generated: {len(final_watchlist)} tickers")
    print(f"[SCREENER] Top 10: {', '.join(final_watchlist[:10])}")

    return final_watchlist


def get_sector_screener(sector: str, limit: int = 20) -> List[str]:
    filters = [
        ["market_capitalization", ">", 1000000000],
        ["volume", ">", 500000],
        ["sector", "=", sector],
        ["close", ">", 5],
    ]
    return run_screener(filters=filters, limit=limit, sort_by="volume.desc")


def get_gap_candidates(min_gap_pct: float = 3.0, limit: int = 30) -> List[str]:
    filters = [
        ["market_capitalization", ">", 500000000],
        ["volume", ">", 300000],
        ["percent_change", ">", min_gap_pct],
        ["close", ">", 3],
    ]
    return run_screener(filters=filters, limit=limit, sort_by="percent_change.desc")


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
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
