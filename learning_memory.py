# learning_memory.py — GOD MODE LEARNING CORE
import sqlite3
from datetime import datetime

DB = "market_memory.db"

def conn():
    return sqlite3.connect(DB)

def init():
    c = conn().cursor()

    # individual trades
    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        direction TEXT,
        timeframe TEXT,
        grade TEXT,
        result TEXT,
        timestamp TEXT
    )
    """)

    # aggregated stats
    c.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        key TEXT PRIMARY KEY,
        wins INTEGER,
        losses INTEGER
    )
    """)

    conn().commit()

init()

# ===============================
# LOG TRADE
# ===============================
def log_trade(ticker, direction, timeframe, grade, result):
    try:
        db = conn()
        c = db.cursor()

        c.execute("""
        INSERT INTO trades
        (ticker,direction,timeframe,grade,result,timestamp)
        VALUES (?,?,?,?,?,?)
        """,(ticker,direction,timeframe,grade,result,datetime.utcnow().isoformat()))

        db.commit()
        db.close()
    except Exception as e:
        print("learning log error:", e)

# ===============================
# UPDATE RESULT (WIN/LOSS)
# ===============================
def update_result(ticker, timeframe, grade, result):
    try:
        key = f"{timeframe}_{grade}"

        db = conn()
        c = db.cursor()

        c.execute("SELECT wins,losses FROM stats WHERE key=?", (key,))
        row = c.fetchone()

        if not row:
            wins, losses = 0,0
        else:
            wins, losses = row

        if result == "WIN":
            wins += 1
        else:
            losses += 1

        c.execute("""
        INSERT OR REPLACE INTO stats (key,wins,losses)
        VALUES (?,?,?)
        """,(key,wins,losses))

        db.commit()
        db.close()
    except Exception as e:
        print("stat update error:", e)

# ===============================
# GET CONFIDENCE BOOST
# ===============================
def get_confidence_boost(timeframe, grade):
    try:
        key = f"{timeframe}_{grade}"

        db = conn()
        c = db.cursor()
        c.execute("SELECT wins,losses FROM stats WHERE key=?", (key,))
        row = c.fetchone()
        db.close()

        if not row:
            return 0

        wins, losses = row
        total = wins + losses
        if total < 5:
            return 0

        winrate = wins / total

        # boost or punish
        if winrate > 0.7:
            return 0.15
        if winrate > 0.6:
            return 0.08
        if winrate < 0.4:
            return -0.15
        if winrate < 0.5:
            return -0.08

        return 0
    except:
        return 0

def get_ticker_score(ticker):
    try:
        import sqlite3
        conn = sqlite3.connect("war_machine_trades.db")
        c = conn.cursor()

        c.execute("SELECT outcome FROM trades WHERE ticker=?", (ticker,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return 0

        wins = sum(1 for r in rows if r[0] in ("T1","T2"))
        wr = wins / len(rows)

        return (wr - 0.5) * 4  # boost/penalty
    except:
        return 0
