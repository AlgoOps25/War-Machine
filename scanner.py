# scanner.py
# Momentum scanner that selects top movers and hands them to sniper.process_ticker
import time
from eodhd_api import screener_top_by_marketcap
import config
from discord_bot import send
from sniper.py import process_ticker  # careful: if import error, use from .sniper import process_ticker
# Note: in some environments, relative imports are needed. Adjust import if Railway complains.

def score_stock_quick(rec):
    try:
        price = float(rec.get("close", 0) or 0)
        change = float(rec.get("change_p", 0) or 0)
        volume = float(rec.get("volume", 0) or 0)
        avgvol = float(rec.get("avgvol_200d", rec.get("avgVolume", 1) or 1) or 1)
        relvol = volume / avgvol if avgvol > 0 else 0
        score = abs(change) * 1.8 + relvol * 2.2
        return score, relvol, change, price
    except:
        return 0,0,0,0

def scan_cycle():
    data = screener_top_by_marketcap(limit=config.MAX_UNIVERSE, min_market_cap=config.MARKET_CAP_MIN)
    pool = []
    for rec in data[:config.TOP_SCAN_COUNT]:
        try:
            code = rec.get("code")
            s, rv, ch, price = score_stock_quick(rec)
            if s > 6 and rv > config.RETEST_MIN_RELVOL:
                pool.append((code, s, rv, ch, price))
        except:
            continue
    pool.sort(key=lambda x: x[1], reverse=True)
    top = [p[0] for p in pool[:config.TOP_MOMENTUM_COUNT]]
    # publish top list once per cycle
    if top:
        msg = "🔥 WAR MACHINE — ELITE TOP MOVERS\n\n"
        for t in top:
            msg += f"{t}\n"
        send(msg)
    # hand to sniper: process concurrently or sequentially (sequential to reduce API load)
    for tkr in top:
        try:
            process_ticker(tkr)
        except Exception as e:
            print("process_ticker error:", e)

def start_scanner_loop():
    print("Scanner loop started")
    while True:
        try:
            scan_cycle()
        except Exception as e:
            print("scan_cycle error:", e)
        time.sleep(config.SCAN_INTERVAL)
