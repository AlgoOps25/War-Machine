import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Dev\War-Machine')))

from dotenv import load_dotenv
load_dotenv(Path(r'C:\Dev\War-Machine\.env'))

import os, requests
from datetime import datetime
from app.data.db_connection import get_conn, return_conn

TICKERS  = ['MSTR', 'AMD', 'MU', 'QQQ', 'NVDA', 'TSLA', 'SPY']
API_KEY  = os.getenv('EODHD_API_KEY')
start_dt = datetime(2025, 9, 1)
end_dt   = datetime(2026, 2, 2)

conn = get_conn()
cur  = conn.cursor()

for ticker in TICKERS:
    print(f'{ticker}: fetching...', flush=True)
    url = f'https://eodhd.com/api/intraday/{ticker}?api_token={API_KEY}&interval=5m&from={int(start_dt.timestamp())}&to={int(end_dt.timestamp())}&fmt=json'
    resp = requests.get(url, timeout=60)
    bars = resp.json()
    if not isinstance(bars, list) or not bars:
        print(f'{ticker}: ERROR - {bars}')
        continue

    inserted = skipped = 0
    for b in bars:
        try:
            cur.execute(
                "INSERT INTO intraday_bars (ticker, datetime, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (ticker, datetime) DO NOTHING",
                (ticker, b['datetime'], b['open'], b['high'], b['low'], b['close'], int(b.get('volume') or 0))
            )
            inserted += 1
        except Exception as e:
            conn.rollback()
            skipped += 1
            print(f'  {ticker} row error: {e}')

    conn.commit()
    print(f'{ticker}: {inserted} inserted, {skipped} skipped', flush=True)

return_conn(conn)
print('Done.')
