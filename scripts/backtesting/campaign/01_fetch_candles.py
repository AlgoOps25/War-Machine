#!/usr/bin/env python3
"""
01_fetch_candles.py  —  Campaign Data Audit
============================================
Audits market_memory.db to show exactly what 5m bar data is cached,
which tickers have enough history, and which date ranges are available.

Run FIRST before the campaign to confirm you have sufficient data.

Usage:
    python scripts/backtesting/campaign/01_fetch_candles.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

ET = ZoneInfo("America/New_York")
MIN_BARS = 500          # Minimum bars to consider a ticker usable
MIN_DAYS  = 30          # Minimum trading days required


def audit_database():
    from app.data.db_connection import get_conn, dict_cursor

    db_path = os.path.join(os.path.dirname(__file__), '../../../market_memory.db')
    if not os.path.exists(db_path):
        db_path = 'market_memory.db'

    print('='*72)
    print('WAR MACHINE — BACKTEST CAMPAIGN DATA AUDIT')
    print('='*72)
    print(f'DB path : {os.path.abspath(db_path)}')
    print(f'Run at  : {datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")}')
    print()

    conn = get_conn(db_path)
    cur  = dict_cursor(conn)

    # ── 1. What tables exist? ───────────────────────────────────────────
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r['name'] for r in cur.fetchall()]
    print(f'Tables found: {tables}')
    print()

    # Identify the bar table
    bar_table = None
    for candidate in ('intraday_bars', 'bars', 'candles', 'ohlcv'):
        if candidate in tables:
            bar_table = candidate
            break

    if not bar_table:
        print('❌  No bar table found. Expected: intraday_bars, bars, candles, or ohlcv.')
        print('    Run the main scanner first to populate market_memory.db.')
        conn.close()
        return []

    print(f'Bar table : {bar_table}')

    # ── 2. Per-ticker summary ───────────────────────────────────────────
    cur.execute(f"""
        SELECT
            ticker,
            COUNT(*)                         AS total_bars,
            MIN(datetime)                    AS earliest,
            MAX(datetime)                    AS latest,
            COUNT(DISTINCT DATE(datetime))   AS trading_days
        FROM {bar_table}
        GROUP BY ticker
        ORDER BY total_bars DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print('❌  No rows in bar table. Database is empty.')
        return []

    print(f'Tickers in DB : {len(rows)}')
    print()

    usable   = []
    unusable = []

    header = f"{'Ticker':<8} {'Bars':>7} {'Days':>5}  {'Earliest':<12} {'Latest':<12}  Status"
    print(header)
    print('-' * len(header))

    for r in rows:
        ticker = r['ticker']
        bars   = r['total_bars']
        days   = r['trading_days']
        earliest = str(r['earliest'])[:10] if r['earliest'] else 'N/A'
        latest   = str(r['latest'])[:10]   if r['latest']   else 'N/A'

        ok = bars >= MIN_BARS and days >= MIN_DAYS
        status = '✅ USABLE' if ok else f'⚠️  LOW ({bars} bars, {days} days)'
        print(f"{ticker:<8} {bars:>7} {days:>5}  {earliest:<12} {latest:<12}  {status}")

        if ok:
            usable.append(ticker)
        else:
            unusable.append(ticker)

    print()
    print(f'✅  Usable tickers  : {len(usable):>3}  — {usable}')
    print(f'⚠️   Too-thin tickers: {len(unusable):>3}  — {unusable}')
    print()

    if not usable:
        print('❌  No tickers meet the minimum bar/day requirement.')
        print('    Run the main scanner for several days to build up history.')
    else:
        print('✅  Run 02_run_campaign.py next.')
        print('    It will automatically use all USABLE tickers listed above.')

    # ── 3. Write ticker list for campaign ──────────────────────────────
    out_path = os.path.join(os.path.dirname(__file__), 'usable_tickers.txt')
    with open(out_path, 'w') as f:
        for t in usable:
            f.write(t + '\n')
    print(f'\nTicker list saved to: {out_path}')

    return usable


if __name__ == '__main__':
    audit_database()
