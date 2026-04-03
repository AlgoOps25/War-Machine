"""Quick DB probe -- run once to diagnose table visibility and date ranges.

BUG-BT-14 (Apr 03 2026): Added per-ticker MIN/MAX datetime queries for
  intraday_bars and intraday_bars_5m so data gaps are immediately visible
  without needing a separate SQL client.
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
        print(f"  {table:<25} MISSING -- {e}")

print()

# ---------------------------------------------------------------------------
# BUG-BT-14: Date ranges per ticker for both bar tables
# ---------------------------------------------------------------------------
DEFAULT_TICKERS = ('AAPL', 'TSLA', 'NVDA', 'MSFT', 'AMD')

for table in ('intraday_bars', 'intraday_bars_5m'):
    print(f"  {table} -- date ranges:")
    print(f"    {'Ticker':<8}  {'First bar':<12}  {'Last bar':<12}  {'Rows':>8}")
    print(f"    {'-'*8}  {'-'*12}  {'-'*12}  {'-'*8}")
    try:
        cur.execute(
            f"""
            SELECT ticker,
                   MIN(datetime)::date  AS first_bar,
                   MAX(datetime)::date  AS last_bar,
                   COUNT(*)             AS rows
            FROM {table}
            WHERE ticker = ANY(%s)
            GROUP BY ticker
            ORDER BY ticker
            """,
            (list(DEFAULT_TICKERS),),
        )
        rows = cur.fetchall()
        if rows:
            for ticker, first, last, cnt in rows:
                print(f"    {ticker:<8}  {str(first):<12}  {str(last):<12}  {cnt:>8,}")
        else:
            print("    (no rows for default tickers)")
    except Exception as e:
        conn.rollback()
        print(f"    ERROR: {e}")
    print()

# ---------------------------------------------------------------------------
# All public tables
# ---------------------------------------------------------------------------
cur.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='public' ORDER BY table_name"
)
print("All public tables:", [r[0] for r in cur.fetchall()])
conn.close()
