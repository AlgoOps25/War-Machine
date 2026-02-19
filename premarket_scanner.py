"""
Pre-Market Scanner (4 AM - 9:30 AM EST)
Builds intelligent watchlist before market opens
"""
import requests
from datetime import datetime
from typing import List, Dict
import config

# Tickers to scan for pre-market gaps
SCAN_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "NFLX", "ADBE", "CRM", "INTC", "CSCO", "JPM", "BAC", "GS",
    "MS", "WFC", "UNH", "JNJ", "PFE", "ABBV", "MRK", "WMT",
    "HD", "COST", "NKE", "MCD", "SPY", "QQQ", "IWM", "DIA"
]


def get_gap_movers(min_gap_pct: float = 2.0) -> List[Dict]:
    """
    Find stocks gapping significantly in pre-market.
    Uses EODHD bulk real-time quotes via s= parameter.
    FIX: Previous code iterated dict keys (strings) instead of values.
    """
    primary = f"{SCAN_UNIVERSE[0]}.US"
    extra   = ",".join(f"{t}.US" for t in SCAN_UNIVERSE[1:])

    url = f"https://eodhd.com/api/real-time/{primary}"
    params = {
        "api_token": config.EODHD_API_KEY,
        "s":         extra,
        "fmt":       "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Normalize: API returns dict for single ticker, list for bulk
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            print(f"[PREMARKET] Unexpected gap data type: {type(data)}")
            return []

        gap_stocks = []
        for item in items:
            if not isinstance(item, dict):
                continue  # Skip string keys if dict returned

            code   = item.get("code", "")
            ticker = code.replace(".US", "") if code else ""
            if not ticker:
                continue

            prev_close    = float(item.get("previousClose", 0) or 0)
            current_price = float(item.get("close", 0) or item.get("open", 0) or 0)
            volume        = int(item.get("volume", 0) or 0)

            if prev_close > 0 and current_price > 0:
                gap_pct = ((current_price - prev_close) / prev_close) * 100

                if abs(gap_pct) >= min_gap_pct:
                    gap_stocks.append({
                        "ticker":     ticker,
                        "gap_pct":    round(gap_pct, 2),
                        "price":      current_price,
                        "prev_close": prev_close,
                        "volume":     volume
                    })

        gap_stocks.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
        print(f"[PREMARKET] Found {len(gap_stocks)} gap movers (>{min_gap_pct}%)")
        return gap_stocks[:30]

    except Exception as e:
        print(f"[PREMARKET] Gap scanner error: {e}")
        return []


def get_earnings_today() -> List[str]:
    """
    Fetch stocks with earnings today.
    NOTE: EODHD earnings calendar requires extended subscription.
    Returns empty list gracefully if not available (403).
    """
    today = datetime.now().strftime("%Y-%m-%d")

    url = "https://eodhd.com/api/calendar/earnings"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from":      today,
        "to":        today,
        "fmt":       "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)

        # 403 = endpoint not in current plan — skip silently
        if response.status_code == 403:
            print("[PREMARKET] Earnings calendar not available on current EODHD plan — skipping")
            return []

        response.raise_for_status()
        data = response.json()

        tickers = []
        if isinstance(data, dict) and "earnings" in data:
            for item in data["earnings"]:
                ticker = item.get("code", "").replace(".US", "")
                if ticker:
                    tickers.append(ticker)

        print(f"[PREMARKET] Found {len(tickers)} earnings tickers today")
        return tickers[:20]

    except requests.exceptions.HTTPError:
        return []
    except Exception as e:
        print(f"[PREMARKET] Earnings scanner error: {e}")
        return []


def build_premarket_watchlist() -> List[str]:
    """Build master pre-market watchlist with scoring."""
    print("\n" + "=" * 60)
    print(f"PRE-MARKET WATCHLIST - {datetime.now().strftime('%I:%M:%S %p')}")
    print("=" * 60)

    watchlist = set()

    # 1 — Gap movers
    print("[PREMARKET] Scanning gap movers...")
    gaps = get_gap_movers()
    for stock in gaps[:15]:
        watchlist.add(stock["ticker"])
        direction = "📈" if stock["gap_pct"] > 0 else "📉"
        print(f"  {direction} {stock['ticker']}: {stock['gap_pct']:+.2f}%")

    if not gaps:
        print("  No significant gap movers found")

    # 2 — Earnings movers
    print("[PREMARKET] Scanning earnings...")
    earnings = get_earnings_today()
    for ticker in earnings[:10]:
        watchlist.add(ticker)
        print(f"  📰 {ticker}: Earnings today")

    # 3 — Core liquid tickers (always include)
    core = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "MSFT"]
    for ticker in core:
        watchlist.add(ticker)

    final_list = sorted(list(watchlist))

    print(f"\n✅ Watchlist: {len(final_list)} tickers")
    print(f"{', '.join(final_list)}")
    print("=" * 60 + "\n")

    return final_list
