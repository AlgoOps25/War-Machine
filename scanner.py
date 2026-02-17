# scanner.py - WAR MACHINE institutional scanner (FINAL STABLE)
import os
import time
import requests
import sqlite3
import math
from datetime import datetime, time as dtime
import pytz
import json

import incremental_fetch
import sniper

############################################
# CONFIG
############################################

try:
    import config
except:
    config = None

EODHD_API_KEY = os.getenv("EODHD_API_KEY") or getattr(config, "EODHD_API_KEY", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK") or getattr(config, "DISCORD_WEBHOOK", "")

TOP_SCAN_COUNT = 10
MARKET_CAP_MIN = 5_000_000_000
SCAN_INTERVAL = 60

PREMARKET_START = (6, 0)   # 6:00am EST recommended start
MARKET_CLOSE = (16, 0)

MIN_REL_VOL = 1.5
OPTIONS_CACHE_TTL = 90
PER_TICKER_SLEEP = 0.35

EST = pytz.timezone("US/Eastern")
_options_cache = {}

############################################
# DISCORD
############################################

def send_discord(msg):
    print(msg)
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except:
        pass

############################################
# DATABASE
############################################

def init_db():
    conn = sqlite3.connect("market_memory.db")
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS prerankers (
        ticker TEXT,
        score REAL,
        options_score REAL,
        relvol REAL,
        timestamp TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

def save_preranker(ticker, score, opt_score, relvol):
    conn = sqlite3.connect("market_memory.db")
    c = conn.cursor()
    c.execute("INSERT INTO prerankers VALUES (?,?,?,?,?)",
              (ticker, score, opt_score, relvol, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

############################################
# TIME FILTER
############################################

def market_is_active():
    now = datetime.now(EST).time()
    pre = dtime(PREMARKET_START[0], PREMARKET_START[1])
    close = dtime(MARKET_CLOSE[0], MARKET_CLOSE[1])
    return pre <= now <= close

############################################
# EODHD SCREENER (FIXED)
############################################

def screener_top(limit=200):
    url = "https://eodhd.com/api/screener"

    payload = {
        "api_token": EODHD_API_KEY,
        "filters": json.dumps([
            {"field": "market_capitalization", "operator": ">", "value": MARKET_CAP_MIN},
            {"field": "exchange", "operator": "=", "value": "US"}
        ]),
        "sort": json.dumps([
            {"field": "volume", "direction": "desc"}
        ]),
        "limit": limit
    }

    try:
        r = requests.get(url, params=payload, timeout=20)
        if r.status_code != 200:
            print("screener error", r.status_code, r.text[:200])
            return []

        data = r.json()
        return data.get("data", [])
    except Exception as e:
        print("screener fail:", e)
        return []

############################################
# OPTIONS FETCH (REAL FIX)
############################################

def fetch_options_for_ticker(ticker):
    if not EODHD_API_KEY:
        return []

    now = time.time()
    if ticker in _options_cache:
        ts, data = _options_cache[ticker]
        if now - ts < OPTIONS_CACHE_TTL:
            return data

    symbols = [f"{ticker}.US", ticker]

    for sym in symbols:
        url = f"https://eodhd.com/api/unicornbay/options/{sym}?api_token={EODHD_API_KEY}&fmt=json"

        try:
            r = requests.get(url, timeout=15)

            if r.status_code == 200:
                data = r.json()

                if isinstance(data, dict):
                    if "data" in data and "options" in data["data"]:
                        result = data["data"]["options"]
                    elif "options" in data:
                        result = data["options"]
                    else:
                        result = []

                    _options_cache[ticker] = (now, result)
                    return result

            else:
                print(f"options http {r.status_code} {sym}")

        except Exception as e:
            print("options error:", e)

    return []

############################################
# OPTIONS ANALYSIS
############################################

def analyze_options_flow(opts):
    if not opts:
        return False, 0, False

    total = 0
    premium_total = 0
    sweep = False

    for o in opts[:150]:
        try:
            vol = float(o.get("volume", 0))
            price = float(o.get("lastPrice", 0))
            prem = vol * price

            total += vol
            premium_total += prem

            if prem > 50000 or vol > 1500:
                sweep = True

        except:
            continue

    if total == 0:
        return False, 0, False

    score = math.log10(total + 10) + (premium_total / 150000)

    unusual = score > 2 or sweep
    return unusual, score, sweep

############################################
# BUILD WATCHLIST
############################################

def build_watchlist():

    recs = screener_top()
    if not recs:
        send_discord("⚠️ Screener failed — fallback list used")
        return ["SPY","QQQ","NVDA","TSLA","META","AAPL","MSFT"]

    pool = []

    for r in recs:
        try:
            t = r["code"]
            vol = float(r.get("volume", 0))
            avg = float(r.get("avgVolume", 1))
            rel = vol/avg if avg else 0
            change = abs(float(r.get("change_p",0)))

            score = rel*2 + change

            if rel >= MIN_REL_VOL or change > 1:
                pool.append((t, score, rel))
        except:
            pass

    pool.sort(key=lambda x: x[1], reverse=True)
    candidates = [x[0] for x in pool[:30]]

    strong = []

    for t in candidates:
        try:
            incremental_fetch.update_ticker(t)

            opts = fetch_options_for_ticker(t)
            unusual, opt_score, sweep = analyze_options_flow(opts)

            if sweep:
                send_discord(f"🐳 OPTIONS SWEEP: {t}")

            final = opt_score + 1
            strong.append((t, final))

            save_preranker(t, final, opt_score, 1)

            time.sleep(PER_TICKER_SLEEP)

        except Exception as e:
            print("watchlist err", t, e)

    strong.sort(key=lambda x: x[1], reverse=True)

    final = [x[0] for x in strong[:TOP_SCAN_COUNT]]

    if not final:
        final = candidates[:TOP_SCAN_COUNT]

    return final

############################################
# MAIN SCAN
############################################

def scan_cycle():

    if not market_is_active():
        send_discord("Captain Hook: Waiting for premarket")
        return

    send_discord("🔥 Building institutional watchlist")

    watch = build_watchlist()

    send_discord("🔥 WATCHLIST: " + ", ".join(watch))

    for t in watch:
        try:
            incremental_fetch.update_ticker(t)
            sniper.process_ticker(t)
        except Exception as e:
            send_discord(f"Error {t}: {e}")

############################################
# LOOP
############################################

def start_scanner_loop():
    send_discord("⚔️ WAR MACHINE ONLINE")
    print("scanner started")

    while True:
        try:
            scan_cycle()
        except Exception as e:
            send_discord(f"Scanner crash: {e}")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_scanner_loop()
