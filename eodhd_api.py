# eodhd_api.py
# Thin wrapper for EODHD API calls used by War Machine.
import os
import requests

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
BASE = "https://eodhd.com/api"

def screener_top_by_marketcap(limit=1000, min_market_cap=2000000000):
    """
    Return list of screener results sorted by market cap desc.
    """
    try:
        url = f"{BASE}/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{min_market_cap}&limit={limit}&exchange=US"
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            print("EODHD screener failed:", r.status_code, r.text[:200])
            return []
        return r.json().get("data", [])
    except Exception as e:
        print("EODHD screener error:", e)
        return []

def get_intraday_bars(ticker, interval="1m", limit=240):
    """
    Fetch intraday bars for ticker.
    interval: '1m', '5m', '1h'
    """
    try:
        url = f"{BASE}/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            # return empty
            return []
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    except Exception as e:
        # network or parse error
        # print("get_intraday_bars error:", e)
        return []

def get_realtime_quote(ticker):
    try:
        url = f"{BASE}/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None
