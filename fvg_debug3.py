import sys, os
sys.path.insert(0, '.')
os.chdir(r'C:\Dev\War-Machine')
from dotenv import load_dotenv
load_dotenv(r'C:\Dev\War-Machine\.env')

# Check what FVG_MIN_SIZE_PCT is BEFORE and AFTER the monkey-patch
from utils import config as cfg
print(f"FVG_MIN_SIZE_PCT before patch: {cfg.FVG_MIN_SIZE_PCT}")
cfg.FVG_MIN_SIZE_PCT = 0.0001
print(f"FVG_MIN_SIZE_PCT after patch:  {cfg.FVG_MIN_SIZE_PCT}")

import psycopg2, psycopg2.extras
from app.core.sniper import detect_fvg_after_break
import pandas as pd

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY','2026-03-13'))
rows = cur.fetchall()
conn.close()

df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
df['datetime'] = pd.to_datetime(df['datetime'])
minutes = df['datetime'].dt.hour * 60 + df['datetime'].dt.minute
rth = df[(minutes >= 570) & (minutes < 960)].reset_index(drop=True)
bars = rth.to_dict('records')

for idx, direction in [(39,'bear'),(15,'bull'),(125,'bear'),(20,'bull'),(47,'bear')]:
    lo, hi = detect_fvg_after_break(bars, idx, direction)
    print(f'  idx={idx} {direction}: FVG={lo}-{hi}')
