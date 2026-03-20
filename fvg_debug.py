import sys, os
sys.path.insert(0, '.')
os.chdir(r'C:\Dev\War-Machine')
from dotenv import load_dotenv
load_dotenv(r'C:\Dev\War-Machine\.env')
import psycopg2, psycopg2.extras

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY','2026-03-13'))
rows = cur.fetchall()
conn.close()
bars = [{'datetime': str(r['datetime']), 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows]

for idx, direction in [(39,'bear'),(15,'bull'),(125,'bear'),(20,'bull'),(47,'bear')]:
    print(f'\n--- idx={idx} {direction} ---')
    for i in range(idx, min(idx+6, len(bars))):
        b = bars[i]
        dt = b['datetime'][11:16]
        print(f'  [{i}] {dt}  O={b["open"]:.2f} H={b["high"]:.2f} L={b["low"]:.2f} C={b["close"]:.2f}')
