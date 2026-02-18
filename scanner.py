# scanner.py
import requests
import os

API_KEY = os.getenv("EODHD_API_KEY", "")

# -------------------------------------------------
# BUILD INSTITUTIONAL WATCHLIST
# -------------------------------------------------
def build_watchlist():

    print("🔥 Building institutional watchlist")

    url = "https://eodhd.com/api/screener"

    headers = {
        "Content-Type": "application/json"
    }

    # CORRECT EODHD FILTER STRUCTURE
    payload = {
        "api_token": API_KEY,
        "exchange": "US",
        "filters": [
            {
                "field": "market_capitalization",
                "operation": "greater",
                "value": 2000000000
            },
            {
                "field": "avgvol_200d",
                "operation": "greater",
                "value": 1000000
            },
            {
                "field": "price",
                "operation": "greater",
                "value": 5
            }
        ],
        "limit": 200
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)

        if r.status_code != 200:
            print(f"⚠️ Screener HTTP {r.status_code}")
            print(r.text)
            return fallback_list()

        data = r.json()

        if not data:
            print("⚠️ Empty screener response")
            return fallback_list()

        tickers = [x["code"] for x in data]

        print(f"✅ Watchlist built: {len(tickers)} symbols")
        return tickers

    except Exception as e:
        print(f"⚠️ Screener error: {e}")
        return fallback_list()

def start_scanner_loop():
    """
    Main scanner loop - builds watchlist and processes tickers continuously.
    Called by main.py to start the scanning engine.
    """
    import time
    from sniper import process_ticker
    import config
    
    print(f"[SCANNER] Starting scanner loop with {config.SCAN_INTERVAL}s interval")
    
    while True:
        try:
            # Build fresh watchlist
            watchlist = build_watchlist()
            
            if not watchlist:
                print("[SCANNER] No tickers in watchlist, using fallback")
                watchlist = fallback_list()
            
            print(f"[SCANNER] Processing {len(watchlist)} tickers")
            
            # Process each ticker through the sniper
            for ticker in watchlist:
                try:
                    process_ticker(ticker)
                except Exception as e:
                    print(f"[SCANNER] Error processing {ticker}: {e}")
                    continue
            
            print(f"[SCANNER] Cycle complete. Sleeping {config.SCAN_INTERVAL}s")
            time.sleep(config.SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print("[SCANNER] Scanner stopped by user")
            break
        except Exception as e:
            print(f"[SCANNER] Scanner loop error: {e}")
            time.sleep(30)  # Wait 30s on error before retrying

# -------------------------------------------------
# FALLBACK (if API fails)
# -------------------------------------------------
def fallback_list():
    print("⚠️ Screener failed — fallback list used")

    return [
        "SPY","QQQ","NVDA","TSLA","AMD","MSFT","AAPL",
        "AMZN","META","COIN","PLTR","SMCI","NFLX"
    ]
