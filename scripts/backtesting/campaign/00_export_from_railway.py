#!/usr/bin/env python3
"""
00_export_from_railway.py  —  Export Railway Postgres → Local SQLite
====================================================================
Pulls 90 days of bar data from your Railway PostgreSQL database into a
local SQLite file (campaign_data.db) so the backtest campaign runs
entirely offline — no Railway hammering during the 97k-combo run.

PREREQUISITES
  pip install psycopg2-binary   (if not already installed)

USAGE
  # Option A: Pass DATABASE_URL directly
  $env:DATABASE_URL = "postgresql://user:pass@host:port/dbname"
  python scripts/backtesting/campaign/00_export_from_railway.py

  # Option B: Pull from Railway env automatically (if .env is set up)
  python scripts/backtesting/campaign/00_export_from_railway.py

  # Option C: Specify days and output path
  python scripts/backtesting/campaign/00_export_from_railway.py --days 60 --out my_data.db

OUTPUT
  campaign_data.db   — local SQLite with intraday_bars_5m table populated

Then run:
  python scripts/backtesting/campaign/01_fetch_candles.py --db campaign_data.db
  python scripts/backtesting/campaign/02_run_campaign.py  --db campaign_data.db
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

DEFAULT_OUT = os.path.join(os.path.dirname(__file__), 'campaign_data.db')
BATCH_SIZE  = 5000  # rows per INSERT batch


def load_dotenv():
    """Try to load .env file from project root (no dependency on python-dotenv)."""
    env_path = os.path.join(os.path.dirname(__file__), '../../../.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key not in os.environ:   # Don't override real env vars
                os.environ[key] = val
    print('  Loaded .env from project root')


def get_database_url() -> str:
    """Resolve DATABASE_URL from environment or .env file."""
    load_dotenv()
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        print()
        print('ERROR: DATABASE_URL is not set.')
        print()
        print('Set it one of these ways:')
        print('  1. PowerShell:  $env:DATABASE_URL = "postgresql://user:pass@host:port/db"')
        print('  2. .env file :  DATABASE_URL=postgresql://user:pass@host:port/db')
        print()
        print('Find your Railway DATABASE_URL:')
        print('  Railway dashboard → your project → PostgreSQL service → Connect tab')
        sys.exit(1)
    # Normalize postgres:// → postgresql://
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


def open_postgres(url: str):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print('ERROR: psycopg2 not installed.')
        print('  Run: pip install psycopg2-binary')
        sys.exit(1)

    print(f'  Connecting to Railway Postgres...')
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        print('  Connected ✅')
        return conn
    except Exception as e:
        print(f'  ❌ Connection failed: {e}')
        print()
        print('  Check that:')
        print('    1. DATABASE_URL is correct')
        print('    2. Railway service is running')
        print('    3. Your IP is allowed (Railway public networking is on)')
        sys.exit(1)


def detect_source_table(pg_conn) -> dict:
    """
    Find the bar table in Postgres and return its schema dict.
    Checks intraday_bars_5m first, then intraday_bars.
    """
    import psycopg2.extras
    cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    candidates = ['intraday_bars_5m', 'intraday_bars']
    for table in candidates:
        try:
            cur.execute(f'SELECT COUNT(*) AS n FROM {table}')
            n = cur.fetchone()['n']
            if n > 0:
                print(f'  Source table    : {table}  ({n:,} total rows)')
                return {'table': table, 'rows': n}
        except Exception:
            pg_conn.rollback()
            continue

    print('  ❌ No bar data found in Postgres. Tables checked:', candidates)
    print('     Run the main scanner on Railway to populate the database first.')
    sys.exit(1)


def create_local_db(out_path: str) -> sqlite3.Connection:
    """Create (or overwrite) the local SQLite campaign_data.db."""
    if os.path.exists(out_path):
        print(f'  Overwriting existing file: {out_path}')
        os.remove(out_path)

    conn = sqlite3.connect(out_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')   # 64 MB cache
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


def export_bars(
    pg_conn,
    sqlite_conn : sqlite3.Connection,
    source_table: str,
    days_back   : int,
):
    import psycopg2.extras

    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    print(f'  Exporting bars since {cutoff} ({days_back} days)...')

    cur = pg_conn.cursor(name='bar_export', cursor_factory=psycopg2.extras.RealDictCursor)
    cur.itersize = BATCH_SIZE

    cur.execute(f"""
        SELECT ticker, datetime, open, high, low, close, volume
        FROM   {source_table}
        WHERE  datetime >= %s
        ORDER  BY ticker, datetime
    """, (cutoff,))

    total    = 0
    inserted = 0
    batch    = []
    start    = time.time()
    tickers_seen = set()

    for row in cur:
        ticker = row['ticker']
        tickers_seen.add(ticker)

        # Normalise datetime to ISO string
        dt_val = row['datetime']
        if hasattr(dt_val, 'isoformat'):
            dt_str = dt_val.isoformat()
        else:
            dt_str = str(dt_val)

        batch.append((
            ticker,
            dt_str,
            float(row['open']),
            float(row['high']),
            float(row['low']),
            float(row['close']),
            int(row['volume']),
        ))
        total += 1

        if len(batch) >= BATCH_SIZE:
            sqlite_conn.executemany(
                'INSERT OR REPLACE INTO intraday_bars_5m '
                '(ticker,datetime,open,high,low,close,volume) '
                'VALUES (?,?,?,?,?,?,?)',
                batch
            )
            sqlite_conn.commit()
            inserted += len(batch)
            batch = []

            elapsed = time.time() - start
            rate    = inserted / elapsed if elapsed > 0 else 0
            print(f'  Exported {inserted:>8,} bars  ({rate:.0f} rows/s)  '
                  f'tickers={len(tickers_seen)}')

    # Flush remainder
    if batch:
        sqlite_conn.executemany(
            'INSERT OR REPLACE INTO intraday_bars_5m '
            '(ticker,datetime,open,high,low,close,volume) '
            'VALUES (?,?,?,?,?,?,?)',
            batch
        )
        sqlite_conn.commit()
        inserted += len(batch)

    cur.close()
    elapsed = time.time() - start
    print()
    print(f'  ✅  Export complete!')
    print(f'  Total bars exported : {inserted:,}')
    print(f'  Unique tickers      : {len(tickers_seen)}')
    print(f'  Elapsed             : {elapsed:.1f}s')
    print(f'  Output file         : {os.path.abspath(sqlite_conn.execute("PRAGMA database_list").fetchone()[2])}')  # noqa
    return list(tickers_seen)


def main():
    parser = argparse.ArgumentParser(description='Export Railway Postgres bars → local SQLite')
    parser.add_argument('--days', type=int, default=90,
                        help='Days of history to export (default: 90)')
    parser.add_argument('--out',  type=str, default=DEFAULT_OUT,
                        help='Output SQLite path (default: campaign_data.db)')
    args = parser.parse_args()

    print('='*72)
    print('WAR MACHINE — RAILWAY → LOCAL EXPORT')
    print('='*72)
    print(f'Days back  : {args.days}')
    print(f'Output     : {args.out}')
    print()

    db_url  = get_database_url()
    pg_conn = open_postgres(db_url)

    schema  = detect_source_table(pg_conn)
    sqlite_conn = create_local_db(args.out)

    tickers = export_bars(pg_conn, sqlite_conn, schema['table'], args.days)

    pg_conn.close()
    sqlite_conn.close()

    print()
    print('NEXT STEPS')
    print('  1. Audit the exported data:')
    print(f'     python scripts/backtesting/campaign/01_fetch_candles.py --db "{args.out}"')
    print('  2. Run the campaign:')
    print(f'     python scripts/backtesting/campaign/02_run_campaign.py  --db "{args.out}"')


if __name__ == '__main__':
    main()
