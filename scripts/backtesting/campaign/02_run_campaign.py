#!/usr/bin/env python3
"""
02_run_campaign.py  —  Full Backtest Campaign Engine
=====================================================
Exhaustively tests every meaningful combination of indicators against
cached bar data in market_memory.db.

Reads table/schema metadata written by 01_fetch_candles.py.
Falls back to auto-detection if usable_tickers.txt is missing.

Usage:
    python scripts/backtesting/campaign/02_run_campaign.py
    python scripts/backtesting/campaign/02_run_campaign.py --tickers AAPL,NVDA,TSLA
    python scripts/backtesting/campaign/02_run_campaign.py --days 60 --min-trades 10
"""

import sys
import os
import argparse
import sqlite3
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from itertools import product
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

ET = ZoneInfo('America/New_York')

# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER GRID
# ═══════════════════════════════════════════════════════════════════════════

GRID = {
    'bos_strength': [0.0010, 0.0015, 0.0018, 0.0022, 0.0030],
    'tf_confirm'  : ['1m', '3m', '5m', '5m_3m', '5m_3m_1m'],
    'vwap_zone'   : ['above_1sd', 'above_vwap', 'none'],
    'rvol_min'    : [2.0, 3.0, 4.0, 5.0],
    'mfi_min'     : [50, 55, 60, 0],
    'obv_bars'    : [3, 5, 0],
    'session'     : ['or_only', 'early', 'all_day'],
    'direction'   : ['call_only', 'put_only', 'both'],
}

# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA DETECTION
# ═══════════════════════════════════════════════════════════════════════════

BAR_TABLE_CANDIDATES = [
    'intraday_bars_5m',
    'intraday_bars',
    'candle_cache',
    'bars',
    'candles',
    'ohlcv',
]


def detect_schema(conn: sqlite3.Connection) -> dict:
    """
    Auto-detect the bar table and column names.
    Returns a schema dict with keys: table, ticker, dt, open, high, low, close, volume
    """
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}

    for candidate in BAR_TABLE_CANDIDATES:
        if candidate not in tables:
            continue

        cur.execute(f'PRAGMA table_info({candidate})')
        cols = [r[1] for r in cur.fetchall()]

        ticker_col = next((c for c in cols if c.lower() in ('ticker','symbol','sym')), None)
        dt_col     = next((c for c in cols if c.lower() in ('datetime','timestamp','ts','date','time')), None)

        def fc(*names):
            return next((c for c in cols if c.lower() in names), None)

        o = fc('open','o')
        h = fc('high','h')
        l = fc('low','l')
        c = fc('close','c','price')
        v = fc('volume','vol','v')

        if not all([ticker_col, dt_col, o, h, l, c, v]):
            # Check row count — skip empty tables
            cur.execute(f'SELECT COUNT(*) FROM {candidate}')
            n = cur.fetchone()[0]
            if n == 0:
                continue
            print(f'  ⚠️  {candidate} has {n:,} rows but missing columns: '
                  f'ticker={ticker_col} dt={dt_col} O={o} H={h} L={l} C={c} V={v}')
            continue

        # Verify it has actual rows
        cur.execute(f'SELECT COUNT(*) FROM {candidate}')
        if cur.fetchone()[0] == 0:
            continue

        schema = dict(table=candidate, ticker=ticker_col, dt=dt_col,
                      open=o, high=h, low=l, close=c, volume=v)
        print(f'  Detected table  : {candidate}')
        print(f'  Columns         : {schema}')
        return schema

    raise RuntimeError(
        'No usable bar table with OHLCV data found in market_memory.db.\n'
        f'  Tables present: {sorted(tables)}\n'
        '  Row counts:'
    )


def load_schema_from_txt(txt_path: str) -> dict:
    """Parse schema metadata written by 01_fetch_candles.py."""
    schema = {}
    with open(txt_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, val = line[1:].split('=', 1)
            key = key.strip()
            val = val.strip()
            if key == 'bar_table':
                schema['table'] = val
            elif key == 'ticker_col':
                schema['ticker'] = val
            elif key == 'dt_col':
                schema['dt'] = val
            elif key == 'ohlcv':
                parts = val.split(',')
                if len(parts) == 5:
                    schema['open'], schema['high'], schema['low'], schema['close'], schema['volume'] = parts
    return schema if len(schema) == 8 else {}


# ═══════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

def open_source_db() -> sqlite3.Connection:
    for path in [
        'market_memory.db',
        os.path.join(os.path.dirname(__file__), '../../../market_memory.db'),
    ]:
        if os.path.exists(path):
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
    raise FileNotFoundError('market_memory.db not found. Run the main scanner first.')


def open_results_db(out_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(out_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            combo_key       TEXT NOT NULL,
            bos_strength    REAL,
            tf_confirm      TEXT,
            vwap_zone       TEXT,
            rvol_min        REAL,
            mfi_min         INTEGER,
            obv_bars        INTEGER,
            session         TEXT,
            direction       TEXT,
            total_trades    INTEGER,
            wins            INTEGER,
            losses          INTEGER,
            win_rate        REAL,
            avg_r           REAL,
            total_r         REAL,
            score           REAL,
            tickers_used    TEXT,
            created_at      TEXT
        )
    """)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_score    ON results(score DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_win_rate ON results(win_rate DESC)')
    conn.commit()
    return conn


def load_all_bars(
    src_conn  : sqlite3.Connection,
    schema    : dict,
    days_back : int = 90,
) -> Dict[str, List[Dict]]:
    """Load all cached bars into memory once, grouped by ticker."""
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')

    T  = schema['table']
    tk = schema['ticker']
    dt = schema['dt']
    o  = schema['open']
    h  = schema['high']
    l  = schema['low']
    c  = schema['close']
    v  = schema['volume']

    cur = src_conn.cursor()
    cur.execute(f"""
        SELECT {tk}, {dt}, {o}, {h}, {l}, {c}, {v}
        FROM   {T}
        WHERE  {dt} >= ?
        ORDER  BY {tk}, {dt}
    """, (cutoff,))

    ticker_bars: Dict[str, List[Dict]] = {}
    skipped = 0
    for row in cur.fetchall():
        ticker = row[0]
        dt_raw = row[1]
        try:
            if isinstance(dt_raw, str):
                bar_dt = datetime.fromisoformat(dt_raw).replace(tzinfo=None)
            else:
                bar_dt = dt_raw
        except Exception:
            skipped += 1
            continue

        try:
            bar = {
                'dt'    : bar_dt,
                'open'  : float(row[2]),
                'high'  : float(row[3]),
                'low'   : float(row[4]),
                'close' : float(row[5]),
                'volume': int(float(row[6])),
            }
        except (TypeError, ValueError):
            skipped += 1
            continue

        ticker_bars.setdefault(ticker, []).append(bar)

    total_bars = sum(len(v) for v in ticker_bars.values())
    print(f'  Table           : {T}')
    print(f'  Bars loaded     : {total_bars:,}  across {len(ticker_bars)} tickers')
    print(f'  Skipped rows    : {skipped}')
    print(f'  Date cutoff     : {cutoff}')
    if skipped > 0:
        print(f'  ⚠️  {skipped} rows had unparseable datetime or OHLCV values')
    return ticker_bars


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def calc_vwap_bands(bars):
    if not bars:
        return 0.0, 0.0, 0.0
    tp_vol  = sum(((b['high']+b['low']+b['close'])/3) * b['volume'] for b in bars)
    tot_vol = sum(b['volume'] for b in bars)
    vwap    = tp_vol / tot_vol if tot_vol else bars[-1]['close']
    variance = sum((((b['high']+b['low']+b['close'])/3) - vwap)**2 * b['volume'] for b in bars)
    variance /= tot_vol if tot_vol else 1
    sd = variance**0.5
    return vwap, vwap + sd, vwap - sd


def calc_mfi(bars, period=14):
    if len(bars) < period + 1:
        return 50.0
    recent = bars[-(period+1):]
    tps = [(b['high']+b['low']+b['close'])/3 for b in recent]
    mfs = [tps[i]*recent[i]['volume'] for i in range(len(recent))]
    pos = sum(mfs[i] for i in range(1, len(mfs)) if tps[i] > tps[i-1])
    neg = sum(mfs[i] for i in range(1, len(mfs)) if tps[i] < tps[i-1])
    return 100.0 if neg == 0 else 100 - (100 / (1 + pos/neg))


def calc_obv_trend(bars, lookback=5):
    if len(bars) < lookback + 1:
        return 0.0
    recent = bars[-(lookback+1):]
    obv = 0.0
    obvs = []
    for i in range(1, len(recent)):
        if recent[i]['close'] > recent[i-1]['close']:
            obv += recent[i]['volume']
        elif recent[i]['close'] < recent[i-1]['close']:
            obv -= recent[i]['volume']
        obvs.append(obv)
    return (obvs[-1] - obvs[0]) if len(obvs) >= 2 else 0.0


def calc_rvol(bars, lookback=20):
    if len(bars) < lookback + 1:
        return 1.0
    avg = sum(b['volume'] for b in bars[-(lookback+1):-1]) / lookback
    return bars[-1]['volume'] / avg if avg > 0 else 1.0


def calc_atr(bars, period=14):
    if len(bars) < period + 1:
        return bars[-1]['close'] * 0.01 if bars else 1.0
    trs = [
        max(bars[i]['high'] - bars[i]['low'],
            abs(bars[i]['high'] - bars[i-1]['close']),
            abs(bars[i]['low']  - bars[i-1]['close']))
        for i in range(1, len(bars))
    ]
    return sum(trs[-period:]) / period


# ═══════════════════════════════════════════════════════════════════════════
# SESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def is_or_session(dt):    return dt.hour == 9 and 30 <= dt.minute < 60
def is_early_session(dt): return (dt.hour == 9 and dt.minute >= 30) or dt.hour == 10
def is_rth(dt):           return not (dt.hour < 9 or (dt.hour == 9 and dt.minute < 30) or dt.hour >= 16)


def compress_to_tf(bars_input, tf_minutes):
    if tf_minutes <= 1:
        return bars_input
    compressed, bucket = [], []
    for b in bars_input:
        bucket.append(b)
        if len(bucket) >= tf_minutes:
            compressed.append({
                'dt'    : bucket[0]['dt'],
                'open'  : bucket[0]['open'],
                'high'  : max(x['high']  for x in bucket),
                'low'   : min(x['low']   for x in bucket),
                'close' : bucket[-1]['close'],
                'volume': sum(x['volume'] for x in bucket),
            })
            bucket = []
    return compressed


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def detect_bos(bars, idx, strength_threshold, lookback=20):
    if idx < lookback or idx >= len(bars):
        return None
    window     = bars[idx-lookback:idx]
    swing_high = max(b['high'] for b in window)
    swing_low  = min(b['low']  for b in window)
    c = bars[idx]['close']
    if c > swing_high and (c - swing_high) / swing_high >= strength_threshold:
        return 'bull'
    if c < swing_low  and (swing_low - c)  / swing_low  >= strength_threshold:
        return 'bear'
    return None


def detect_fvg(bars, idx):
    if idx < 2 or idx >= len(bars):
        return None
    if bars[idx-2]['high'] < bars[idx]['low']:
        return 'bull'
    if bars[idx-2]['low']  > bars[idx]['high']:
        return 'bear'
    return None


# ═══════════════════════════════════════════════════════════════════════════
# FILTER APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

def signal_passes_combo(raw_dir, idx, bars_rth, session_bars, params):
    direction = params['direction']
    if direction == 'call_only' and raw_dir != 'bull': return False
    if direction == 'put_only'  and raw_dir != 'bear': return False

    dt   = bars_rth[idx]['dt']
    sess = params['session']
    if sess == 'or_only' and not is_or_session(dt):   return False
    if sess == 'early'   and not is_early_session(dt): return False

    bars_so_far = bars_rth[:idx+1]

    if calc_rvol(bars_so_far) < params['rvol_min']:
        return False

    if params['mfi_min'] > 0:
        mfi = calc_mfi(bars_so_far)
        if raw_dir == 'bull' and mfi < params['mfi_min']:         return False
        if raw_dir == 'bear' and mfi > (100 - params['mfi_min']): return False

    if params['obv_bars'] > 0:
        slope = calc_obv_trend(bars_so_far, params['obv_bars'])
        if raw_dir == 'bull' and slope <= 0: return False
        if raw_dir == 'bear' and slope >= 0: return False

    vzone = params['vwap_zone']
    if vzone != 'none' and session_bars:
        vwap, upper_1sd, lower_1sd = calc_vwap_bands(session_bars)
        price = bars_rth[idx]['close']
        if vzone == 'above_vwap':
            if raw_dir == 'bull' and price <= vwap:       return False
            if raw_dir == 'bear' and price >= vwap:       return False
        elif vzone == 'above_1sd':
            if raw_dir == 'bull' and price <= upper_1sd:  return False
            if raw_dir == 'bear' and price >= lower_1sd:  return False

    tf = params['tf_confirm']
    if tf != '1m':
        tf_map = {'3m':[3], '5m':[5], '5m_3m':[5,3], '5m_3m_1m':[5,3]}
        window = bars_rth[max(0, idx-100):idx+1]
        for tf_min in tf_map.get(tf, []):
            compressed = compress_to_tf(window, tf_min)
            if len(compressed) < 3:
                return False
            c_dir = detect_bos(compressed, len(compressed)-1,
                               params['bos_strength'], lookback=min(10, len(compressed)-1))
            if c_dir is None:
                fvg = detect_fvg(compressed, len(compressed)-1)
                if fvg != raw_dir:
                    return False
            elif c_dir != raw_dir:
                return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════

def simulate_outcome(bars, entry_idx, direction, atr_mult=1.5, max_bars=30):
    entry_price = bars[entry_idx]['close']
    risk = calc_atr(bars[:entry_idx+1]) * atr_mult
    if risk <= 0:
        return 0.0
    if direction == 'bull':
        stop, t1, t2 = entry_price-risk, entry_price+risk, entry_price+risk*2
    else:
        stop, t1, t2 = entry_price+risk, entry_price-risk, entry_price-risk*2

    for bar in bars[entry_idx+1: entry_idx+1+max_bars]:
        h, l = bar['high'], bar['low']
        if direction == 'bull':
            if l <= stop: return -1.0
            if h >= t2:   return  2.0
            if h >= t1:   return  1.0
        else:
            if h >= stop: return -1.0
            if l <= t2:   return  2.0
            if l <= t1:   return  1.0

    future = bars[entry_idx+1: entry_idx+1+max_bars]
    last   = future[-1]['close'] if future else entry_price
    return (last - entry_price) / risk if direction == 'bull' else (entry_price - last) / risk


# ═══════════════════════════════════════════════════════════════════════════
# COMBO EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_combo(params, ticker_bars, tickers, min_trades=15):
    all_rs: List[float] = []
    used_tickers: List[str] = []

    for ticker in tickers:
        bars = ticker_bars.get(ticker, [])
        if len(bars) < 100:
            continue

        day_buckets: Dict[date, List[Dict]] = {}
        for b in bars:
            day_buckets.setdefault(b['dt'].date(), []).append(b)

        ticker_rs: List[float] = []

        for day_bars in day_buckets.values():
            rth = sorted([b for b in day_bars if is_rth(b['dt'])], key=lambda x: x['dt'])
            if len(rth) < 30:
                continue

            for idx in range(20, len(rth) - 5):
                bos_dir = detect_bos(rth, idx, params['bos_strength'])
                fvg_dir = detect_fvg(rth, idx)

                signal_dir = None
                if bos_dir and fvg_dir and bos_dir == fvg_dir:
                    signal_dir = bos_dir
                elif bos_dir:
                    signal_dir = bos_dir

                if signal_dir is None:
                    continue

                session_bars = rth[:idx+1]
                if not signal_passes_combo(signal_dir, idx, rth, session_bars, params):
                    continue

                r = simulate_outcome(rth, idx, signal_dir)
                ticker_rs.append(r)

        if ticker_rs:
            all_rs.extend(ticker_rs)
            used_tickers.append(ticker)

    if len(all_rs) < min_trades:
        return None

    wins     = sum(1 for r in all_rs if r > 0)
    win_rate = wins / len(all_rs)
    avg_r    = sum(all_rs) / len(all_rs)
    total_r  = sum(all_rs)
    score    = win_rate * max(avg_r, 0)

    return {
        'total_trades': len(all_rs),
        'wins'        : wins,
        'losses'      : len(all_rs) - wins,
        'win_rate'    : round(win_rate, 4),
        'avg_r'       : round(avg_r,    4),
        'total_r'     : round(total_r,  4),
        'score'       : round(score,    4),
        'tickers_used': ','.join(used_tickers),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_campaign(tickers, days_back=90, min_trades=15, out_path=None):
    if out_path is None:
        out_path = os.path.join(os.path.dirname(__file__), 'campaign_results.db')

    print('='*72)
    print('WAR MACHINE — FULL BACKTEST CAMPAIGN')
    print('='*72)
    print(f'Tickers      : {len(tickers)}')
    print(f'Days back    : {days_back}')
    print(f'Min trades   : {min_trades}')
    print(f'Results DB   : {out_path}')
    print()

    print('[1/3] Loading cached bar data...')
    src_conn = open_source_db()
    schema   = detect_schema(src_conn)
    ticker_bars = load_all_bars(src_conn, schema, days_back)
    src_conn.close()
    print()

    available = [t for t in tickers if t in ticker_bars]
    if not available:
        # If requested tickers not found, use whatever is in the DB
        available = list(ticker_bars.keys())
        if not available:
            print('❌  No bar data found in market_memory.db.')
            print('   Run 01_fetch_candles.py to diagnose the database.')
            return
        print(f'⚠️  Requested tickers not in DB — using all {len(available)} available tickers.')

    print(f'  Running on {len(available)} tickers: {available}')
    print()

    keys   = list(GRID.keys())
    values = [GRID[k] for k in keys]
    combos = list(product(*values))
    total  = len(combos)
    print(f'[2/3] Running {total:,} parameter combinations...')
    print()

    res_conn   = open_results_db(out_path)
    start_time = time.time()
    saved = skipped = 0
    batch: List[Tuple] = []
    BATCH_SIZE = 500

    for i, combo_vals in enumerate(combos):
        params    = dict(zip(keys, combo_vals))
        combo_key = '|'.join(f'{k}={v}' for k, v in params.items())
        result    = evaluate_combo(params, ticker_bars, available, min_trades)

        if result:
            batch.append((
                combo_key,
                params['bos_strength'], params['tf_confirm'], params['vwap_zone'],
                params['rvol_min'],     params['mfi_min'],    params['obv_bars'],
                params['session'],      params['direction'],
                result['total_trades'], result['wins'],       result['losses'],
                result['win_rate'],     result['avg_r'],      result['total_r'],
                result['score'],        result['tickers_used'],
                datetime.now(ET).isoformat(),
            ))
            saved += 1
        else:
            skipped += 1

        if len(batch) >= BATCH_SIZE:
            res_conn.executemany("""
                INSERT INTO results (
                    combo_key,bos_strength,tf_confirm,vwap_zone,
                    rvol_min,mfi_min,obv_bars,session,direction,
                    total_trades,wins,losses,win_rate,avg_r,
                    total_r,score,tickers_used,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, batch)
            res_conn.commit()
            batch = []

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate    = (i + 1) / elapsed
            eta_s   = (total - i - 1) / rate if rate > 0 else 0
            print(f'  {(i+1)/total*100:5.1f}%  {i+1:>7}/{total}  '
                  f'saved={saved:<6} skipped={skipped:<6}  '
                  f'ETA {int(eta_s//60)}m{int(eta_s%60):02d}s')

    if batch:
        res_conn.executemany("""
            INSERT INTO results (
                combo_key,bos_strength,tf_confirm,vwap_zone,
                rvol_min,mfi_min,obv_bars,session,direction,
                total_trades,wins,losses,win_rate,avg_r,
                total_r,score,tickers_used,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
        res_conn.commit()

    elapsed = time.time() - start_time
    print()
    print('[3/3] Campaign complete!')
    print(f'  Elapsed      : {int(elapsed//60)}m {int(elapsed%60):02d}s')
    print(f'  Total combos : {total:,}')
    print(f'  Saved        : {saved:,}')
    print(f'  Skipped      : {skipped:,}  (< {min_trades} trades)')
    print(f'  Results DB   : {out_path}')
    print()
    print('✅  Run 03_analyze_results.py to see the leaderboard.')
    res_conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers',    type=str, default=None)
    parser.add_argument('--days',       type=int, default=90)
    parser.add_argument('--min-trades', type=int, default=15)
    parser.add_argument('--out',        type=str, default=None)
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    else:
        txt_path = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                tickers = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            print(f'Loaded {len(tickers)} tickers from usable_tickers.txt')
        else:
            tickers = ['AAPL','NVDA','TSLA','SPY','QQQ','AMZN','MSFT','META','GOOGL','AMD',
                       'MRVL','HIMS','VRT','AVGO','ORCL']
            print(f'usable_tickers.txt not found — using {len(tickers)} default tickers')

    run_campaign(
        tickers    = tickers,
        days_back  = args.days,
        min_trades = args.min_trades,
        out_path   = args.out,
    )
