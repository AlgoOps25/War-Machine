"""Quick DB probe — run once to diagnose table visibility and date coverage.

BUG-BT-12 (Apr 03 2026): Added per-ticker MIN/MAX datetime queries so data
  gaps (e.g. intraday_bars_5m starting Feb 02 instead of Jan 03) are visible
  immediately without a separate SQL session.
"""
import os, sys
sys.path.insert(0, '.')
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

url = os.getenv('DATABASE_URL', '').replace('postgres://', 'postgresql://', 1)
if not url:
    print("ERROR: DATABASE_URL not set"); sys.exit(1)

import psycopg2
print(f"Connecting to: {url[:60]}...")
conn = psycopg2.connect(url, connect_timeout=15)
print("Connected OK\n")
cur = conn.cursor()

# ---------------------------------------------------------------------------
# Row counts
# ---------------------------------------------------------------------------
for table in ('intraday_bars', 'candle_cache', 'intraday_bars_5m'):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
        print(f"  {table:<25} EXISTS  ({n:,} rows)")
    except Exception as e:
        conn.rollback()
        print(f"  {table:<25} MISSING — {e}")

# ---------------------------------------------------------------------------
# BUG-BT-12: Per-ticker date ranges for backtest tickers
# ---------------------------------------------------------------------------
TICKERS = ('AAPL', 'TSLA', 'NVDA', 'MSFT', 'AMD')

for table in ('intraday_bars', 'intraday_bars_5m'):
    print(f"\n  {table} — date ranges per ticker:")
    print(f"  {'Ticker':<8} {'First bar':<14} {'Last bar':<14} {'Rows':>10}")
    print(f"  {'-'*8} {'-'*13} {'-'*13} {'-'*10}")
    try:
        for ticker in TICKERS:
            cur.execute(
                f"SELECT MIN(datetime)::date, MAX(datetime)::date, COUNT(*) "
                f"FROM {table} WHERE ticker = %s",
                (ticker,),
            )
            row = cur.fetchone()
            first, last, count = row if row else (None, None, 0)
            if count:
                print(f"  {ticker:<8} {str(first):<14} {str(last):<14} {count:>10,}")
            else:
                print(f"  {ticker:<8} {'NO DATA':<14} {'':14} {'0':>10}")
    except Exception as e:
        conn.rollback()
        print(f"  ERROR querying {table}: {e}")

print()
cur.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='public' ORDER BY table_name"
)
print("All public tables:", [r[0] for r in cur.fetchall()])
conn.close()
