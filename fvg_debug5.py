from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = 0.0001
import psycopg2, psycopg2.extras, os, pandas as pd, logging
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.DEBUG, format="%(message)s")

from app.signals.opening_range import detect_breakout_after_or, detect_fvg_after_break
from app.validation.cfw6_confirmation import grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets
from utils import config as cfg

OR_MIN_RANGE_PCT = getattr(cfg, "OR_MIN_RANGE_PCT", 0.003)
OR_5M_START = __import__("datetime").time(9,30)
OR_5M_END   = __import__("datetime").time(9,45)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

for date in ['2026-03-16','2026-03-17','2026-03-18','2026-03-19']:
    cur.execute('SELECT datetime,open,high,low,close,volume FROM intraday_bars WHERE ticker=%s AND datetime::date=%s ORDER BY datetime', ('SPY', date))
    rows = cur.fetchall()
    if not rows: continue
    df = pd.DataFrame([{'datetime': r['datetime'], 'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']), 'volume': int(r['volume'])} for r in rows])
    df['datetime'] = pd.to_datetime(df['datetime'])
    minutes = df['datetime'].dt.hour * 60 + df['datetime'].dt.minute
    rth = df[(minutes >= 570) & (minutes < 960)].reset_index(drop=True)
    bars = rth.to_dict('records')

    or_bars = [b for b in bars if OR_5M_START <= b['datetime'].time() < OR_5M_END]
    if len(or_bars) < 2: print(f"{date}: FAIL no OR bars"); continue
    or_high = max(b['high'] for b in or_bars)
    or_low  = min(b['low']  for b in or_bars)
    or_pct  = (or_high - or_low) / or_low
    print(f"\n{date}: OR={or_low:.2f}-{or_high:.2f} range={or_pct*100:.3f}%", "FAIL<0.3%" if or_pct < OR_MIN_RANGE_PCT else "OK")
    if or_pct < OR_MIN_RANGE_PCT: continue

    direction, bidx = detect_breakout_after_or(bars, or_high, or_low)
    print(f"  Breakout: {direction} idx={bidx}")
    if direction is None: continue

    bvol = bars[bidx].get('volume', 0)
    pvols = [b['volume'] for b in bars[:bidx] if b['volume'] > 0]
    avg_vol = sum(pvols)/len(pvols) if pvols else 0
    rvol = bvol / avg_vol if avg_vol else 0
    print(f"  RVOL: {rvol:.2f}x (bvol={bvol} avg={avg_vol:.0f})", "FAIL<1.2x" if rvol < 1.2 else "OK")
    if len(pvols) >= 3 and rvol < 1.2: continue

    flo, fhi = detect_fvg_after_break(bars, bidx, direction)
    print(f"  FVG: {flo}-{fhi}", "FAIL None" if flo is None else "OK")
    if flo is None: continue

    fvg_mid = (flo + fhi) / 2.0
    try:
        graded = grade_signal_with_confirmations('SPY', direction, bars, fvg_mid, bidx, 'A', session_date=date)
        print(f"  Grade: {graded.get('final_grade')} confirmations={graded.get('confirmations_met',[])} total={graded.get('total_confirmations',0)}")
        if graded.get('final_grade') == 'reject': continue
    except Exception as e:
        print(f"  Grade ERROR: {e}")

    try:
        stop, t1, t2 = compute_stop_and_targets(bars, direction, or_high, or_low, fvg_mid, grade='A')
        risk = abs(fvg_mid - stop)
        print(f"  Levels: entry={fvg_mid:.2f} stop={stop} t1={t1} t2={t2} risk={risk:.2f}", "FAIL<0.25" if risk < 0.25 else "OK")
    except Exception as e:
        print(f"  Levels ERROR: {e}")

conn.close()
