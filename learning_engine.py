# learning_engine.py
# Periodically analyze trade DB and update policy.json via learning_policy.update_policy
import sqlite3
import time
import threading
import os
from datetime import datetime, timedelta
import learning_policy

DB_PATH = os.getenv("LEARNING_DB_PATH", "war_machine_trades.db")
ANALYZE_INTERVAL = int(os.getenv("LEARNING_ANALYZE_INTERVAL", str(60 * 60)))  # seconds (default 1h)
MIN_TRADES_TO_LEARN = int(os.getenv("LEARNING_MIN_TRADES", "10"))

def _connect():
    return sqlite3.connect(DB_PATH)

def compute_stats():
    """
    Returns statistics needed to update policy:
    - win_rate by timeframe
    - win_rate by ticker
    - average rr per timeframe
    """
    conn = _connect()
    c = conn.cursor()
    # ensure trades table exists
    try:
        c.execute("SELECT id, ticker, grade, entry_price, stop_price, t1_price, t2_price, outcome, entry_ts FROM trades")
    except Exception as e:
        conn.close()
        return None
    rows = c.fetchall()
    conn.close()
    if not rows:
        return None

    # parse
    by_tf = {}
    by_ticker = {}
    total = 0
    wins = 0
    for r in rows:
        total += 1
        tid, ticker, grade, entry_price, stop_price, t1, t2, outcome, entry_ts = r
        # derive timeframe from grade? (grade stored earlier) - ideally grade contained tf but if not, fallback
        # For safety, try to read timeframe stored in a separate column; if not present skip tf stats
        # Here, we'll compute only ticker stats reliably
        if outcome and outcome in ("T1", "T2"):
            wins += 1
        # ticker buckets
        stats = by_ticker.setdefault(ticker, {"trades": 0, "wins": 0})
        stats["trades"] += 1
        if outcome and outcome in ("T1", "T2"):
            stats["wins"] += 1

    # compute win rates
    ticker_boosts = {}
    for t, s in by_ticker.items():
        trades = s["trades"]
        wins_t = s["wins"]
        if trades >= 3:  # need some minimum to trust
            wr = wins_t / trades
            # convert wr into a multiplier around 1.0: map [0.3..0.9] -> [0.7..1.3]
            mult = 1.0 + ((wr - 0.6) * 0.8)
            # clamp
            mult = max(0.5, min(1.5, round(mult, 3)))
            ticker_boosts[t] = mult

    # overall winrate
    overall_wr = wins / total if total else 0.0

    return {
        "total_trades": total,
        "overall_winrate": overall_wr,
        "ticker_boosts": ticker_boosts
    }

def analyze_and_update():
    stats = compute_stats()
    if not stats:
        return None
    # Only update if we have enough trades
    if stats["total_trades"] < MIN_TRADES_TO_LEARN:
        return None

    # propose updates
    # Example: If overall winrate is high, we can increase min_confidence slightly; if low, decrease
    target_min_conf = 0.80
    if stats["overall_winrate"] >= 0.7:
        target_min_conf = min(0.95, 0.85 + (stats["overall_winrate"] - 0.7))
    elif stats["overall_winrate"] >= 0.6:
        target_min_conf = 0.82
    else:
        target_min_conf = max(0.65, 0.78 * stats["overall_winrate"] + 0.4)

    updates = {
        "min_confidence": round(target_min_conf, 4),
        "ticker_boosts": stats["ticker_boosts"]
    }
    new_policy = learning_policy.update_policy(updates, smoothing=0.25)
    return new_policy

def _loop():
    print("Learning engine started (analyzing every", ANALYZE_INTERVAL, "s)")
    while True:
        try:
            res = analyze_and_update()
            if res:
                print("Learning engine updated policy:", res.get("last_updated"))
            else:
                print("Learning engine: not enough data or no changes")
        except Exception as e:
            print("learning_engine error:", e)
        time.sleep(ANALYZE_INTERVAL)

def start_background():
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t