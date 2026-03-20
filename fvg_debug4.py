from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = 0.0001
import psycopg2, psycopg2.extras, os, pandas as pd
from dotenv import load_dotenv
load_dotenv()
from app.core.sniper import detect_fvg_after_break

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY','2026-03-19'))
rows = cur.fetchall()
conn.close()

df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
df['datetime'] = pd.to_datetime(df['datetime'])
minutes = df['datetime'].dt.hour * 60 + df['datetime'].dt.minute
rth = df[(minutes >= 570) & (minutes < 960)].reset_index(drop=True)
bars = rth.to_dict('records')
print(f'total bars: {len(bars)}')

for idx, direction in [(15,'bull'),(125,'bear'),(20,'bull')]:
    lo, hi = detect_fvg_after_break(bars, idx, direction)
    print(f'  idx={idx} {direction}: FVG={lo}-{hi}')
    if lo is None:
        for i in range(max(0,idx-2), min(len(bars), idx+4)):
            b = bars[i]
            print(f'    bar[{i}] {b["datetime"]} O={b["open"]} H={b["high"]} L={b["low"]} C={b["close"]}')
