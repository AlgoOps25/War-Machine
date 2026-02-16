# learning_memory.py
import sqlite3
from datetime import datetime

DB = "market_memory.db"

def get_conn():
    return sqlite3.connect(DB)

def init_learning_table():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS setup_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        direction TEXT,
        timeframe TEXT,
        grade TEXT,
        result TEXT,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()

def log_trade_result(ticker, direction, timeframe, grade, result):
    """
    result = WIN / LOSS
    """
    try:
        conn = get_conn()
        c = conn.cursor()

        c.execute("""
        INSERT INTO setup_stats
        (ticker, direction, timeframe, grade, result, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            direction,
            timeframe,
            grade,
            result,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()
    except Exception as e:
        print("learning log error:", e)

def get_stats():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    SELECT timeframe, grade, result, COUNT(*)
    FROM setup_stats
    GROUP BY timeframe, grade, result
    """)

    rows = c.fetchall()
    conn.close()
    return rows

init_learning_table()
