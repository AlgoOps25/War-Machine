"""
Pre-Market Scanner (4 AM - 9:30 AM EST)
Builds intelligent watchlist before market opens
"""

import requests
from datetime import datetime
from typing import List, Dict
import config


def get_gap_movers(min_gap_pct: float = 3.0) -> List[Dict]:
    """Find stocks gapping significantly in pre-market."""
    url = "https://eodhd.com/api/real-time/US"
    params = {"api_token": config.EODHD_API_KEY, "fmt": "json"}
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        gap_stocks = []
        
        for ticker_data in data:
            ticker = ticker_data.get("code", "").replace(".US", "")
            previous_close = ticker_data.get("previousClose", 0)
            current_price = ticker_data.get("price", 0)
            volume = ticker_data.get("volume", 0)
            
            if previous_close > 0 and current_price > 0:
                gap_pct = ((current_price - previous_close) / previous_close) * 100
                
                if abs(gap_pct) >= min_gap_pct:
                    gap_stocks.append({
                        "ticker": ticker,
                        "gap_pct": round(gap_pct, 2),
                        "price": current_price,
                        "prev_close": previous_close,
                        "volume": volume
                    })
        
        gap_stocks.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
        return gap_stocks[:30]
        
    except Exception as e:
        print(f"[PREMARKET] Gap scanner error: {e}")
        return []


def get_earnings_today() -> List[str]:
    """Fetch stocks with earnings announcements today."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    url = "https://eodhd.com/api/calendar/earnings"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from": today,
        "to": today,
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        tickers = []
        if isinstance(data, dict) and "earnings" in data:
            for item in data["earnings"]:
                ticker = item.get("code", "").replace(".US", "")
                if ticker:
                    tickers.append(ticker)
        
        return tickers[:20]
        
    except Exception as e:
        print(f"[PREMARKET] Earnings scanner error: {e}")
        return []


def build_premarket_watchlist() -> List[str]:
    """Build master pre-market watchlist with scoring."""
    print("\n" + "="*60)
    print(f"PRE-MARKET WATCHLIST - {datetime.now().strftime('%I:%M:%S %p')}")
    print("="*60)
    
    watchlist = set()
    
    # Gap movers
    print("[PREMARKET] Scanning gap movers...")
    gaps = get_gap_movers()
    for stock in gaps[:15]:  # Top 15 gaps
        watchlist.add(stock["ticker"])
        print(f"  📈 {stock['ticker']}: {stock['gap_pct']:+.2f}%")
    
    # Earnings
    print("[PREMARKET] Scanning earnings...")
    earnings = get_earnings_today()
    for ticker in earnings[:10]:  # Top 10 earnings
        watchlist.add(ticker)
        print(f"  📰 {ticker}: Earnings")
    
    # Core liquid tickers (always include)
    core = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "MSFT"]
    for ticker in core:
        watchlist.add(ticker)
    
    final_list = sorted(list(watchlist))
    
    print(f"\n✅ Watchlist: {len(final_list)} tickers")
    print(f"{', '.join(final_list)}")
    print("="*60 + "\n")
    
    return final_list
