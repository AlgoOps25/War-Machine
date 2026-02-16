import sqlite3
from datetime import datetime, timedelta

DB = "market_memory.db"

def get_recent_bars(ticker, minutes=120):
    """
    Pull recent candles from local DB instead of EODHD
    """
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    c.execute("""
    SELECT datetime, open, high, low, close, volume
    FROM candles
    WHERE ticker=?
    ORDER BY datetime DESC
    LIMIT ?
    """,(ticker, minutes))

    rows = c.fetchall()
    conn.close()

    bars = []
    for r in reversed(rows):
        bars.append({
            "datetime": r[0],
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5]
        })

    return bars


def store_new_bars(ticker, bars):
    """
    Store only NEW candles into memory
    """
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    added = 0

    for b in bars:
        try:
            ts = b.get("datetime") or b.get("date")
            o = float(b.get("open"))
            h = float(b.get("high"))
            l = float(b.get("low"))
            cl = float(b.get("close"))
            v = float(b.get("volume",0))

            c.execute("""
            INSERT OR IGNORE INTO candles
            VALUES (?,?,?,?,?,?,?)
            """,(ticker, ts, o, h, l, cl, v))

            added += 1
        except:
            pass

    conn.commit()
    conn.close()

    if added:
        print(f"🧠 Memory updated: {ticker} +{added} candles")
