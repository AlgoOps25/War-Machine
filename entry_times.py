from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = 0.0001
import psycopg2, psycopg2.extras, os, pandas as pd
from dotenv import load_dotenv; load_dotenv()
from app.signals.opening_range import detect_breakout_after_or, detect_fvg_after_break
from utils import config as cfg
from datetime import time as dtime
from collections import Counter

OR_MIN_RANGE_PCT = getattr(cfg, 'OR_MIN_RANGE_PCT', 0.003)
OR_START, OR_END = dtime(9,30), dtime(9,45)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT DISTINCT datetime::date as d FROM intraday_bars WHERE ticker='SPY' AND datetime::date BETWEEN '2025-12-20' AND '2026-03-20' ORDER BY d")
dates = [r['d'] for r in cur.fetchall()]

entry_times = Counter()
for date in dates:
    cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY', date))
    rows = cur.fetchall()
    if not rows: continue
    df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
    df['datetime'] = pd.to_datetime(df['datetime'])
    mins = df['datetime'].dt.hour*60+df['datetime'].dt.minute
    rth = df[(mins>=570)&(mins<960)].reset_index(drop=True)
    if len(rth) < 20: continue
    bars = rth.to_dict('records')
    or_bars = [b for b in bars if OR_START <= b['datetime'].time() < OR_END]
    if len(or_bars) < 2: continue
    or_high = max(b['high'] for b in or_bars)
    or_low  = min(b['low']  for b in or_bars)
    if (or_high-or_low)/or_low < OR_MIN_RANGE_PCT: continue
    direction, bidx = detect_breakout_after_or(bars, or_high, or_low)
    if direction is None or bidx > 60: continue
    flo, fhi = detect_fvg_after_break(bars, bidx, direction)
    if flo is None: continue
    t = bars[bidx]['datetime']
    entry_times[f"{t.hour:02d}:{t.minute:02d}"] += 1

conn.close()
print("Breakout entry time distribution (25 sessions):")
for k in sorted(entry_times):
    mins = int(k[:2])*60 + int(k[3:])
    blocked = mins == 600 or 620 <= mins <= 630
    print(f"  {k}  x{entry_times[k]}{'  <-- DEAD ZONE BLOCKED' if blocked else ''}")
