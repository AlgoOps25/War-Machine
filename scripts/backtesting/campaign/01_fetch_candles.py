#!/usr/bin/env python3
"""
01_fetch_candles.py  —  Campaign Data Audit
============================================
Audits a bar database to show what 5m data is cached,
which tickers have enough history, and date ranges available.

Default DB: market_memory.db
For Railway export workflow, pass --db campaign_data.db

Usage:
    python scripts/backtesting/campaign/01_fetch_candles.py
    python scripts/backtesting/campaign/01_fetch_candles.py --db scripts/backtesting/campaign/campaign_data.db
"""

import sys
import os
import sqlite3
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
MIN_BARS = 100   # lowered: 117 tickers with 28k total bars means ~242 bars avg
MIN_DAYS = 5

BAR_TABLE_CANDIDATES = [
    'intraday_bars_5m',
    'intraday_bars',
    'candle_cache',
    'bars',
    'candles',
    'ohlcv',
]


def inspect_columns(cur, table):
    cur.execute(f'PRAGMA table_info({table})')
    return [r[1] for r in cur.fetchall()]


def find_bar_table(cur, tables):
    for candidate in BAR_TABLE_CANDIDATES:
        if candidate not in tables:
            continue
        cols = inspect_columns(cur, candidate)
        ticker_col = next((c for c in cols if c.lower() in ('ticker','symbol','sym')), None)
        dt_col     = next((c for c in cols if c.lower() in ('datetime','timestamp','ts','date','time')), None)
        def fc(*n): return next((c for c in cols if c.lower() in n), None)
        o, h, l, c, v = fc('open','o'), fc('high','h'), fc('low','l'), fc('close','c','price'), fc('volume','vol','v')
        if not all([ticker_col, dt_col, o, h, l, c, v]):
            continue
        cur.execute(f'SELECT COUNT(*) FROM {candidate}')
        if cur.fetchone()[0] == 0:
            continue
        return (candidate, ticker_col, dt_col, o, h, l, c, v, cols)
    raise RuntimeError(
        'No usable bar table found.\n'
        f'  Tables: {sorted(tables)}\n'
        '  Expected: ' + ', '.join(BAR_TABLE_CANDIDATES)
    )


def audit_database(db_path=None):
    # Resolve DB path
    if db_path is None:
        candidates = [
            os.path.join(os.path.dirname(__file__), '../../../market_memory.db'),
            'market_memory.db',
        ]
        db_path = next((p for p in candidates if os.path.exists(p)), None)
    if db_path is None or not os.path.exists(db_path):
        print(f'❌  DB not found: {db_path}')
        return []

    print('='*72)
    print('WAR MACHINE — BACKTEST CAMPAIGN DATA AUDIT')
    print('='*72)
    print(f'DB path : {os.path.abspath(db_path)}')
    print(f'DB size : {os.path.getsize(db_path)/1024/1024:.1f} MB')
    print(f'Run at  : {datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")}')
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0] for r in cur.fetchall()}
    print(f'Tables found: {sorted(tables)}')
    print()

    print('Row counts per candidate table:')
    for t in BAR_TABLE_CANDIDATES:
        if t in tables:
            cur.execute(f'SELECT COUNT(*) FROM {t}')
            print(f'  {t:<24} {cur.fetchone()[0]:>10,} rows')
    print()

    try:
        result = find_bar_table(cur, tables)
    except RuntimeError as e:
        print(f'❌  {e}')
        conn.close()
        return []

    bar_table, ticker_col, dt_col = result[0], result[1], result[2]
    o_col, h_col, l_col, c_col, v_col = result[3], result[4], result[5], result[6], result[7]

    print(f'Using table : {bar_table}')
    print(f'Columns     : ticker={ticker_col}  dt={dt_col}  O={o_col}  H={h_col}  L={l_col}  C={c_col}  V={v_col}')
    print()

    cur.execute(f"""
        SELECT
            {ticker_col}                       AS ticker,
            COUNT(*)                           AS total_bars,
            MIN({dt_col})                      AS earliest,
            MAX({dt_col})                      AS latest,
            COUNT(DISTINCT DATE({dt_col}))     AS trading_days
        FROM {bar_table}
        GROUP BY {ticker_col}
        ORDER BY total_bars DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f'❌  {bar_table} exists but has 0 rows.')
        return []

    print(f'Tickers in {bar_table}: {len(rows)}')
    print()

    usable, unusable = [], []
    header = f"{'Ticker':<8} {'Bars':>7} {'Days':>5}  {'Earliest':<12} {'Latest':<12}  Status"
    print(header)
    print('-' * len(header))

    for r in rows:
        ticker   = r['ticker']
        bars     = r['total_bars']
        days     = r['trading_days']
        earliest = str(r['earliest'])[:10] if r['earliest'] else 'N/A'
        latest   = str(r['latest'])[:10]   if r['latest']   else 'N/A'
        ok       = bars >= MIN_BARS and days >= MIN_DAYS
        status   = '✅ USABLE' if ok else f'⚠️  LOW ({bars} bars / {days} days)'
        print(f"{ticker:<8} {bars:>7} {days:>5}  {earliest:<12} {latest:<12}  {status}")
        (usable if ok else unusable).append(ticker)

    print()
    print(f'✅  Usable tickers   : {len(usable):>3}  — {usable[:20]}{" ..." if len(usable)>20 else ""}')
    print(f'⚠️   Too-thin tickers : {len(unusable):>3}')
    print()

    if not usable:
        print(f'❌  No tickers meet >= {MIN_BARS} bars / >= {MIN_DAYS} days.')
        print('   Lower MIN_BARS / MIN_DAYS at the top of this file if needed.')
    else:
        out_path = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
        with open(out_path, 'w') as f:
            f.write(f'# bar_table={bar_table}\n')
            f.write(f'# ticker_col={ticker_col}\n')
            f.write(f'# dt_col={dt_col}\n')
            f.write(f'# ohlcv={o_col},{h_col},{l_col},{c_col},{v_col}\n')
            f.write(f'# db_path={os.path.abspath(db_path)}\n')
            for t in usable:
                f.write(t + '\n')
        print(f'✅  Saved {len(usable)} usable tickers to: {out_path}')
        print('   Run 02_run_campaign.py next (it reads usable_tickers.txt automatically).')

    return usable


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=str, default=None,
                        help='Path to SQLite bar database (default: market_memory.db)')
    args = parser.parse_args()
    audit_database(args.db)
