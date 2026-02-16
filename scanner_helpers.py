# scanner_helpers.py
import requests, os, sqlite3
from datetime import datetime

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DB_FILE = "market_memory.db"

# ================================
# DATABASE
# ================================
def get_db():
    return sqlite3.connect(DB_FILE)

def get_last_timestamp(ticker):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT datetime FROM candles WHERE ticker=? ORDER BY datetime DESC LIMIT 1", (ticker,))
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
        return None
    except:
        return None

def store_bars(ticker, bars):
    if not bars:
        return

    try:
        conn = get_db()
        c = conn.cursor()

        for b in bars:
            ts = b.get("datetime") or b.get("date")
            if not ts:
                continue

            c.execute("""
            INSERT OR IGNORE INTO candles
            (ticker, datetime, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                ts,
                float(b.get("open",0)),
                float(b.get("high",0)),
                float(b.get("low",0)),
                float(b.get("close",0)),
                float(b.get("volume",0))
            ))

        conn.commit()
        conn.close()
    except Exception as e:
        print("DB store error:", e)

def load_recent_from_db(ticker, limit=400):
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute("""
        SELECT datetime, open, high, low, close, volume
        FROM candles
        WHERE ticker=?
        ORDER BY datetime DESC
        LIMIT ?
        """, (ticker, limit))

        rows = c.fetchall()
        conn.close()

        rows.reverse()

        out = []
        for r in rows:
            out.append({
                "datetime": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5]
            })
        return out
    except:
        return []

# ================================
# SMART FETCH (KEY PART)
# ================================
def fetch_new_bars_from_eodhd(ticker, limit=200, interval="1m"):
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print("EODHD error:", r.text)
            return []

        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        return data or []
    except Exception as e:
        print("Fetch error:", e)
        return []

# ================================
# MAIN FUNCTION USED BY SNIPER
# ================================
def get_intraday_bars_for_logger(ticker, limit=400, interval="1m"):
    """
    Smart loader:
    1. Load recent history from DB
    2. Pull only newest candles from EODHD
    3. Store new candles
    4. Return combined recent set
    """

    # STEP 1 — get last stored timestamp
    last_ts = get_last_timestamp(ticker)

    # STEP 2 — fetch recent candles from API
    new_bars = fetch_new_bars_from_eodhd(ticker, limit=200, interval=interval)

    if new_bars:
        # STEP 3 — store them
        store_bars(ticker, new_bars)

    # STEP 4 — load final recent set from DB
    final = load_recent_from_db(ticker, limit=limit)

    print(f"📊 {ticker} using MEMORY DB bars:", len(final))
    return final

# ================================
def get_realtime_quote_for_logger(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None
