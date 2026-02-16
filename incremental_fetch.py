# incremental_fetch.py
import requests
import os
import sqlite3
import time
import json

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DB_FILE = "market_memory.db"

def get_db():
    return sqlite3.connect(DB_FILE, timeout=10)

def fetch_new_bars_from_eodhd(ticker, limit=200, interval="1m", retries=2):
    """
    Robust fetcher: returns list of bars or [].
    Handles both JSON array and {"data": [...]} shapes.
    """
    if not EODHD_API_KEY:
        print("Fetch error: no EODHD_API_KEY set")
        return []

    url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval={interval}&limit={limit}&fmt=json"

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=15)
        except Exception as e:
            print("Fetch error (request):", e)
            time.sleep(1 + attempt)
            continue

        if r.status_code != 200:
            # print first 200 chars of body for debugging
            body_preview = (r.text or "")[:200]
            print(f"Fetch error: HTTP {r.status_code} | {body_preview}")
            # don't retry on 4xx except possibly 429 -> but we still sleep a bit
            time.sleep(1 + attempt)
            continue

        txt = (r.text or "").strip()
        if not txt:
            print("Fetch error: empty response text")
            time.sleep(1 + attempt)
            continue

        # try r.json() first (faster)
        try:
            data = r.json()
        except ValueError:
            # fallback to json.loads for any weird whitespace/BOM cases
            try:
                data = json.loads(txt)
            except Exception as e:
                preview = txt[:300].replace("\n"," ")
                print("Fetch error: invalid JSON response preview:", preview)
                time.sleep(1 + attempt)
                continue

        # normalize shape
        if isinstance(data, dict) and "data" in data:
            bars = data["data"] or []
        elif isinstance(data, list):
            bars = data
        else:
            # unknown shape
            print("Fetch warning: unexpected JSON shape, attempting best-effort conversion")
            # try to coerce dict values to list
            try:
                bars = list(data.values())
            except Exception:
                bars = []

        # ensure list
        if not isinstance(bars, list):
            print("Fetch warning: bars not a list after normalization")
            bars = []

        return bars

    # exhausted retries
    print("Fetch error: retries exhausted, returning []")
    return []


def update_ticker(ticker, limit=200, interval="1m"):
    """
    Pull newest intraday bars for ticker, store only new ones into market_memory.db.
    """
    try:
        bars = fetch_new_bars_from_eodhd(ticker, limit=limit, interval=interval)
        if not bars:
            # nothing new or fetch failed
            return 0

        # normalize incoming bars to dicts that contain datetime/open/high/low/close/volume
        inserted = 0
        conn = get_db()
        c = conn.cursor()

        for b in bars:
            # attempt to read common fields robustly
            ts = b.get("datetime") or b.get("date") or b.get("timestamp")
            if ts is None:
                # if timestamp integer provided, convert to iso-ish (best-effort)
                if b.get("timestamp"):
                    try:
                        ts = str(int(b.get("timestamp")))
                    except:
                        ts = None
                else:
                    ts = None

            if not ts:
                continue

            try:
                o = float(b.get("open") or b.get("Open") or 0)
                h = float(b.get("high") or b.get("High") or 0)
                l = float(b.get("low") or b.get("Low") or 0)
                cl = float(b.get("close") or b.get("Close") or 0)
                v = float(b.get("volume") or b.get("Volume") or 0)
            except Exception:
                # skip malformed bar
                continue

            try:
                c.execute("""
                    INSERT OR IGNORE INTO candles
                    (ticker, datetime, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (ticker, ts, o, h, l, cl, v))
                if c.rowcount:
                    inserted += 1
            except Exception as e:
                # continue on DB errors for individual rows
                # but print minimal debug info
                print("DB insert error for", ticker, ts, e)
                continue

        conn.commit()
        conn.close()

        if inserted:
            print(f"{ticker}: added {inserted} new candles")
        else:
            print(f"{ticker}: added 0 new candles")

        return inserted

    except Exception as e:
        print("update_ticker error:", e)
        return 0
