"""
Pre-Market Scanner (4 AM - 9:30 AM EST)
Builds intelligent watchlist before market opens.

Exports:
  build_premarket_watchlist() — Main entry point, returns list of tickers
  get_gap_movers() — Find stocks gapping significantly
  has_earnings_today() — Check if ticker has earnings today
"""
import requests
import os
from datetime import datetime
from typing import List, Dict
import config

# ------------------------------------------------------------------ #
#  Watchlist universe                                                  #
# ------------------------------------------------------------------ #

SCAN_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "NFLX", "ADBE", "CRM",  "INTC", "CSCO", "JPM",  "BAC",  "GS",
    "MS",   "WFC",  "UNH",  "JNJ",  "PFE",  "ABBV", "MRK",  "WMT",
    "HD",   "COST", "NKE",  "MCD",  "SPY",  "QQQ",  "IWM",  "DIA"
]

# ------------------------------------------------------------------ #
#  Earnings filter                                                     #
# ------------------------------------------------------------------ #

def has_earnings_today(ticker: str) -> bool:
    """
    Returns True if ticker has earnings within the guard window.
    Delegates to earnings_filter.has_earnings_soon() which uses the EODHD
    earnings calendar — the same guard already active in sniper.process_ticker().
    """
    try:
        from earnings_filter import has_earnings_soon
        has_earns, earns_date = has_earnings_soon(ticker)
        return has_earns
    except Exception as e:
        print(f"[PREMARKET] Earnings check error for {ticker}: {e}")
        return False


# ------------------------------------------------------------------ #
#  Gap scanner                                                         #
# ------------------------------------------------------------------ #

def get_gap_movers(min_gap_pct: float = 2.0) -> List[Dict]:
    """
    Find stocks gapping significantly in pre-market.
    Uses EODHD bulk real-time quotes via s= parameter.
    """
    primary = f"{SCAN_UNIVERSE[0]}.US"
    extra   = ",".join(f"{t}.US" for t in SCAN_UNIVERSE[1:])

    url = f"https://eodhd.com/api/real-time/{primary}"
    params = {
        "api_token": config.EODHD_API_KEY,
        "s":   extra,
        "fmt": "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            return []

        gap_stocks = []
        for item in items:
            if not isinstance(item, dict):
                continue

            code          = item.get("code", "")
            ticker        = code.replace(".US", "") if code else ""
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
        return gap_stocks[:30]
    except Exception as e:
        print(f"[PREMARKET] Gap scanner error: {e}")
        return []


# ------------------------------------------------------------------ #
#  Master watchlist builder                                            #
# ------------------------------------------------------------------ #

def build_premarket_watchlist() -> List[str]:
    """Build master pre-market watchlist with scoring and earnings filter."""
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

    # 2 — Core liquid tickers always included
    core = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "MSFT"]
    for ticker in core:
        watchlist.add(ticker)

    # 3 — Filter earnings
    tickers = sorted(list(watchlist))
    clean   = []
    for t in tickers:
        if has_earnings_today(t):
            print(f"[EARNINGS] ⚠️  Removing {t} — earnings within guard window")
        else:
            clean.append(t)

    final_list = clean

    print(f"\n✅ Watchlist: {len(final_list)} tickers")
    print(f"{', '.join(final_list)}")
    print("=" * 60 + "\n")

    return final_list
