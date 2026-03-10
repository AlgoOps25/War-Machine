#!/usr/bin/env python3
"""
00b_backfill_eodhd.py  —  Backfill 5m bars from EODHD → campaign_data.db
========================================================================
Pulls native 5m (or 1m aggregated) intraday bars from EODHD for core
tickers and writes them into campaign_data.db for offline backtesting.

EODHD intraday endpoint:
  GET https://eodhd.com/api/intraday/{TICKER}.US
      ?interval=5m&from=YYYY-MM-DD&to=YYYY-MM-DD&api_token=KEY&fmt=json

NOTE: EODHD intraday max window is ~180 days per request.
      Requesting more than that returns HTTP 422.

USAGE
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --probe
  python scripts/backtesting/campaign/00b_backfill_eodhd.py
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --days 180
  python scripts/backtesting/campaign/00b_backfill_eodhd.py --tickers AAPL,NVDA,SPY
"""

import sys, os, sqlite3, argparse, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

try:
    import requests
except ImportError:
    print('ERROR: pip install requests'); sys.exit(1)

ET           = ZoneInfo('America/New_York')
DEFAULT_OUT  = os.path.join(os.path.dirname(__file__), 'campaign_data.db')
EODHD_BASE   = 'https://eodhd.com/api/intraday'
MAX_DAYS     = 180   # EODHD intraday hard limit per request

CORE_TICKERS = [
    'AAPL','MSFT','NVDA','TSLA','META','SPY','AMD','QQQ',
    'AMZN','GOOGL','ORCL','WMT','CSCO','INTC','BAC',
]


# ── helpers ───────────────────────────────────────────────────────────────

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
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')
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


# ── EODHD fetch ───────────────────────────────────────────────────────────

def fetch_eodhd(ticker, api_key, from_date, to_date, interval='5m', retries=3):
    """
    Fetch intraday bars from EODHD.
    from_date / to_date must be 'YYYY-MM-DD' strings.
    Returns (bars_list, interval_used).
    """
    url    = f'{EODHD_BASE}/{ticker}.US'
    params = {
        'api_token' : api_key,
        'interval'  : interval,
        'from'      : from_date,
        'to'        : to_date,
        'fmt'       : 'json',
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data, interval
                if isinstance(data, dict) and 'error' in data:
                    print(f'    EODHD error: {data["error"]}')
                    return [], interval
                return [], interval
            elif r.status_code == 422:
                if interval == '5m':
                    # Try 1m as fallback (will aggregate locally)
                    print(f'    5m returned 422 — retrying with 1m...')
                    return fetch_eodhd(ticker, api_key, from_date, to_date,
                                       interval='1m', retries=retries)
                print(f'    HTTP 422 on 1m — date range too large or ticker invalid.')
                print(f'    Max window is {MAX_DAYS} days. Try --days 60 to test.')
                return [], interval
            elif r.status_code == 429:
                wait = 2 ** attempt
                print(f'    Rate limited — waiting {wait}s...')
                time.sleep(wait)
            else:
                print(f'    HTTP {r.status_code}: {r.text[:200]}')
                return [], interval
        except Exception as e:
            print(f'    Request error: {e}')
            if attempt < retries - 1: time.sleep(2)
    return [], interval


def aggregate_1m_to_5m(bars_1m):
    """Aggregate 1m EODHD bars to 5m buckets locally."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for b in bars_1m:
        try:
            dt = datetime.strptime(b['datetime'][:19], '%Y-%m-%d %H:%M:%S')
            floored = dt.replace(minute=(dt.minute // 5) * 5, second=0)
            buckets[floored].append(b)
        except Exception:
            continue
    result = []
    for dt_bucket in sorted(buckets):
        group = buckets[dt_bucket]
        try:
            result.append({
                'datetime' : dt_bucket.strftime('%Y-%m-%d %H:%M:%S'),
                'open'     : float(group[0]['open']),
                'high'     : max(float(b['high'])  for b in group),
                'low'      : min(float(b['low'])   for b in group),
                'close'    : float(group[-1]['close']),
                'volume'   : sum(int(b.get('volume', 0)) for b in group),
            })
        except Exception:
            continue
    return result


# ── probe ──────────────────────────────────────────────────────────────────

def probe_ticker(ticker, api_key, days=60):
    """Test a single ticker with a safe date window."""
    now       = datetime.now(ET)
    to_date   = now.strftime('%Y-%m-%d')
    from_date = (now - timedelta(days=days)).strftime('%Y-%m-%d')
    print(f'  Probing {ticker}  ({from_date} → {to_date}, {days}d window)...')
    bars, iv = fetch_eodhd(ticker, api_key, from_date, to_date, interval='5m')
    if not bars:
        print(f'    ❌ No data returned.')
        return
    earliest = bars[0].get('datetime', '?')
    latest   = bars[-1].get('datetime', '?')
    bars_per_day = 78 if iv == '5m' else 390
    days_est = len(bars) // bars_per_day
    print(f'    Interval      : {iv}')
    print(f'    Bars returned : {len(bars):,}')
    print(f'    Earliest      : {earliest}')
    print(f'    Latest        : {latest}')
    print(f'    Est. days     : ~{days_est}')
    print(f'    ✅ API working!')


# ── backfill ────────────────────────────────────────────────────────────────

def backfill(tickers, days_back, out_path, api_key):
    # Clamp to EODHD's hard limit
    if days_back > MAX_DAYS:
        print(f'  ⚠️  Clamping days from {days_back} → {MAX_DAYS} (EODHD intraday max)')
        days_back = MAX_DAYS

    now       = datetime.now(ET)
    to_date   = now.strftime('%Y-%m-%d')
    from_date = (now - timedelta(days=days_back)).strftime('%Y-%m-%d')
    print(f'  Date range : {from_date} → {to_date}  ({days_back} days)')
    print()

    conn = open_or_create_db(out_path)
    total_inserted = 0
    summary        = []

    for i, ticker in enumerate(tickers):
        print(f'  [{i+1:>2}/{len(tickers)}] {ticker:<8}', end='  ', flush=True)
        t0 = time.time()

        bars, iv = fetch_eodhd(ticker, api_key, from_date, to_date, interval='5m')

        if not bars:
            print('0 bars — skipped')
            summary.append((ticker, 0, 'NO DATA'))
            time.sleep(0.5)
            continue

        # Aggregate locally if 1m was returned
        if iv == '1m':
            bars = aggregate_1m_to_5m(bars)

        batch   = []
        skipped = 0
        for b in bars:
            try:
                dt_str = b['datetime'][:19]
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

        inserted  = len(batch)
        total_inserted += inserted
        elapsed   = time.time() - t0
        days_est  = inserted // 78
        ivlabel   = iv if iv == '5m' else '1m→5m'
        skip_str  = f'  ⚠️ skipped={skipped}' if skipped else ''
        print(f'{inserted:>6,} bars  (~{days_est}d)  [{ivlabel}]  {elapsed:.1f}s{skip_str}')
        summary.append((ticker, inserted, f'~{days_est}d'))

        time.sleep(0.3)

    conn.close()
    return total_inserted, summary


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',    type=int,  default=180,
                        help=f'Days of history to fetch (max {MAX_DAYS}, default 180)')
    parser.add_argument('--tickers', type=str,  default=None)
    parser.add_argument('--out',     type=str,  default=DEFAULT_OUT)
    parser.add_argument('--probe',   action='store_true',
                        help='Test API with a 60-day window before committing to full fetch')
    parser.add_argument('--probe-days', type=int, default=60,
                        help='Window size for probe test (default 60)')
    args = parser.parse_args()

    api_key = get_api_key()

    if args.probe:
        print('='*60)
        print('EODHD API PROBE')
        print('='*60)
        probe_ticker('SPY',  api_key, days=args.probe_days)
        print()
        probe_ticker('AAPL', api_key, days=args.probe_days)
        return

    tickers = ([t.strip().upper() for t in args.tickers.split(',') if t.strip()]
               if args.tickers else CORE_TICKERS)

    print('='*72)
    print('WAR MACHINE — EODHD 5m BACKFILL')
    print('='*72)
    print(f'Tickers   : {len(tickers)}  — {tickers}')
    print(f'Days back : {args.days}  (max {MAX_DAYS})')
    print(f'Output    : {args.out}')
    print()

    t0 = time.time()
    total, summary = backfill(tickers, args.days, args.out, api_key)
    elapsed = time.time() - t0

    print()
    print('='*72)
    print(f'✅  Backfill complete!  {total:,} total bars  {elapsed:.1f}s')
    print()
    print(f'  {"Ticker":<8}  {"Bars":>7}  History')
    print(f'  {"-"*8}  {"-"*7}  -------')
    for t, n, d in summary:
        status = '✅' if n > 500 else ('⚠️' if n > 0 else '❌')
        print(f'  {t:<8}  {n:>7,}  {d}  {status}')
    print()
    print('NEXT STEPS')
    print(f'  python scripts/backtesting/campaign/01_fetch_candles.py --db "{args.out}"')
    print(f'  python scripts/backtesting/campaign/02_run_campaign.py')


if __name__ == '__main__':
    main()
