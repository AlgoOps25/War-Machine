# scanner.py
import requests

API_KEY = "YOUR_EODHD_KEY"


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


# -------------------------------------------------
# FALLBACK (if API fails)
# -------------------------------------------------
def fallback_list():
    print("⚠️ Screener failed — fallback list used")

    return [
        "SPY","QQQ","NVDA","TSLA","AMD","MSFT","AAPL",
        "AMZN","META","COIN","PLTR","SMCI","NFLX"
    ]
