import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Dev\War-Machine')))
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv(Path(r'C:\Dev\War-Machine\.env'), override=True)

import os, requests
from app.data.db_connection import get_conn, return_conn
from psycopg2.extras import execute_values

TICKERS  = ['IWM']
API_KEY  = os.getenv('EODHD_API_KEY')
end_dt   = datetime.utcnow()
start_dt = end_dt - timedelta(days=120)

for ticker in TICKERS:
    print(f'{ticker}: fetching...', flush=True)
    url = f'https://eodhd.com/api/intraday/{ticker}.US?api_token={API_KEY}&interval=1m&from={int(start_dt.timestamp())}&to={int(end_dt.timestamp())}&fmt=json'
    resp = requests.get(url, timeout=60)
    print(f'  HTTP {resp.status_code} | {resp.text[:300]}')
    if resp.status_code != 200 or not resp.text.strip():
        print(f'{ticker}: ERROR - empty or bad response')
        continue

    bars = resp.json()
    if not isinstance(bars, list) or not bars:
        print(f'{ticker}: ERROR - unexpected response')
        continue

    rows = [
        (ticker, b['datetime'], b['open'], b['high'], b['low'], b['close'], int(b.get('volume') or 0))
        for b in bars
        if all([b.get('open'), b.get('high'), b.get('low'), b.get('close')])
    ]

    conn = get_conn()
    cur  = conn.cursor()
    execute_values(cur,
        "INSERT INTO intraday_bars (ticker, datetime, open, high, low, close, volume) "
        "VALUES %s ON CONFLICT (ticker, datetime) DO NOTHING",
        rows
    )
    conn.commit()
    return_conn(conn)
    print(f'{ticker}: {len(rows)} inserted (bulk), skipped={len(bars)-len(rows)}', flush=True)

print('Done.')