#!/usr/bin/env python3
"""
01_fetch_candles.py  —  Campaign Data Audit
============================================
Audits market_memory.db to show exactly what bar data is cached,
which tickers have enough history, and which date ranges are available.

Probes tables in this order:
  intraday_bars_5m  ← preferred (native 5m)
  intraday_bars     ← 1m bars
  candle_cache      ← EODHD JSON cache
  bars / candles / ohlcv

Usage:
    python scripts/backtesting/campaign/01_fetch_candles.py
"""

import sys
import os
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
MIN_BARS = 200   # 200 x 5m bars ≈ ~8 trading days minimum
MIN_DAYS = 10


# Table candidates in probe order
BAR_TABLE_CANDIDATES = [
    'intraday_bars_5m',
    'intraday_bars',
    'candle_cache',
    'bars',
    'candles',
    'ohlcv',
]


def inspect_columns(cur: sqlite3.Cursor, table: str) -> list:
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]   # r[1] = column name


def find_bar_table(cur: sqlite3.Cursor, tables: set) -> tuple:
    """
    Returns (table_name, ticker_col, dt_col, open_col, high_col, low_col, close_col, vol_col)
    or raises RuntimeError if nothing found.
    """
    for candidate in BAR_TABLE_CANDIDATES:
        if candidate not in tables:
            continue

        cols = inspect_columns(cur, candidate)
        cols_lower = [c.lower() for c in cols]

        # Ticker column
        ticker_col = next((c for c in cols if c.lower() in ('ticker','symbol','sym')), None)
        if not ticker_col:
            continue

        # Datetime column
        dt_col = next((c for c in cols if c.lower() in ('datetime','timestamp','ts','date','time')), None)
        if not dt_col:
            continue

        # OHLCV columns (case-insensitive)
        def find_col(*names):
            return next((c for c in cols if c.lower() in names), None)

        o = find_col('open', 'o')
        h = find_col('high', 'h')
        l = find_col('low',  'l')
        c = find_col('close','c','price')
        v = find_col('volume','vol','v')

        if not all([o, h, l, c, v]):
            # Try candle_cache which may store JSON
            if candidate == 'candle_cache':
                return (candidate, ticker_col, dt_col, o, h, l, c, v, cols)
            continue

        return (candidate, ticker_col, dt_col, o, h, l, c, v, cols)

    raise RuntimeError(
        'No usable bar table found.\n'
        f'  Tables in DB : {sorted(tables)}\n'
        '  Expected one of: ' + ', '.join(BAR_TABLE_CANDIDATES)
    )


def audit_candle_cache(cur: sqlite3.Cursor, table: str, cols: list) -> dict:
    """
    candle_cache stores JSON blobs.  Try to count tickers and date ranges
    from whatever metadata columns exist.
    """
    cols_lower = [c.lower() for c in cols]
    ticker_col = next((c for c in cols if c.lower() in ('ticker','symbol','sym')), None)

    print(f'  candle_cache columns: {cols}')

    if ticker_col:
        cur.execute(f"SELECT {ticker_col}, COUNT(*) AS n FROM {table} GROUP BY {ticker_col} ORDER BY n DESC")
        rows = cur.fetchall()
        print(f'  Rows in candle_cache: {sum(r[1] for r in rows):,}  across {len(rows)} tickers')
        for r in rows[:20]:
            print(f'    {r[0]:<10} {r[1]:>6} rows')
        return {r[0]: r[1] for r in rows}
    else:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
        print(f'  candle_cache: {n:,} rows (no ticker column detected)')
        return {}


def audit_database():
    db_path = os.path.join(os.path.dirname(__file__), '../../../market_memory.db')
    if not os.path.exists(db_path):
        db_path = 'market_memory.db'
    if not os.path.exists(db_path):
        print('❌  market_memory.db not found.')
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

    # List all tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0] for r in cur.fetchall()}
    print(f'Tables found: {sorted(tables)}')
    print()

    # Check row counts for ALL candidate tables
    print('Row counts per candidate table:')
    for t in BAR_TABLE_CANDIDATES:
        if t in tables:
            cur.execute(f'SELECT COUNT(*) FROM {t}')
            n = cur.fetchone()[0]
            print(f'  {t:<24} {n:>10,} rows')
    print()

    # Find the best usable table
    try:
        result = find_bar_table(cur, tables)
    except RuntimeError as e:
        print(f'❌  {e}')
        conn.close()
        return []

    bar_table  = result[0]
    ticker_col = result[1]
    dt_col     = result[2]
    o_col, h_col, l_col, c_col, v_col = result[3], result[4], result[5], result[6], result[7]
    all_cols   = result[8]

    print(f'Using table : {bar_table}')
    print(f'Columns     : ticker={ticker_col}  dt={dt_col}  O={o_col}  H={h_col}  L={l_col}  C={c_col}  V={v_col}')
    print()

    # Handle candle_cache specially if OHLCV cols are missing
    if bar_table == 'candle_cache' and not all([o_col, h_col, l_col, c_col, v_col]):
        print('⚠️  candle_cache detected but OHLCV columns not found directly.')
        print('   Performing metadata audit...')
        audit_candle_cache(cur, bar_table, all_cols)
        print()
        print('❌  Cannot run campaign directly against candle_cache JSON blobs.')
        print('   Solution: run the main scanner to populate intraday_bars_5m, then re-audit.')
        conn.close()
        return []

    # Per-ticker summary
    cur.execute(f"""
        SELECT
            {ticker_col}                         AS ticker,
            COUNT(*)                             AS total_bars,
            MIN({dt_col})                        AS earliest,
            MAX({dt_col})                        AS latest,
            COUNT(DISTINCT DATE({dt_col}))       AS trading_days
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

    usable   = []
    unusable = []

    header = f"{'Ticker':<8} {'Bars':>7} {'Days':>5}  {'Earliest':<12} {'Latest':<12}  Status"
    print(header)
    print('-' * len(header))

    for r in rows:
        ticker   = r['ticker']
        bars     = r['total_bars']
        days     = r['trading_days']
        earliest = str(r['earliest'])[:10] if r['earliest'] else 'N/A'
        latest   = str(r['latest'])[:10]   if r['latest']   else 'N/A'

        ok = bars >= MIN_BARS and days >= MIN_DAYS
        status = '✅ USABLE' if ok else f'⚠️  LOW ({bars} bars / {days} days)'
        print(f"{ticker:<8} {bars:>7} {days:>5}  {earliest:<12} {latest:<12}  {status}")

        if ok:
            usable.append(ticker)
        else:
            unusable.append(ticker)

    print()
    print(f'✅  Usable tickers   : {len(usable):>3}  — {usable}')
    print(f'⚠️   Too-thin tickers : {len(unusable):>3}  — {unusable}')
    print()

    if not usable:
        print('❌  No tickers meet the minimum bar/day requirement.')
        print(f'   Requirements: >= {MIN_BARS} bars AND >= {MIN_DAYS} trading days')
        print('   If bars exist but fall below threshold, lower MIN_BARS/MIN_DAYS at top of this file.')
    else:
        out_path = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
        with open(out_path, 'w') as f:
            # Write table name on line 1 as comment so campaign engine knows which table to use
            f.write(f'# bar_table={bar_table}\n')
            f.write(f'# ticker_col={ticker_col}\n')
            f.write(f'# dt_col={dt_col}\n')
            f.write(f'# ohlcv={o_col},{h_col},{l_col},{c_col},{v_col}\n')
            for t in usable:
                f.write(t + '\n')
        print(f'✅  Ticker list + schema saved to: {out_path}')
        print('   Run 02_run_campaign.py next.')

    return usable


if __name__ == '__main__':
    audit_database()
