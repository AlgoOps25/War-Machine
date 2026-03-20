import sys, os
sys.path.insert(0, '.')
os.chdir(r'C:\Dev\War-Machine')
from dotenv import load_dotenv
load_dotenv(r'C:\Dev\War-Machine\.env')
import psycopg2, psycopg2.extras
import pandas as pd
from datetime import time as dtime

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY','2026-03-13'))
rows = cur.fetchall()
conn.close()

df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
df['datetime'] = pd.to_datetime(df['datetime'])
minutes = df['datetime'].dt.hour * 60 + df['datetime'].dt.minute
rth = df[(minutes >= 570) & (minutes < 960)].reset_index(drop=True)
print(f'Total bars: {len(df)},  RTH only: {len(rth)}')
print(f'RTH start: {rth.iloc[0]["datetime"]}')
print(f'RTH end:   {rth.iloc[-1]["datetime"]}')

# Now show the actual breakout bars at the indices the backtest sees
for idx, direction in [(39,'bear'),(15,'bull'),(125,'bear'),(20,'bull'),(47,'bear')]:
    if idx < len(rth):
        b = rth.iloc[idx]
        print(f'  idx={idx} {direction}: {b["datetime"]}  O={b["open"]:.2f} H={b["high"]:.2f} L={b["low"]:.2f} C={b["close"]:.2f}')
