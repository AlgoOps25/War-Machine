import sys, os
from dotenv import load_dotenv
load_dotenv(override=True)
import requests
import panda as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print("DATABASE_URL =", os.getenv("DATABASE_URL", "NOT SET")[:40])
from app.data.db_connection import get_conn, return_conn, dict_cursor

conn = get_conn()
cur  = dict_cursor(conn)

cur.execute("""
    SELECT ticker, COUNT(datetime) as cnt,
           MIN(datetime) as earliest,
           MAX(datetime) as latest
    FROM intraday_bars
    GROUP BY ticker
    ORDER BY cnt DESC
    LIMIT 15
""")
rows = cur.fetchall()
print("\n=== intraday_bars inventory ===")
if rows:
    for r in rows:
        d = dict(r)
        print(f"  {d['ticker']:6s}  {d['cnt']:>7,} bars  |  {d['earliest']}  ->  {d['latest']}")
else:
    print("  *** TABLE IS EMPTY ***")

print("\n=== Sample NVDA rows (first 3) ===")
cur.execute("""
    SELECT datetime, open, high, low, close, volume
    FROM intraday_bars
    WHERE ticker = 'NVDA'
    ORDER BY datetime
    LIMIT 3
""")
for r in cur.fetchall():
    print(" ", dict(r))

return_conn(conn)