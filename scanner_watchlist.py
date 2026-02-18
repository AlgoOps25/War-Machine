import requests
import os

API_KEY = os.getenv("EODHD_API_KEY")

# -----------------------------------------
# PULL US SYMBOLS (ONLY REAL STOCKS/ETFs)
# -----------------------------------------
def get_us_symbols():

    url = f"https://eodhd.com/api/exchange-symbol-list/US?api_token={API_KEY}&fmt=json"
    r = requests.get(url, timeout=30)

    if r.status_code != 200:
        print("❌ symbol list failed")
        return []

    data = r.json()

    symbols = []

    for s in data:
        code = s.get("Code")
        typ = str(s.get("Type","")).lower()
        name = str(s.get("Name","")).lower()

        if not code:
            continue

        # remove garbage
        if "^" in code:
            continue
        if "fund" in name:
            continue
        if "trust" in name:
            continue
        if "bond" in name:
            continue
        if len(code) > 5:
            continue

        # keep stocks + ETFs only
        if typ in ["common stock","etf"]:
            symbols.append(code)

    return list(set(symbols))


# -----------------------------------------
# BUILD WAR MACHINE WATCHLIST
# -----------------------------------------
def build_watchlist():

    print("🔥 Building institutional watchlist")

    symbols = get_us_symbols()

    if not symbols:
        print("⚠️ Failed pulling symbols")
        return fallback()

    # Core institutional tickers
    core = [
        "SPY","QQQ","NVDA","TSLA","META","AAPL","MSFT",
        "AMD","AMZN","SMCI","COIN","NFLX","GOOGL"
    ]

    watch = []

    # force include core
    for c in core:
        if c in symbols:
            watch.append(c)

    # add rest of liquid stocks
    for s in symbols:
        if s not in watch:
            watch.append(s)

    final = watch[:30]

    print(f"✅ Clean Watchlist Built: {len(final)}")
    return final


def fallback():
    print("⚠️ Using fallback majors")
    return ["SPY","QQQ","NVDA","TSLA","META","AAPL","MSFT"]
