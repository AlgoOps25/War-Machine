from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = 0.0001
import psycopg2, psycopg2.extras, os, pandas as pd
from dotenv import load_dotenv; load_dotenv()
from app.risk.trade_calculator import calculate_atr
from datetime import time as dtime

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

for date in ['2026-02-04','2026-02-06','2026-02-09','2026-02-20','2026-02-23']:
    cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY', date))
    rows = cur.fetchall()
    df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
    df['datetime'] = pd.to_datetime(df['datetime'])
    mins = df['datetime'].dt.hour*60+df['datetime'].dt.minute
    rth = df[(mins>=570)&(mins<960)].reset_index(drop=True)
    bars = rth.to_dict('records')
    atr = calculate_atr(bars)
    price = bars[-1]['close']
    print(f"  {date}: ATR={atr:.4f} ({atr/price*100:.3f}% of price)  bars={len(bars)}")

conn.close()
