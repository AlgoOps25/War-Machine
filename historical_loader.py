import sqlite3
from scanner_helpers import get_intraday_bars_for_logger
from datetime import datetime
import pytz

DB = "market_memory.db"
est = pytz.timezone("US/Eastern")

# ================================
# INIT DATABASE
# ================================
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


# ================================
# MARKET HOURS FILTER
# ================================
def is_market_hours(ts):
    try:
        # parse timestamp
        d = datetime.fromisoformat(ts.replace("Z",""))

        # assume UTC → convert to EST
        if d.tzinfo is None:
            d = pytz.utc.localize(d).astimezone(est)
        else:
            d = d.astimezone(est)

        # skip weekends
        if d.weekday() >= 5:
            return False

        # before 9:30
        if d.hour < 9:
            return False
        if d.hour == 9 and d.minute < 30:
            return False

        # after 4pm
        if d.hour > 16:
            return False
        if d.hour == 16 and d.minute > 0:
            return False

        return True
    except:
        return False


# ================================
# STORE BARS
# ================================
def store_bars(ticker, bars):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    inserted = 0

    for b in bars:
        try:
            ts = b.get("datetime") or b.get("date")
            if not ts:
                continue

            # FILTER: only real session candles
            if not is_market_hours(ts):
                continue

            o = float(b.get("open") or 0)
            h = float(b.get("high") or 0)
            l = float(b.get("low") or 0)
            cl = float(b.get("close") or 0)
            v = float(b.get("volume") or 0)

            c.execute("""
            INSERT OR IGNORE INTO candles
            (ticker, datetime, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
            """,(ticker, ts, o, h, l, cl, v))

            inserted += 1

        except Exception:
            pass

    conn.commit()
    conn.close()

    print(f"✅ Stored {inserted} valid market candles for {ticker}")


# ================================
# BUILD FULL HISTORY
# ================================
def build_history(ticker):
    print(f"Building historical DB for {ticker}")

    bars = get_intraday_bars_for_logger(
        ticker,
        limit=50000,   # max allowed
        interval="1m"
    )

    if not bars:
        print("❌ No data returned from EODHD")
        return

    print(f"📊 Raw bars pulled: {len(bars)}")

    store_bars(ticker, bars)


# ================================
# RUN
# ================================
if __name__ == "__main__":
    init_db()
    build_history("SPY")
