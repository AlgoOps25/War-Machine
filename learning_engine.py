# learning_engine.py — STABLE AUTO-POLICY ENGINE

import sqlite3
import time
import threading
import os
import learning_policy

DB_PATH = os.getenv("LEARNING_DB_PATH", "war_machine_trades.db")
ANALYZE_INTERVAL = int(os.getenv("LEARNING_ANALYZE_INTERVAL", "3600"))
MIN_TRADES_TO_LEARN = int(os.getenv("LEARNING_MIN_TRADES", "5"))

def compute_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT ticker, outcome FROM trades")
        rows = c.fetchall()
        conn.close()
    except:
        return None

    if not rows:
        return None

    total = len(rows)
    wins = 0
    ticker_stats = {}

    for ticker, outcome in rows:
        if outcome in ("T1","T2"):
            wins += 1

        s = ticker_stats.setdefault(ticker, {"trades":0,"wins":0})
        s["trades"] += 1
        if outcome in ("T1","T2"):
            s["wins"] += 1

    ticker_boosts = {}
    for t, s in ticker_stats.items():
        if s["trades"] >= 3:
            wr = s["wins"]/s["trades"]
            mult = 1.0 + ((wr-0.6)*0.8)
            mult = max(0.5, min(1.5, round(mult,3)))
            ticker_boosts[t] = mult

    overall_wr = wins/total if total else 0

    return {
        "total": total,
        "wr": overall_wr,
        "ticker_boosts": ticker_boosts
    }

def analyze_and_update():
    stats = compute_stats()
    if not stats:
        return None

    if stats["total"] < MIN_TRADES_TO_LEARN:
        return None

    wr = stats["wr"]

    if wr > 0.7:
        min_conf = 0.88
    elif wr > 0.6:
        min_conf = 0.82
    else:
        min_conf = 0.72

    updates = {
        "min_confidence": min_conf,
        "ticker_boosts": stats["ticker_boosts"]
    }

    return learning_policy.update_policy(updates, smoothing=0.3)

def loop():
    print("🧠 Learning engine started")

    while True:
        try:
            res = analyze_and_update()
            if res:
                print("🧠 Policy updated")
            else:
                print("🧠 Waiting for trades...")
        except Exception as e:
            print("learning error:", e)

        time.sleep(ANALYZE_INTERVAL)

def start_background():
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
