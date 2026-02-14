# scanner_helpers.py
import requests, os
EODHD_API_KEY = os.getenv("EODHD_API_KEY")

def get_intraday_bars_for_logger(ticker, limit=120, interval="1m"):
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    except Exception:
        return []

def get_realtime_quote_for_logger(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None
