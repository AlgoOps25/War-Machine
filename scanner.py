# scanner.py - main scanner loop (safe, self-contained)
import os
import time
import requests
from datetime import datetime
from scanner_helpers import get_intraday_bars_for_logger
import sniper
import math

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
TOP_SCAN_COUNT = int(os.getenv("TOP_SCAN_COUNT", "10"))
MARKET_CAP_MIN = int(os.getenv("MARKET_CAP_MIN", "2000000000"))

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        print(msg)
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception as e:
        print("discord send error:", e)

def screener_top_by_marketcap(limit=200, min_market_cap=2000000000):
    try:
        url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{min_market_cap}&limit={limit}&exchange=US"
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return []
        return r.json().get("data", []) or []
    except Exception as e:
        print("screener error:", e)
        return []

def score_stock_quick(rec):
    try:
        change = float(rec.get("change_p", 0) or 0)
        volume = float(rec.get("volume", 0) or 0)
        avgvol = float(rec.get("avgVolume", 1) or 1)
        relvol = volume / avgvol if avgvol > 0 else 0
        score = abs(change) * 1.8 + relvol * 2.2
        return score, relvol, change
    except:
        return 0,0,0

def scan_cycle():
    data = screener_top_by_marketcap(limit=500, min_market_cap=MARKET_CAP_MIN)
    pool = []
    for rec in data[:500]:
        try:
            code = rec.get("code")
            s, rv, ch = score_stock_quick(rec)
            if s > 4 and rv > 1.2:
                pool.append((code, s, rv, ch))
        except:
            continue
    pool.sort(key=lambda x: x[1], reverse=True)
    top = [p[0] for p in pool[:TOP_SCAN_COUNT]]
    now = datetime.utcnow().isoformat()
    if top:
        send_discord(f"🔥 Top movers @ {now}: " + ", ".join(top))
    else:
        send_discord("No strong movers detected.")
    # hand to sniper
    for t in top:
        try:
            sniper.process_ticker(t)
        except Exception as e:
            print("process_ticker error:", e)
            # don't crash scanner

def start_scanner_loop():
    print("Scanner loop started")
    # start sniper monitor thread (if not started already)
    try:
        sniper.start_fast_monitor()
    except Exception:
        pass
    while True:
        try:
            scan_cycle()
        except Exception as e:
            print("scan_cycle error:", e)
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_scanner_loop()