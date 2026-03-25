"""Quick DB probe — run once to diagnose table visibility."""
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

for table in ('intraday_bars', 'candle_cache', 'intraday_bars_5m'):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
        print(f"  {table:<25} EXISTS  ({n:,} rows)")
    except Exception as e:
        conn.rollback()
        print(f"  {table:<25} MISSING — {e}")

print()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
print("All public tables:", [r[0] for r in cur.fetchall()])
conn.close()
