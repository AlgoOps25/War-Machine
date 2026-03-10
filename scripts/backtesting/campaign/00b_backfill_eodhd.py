#!/usr/bin/env python3
"""
00b_backfill_eodhd.py  —  Backfill 5m bars from EODHD → campaign_data.db
========================================================================
Pulls up to 1 year of native 5-minute intraday bars from the EODHD API
for the core tickers and writes them into campaign_data.db.

EODHD intraday endpoint:
  GET https://eodhd.com/api/intraday/{TICKER}.US
      ?interval=5m&from=UNIX&to=UNIX&api_token=KEY&fmt=json

History depth (EODHD plan dependent):
  All-World / Extended plans : up to 2 years
  Basic plan                 : 120 days

USAGE
  python scripts/backtesting/campaign/00b_backfill_eodhd.py
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --days 365
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --tickers AAPL,NVDA,SPY
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --probe     # test API + show depth
"""

import sys, os, sqlite3, argparse, time, json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

try:
    import requests
except ImportError:
    print('ERROR: pip install requests'); sys.exit(1)

ET           = ZoneInfo('America/New_York')
DEFAULT_OUT  = os.path.join(os.path.dirname(__file__), 'campaign_data.db')
EODHD_BASE   = 'https://eodhd.com/api/intraday'

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


def get_api_key():
    load_dotenv()
    key = os.getenv('EODHD_API_KEY', '').strip()
    if not key:
        print('ERROR: EODHD_API_KEY not set in .env or environment')
        sys.exit(1)
    return key


def open_or_create_db(path):
    """Open existing campaign_data.db or create fresh one."""
    exists = os.path.exists(path)
    conn   = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')
    if not exists:
        print(f'  Creating new DB: {path}')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intraday_bars_5m (
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
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ticker_dt ON intraday_bars_5m(ticker, datetime)')
    conn.commit()
    return conn


# ── EODHD fetch ────────────────────────────────────────────────────────────

def fetch_eodhd_5m(ticker, api_key, from_ts, to_ts, retries=3):
    """
    Fetch 5m bars from EODHD for a single ticker.
    Returns list of dicts: {datetime, open, high, low, close, volume}
    """
    url    = f'{EODHD_BASE}/{ticker}.US'
    params = {
        'interval'  : '5m',
        'from'      : int(from_ts),
        'to'        : int(to_ts),
        'api_token' : api_key,
        'fmt'       : 'json',
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'error' in data:
                    print(f'    EODHD error: {data["error"]}')
                    return []
                return []
            elif r.status_code == 429:
                wait = 2 ** attempt
                print(f'    Rate limited — waiting {wait}s...')
                time.sleep(wait)
            else:
                print(f'    HTTP {r.status_code} for {ticker}')
                return []
        except Exception as e:
            print(f'    Request error: {e}')
            if attempt < retries - 1:
                time.sleep(2)
    return []


def probe_ticker(ticker, api_key):
    """Test API key and show available history depth for one ticker."""
    print(f'  Probing {ticker}...')
    # Request max lookback: 2 years
    to_ts   = int(datetime.now(timezone.utc).timestamp())
    from_ts = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp())
    bars    = fetch_eodhd_5m(ticker, api_key, from_ts, to_ts)
    if not bars:
        print(f'    No data returned — check API key or plan')
        return
    earliest = bars[0].get('datetime', bars[0].get('date', '?'))
    latest   = bars[-1].get('datetime', bars[-1].get('date', '?'))
    print(f'    Bars returned : {len(bars):,}')
    print(f'    Earliest      : {earliest}')
    print(f'    Latest        : {latest}')
    print(f'    ✅ API key works. Approx history: {len(bars)//78:.0f} trading days')


# ── main backfill ───────────────────────────────────────────────────────────

def backfill(tickers, days_back, out_path, api_key):
    to_ts   = int(datetime.now(timezone.utc).timestamp())
    from_ts = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())

    conn = open_or_create_db(out_path)

    total_inserted = 0
    summary        = []

    for i, ticker in enumerate(tickers):
        print(f'  [{i+1:>2}/{len(tickers)}] {ticker:<8}', end='  ', flush=True)
        t0   = time.time()
        bars = fetch_eodhd_5m(ticker, api_key, from_ts, to_ts)

        if not bars:
            print('0 bars — skipped')
            summary.append((ticker, 0, 'NO DATA'))
            continue

        # Parse and insert
        batch = []
        skipped = 0
        for b in bars:
            try:
                # EODHD returns 'datetime' as unix timestamp or ISO string
                dt_raw = b.get('datetime', b.get('date'))
                if isinstance(dt_raw, (int, float)):
                    dt_str = datetime.fromtimestamp(dt_raw, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
                else:
                    dt_str = str(dt_raw)[:19]  # trim microseconds

                batch.append((
                    ticker, dt_str,
                    float(b['open']), float(b['high']), float(b['low']),
                    float(b['close']), int(b.get('volume', 0)),
                ))
            except Exception:
                skipped += 1

        conn.executemany(
            'INSERT OR REPLACE INTO intraday_bars_5m '
            '(ticker,datetime,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
            batch
        )
        conn.commit()

        inserted = len(batch)
        total_inserted += inserted
        elapsed  = time.time() - t0
        days_est = inserted // 78
        print(f'{inserted:>6,} bars  (~{days_est} days)  {elapsed:.1f}s  {"⚠️ skipped="+str(skipped) if skipped else ""}')
        summary.append((ticker, inserted, f'~{days_est}d'))

        # EODHD rate limit: ~5 req/s on most plans; be polite
        time.sleep(0.3)

    conn.close()
    return total_inserted, summary


# ── entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',    type=int, default=365,
                        help='Days of history to fetch (default: 365)')
    parser.add_argument('--tickers', type=str, default=None,
                        help='Comma-separated tickers (default: 15 core)')
    parser.add_argument('--out',     type=str, default=DEFAULT_OUT)
    parser.add_argument('--probe',   action='store_true',
                        help='Test API key and show history depth, then exit')
    args = parser.parse_args()

    api_key = get_api_key()

    if args.probe:
        print('='*60)
        print('EODHD API PROBE')
        print('='*60)
        probe_ticker('SPY', api_key)
        probe_ticker('AAPL', api_key)
        return

    tickers = [t.strip().upper() for t in args.tickers.split(',')] if args.tickers else CORE_TICKERS

    print('='*72)
    print('WAR MACHINE — EODHD 5m BACKFILL')
    print('='*72)
    print(f'Tickers   : {len(tickers)}  — {tickers}')
    print(f'Days back : {args.days}')
    print(f'Output    : {args.out}')
    print()

    t0 = time.time()
    total, summary = backfill(tickers, args.days, args.out, api_key)
    elapsed = time.time() - t0

    print()
    print('='*72)
    print(f'✅  Backfill complete!  {total:,} bars  {elapsed:.1f}s')
    print()
    print(f'  {"Ticker":<8}  {"Bars":>7}  History')
    print(f'  {"-"*8}  {"-"*7}  -------')
    for t, n, d in summary:
        status = '✅' if n > 500 else ('⚠️' if n > 0 else '❌')
        print(f'  {t:<8}  {n:>7,}  {d}  {status}')
    print()
    print('NEXT STEPS')
    print(f'  python scripts/backtesting/campaign/01_fetch_candles.py --db "{args.out}"')
    print(f'  python scripts/backtesting/campaign/02_run_campaign.py  --db "{args.out}"')


if __name__ == '__main__':
    main()
