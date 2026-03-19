"""
backfill_history.py v5 — execute_values bulk insert, 7-day chunks, no DataManager
"""
import requests
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from psycopg2.extras import execute_values
from app.data.db_connection import get_conn, return_conn, dict_cursor, ph
from utils import config

ET      = ZoneInfo("America/New_York")
TICKERS = ["AAPL", "AMD", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]

UPSERT_1M = """
    INSERT INTO intraday_bars (ticker, datetime, open, high, low, close, volume)
    VALUES %s
    ON CONFLICT (ticker, datetime) DO UPDATE SET
        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
        close=EXCLUDED.close, volume=EXCLUDED.volume
"""

UPSERT_5M = """
    INSERT INTO intraday_bars_5m (ticker, datetime, open, high, low, close, volume)
    VALUES %s
    ON CONFLICT (ticker, datetime) DO UPDATE SET
        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
        close=EXCLUDED.close, volume=EXCLUDED.volume
"""

def get_count(ticker, table="intraday_bars"):
    p = ph(); conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE ticker={p}", (ticker,))
        return cur.fetchone()['cnt']
    finally:
        return_conn(conn)

def fetch_chunk(ticker, from_ts, to_ts, attempt=1):
    try:
        r = requests.get(
            f"https://eodhd.com/api/intraday/{ticker}.US",
            params={"api_token": config.EODHD_API_KEY, "interval": "1m",
                    "from": from_ts, "to": to_ts, "fmt": "json"},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        bars = []
        for b in data:
            if any(b.get(k) is None for k in ["timestamp","open","high","low","close","volume"]):
                continue
            try:
                bars.append((
                    ticker,
                    datetime.fromtimestamp(b["timestamp"], tz=ET).replace(tzinfo=None),
                    float(b["open"]), float(b["high"]),
                    float(b["low"]),  float(b["close"]),
                    int(b["volume"]),
                ))
            except Exception:
                continue
        return bars
    except requests.exceptions.Timeout:
        if attempt < 3:
            print(f"TIMEOUT(retry {attempt})...", end=" ", flush=True)
            time.sleep(2)
            return fetch_chunk(ticker, from_ts, to_ts, attempt+1)
        print("TIMEOUT(skipping)", end=" ")
        return []
    except Exception as e:
        print(f"ERR({e})", end=" ")
        return []

def bulk_insert(bars, sql=UPSERT_1M):
    if not bars:
        return 0
    conn = get_conn()
    try:
        execute_values(conn.cursor(), sql, bars, page_size=500)
        conn.commit()
        return len(bars)
    except Exception as e:
        conn.rollback()
        print(f"INSERT ERR: {e}")
        return 0
    finally:
        return_conn(conn)

def materialize_5m(all_bars_1m):
    from collections import defaultdict
    buckets = defaultdict(list)
    for row in all_bars_1m:
        ticker, dt, o, h, l, c, v = row
        floored = dt.replace(minute=(dt.minute // 5)*5, second=0, microsecond=0)
        buckets[(ticker, floored)].append(row)
    bars_5m = []
    for (ticker, ts) in sorted(buckets):
        bkt = buckets[(ticker, ts)]
        bars_5m.append((
            ticker, ts,
            bkt[0][2],                      # open
            max(b[3] for b in bkt),         # high
            min(b[4] for b in bkt),         # low
            bkt[-1][5],                     # close
            sum(b[6] for b in bkt),         # volume
        ))
    return bars_5m

if __name__ == "__main__":
    now_et         = datetime.now(ET)
    today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    days_back      = 90
    chunk_days     = 7

    print(f"\n[BACKFILL] {days_back} days in {chunk_days}-day chunks | {len(TICKERS)} tickers\n")

    for ticker in TICKERS:
        before = get_count(ticker)
        print(f"[{ticker}] {before:,} bars existing")

        all_bars = []
        cursor_end = today_midnight

        for _ in range(days_back // chunk_days + 1):
            cursor_start = max(
                cursor_end - timedelta(days=chunk_days),
                today_midnight - timedelta(days=days_back)
            )
            from_ts = int(cursor_start.timestamp())
            to_ts   = int((cursor_end - timedelta(seconds=1)).timestamp())

            print(f"  {cursor_start.date()}→{cursor_end.date()} ...", end=" ", flush=True)
            bars = fetch_chunk(ticker, from_ts, to_ts)
            stored = bulk_insert(bars)
            all_bars.extend(bars)
            print(f"{len(bars)} fetched | {stored} stored")

            cursor_end = cursor_start
            if cursor_end <= today_midnight - timedelta(days=days_back):
                break
            time.sleep(0.3)

        bars_5m = materialize_5m(all_bars)
        stored_5m = bulk_insert(bars_5m, sql=UPSERT_5M)
        after = get_count(ticker)
        print(f"[{ticker}] ✅ {before:,}→{after:,} (+{after-before:,}) | 5m materialized: {stored_5m}\n")

    print("[BACKFILL] Complete.")
