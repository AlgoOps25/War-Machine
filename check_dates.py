import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT DISTINCT datetime::date as d, COUNT(*) FROM intraday_bars WHERE ticker='SPY' GROUP BY d ORDER BY d DESC LIMIT 10")
for row in cur.fetchall():
    print(row)
conn.close()
