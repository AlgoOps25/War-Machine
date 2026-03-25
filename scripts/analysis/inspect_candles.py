from dotenv import load_dotenv
load_dotenv()
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("""
    SELECT ticker, timeframe, COUNT(*) as bars,
           MIN(datetime) as earliest, MAX(datetime) as latest
    FROM candle_cache
    GROUP BY ticker, timeframe
    ORDER BY ticker, timeframe
""")
for row in cur.fetchall():
    print(f"  {row[0]:6s} | {row[1]:5s} | {row[2]:7,d} bars | {str(row[3])[:10]} → {str(row[4])[:10]}")
