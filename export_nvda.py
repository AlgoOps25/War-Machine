import csv
from dotenv import load_dotenv
load_dotenv()
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT datetime, open, high, low, close, volume FROM intraday_bars_5m WHERE ticker = 'NVDA' ORDER BY datetime ASC")
rows = cur.fetchall()
with open('nvda_5m.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['datetime','open','high','low','close','volume'])
    w.writerows(rows)
conn.close()
print(f'Done - {len(rows)} rows written')