import sqlite3
from scanner_helpers import get_intraday_bars_for_logger

DB = "market_memory.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS candles(
        ticker TEXT,
        datetime TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY(ticker, datetime)
    )
    """)

    conn.commit()
    conn.close()

def store_bars(ticker, bars):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    for b in bars:
        try:
            ts = b.get("datetime") or b.get("date")
            o = float(b.get("open"))
            h = float(b.get("high"))
            l = float(b.get("low"))
            cl = float(b.get("close"))
            v = float(b.get("volume", 0))

            c.execute("""
            INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?)
            """,(ticker, ts, o, h, l, cl, v))
        except:
            pass

    conn.commit()
    conn.close()

def build_history(ticker):
    print(f"Building historical DB for {ticker}")
    bars = get_intraday_bars_for_logger(ticker, limit=50000, interval="1m")

    if not bars:
        print("❌ No data returned")
        return

    store_bars(ticker, bars)
    print(f"✅ Stored {len(bars)} candles for {ticker}")

if __name__ == "__main__":
    init_db()
    build_history("SPY")
