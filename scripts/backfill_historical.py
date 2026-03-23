import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Dev\War-Machine')))

from dotenv import load_dotenv
load_dotenv(Path(r'C:\Dev\War-Machine\.env'))

import os, requests
from datetime import datetime
from app.data.db_connection import get_conn, return_conn

TICKERS  = ['MSTR', 'AMD', 'MU', 'QQQ', 'NVDA', 'TSLA', 'SPY', 'IWM']
API_KEY  = os.getenv('EODHD_API_KEY')
start_dt = datetime(2025, 9, 1)
end_dt   = datetime(2026, 2, 2)

for ticker in TICKERS:
    print(f'{ticker}: fetching...', flush=True)
    url = f'https://eodhd.com/api/intraday/{ticker}?api_token={API_KEY}&interval=1m&from={int(start_dt.timestamp())}&to={int(end_dt.timestamp())}&fmt=json'
    resp = requests.get(url, timeout=60)
    bars = resp.json()
    if not isinstance(bars, list) or not bars:
        print(f'{ticker}: ERROR - {bars}')
        continue

    conn = get_conn()
    cur  = conn.cursor()
    inserted = skipped = 0

    resp = requests.get(url)
    print(f"  Status: {resp.status_code}, Length: {len(resp.text)}, Preview: {resp.text[:200]}")
    bars = resp.json()

    for b in bars:
        if not all([b.get('open'), b.get('high'), b.get('low'), b.get('close')]):
            skipped += 1
            continue
        cur.execute(
            "INSERT INTO candles_1m (ticker, datetime, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (ticker, datetime) DO NOTHING",
            (ticker, b['datetime'], b['open'], b['high'], b['low'], b['close'], int(b.get('volume') or 0))
        )
        inserted += 1

    conn.commit()
    return_conn(conn)
    print(f'{ticker}: {inserted} inserted, {skipped} skipped', flush=True)

print('Done.')