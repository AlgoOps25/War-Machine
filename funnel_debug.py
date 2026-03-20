from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = 0.0001
import psycopg2, psycopg2.extras, os, pandas as pd
from dotenv import load_dotenv; load_dotenv()
from app.signals.opening_range import detect_breakout_after_or, detect_fvg_after_break
from app.validation.cfw6_confirmation import grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets
from utils import config as cfg
from datetime import time as dtime

OR_MIN_RANGE_PCT = getattr(cfg, 'OR_MIN_RANGE_PCT', 0.003)
OR_START, OR_END = dtime(9,30), dtime(9,45)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT DISTINCT datetime::date as d FROM intraday_bars WHERE ticker='SPY' AND datetime::date BETWEEN '2025-12-20' AND '2026-03-20' ORDER BY d")
dates = [r['d'] for r in cur.fetchall()]

counts = {'total':0,'no_or':0,'tight_or':0,'no_breakout':0,'late_breakout':0,'no_fvg':0,'grade_reject':0,'no_levels':0,'fired':0}
for date in dates:
    cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY', date))
    rows = cur.fetchall()
    if not rows: continue
    df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
    df['datetime'] = pd.to_datetime(df['datetime'])
    mins = df['datetime'].dt.hour*60+df['datetime'].dt.minute
    rth = df[(mins>=570)&(mins<960)].reset_index(drop=True)
    if len(rth) < 20: continue
    counts['total'] += 1
    bars = rth.to_dict('records')

    or_bars = [b for b in bars if OR_START <= b['datetime'].time() < OR_END]
    if len(or_bars) < 2: counts['no_or'] += 1; continue
    or_high = max(b['high'] for b in or_bars)
    or_low  = min(b['low']  for b in or_bars)
    or_pct  = (or_high - or_low) / or_low
    if or_pct < OR_MIN_RANGE_PCT: counts['tight_or'] += 1; continue

    direction, bidx = detect_breakout_after_or(bars, or_high, or_low)
    if direction is None: counts['no_breakout'] += 1; continue
    if bidx > 60: counts['late_breakout'] += 1; continue

    flo, fhi = detect_fvg_after_break(bars, bidx, direction)
    if flo is None: counts['no_fvg'] += 1; continue

    fvg_mid = (flo+fhi)/2
    try:
        graded = grade_signal_with_confirmations('SPY', direction, bars, fvg_mid, bidx, 'A', session_date=str(date))
        if graded.get('final_grade') == 'reject': counts['grade_reject'] += 1; continue
    except: pass

    try:
        stop,t1,t2 = compute_stop_and_targets(bars, direction, or_high, or_low, fvg_mid, grade='A')
        if stop is None or abs(fvg_mid-stop) < 0.25: counts['no_levels'] += 1; continue
    except: counts['no_levels'] += 1; continue

    counts['fired'] += 1

conn.close()
for k,v in counts.items():
    print(f'  {k}: {v}')
