# trade_logger.py
import sqlite3
import threading
import time
from datetime import datetime
import os
from eodhd_api import get_intraday_bars
from discord_bot import send
import config

DB_PATH = os.getenv("LEARNING_DB_PATH", "war_machine_trades.db")
POLL_SECONDS = 15

def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        direction TEXT,
        grade TEXT,
        entry_price REAL,
        entry_ts TEXT,
        stop_price REAL,
        t1_price REAL,
        t2_price REAL,
        chosen_target TEXT,
        outcome TEXT,
        outcome_ts TEXT
    )
    """)
    conn.commit()
    conn.close()

def log_confirmed_trade(ticker, direction, grade, entry_price, entry_ts, stop_price, t1_price, t2_price, chosen):
    ensure_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO trades
                 (ticker, direction, grade, entry_price, entry_ts, stop_price, t1_price, t2_price, chosen_target, outcome)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""",
              (ticker, direction, grade, entry_price, entry_ts, stop_price, t1_price, t2_price, chosen, None))
    conn.commit()
    trade_id = c.lastrowid
    conn.close()
    send(f"💾 Logged trade {ticker} id={trade_id} entry={entry_price} grade={grade}")
    return trade_id

def update_trade_outcome(trade_id, outcome, exit_price):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""UPDATE trades SET outcome=?, outcome_ts=? WHERE id=?""",
              (outcome, datetime.utcnow().isoformat(), trade_id))
    conn.commit()
    conn.close()
    send(f"📈 Trade {trade_id} result: {outcome} @ {exit_price}")

def load_open_trades():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, ticker, direction, entry_price, stop_price, t1_price, t2_price, chosen_target FROM trades WHERE outcome IS NULL""")
    rows = c.fetchall()
    conn.close()
    return rows

def monitor_thread_loop():
    ensure_db()
    print("Trade logger monitor started")
    while True:
        try:
            rows = load_open_trades()
            for r in rows:
                trade_id, ticker, direction, entry_price, stop_price, t1_price, t2_price, chosen = r
                bars = get_intraday_bars(ticker, interval="1m", limit=120)
                if not bars:
                    continue
                highs = [float(b.get("high") or b.get("High") or 0) for b in bars]
                lows = [float(b.get("low") or b.get("Low") or 0) for b in bars]
                max_high = max(highs) if highs else None
                min_low = min(lows) if lows else None
                if direction == "bull":
                    if chosen == "t2" and t2_price and max_high and max_high >= t2_price:
                        update_trade_outcome(trade_id, "T2", t2_price)
                        continue
                    if t1_price and max_high and max_high >= t1_price:
                        update_trade_outcome(trade_id, "T1", t1_price)
                        continue
                    if stop_price and min_low and min_low <= stop_price:
                        update_trade_outcome(trade_id, "STOP", stop_price)
                        continue
                else:
                    if chosen == "t2" and t2_price and min_low and min_low <= t2_price:
                        update_trade_outcome(trade_id, "T2", t2_price)
                        continue
                    if t1_price and min_low and min_low <= t1_price:
                        update_trade_outcome(trade_id, "T1", t1_price)
                        continue
                    if stop_price and max_high and max_high >= stop_price:
                        update_trade_outcome(trade_id, "STOP", stop_price)
                        continue
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print("Trade logger monitor error:", e)
            time.sleep(POLL_SECONDS)

def start_monitor_thread():
    t = threading.Thread(target=monitor_thread_loop, daemon=True)
    t.start()
    return t