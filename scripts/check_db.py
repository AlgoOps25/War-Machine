import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()
from app.data.db_connection import get_conn, dict_cursor

conn = get_conn()
cur  = dict_cursor(conn)
cur.execute("""
    SELECT ticker, COUNT(*) as bars,
           MIN(datetime) as earliest,
           MAX(datetime) as latest
    FROM intraday_bars
    GROUP BY ticker
    ORDER BY ticker
""")
rows = cur.fetchall()
if not rows:
    print("No data found in intraday_bars.")
else:
    print(f"{'Ticker':<8} {'Bars':>8} {'Earliest':<22} {'Latest':<22}")
    print("-" * 62)
    for row in rows:
        r = dict(row)
        print(f"{r['ticker']:<8} {r['bars']:>8} {str(r['earliest']):<22} {str(r['latest']):<22}")