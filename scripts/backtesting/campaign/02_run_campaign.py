#!/usr/bin/env python3
"""
02_run_campaign.py  —  Full Backtest Campaign Engine
=====================================================
Exhaustively tests every combination of indicators against
cached bar data.

Usage:
    python scripts/backtesting/campaign/02_run_campaign.py
    python scripts/backtesting/campaign/02_run_campaign.py --db scripts/backtesting/campaign/campaign_data.db
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


def resolve_db_path(arg_db=None):
    """Find the SQLite DB to use, in priority order."""
    if arg_db and os.path.exists(arg_db):
        return arg_db
    # Check usable_tickers.txt for db_path written by 01_fetch_candles
    txt = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
    if os.path.exists(txt):
        with open(txt) as f:
            for line in f:
                if line.startswith('# db_path='):
                    p = line.split('=', 1)[1].strip()
                    if os.path.exists(p):
                        return p
    # Fallback candidates
    for p in [
        os.path.join(os.path.dirname(__file__), 'campaign_data.db'),
        os.path.join(os.path.dirname(__file__), '../../../market_memory.db'),
        'market_memory.db',
    ]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        'No bar database found. Run 00_export_from_railway.py first, '
        'or pass --db <path>.'
    )


def detect_schema(conn):
    BAR_TABLE_CANDIDATES = ['intraday_bars_5m','intraday_bars','bars','candles','ohlcv']
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    for candidate in BAR_TABLE_CANDIDATES:
        if candidate not in tables:
            continue
        cur.execute(f'PRAGMA table_info({candidate})')
        cols = [r[1] for r in cur.fetchall()]
        def fc(*n): return next((c for c in cols if c.lower() in n), None)
        tk = fc('ticker','symbol','sym')
        dt = fc('datetime','timestamp','ts','date','time')
        o, h, l, c, v = fc('open','o'), fc('high','h'), fc('low','l'), fc('close','c','price'), fc('volume','vol','v')
        if not all([tk, dt, o, h, l, c, v]):
            continue
        cur.execute(f'SELECT COUNT(*) FROM {candidate}')
        if cur.fetchone()[0] == 0:
            continue
        schema = dict(table=candidate, ticker=tk, dt=dt, open=o, high=h, low=l, close=c, volume=v)
        print(f'  Schema: {schema}')
        return schema
    raise RuntimeError(f'No usable bar table found. Tables: {sorted(tables)}')


def load_schema_from_txt(txt_path):
    schema = {}
    with open(txt_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith('#') or '=' not in line:
                continue
            key, val = line[1:].split('=', 1)
            key, val = key.strip(), val.strip()
            if key == 'bar_table':  schema['table']  = val
            elif key == 'ticker_col': schema['ticker'] = val
            elif key == 'dt_col':    schema['dt']     = val
            elif key == 'ohlcv':
                p = val.split(',')
                if len(p) == 5:
                    schema['open'], schema['high'], schema['low'], schema['close'], schema['volume'] = p
    return schema if len(schema) >= 7 else {}


def open_results_db(out_path):
    conn = sqlite3.connect(out_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            combo_key TEXT, bos_strength REAL, tf_confirm TEXT,
            vwap_zone TEXT, rvol_min REAL, mfi_min INTEGER, obv_bars INTEGER,
            session TEXT, direction TEXT, total_trades INTEGER,
            wins INTEGER, losses INTEGER, win_rate REAL, avg_r REAL,
            total_r REAL, score REAL, tickers_used TEXT, created_at TEXT
        )
    """)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_score    ON results(score DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_win_rate ON results(win_rate DESC)')
    conn.commit()
    return conn


def load_all_bars(src_conn, schema, days_back=90):
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    T, tk = schema['table'], schema['ticker']
    dt, o, h, l, c, v = schema['dt'], schema['open'], schema['high'], schema['low'], schema['close'], schema['volume']
    cur = src_conn.cursor()
    cur.execute(f"""
        SELECT {tk},{dt},{o},{h},{l},{c},{v}
        FROM {T} WHERE {dt} >= ? ORDER BY {tk},{dt}
    """, (cutoff,))
    ticker_bars: Dict[str, List[Dict]] = {}
    skipped = 0
    for row in cur.fetchall():
        try:
            dt_raw = row[1]
            bar_dt = datetime.fromisoformat(dt_raw).replace(tzinfo=None) if isinstance(dt_raw, str) else dt_raw
            bar = {'dt': bar_dt, 'open': float(row[2]), 'high': float(row[3]),
                   'low': float(row[4]), 'close': float(row[5]), 'volume': int(float(row[6]))}
            ticker_bars.setdefault(row[0], []).append(bar)
        except Exception:
            skipped += 1
    total = sum(len(v) for v in ticker_bars.values())
    print(f'  Loaded {total:,} bars across {len(ticker_bars)} tickers (since {cutoff})')
    if skipped: print(f'  ⚠️  Skipped {skipped} unparseable rows')
    return ticker_bars


# ═══ INDICATORS ═══

def calc_vwap_bands(bars):
    if not bars: return 0.0, 0.0, 0.0
    tp_vol  = sum(((b['high']+b['low']+b['close'])/3)*b['volume'] for b in bars)
    tot_vol = sum(b['volume'] for b in bars)
    vwap    = tp_vol/tot_vol if tot_vol else bars[-1]['close']
    var     = sum((((b['high']+b['low']+b['close'])/3)-vwap)**2*b['volume'] for b in bars)
    sd      = (var/tot_vol)**0.5 if tot_vol else 0
    return vwap, vwap+sd, vwap-sd

def calc_mfi(bars, period=14):
    if len(bars) < period+1: return 50.0
    r = bars[-(period+1):]
    tps = [(b['high']+b['low']+b['close'])/3 for b in r]
    mfs = [tps[i]*r[i]['volume'] for i in range(len(r))]
    pos = sum(mfs[i] for i in range(1,len(mfs)) if tps[i]>tps[i-1])
    neg = sum(mfs[i] for i in range(1,len(mfs)) if tps[i]<tps[i-1])
    return 100.0 if neg==0 else 100-(100/(1+pos/neg))

def calc_obv_trend(bars, lookback=5):
    if len(bars)<lookback+1: return 0.0
    r=bars[-(lookback+1):]; obv=0.0; obvs=[]
    for i in range(1,len(r)):
        obv += r[i]['volume'] if r[i]['close']>r[i-1]['close'] else (-r[i]['volume'] if r[i]['close']<r[i-1]['close'] else 0)
        obvs.append(obv)
    return (obvs[-1]-obvs[0]) if len(obvs)>=2 else 0.0

def calc_rvol(bars, lookback=20):
    if len(bars)<lookback+1: return 1.0
    avg=sum(b['volume'] for b in bars[-(lookback+1):-1])/lookback
    return bars[-1]['volume']/avg if avg>0 else 1.0

def calc_atr(bars, period=14):
    if len(bars)<period+1: return bars[-1]['close']*0.01 if bars else 1.0
    trs=[max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-bars[i-1]['close']),abs(bars[i]['low']-bars[i-1]['close'])) for i in range(1,len(bars))]
    return sum(trs[-period:])/period

# ═══ SESSION ═══

def is_or_session(dt):    return dt.hour==9 and 30<=dt.minute<60
def is_early_session(dt): return (dt.hour==9 and dt.minute>=30) or dt.hour==10
def is_rth(dt):           return not(dt.hour<9 or (dt.hour==9 and dt.minute<30) or dt.hour>=16)

def compress_to_tf(bars, tf):
    if tf<=1: return bars
    out,bkt=[],[]
    for b in bars:
        bkt.append(b)
        if len(bkt)>=tf:
            out.append({'dt':bkt[0]['dt'],'open':bkt[0]['open'],'high':max(x['high'] for x in bkt),'low':min(x['low'] for x in bkt),'close':bkt[-1]['close'],'volume':sum(x['volume'] for x in bkt)})
            bkt=[]
    return out

# ═══ SIGNALS ═══

def detect_bos(bars, idx, thr, lookback=20):
    if idx<lookback or idx>=len(bars): return None
    w=bars[idx-lookback:idx]; sh=max(b['high'] for b in w); sl=min(b['low'] for b in w); c=bars[idx]['close']
    if c>sh and (c-sh)/sh>=thr: return 'bull'
    if c<sl and (sl-c)/sl>=thr: return 'bear'
    return None

def detect_fvg(bars, idx):
    if idx<2 or idx>=len(bars): return None
    if bars[idx-2]['high']<bars[idx]['low']:  return 'bull'
    if bars[idx-2]['low'] >bars[idx]['high']: return 'bear'
    return None

# ═══ FILTER ═══

def signal_passes_combo(raw_dir, idx, rth, sess_bars, p):
    if p['direction']=='call_only' and raw_dir!='bull': return False
    if p['direction']=='put_only'  and raw_dir!='bear': return False
    dt=rth[idx]['dt']
    if p['session']=='or_only' and not is_or_session(dt):   return False
    if p['session']=='early'   and not is_early_session(dt): return False
    bf=rth[:idx+1]
    if calc_rvol(bf)<p['rvol_min']: return False
    if p['mfi_min']>0:
        mfi=calc_mfi(bf)
        if raw_dir=='bull' and mfi<p['mfi_min']:          return False
        if raw_dir=='bear' and mfi>(100-p['mfi_min']):    return False
    if p['obv_bars']>0:
        s=calc_obv_trend(bf,p['obv_bars'])
        if raw_dir=='bull' and s<=0: return False
        if raw_dir=='bear' and s>=0: return False
    vz=p['vwap_zone']
    if vz!='none' and sess_bars:
        vwap,u1,l1=calc_vwap_bands(sess_bars); pr=rth[idx]['close']
        if vz=='above_vwap':
            if raw_dir=='bull' and pr<=vwap: return False
            if raw_dir=='bear' and pr>=vwap: return False
        elif vz=='above_1sd':
            if raw_dir=='bull' and pr<=u1: return False
            if raw_dir=='bear' and pr>=l1: return False
    tf=p['tf_confirm']
    if tf!='1m':
        tf_map={'3m':[3],'5m':[5],'5m_3m':[5,3],'5m_3m_1m':[5,3]}
        win=rth[max(0,idx-100):idx+1]
        for tfm in tf_map.get(tf,[]):
            comp=compress_to_tf(win,tfm)
            if len(comp)<3: return False
            cd=detect_bos(comp,len(comp)-1,p['bos_strength'],lookback=min(10,len(comp)-1))
            if cd is None:
                if detect_fvg(comp,len(comp)-1)!=raw_dir: return False
            elif cd!=raw_dir: return False
    return True

# ═══ SIMULATION ═══

def simulate_outcome(bars, idx, direction, atr_mult=1.5, max_bars=30):
    ep=bars[idx]['close']; risk=calc_atr(bars[:idx+1])*atr_mult
    if risk<=0: return 0.0
    if direction=='bull': stop,t1,t2=ep-risk,ep+risk,ep+risk*2
    else:                 stop,t1,t2=ep+risk,ep-risk,ep-risk*2
    for b in bars[idx+1:idx+1+max_bars]:
        h,l=b['high'],b['low']
        if direction=='bull':
            if l<=stop: return -1.0
            if h>=t2:   return  2.0
            if h>=t1:   return  1.0
        else:
            if h>=stop: return -1.0
            if l<=t2:   return  2.0
            if l<=t1:   return  1.0
    future=bars[idx+1:idx+1+max_bars]
    last=future[-1]['close'] if future else ep
    return (last-ep)/risk if direction=='bull' else (ep-last)/risk

# ═══ COMBO EVAL ═══

def evaluate_combo(params, ticker_bars, tickers, min_trades=15):
    all_rs=[]; used=[]
    for ticker in tickers:
        bars=ticker_bars.get(ticker,[])
        if len(bars)<50: continue
        day_buckets: Dict[date,List[Dict]]={}
        for b in bars: day_buckets.setdefault(b['dt'].date(),[]).append(b)
        tr=[]
        for db in day_buckets.values():
            rth=sorted([b for b in db if is_rth(b['dt'])],key=lambda x:x['dt'])
            if len(rth)<20: continue
            for idx in range(15,len(rth)-3):
                bd=detect_bos(rth,idx,params['bos_strength'])
                fd=detect_fvg(rth,idx)
                sd=bd if bd and (not fd or fd==bd) else None
                if not sd: continue
                if not signal_passes_combo(sd,idx,rth,rth[:idx+1],params): continue
                tr.append(simulate_outcome(rth,idx,sd))
        if tr: all_rs.extend(tr); used.append(ticker)
    if len(all_rs)<min_trades: return None
    wins=sum(1 for r in all_rs if r>0)
    wr=wins/len(all_rs); ar=sum(all_rs)/len(all_rs)
    return {'total_trades':len(all_rs),'wins':wins,'losses':len(all_rs)-wins,
            'win_rate':round(wr,4),'avg_r':round(ar,4),'total_r':round(sum(all_rs),4),
            'score':round(wr*max(ar,0),4),'tickers_used':','.join(used)}

# ═══ CAMPAIGN ═══

def run_campaign(tickers, days_back=90, min_trades=15, out_path=None, db_path=None):
    if out_path is None:
        out_path = os.path.join(os.path.dirname(__file__), 'campaign_results.db')

    print('='*72)
    print('WAR MACHINE — FULL BACKTEST CAMPAIGN')
    print('='*72)
    print(f'Tickers    : {len(tickers)}')
    print(f'Days back  : {days_back}')
    print(f'Min trades : {min_trades}')
    print(f'Source DB  : {db_path}')
    print(f'Results DB : {out_path}')
    print()

    print('[1/3] Loading bar data...')
    src_conn = sqlite3.connect(db_path)
    src_conn.row_factory = sqlite3.Row
    schema = detect_schema(src_conn)
    ticker_bars = load_all_bars(src_conn, schema, days_back)
    src_conn.close()
    print()

    available = [t for t in tickers if t in ticker_bars]
    if not available:
        available = list(ticker_bars.keys())
        if not available:
            print('❌  No bar data found.')
            return
        print(f'⚠️  Requested tickers not in DB — using all {len(available)} available.')
    print(f'  Running on {len(available)} tickers')
    print()

    keys   = list(GRID.keys())
    combos = list(product(*[GRID[k] for k in keys]))
    total  = len(combos)
    print(f'[2/3] Testing {total:,} combinations...')
    print()

    res_conn   = open_results_db(out_path)
    start      = time.time()
    saved=skipped=0
    batch: List[Tuple]=[]

    for i, vals in enumerate(combos):
        params    = dict(zip(keys,vals))
        combo_key = '|'.join(f'{k}={v}' for k,v in params.items())
        result    = evaluate_combo(params, ticker_bars, available, min_trades)

        if result:
            batch.append((
                combo_key, params['bos_strength'], params['tf_confirm'], params['vwap_zone'],
                params['rvol_min'], params['mfi_min'], params['obv_bars'],
                params['session'], params['direction'],
                result['total_trades'], result['wins'], result['losses'],
                result['win_rate'], result['avg_r'], result['total_r'],
                result['score'], result['tickers_used'], datetime.now(ET).isoformat(),
            ))
            saved+=1
        else:
            skipped+=1

        if len(batch)>=500:
            res_conn.executemany("""
                INSERT INTO results (combo_key,bos_strength,tf_confirm,vwap_zone,
                rvol_min,mfi_min,obv_bars,session,direction,total_trades,wins,losses,
                win_rate,avg_r,total_r,score,tickers_used,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, batch)
            res_conn.commit(); batch=[]

        if (i+1)%500==0:
            el=time.time()-start; rate=(i+1)/el; eta=(total-i-1)/rate if rate else 0
            print(f'  {(i+1)/total*100:5.1f}%  {i+1:>7}/{total}  saved={saved}  ETA {int(eta//60)}m{int(eta%60):02d}s')

    if batch:
        res_conn.executemany("""
            INSERT INTO results (combo_key,bos_strength,tf_confirm,vwap_zone,
            rvol_min,mfi_min,obv_bars,session,direction,total_trades,wins,losses,
            win_rate,avg_r,total_r,score,tickers_used,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
        res_conn.commit()

    el=time.time()-start
    print(f'\n[3/3] Done!  {int(el//60)}m{int(el%60):02d}s  saved={saved:,}  skipped={skipped:,}')
    print(f'Results: {out_path}')
    print('✅  Run 03_analyze_results.py to see the leaderboard.')
    res_conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',         type=str, default=None)
    parser.add_argument('--tickers',    type=str, default=None)
    parser.add_argument('--days',       type=int, default=90)
    parser.add_argument('--min-trades', type=int, default=15)
    parser.add_argument('--out',        type=str, default=None)
    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    print(f'Source DB: {db_path}')

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    else:
        txt = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
        if os.path.exists(txt):
            with open(txt) as f:
                tickers = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            print(f'Loaded {len(tickers)} tickers from usable_tickers.txt')
        else:
            tickers = ['AAPL','NVDA','TSLA','SPY','QQQ','AMZN','MSFT','META',
                       'GOOGL','AMD','MRVL','HIMS','VRT','AVGO','ORCL']
            print(f'No usable_tickers.txt — using {len(tickers)} defaults')

    run_campaign(
        tickers    = tickers,
        days_back  = args.days,
        min_trades = args.min_trades,
        out_path   = args.out,
        db_path    = db_path,
    )
