"""
Dynamic Stock Screener
Replaces static watchlist with EODHD screener API to find best tickers daily.

EODHD Screener API:
  GET https://eodhd.com/api/screener?api_token=KEY&filters=...

  Valid filter fields (from official docs):
    String:  code, name, exchange, sector, industry
    Number:  market_capitalization, earnings_share, dividend_yield,
             refund_1d_p, refund_5d_p, avgvol_1d, avgvol_200d, adjusted_close

  Sort format: sort=field_name.(asc|desc)
    e.g. sort=avgvol_1d.desc, sort=market_capitalization.desc

Features:
  - Find top volume movers automatically each morning
  - Filter by market cap, price change, sector
  - Adaptive criteria based on market conditions
  - Cache results to avoid redundant API calls
"""
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from utils import config

# Cache to avoid redundant API calls
_screener_cache = {}  # {"date": datetime, "results": [...]}
_CACHE_TTL_HOURS = 6

# Default screening criteria â€” US stocks, $1B+ market cap, $5-$1000 price
# Field names from EODHD docs: avgvol_1d, adjusted_close, market_capitalization
DEFAULT_FILTERS = [
    ["market_capitalization", ">", 1000000000],    # Market cap > $1B
    ["avgvol_1d", ">", 500000],                    # Volume > 500K
    ["adjusted_close", ">", 5],                    # Price > $5
    ["adjusted_close", "<", 1000],                 # Price < $1000
    ["exchange", "=", "us"],                       # US markets only
]

# High-volume day filters (FOMC, earnings season, etc.)
HIGH_VOLUME_FILTERS = [
    ["market_capitalization", ">", 1000000000],
    ["avgvol_1d", ">", 1000000],                   # Higher volume threshold
    ["refund_1d_p", ">", 1],                       # Moving > 1% today
    ["adjusted_close", ">", 5],
    ["exchange", "=", "us"],
]

# Core tickers always included
CORE_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "TSLA", "META", "AMD",
]

# Expanded fallback â€” used when screener returns no live results
FALLBACK_WATCHLIST = [
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "AMD", "NFLX", "ADBE", "CRM", "ORCL", "SNOW", "PLTR", "COIN",
    "JPM", "BAC", "GS", "MS", "WFC",
    "UNH", "JNJ", "PFE", "ABBV", "MRK",
    "WMT", "HD", "COST", "NKE", "MCD",
    "XOM", "CVX", "OXY",
    "QCOM", "MU", "INTC", "AMAT", "LRCX",
    "UBER", "MSTR", "SMCI", "ARM", "MRVL",
]


def _is_cache_valid() -> bool:
    if not _screener_cache:
        return False
    cached_time = _screener_cache.get("date")
    if not cached_time:
        return False
    return (datetime.now() - cached_time) < timedelta(hours=_CACHE_TTL_HOURS)


def run_screener(
    filters: Optional[List] = None,
    limit: int = 50,
    sort_by: str = "avgvol_1d.desc"
) -> List[str]:
    """
    Run EODHD stock screener with custom filters.

    EODHD valid field names:
      Number: market_capitalization, avgvol_1d, avgvol_200d,
              adjusted_close, refund_1d_p, refund_5d_p,
              earnings_share, dividend_yield
      String: code, name, exchange, sector, industry

    Sort format: field_name.(asc|desc)
      e.g. sort_by="avgvol_1d.desc"

    URL is built manually (NOT via requests params={}) because EODHD
    requires the filter JSON brackets and quotes to be literal characters
    in the URL, not percent-encoded (%5B, %22, etc.).
    """
    if filters is None:
        filters = DEFAULT_FILTERS

    # Compact JSON â€” no spaces (spaces become + in URLs, also rejected)
    filter_json = json.dumps(filters, separators=(',', ':'))

    # Build URL manually to keep [ ] " as raw characters
    url = (
        f"https://eodhd.com/api/screener"
        f"?api_token={config.EODHD_API_KEY}"
        f"&filters={filter_json}"
        f"&limit={limit}"
        f"&sort={sort_by}"
        f"&fmt=json"
    )

    try:
        print(f"[SCREENER] Calling API: filters={filter_json[:80]}... limit={limit} sort={sort_by}")
        response = requests.get(url, timeout=15)
        print(f"[SCREENER] HTTP {response.status_code}")

        if response.status_code == 422:
            print(f"[SCREENER] âŒ 422 â€” filter format rejected")
            try:
                print(f"[SCREENER] API error: {response.text[:400]}")
            except Exception:
                pass
            return []
        if response.status_code == 403:
            print("[SCREENER] âŒ 403 â€” screener not in your EODHD plan")
            return []
        if response.status_code == 401:
            print("[SCREENER] âŒ 401 â€” check EODHD_API_KEY in config.py")
            return []

        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            total = data.get("total", "?")
            print(f"[SCREENER] âœ… Total results from API: {total}")
        else:
            print(f"[SCREENER] Unexpected response: {type(data)} | {str(data)[:200]}")
            return []

        results = data.get("data", [])
        if not results:
            print("[SCREENER] âš ï¸  0 results â€” filters may be too strict or market is closed")
            return []

        tickers = []
        for item in results:
            code = item.get("code", "")
            if not code:
                continue
            ticker = code.split(".")[0]
            if ticker and ticker not in tickers:
                tickers.append(ticker)

        print(f"[SCREENER] âœ… {len(tickers)} tickers returned")
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
    Falls back to FALLBACK_WATCHLIST (50 tickers) if API returns no results.
    Does NOT cache fallback â€” retries API on next call.
    """
    if not force_refresh and _is_cache_valid():
        cached_results = _screener_cache.get("results", [])
        print(f"[SCREENER] Using cached results ({len(cached_results)} tickers)")
        return cached_results

    print("[SCREENER] Running dynamic screener...")

    watchlist = list(CORE_TICKERS) if include_core else []
    screener_success = False

    # Run 1: Top volume stocks today
    volume_movers = run_screener(
        filters=DEFAULT_FILTERS,
        limit=max_tickers,
        sort_by="avgvol_1d.desc"
    )
    if volume_movers:
        screener_success = True
        for ticker in volume_movers:
            if ticker not in watchlist:
                watchlist.append(ticker)

    # Run 2: Top % movers today (refund_1d_p = 1-day gain/loss %)
    price_movers = run_screener(
        filters=[
            ["market_capitalization", ">", 1000000000],
            ["avgvol_1d", ">", 500000],
            ["refund_1d_p", ">", 2],               # > 2% move today
            ["adjusted_close", ">", 5],
            ["exchange", "=", "us"],
        ],
        limit=20,
        sort_by="refund_1d_p.desc"
    )
    if price_movers:
        screener_success = True
        for ticker in price_movers:
            if ticker not in watchlist:
                watchlist.append(ticker)

    # Fallback â€” don't cache so next call retries the live API
    if not screener_success:
        print("[SCREENER] âš ï¸  No live screener data â€” using FALLBACK_WATCHLIST")
        print("[SCREENER] âš ï¸  Cache NOT saved (will retry next call)")
        return list(dict.fromkeys(FALLBACK_WATCHLIST))[:max_tickers]

    final_watchlist = watchlist[:max_tickers]
    _screener_cache["date"] = datetime.now()
    _screener_cache["results"] = final_watchlist

    print(f"[SCREENER] âœ… Watchlist: {len(final_watchlist)} tickers")
    print(f"[SCREENER] Top 10: {', '.join(final_watchlist[:10])}")
    return final_watchlist


def get_sector_screener(sector: str, limit: int = 20) -> List[str]:
    """Screen for stocks in a specific sector."""
    filters = [
        ["market_capitalization", ">", 1000000000],
        ["avgvol_1d", ">", 500000],
        ["sector", "=", sector],
        ["adjusted_close", ">", 5],
        ["exchange", "=", "us"],
    ]
    return run_screener(filters=filters, limit=limit, sort_by="avgvol_1d.desc")


def get_gap_candidates(min_gap_pct: float = 3.0, limit: int = 30) -> List[str]:
    """Find stocks with significant gaps."""
    filters = [
        ["market_capitalization", ">", 500000000],
        ["avgvol_1d", ">", 300000],
        ["refund_1d_p", ">", min_gap_pct],
        ["adjusted_close", ">", 3],
        ["exchange", "=", "us"],
    ]
    return run_screener(filters=filters, limit=limit, sort_by="refund_1d_p.desc")


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    """Generate watchlist for high-volume days (FOMC, earnings season)."""
    return run_screener(
        filters=HIGH_VOLUME_FILTERS,
        limit=limit,
        sort_by="avgvol_1d.desc"
    )


def clear_screener_cache():
    """Clear screener cache. Called at EOD by main.py."""
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

