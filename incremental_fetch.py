import sqlite3
from scanner_helpers import get_intraday_bars_for_logger

DB="market_memory.db"

def update_ticker(ticker):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT datetime FROM candles WHERE ticker=? ORDER BY datetime DESC LIMIT 1",(ticker,))
    row = c.fetchone()

    last_time = row[0] if row else None

    bars = get_intraday_bars_for_logger(ticker, limit=30, interval="1m")

    new = 0
    for b in bars:
        ts = b.get("datetime") or b.get("date")
        if not ts:
            continue

        if last_time and ts <= last_time:
            continue

        try:
            c.execute("""
            INSERT OR IGNORE INTO candles
            (ticker,datetime,open,high,low,close,volume)
            VALUES (?,?,?,?,?,?,?)
            """,(ticker,ts,b["open"],b["high"],b["low"],b["close"],b["volume"]))
            new += 1
        except:
            pass

    conn.commit()
    conn.close()

    print(f"{ticker}: added {new} new candles")
