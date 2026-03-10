#!/usr/bin/env python3
"""
00_export_from_railway.py  —  Export Railway Postgres → Local SQLite
====================================================================
Exports 5m bar data from Railway PostgreSQL into campaign_data.db.

If candle_cache only has 1m bars, aggregates to 5m in Postgres
using date_trunc so only ~63k rows are transferred instead of 314k.

USAGE
  python scripts/backtesting/campaign/00_export_from_railway.py
  python scripts/backtesting/campaign/00_export_from_railway.py --days 90
  python scripts/backtesting/campaign/00_export_from_railway.py --tickers AAPL,NVDA,SPY
  python scripts/backtesting/campaign/00_export_from_railway.py --all
"""

import sys, os, sqlite3, argparse, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

ET           = ZoneInfo('America/New_York')
DEFAULT_OUT  = os.path.join(os.path.dirname(__file__), 'campaign_data.db')
BATCH_SIZE   = 5000

CORE_TICKERS = [
    'AAPL','MSFT','NVDA','TSLA','META','SPY','AMD','QQQ',
    'AMZN','GOOGL','ORCL','WMT','CSCO','INTC','BAC',
]


# ── helpers ────────────────────────────────────────────────────────────────

def load_dotenv():
    p = os.path.join(os.path.dirname(__file__), '../../../.env')
    if not os.path.exists(p): return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k not in os.environ: os.environ[k] = v
    print('  Loaded .env from project root')


def get_database_url():
    load_dotenv()
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        print('\nERROR: DATABASE_URL not set.')
        print('  PowerShell : $env:DATABASE_URL = "postgresql://..."')
        print('  or .env    : DATABASE_URL=postgresql://...')
        sys.exit(1)
    return url.replace('postgres://', 'postgresql://', 1) if url.startswith('postgres://') else url


def open_postgres(url):
    try:
        import psycopg2
    except ImportError:
        print('ERROR: pip install psycopg2-binary'); sys.exit(1)
    print('  Connecting to Railway Postgres...')
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        print('  Connected ✅')
        return conn
    except Exception as e:
        print(f'  ❌ {e}'); sys.exit(1)


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


# ── probe ──────────────────────────────────────────────────────────────────

def probe_candle_cache(pg_conn, days_back, tickers):
    import psycopg2.extras
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cur    = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT COUNT(*) AS n FROM information_schema.tables
        WHERE table_name='candle_cache' AND table_schema='public'
    """)
    if cur.fetchone()['n'] == 0:
        return None

    cur.execute("SELECT DISTINCT timeframe FROM candle_cache ORDER BY timeframe")
    timeframes = [r['timeframe'] for r in cur.fetchall()]
    print(f'  candle_cache timeframes : {timeframes}')

    for tf in timeframes:
        args = [tf, cutoff]
        filt = "timeframe=%s AND datetime>=%s"
        if tickers:
            filt += " AND ticker=ANY(%s)"; args.append(tickers)
        cur.execute(f"SELECT COUNT(*) AS n FROM candle_cache WHERE {filt}", args)
        n = cur.fetchone()['n']
        cur.execute(f"SELECT MIN(datetime) AS mn, MAX(datetime) AS mx FROM candle_cache WHERE {filt}", args)
        r = cur.fetchone()
        print(f'    {tf:<6}  {n:>9,} rows   {str(r["mn"])[:10]} → {str(r["mx"])[:10]}')

    return timeframes


# ── aggregation query ──────────────────────────────────────────────────────

def build_agg_query(tickers, cutoff, source_tf):
    """
    Aggregate source_tf bars to 5-minute buckets in Postgres.
    Uses date_trunc + interval math to align timestamps to 5m grid.
    """
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker = ANY(%(tickers)s)"

    # For 1m→5m: floor(minute / 5) * 5 minutes from start of hour
    return f"""
        SELECT
            ticker,
            date_trunc('hour', datetime)
                + INTERVAL '5 min' * FLOOR(EXTRACT(MINUTE FROM datetime) / 5) AS dt_5m,
            (array_agg(open  ORDER BY datetime))[1]   AS open,
            MAX(high)                                  AS high,
            MIN(low)                                   AS low,
            (array_agg(close ORDER BY datetime DESC))[1] AS close,
            SUM(volume)                                AS volume
        FROM candle_cache
        WHERE timeframe = %(tf)s
          AND datetime  >= %(cutoff)s
          {ticker_filter}
        GROUP BY ticker, dt_5m
        ORDER BY ticker, dt_5m
    """


# ── export ─────────────────────────────────────────────────────────────────

def export_candle_cache(pg_conn, sqlite_conn, days_back, tickers, prefer_tf='5m'):
    import psycopg2.extras
    cutoff = (datetime.now(ET) - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cur    = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Check for native 5m bars first
    args = [prefer_tf, cutoff] + ([tickers] if tickers else [])
    filt = "timeframe=%s AND datetime>=%s" + (" AND ticker=ANY(%s)" if tickers else "")
    cur.execute(f"SELECT COUNT(*) AS n FROM candle_cache WHERE {filt}", args)
    n_5m = cur.fetchone()['n']

    if n_5m > 0:
        # Native 5m — stream directly
        source_tf = prefer_tf
        aggregate = False
        print(f'  Native 5m bars found: {n_5m:,} — exporting directly')
    else:
        # Aggregate 1m → 5m server-side in Postgres
        source_tf = '1m'
        aggregate = True
        args1m = ['1m', cutoff] + ([tickers] if tickers else [])
        filt1m = "timeframe=%s AND datetime>=%s" + (" AND ticker=ANY(%s)" if tickers else "")
        cur.execute(f"SELECT COUNT(*) AS n FROM candle_cache WHERE {filt1m}", args1m)
        n_1m = cur.fetchone()['n']
        expected_5m = n_1m // 5
        print(f'  No native 5m bars — aggregating {n_1m:,} × 1m → ~{expected_5m:,} × 5m bars in Postgres')

    if aggregate:
        sql    = build_agg_query(tickers, cutoff, source_tf)
        params = {'tf': source_tf, 'cutoff': cutoff}
        if tickers: params['tickers'] = tickers
        # Use a named server-side cursor for streaming
        stream = pg_conn.cursor(name='agg_export', cursor_factory=psycopg2.extras.RealDictCursor)
        stream.itersize = BATCH_SIZE
        stream.execute(sql, params)
        dt_col = 'dt_5m'
    else:
        stream = pg_conn.cursor(name='direct_export', cursor_factory=psycopg2.extras.RealDictCursor)
        stream.itersize = BATCH_SIZE
        params = {'tf': source_tf, 'cutoff': cutoff}
        if tickers:
            stream.execute("""
                SELECT ticker, datetime AS dt_5m, open, high, low, close, volume
                FROM candle_cache
                WHERE timeframe=%(tf)s AND datetime>=%(cutoff)s AND ticker=ANY(%(tickers)s)
                ORDER BY ticker, datetime
            """, {**params, 'tickers': tickers})
        else:
            stream.execute("""
                SELECT ticker, datetime AS dt_5m, open, high, low, close, volume
                FROM candle_cache
                WHERE timeframe=%(tf)s AND datetime>=%(cutoff)s
                ORDER BY ticker, datetime
            """, params)
        dt_col = 'dt_5m'

    inserted     = 0
    batch        = []
    start        = time.time()
    tickers_seen = set()

    for row in stream:
        dt_val = row[dt_col]
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
            batch     = []
            elapsed   = time.time() - start
            print(f'  Exported {inserted:>8,} bars  ({inserted/elapsed:.0f} rows/s)  tickers={len(tickers_seen)}')

    if batch:
        sqlite_conn.executemany(
            'INSERT OR REPLACE INTO intraday_bars_5m '
            '(ticker,datetime,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
            batch
        )
        sqlite_conn.commit()
        inserted += len(batch)

    stream.close()
    return inserted, list(tickers_seen), ('1m→5m' if aggregate else source_tf)


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',      type=int,  default=90)
    parser.add_argument('--out',       type=str,  default=DEFAULT_OUT)
    parser.add_argument('--tickers',   type=str,  default=None)
    parser.add_argument('--all',       action='store_true')
    parser.add_argument('--timeframe', type=str,  default='5m')
    args = parser.parse_args()

    if args.all:
        tickers     = None
        ticker_desc = 'ALL tickers'
    elif args.tickers:
        tickers     = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
        ticker_desc = f'{len(tickers)} specified tickers'
    else:
        tickers     = CORE_TICKERS
        ticker_desc = f'{len(CORE_TICKERS)} core tickers'

    print('='*72)
    print('WAR MACHINE — RAILWAY → LOCAL EXPORT')
    print('='*72)
    print(f'Days back  : {args.days}')
    print(f'Tickers    : {ticker_desc}')
    print(f'Timeframe  : {args.timeframe} (with 1m→5m aggregation fallback)')
    print(f'Output     : {args.out}')
    print()

    url         = get_database_url()
    pg_conn     = open_postgres(url)
    print()

    print('Probing candle_cache...')
    timeframes = probe_candle_cache(pg_conn, args.days, tickers)
    print()

    if timeframes is None:
        print('❌  candle_cache not found.')
        sys.exit(1)

    sqlite_conn = create_local_db(args.out)

    t0 = time.time()
    print('Exporting...')
    inserted, exported_tickers, tf_used = export_candle_cache(
        pg_conn, sqlite_conn, args.days, tickers, prefer_tf=args.timeframe
    )
    elapsed = time.time() - t0

    pg_conn.close()
    sqlite_conn.close()

    print()
    print('✅  Export complete!')
    print(f'  Bars exported  : {inserted:,}')
    print(f'  Tickers        : {len(exported_tickers)}  — {sorted(exported_tickers)}')
    print(f'  Timeframe      : {tf_used}')
    print(f'  Elapsed        : {elapsed:.1f}s')
    print(f'  Output         : {os.path.abspath(args.out)}')
    print()
    print('NEXT STEPS')
    print(f'  python scripts/backtesting/campaign/01_fetch_candles.py --db "{args.out}"')
    print(f'  python scripts/backtesting/campaign/02_run_campaign.py  --db "{args.out}"')


if __name__ == '__main__':
    main()
