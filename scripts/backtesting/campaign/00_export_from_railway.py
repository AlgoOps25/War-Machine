#!/usr/bin/env python3
"""
00_export_from_railway.py  —  Export Railway Postgres → Local SQLite
====================================================================
Exports bar data from Railway PostgreSQL into a local SQLite file
(campaign_data.db) for offline backtesting.

SOURCE PRIORITY
  1. candle_cache WHERE timeframe='5m'   (1.29M rows — preferred)
  2. candle_cache WHERE timeframe='1m'   aggregated to 5m
  3. intraday_bars_5m                    (materialized 5m)
  4. intraday_bars                       (1m, aggregated to 5m)

USAGE
  $env:DATABASE_URL = "postgresql://..."
  python scripts/backtesting/campaign/00_export_from_railway.py
  python scripts/backtesting/campaign/00_export_from_railway.py --days 90
  python scripts/backtesting/campaign/00_export_from_railway.py --tickers AAPL,NVDA,TSLA,SPY,QQQ
  python scripts/backtesting/campaign/00_export_from_railway.py --timeframe 1m
"""

import sys
import os
import sqlite3
import argparse
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

ET = ZoneInfo('America/New_York')
DEFAULT_OUT  = os.path.join(os.path.dirname(__file__), 'campaign_data.db')
BATCH_SIZE   = 5000

# Core tickers with the deepest history — use these for the 90-day campaign
CORE_TICKERS = [
    'AAPL','MSFT','NVDA','TSLA','META','SPY','AMD','QQQ',
    'AMZN','GOOGL','ORCL','WMT','CSCO','INTC','BAC',
]


def load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), '../../../.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v
    print('  Loaded .env from project root')


def get_database_url():
    load_dotenv()
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        print('\nERROR: DATABASE_URL is not set.')
        print('  PowerShell: $env:DATABASE_URL = "postgresql://..."')
        print('  or add to .env: DATABASE_URL=postgresql://...')
        sys.exit(1)
    return url.replace('postgres://', 'postgresql://', 1) if url.startswith('postgres://') else url


def open_postgres(url):
    try:
        import psycopg2
    except ImportError:
        print('ERROR: pip install psycopg2-binary')
        sys.exit(1)
    print('  Connecting to Railway Postgres...')
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        print('  Connected ✅')
        return conn
    except Exception as e:
        print(f'  ❌ {e}')
        sys.exit(1)


def probe_candle_cache(pg_conn, days_back, tickers):
    """Check what timeframes and tickers exist in candle_cache."""
    import psycopg2.extras
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Check if candle_cache exists
    cur.execute("""
        SELECT COUNT(*) AS n FROM information_schema.tables
        WHERE table_name = 'candle_cache' AND table_schema = 'public'
    """)
    if cur.fetchone()['n'] == 0:
        return None

    # Distinct timeframes
    cur.execute("SELECT DISTINCT timeframe FROM candle_cache ORDER BY timeframe")
    timeframes = [r['timeframe'] for r in cur.fetchall()]
    print(f'  candle_cache timeframes: {timeframes}')

    # Row counts per timeframe since cutoff
    for tf in timeframes:
        if tickers:
            cur.execute(
                "SELECT COUNT(*) AS n FROM candle_cache WHERE timeframe=%s AND datetime>=%s AND ticker=ANY(%s)",
                (tf, cutoff, tickers)
            )
        else:
            cur.execute(
                "SELECT COUNT(*) AS n FROM candle_cache WHERE timeframe=%s AND datetime>=%s",
                (tf, cutoff)
            )
        n = cur.fetchone()['n']

        # Date range
        if tickers:
            cur.execute(
                "SELECT MIN(datetime) AS mn, MAX(datetime) AS mx FROM candle_cache WHERE timeframe=%s AND datetime>=%s AND ticker=ANY(%s)",
                (tf, cutoff, tickers)
            )
        else:
            cur.execute(
                "SELECT MIN(datetime) AS mn, MAX(datetime) AS mx FROM candle_cache WHERE timeframe=%s AND datetime>=%s",
                (tf, cutoff)
            )
        r = cur.fetchone()
        print(f'    {tf:<6}  {n:>9,} rows   {str(r["mn"])[:10]} → {str(r["mx"])[:10]}')

    return timeframes


def export_candle_cache(pg_conn, sqlite_conn, days_back, tickers, prefer_tf='5m'):
    """Export from candle_cache, preferring 5m bars."""
    import psycopg2.extras
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')

    # Decide which timeframe to pull
    cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if tickers:
        cur.execute(
            "SELECT COUNT(*) AS n FROM candle_cache WHERE timeframe=%s AND datetime>=%s AND ticker=ANY(%s)",
            (prefer_tf, cutoff, tickers)
        )
    else:
        cur.execute(
            "SELECT COUNT(*) AS n FROM candle_cache WHERE timeframe=%s AND datetime>=%s",
            (prefer_tf, cutoff)
        )
    n_preferred = cur.fetchone()['n']

    if n_preferred > 0:
        tf_to_use = prefer_tf
        print(f'  Using timeframe : {tf_to_use}  ({n_preferred:,} rows)')
    else:
        # Fallback to 1m
        tf_to_use = '1m'
        print(f'  No {prefer_tf} bars found — falling back to 1m (will aggregate to 5m)')

    # Stream export
    stream_cur = pg_conn.cursor(name='candle_export', cursor_factory=psycopg2.extras.RealDictCursor)
    stream_cur.itersize = BATCH_SIZE

    if tickers:
        stream_cur.execute("""
            SELECT ticker, datetime, open, high, low, close, volume
            FROM   candle_cache
            WHERE  timeframe = %s AND datetime >= %s AND ticker = ANY(%s)
            ORDER  BY ticker, datetime
        """, (tf_to_use, cutoff, tickers))
    else:
        stream_cur.execute("""
            SELECT ticker, datetime, open, high, low, close, volume
            FROM   candle_cache
            WHERE  timeframe = %s AND datetime >= %s
            ORDER  BY ticker, datetime
        """, (tf_to_use, cutoff))

    inserted = 0
    batch    = []
    start    = time.time()
    tickers_seen = set()

    for row in stream_cur:
        dt_val = row['datetime']
        dt_str = dt_val.isoformat() if hasattr(dt_val, 'isoformat') else str(dt_val)
        batch.append((
            row['ticker'], dt_str,
            float(row['open']), float(row['high']), float(row['low']),
            float(row['close']), int(row['volume']),
        ))
        tickers_seen.add(row['ticker'])

        if len(batch) >= BATCH_SIZE:
            sqlite_conn.executemany(
                'INSERT OR REPLACE INTO intraday_bars_5m '
                '(ticker,datetime,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
                batch
            )
            sqlite_conn.commit()
            inserted += len(batch)
            batch = []
            elapsed = time.time() - start
            print(f'  Exported {inserted:>9,} bars  ({inserted/elapsed:.0f} rows/s)  tickers={len(tickers_seen)}')

    if batch:
        sqlite_conn.executemany(
            'INSERT OR REPLACE INTO intraday_bars_5m '
            '(ticker,datetime,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
            batch
        )
        sqlite_conn.commit()
        inserted += len(batch)

    stream_cur.close()
    return inserted, list(tickers_seen), tf_to_use


def create_local_db(out_path):
    if os.path.exists(out_path):
        print(f'  Overwriting: {out_path}')
        os.remove(out_path)
    conn = sqlite3.connect(out_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')
    conn.execute("""
        CREATE TABLE intraday_bars_5m (
            ticker   TEXT    NOT NULL,
            datetime TEXT    NOT NULL,
            open     REAL    NOT NULL,
            high     REAL    NOT NULL,
            low      REAL    NOT NULL,
            close    REAL    NOT NULL,
            volume   INTEGER NOT NULL,
            PRIMARY KEY (ticker, datetime)
        )
    """)
    conn.execute('CREATE INDEX idx_ticker_dt ON intraday_bars_5m(ticker, datetime)')
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',      type=int,  default=90)
    parser.add_argument('--out',       type=str,  default=DEFAULT_OUT)
    parser.add_argument('--tickers',   type=str,  default=None,
                        help='Comma-separated tickers. Default: 15 core tickers.')
    parser.add_argument('--all',       action='store_true',
                        help='Export ALL tickers (not just core list)')
    parser.add_argument('--timeframe', type=str,  default='5m',
                        help='Preferred timeframe in candle_cache (default: 5m)')
    args = parser.parse_args()

    # Resolve ticker list
    if args.all:
        tickers = None
        ticker_desc = 'ALL tickers'
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
        ticker_desc = f'{len(tickers)} specified tickers'
    else:
        tickers = CORE_TICKERS
        ticker_desc = f'{len(tickers)} core tickers'

    print('='*72)
    print('WAR MACHINE — RAILWAY → LOCAL EXPORT')
    print('='*72)
    print(f'Days back  : {args.days}')
    print(f'Tickers    : {ticker_desc}')
    print(f'Timeframe  : {args.timeframe}')
    print(f'Output     : {args.out}')
    print()

    url         = get_database_url()
    pg_conn     = open_postgres(url)
    print()

    print('Probing candle_cache...')
    timeframes = probe_candle_cache(pg_conn, args.days, tickers)
    print()

    sqlite_conn = create_local_db(args.out)

    if timeframes is not None:
        print('Exporting from candle_cache...')
        inserted, exported_tickers, tf_used = export_candle_cache(
            pg_conn, sqlite_conn, args.days, tickers, prefer_tf=args.timeframe
        )
    else:
        print('❌  candle_cache not found. Exiting.')
        sys.exit(1)

    pg_conn.close()

    elapsed = time.time()
    print()
    print('✅  Export complete!')
    print(f'  Bars exported  : {inserted:,}')
    print(f'  Tickers        : {len(exported_tickers)}  — {sorted(exported_tickers)}')
    print(f'  Timeframe used : {tf_used}')
    print(f'  Output file    : {os.path.abspath(args.out)}')
    print()
    print('NEXT STEPS')
    print(f'  python scripts/backtesting/campaign/01_fetch_candles.py --db "{args.out}"')
    print(f'  python scripts/backtesting/campaign/02_run_campaign.py  --db "{args.out}"')


if __name__ == '__main__':
    main()
