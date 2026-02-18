"""
Scanner Helpers - Data Fetching and Caching
Provides bar retrieval, dark pool analysis, and screener functions.
"""
import requests
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict
import config

# ── Constants ────────────────────────────────────────────────────────────────
DB_PATH = "market_memory.db"
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")


# ── Database Init ─────────────────────────────────────────────────────────────
def init_memory_db():
    """Initialize SQLite database for bar caching."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            datetime    TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            timeframe   TEXT DEFAULT '1m',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, datetime, timeframe)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticker_datetime
        ON bars(ticker, datetime DESC)
    """)
    conn.commit()
    conn.close()


# Initialize on module load
init_memory_db()


# ── Bar Storage ───────────────────────────────────────────────────────────────
def insert_bars_to_memory(ticker: str, bars: List[Dict]):
    """Insert bars into SQLite memory cache."""
    if not bars:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for bar in bars:
        try:
            dt = bar["datetime"]
            dt_str = dt.isoformat() if isinstance(dt, datetime) else str(dt)
            cursor.execute("""
                INSERT OR IGNORE INTO bars
                    (ticker, datetime, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, dt_str, bar["open"], bar["high"],
                  bar["low"], bar["close"], bar["volume"]))
        except Exception as e:
            print(f"[DB] Error inserting bar for {ticker}: {e}")
            continue
    conn.commit()
    conn.close()


def get_recent_bars_from_memory(ticker: str, limit: int = 300) -> List[Dict]:
    """
    Retrieve recent bars from SQLite memory cache.
    Returns list of bar dicts in chronological order (oldest first).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT datetime, open, high, low, close, volume
        FROM bars
        WHERE ticker = ?
        ORDER BY datetime DESC
        LIMIT ?
    """, (ticker, limit))
    rows = cursor.fetchall()
    conn.close()

    bars = []
    for row in rows:
        try:
            bars.append({
                "datetime": datetime.fromisoformat(row[0]),
                "open":     float(row[1]),
                "high":     float(row[2]),
                "low":      float(row[3]),
                "close":    float(row[4]),
                "volume":   int(row[5])
            })
        except Exception as e:
            print(f"[DB] Error parsing bar for {ticker}: {e}")
            continue

    # Return chronological order (oldest → newest)
    return list(reversed(bars))


# ── EODHD Intraday Fetch (FIXED: Unix timestamps) ─────────────────────────────
def fetch_intraday_bars(ticker: str, interval: str = "1m",
                        days_back: int = 5) -> List[Dict]:
    """
    Fetch intraday bars from EODHD API.

    FIX: EODHD intraday endpoint requires Unix timestamps for from/to,
         NOT YYYY-MM-DD strings. Using date strings causes 422 errors.
    """
    api_key = EODHD_API_KEY or getattr(config, "EODHD_API_KEY", "")

    # Build Unix timestamps
    now_dt   = datetime.utcnow()
    from_dt  = now_dt - timedelta(days=days_back)
    from_ts  = int(from_dt.timestamp())
    to_ts    = int(now_dt.timestamp())

    url = f"https://eodhd.com/api/intraday/{ticker}.US"
    params = {
        "api_token": api_key,
        "interval":  interval,
        "from":      from_ts,   # ← Unix timestamp (int), NOT "YYYY-MM-DD"
        "to":        to_ts,     # ← Unix timestamp (int), NOT "YYYY-MM-DD"
        "fmt":       "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        bars = []
        for bar in data:
            try:
                bars.append({
                    "datetime": datetime.utcfromtimestamp(bar["timestamp"]),
                    "open":     float(bar["open"]),
                    "high":     float(bar["high"]),
                    "low":      float(bar["low"]),
                    "close":    float(bar["close"]),
                    "volume":   int(bar["volume"])
                })
            except Exception as e:
                print(f"[FETCH] Bar parse error for {ticker}: {e}")
                continue

        print(f"[FETCH] {ticker}: {len(bars)} bars fetched")
        return bars

    except requests.exceptions.HTTPError as e:
        print(f"[FETCH] ❌ API Error for {ticker}: {e}")
        return []
    except Exception as e:
        print(f"[FETCH] ❌ Unexpected error for {ticker}: {e}")
        return []


# ── Dark Pool ─────────────────────────────────────────────────────────────────
def get_dark_pool_trades(ticker: str, limit: int = 50) -> List[Dict]:
    """Fetch dark pool trades from EODHD."""
    api_key = EODHD_API_KEY or getattr(config, "EODHD_API_KEY", "")
    try:
        url = f"https://eodhd.com/api/dark-pool/{ticker}.US"
        params = {"api_token": api_key, "limit": limit, "fmt": "json"}
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            return []
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[DARKPOOL] Error fetching {ticker}: {e}")
        return []


def analyze_dark_pool(ticker: str) -> Dict:
    """Analyze dark pool activity for a ticker."""
    trades = get_dark_pool_trades(ticker)
    if not trades:
        return {"active": False, "score": 0, "total_value": 0}

    total_value = 0
    big_prints  = 0

    for trade in trades[:50]:
        try:
            size  = float(trade.get("size",  0))
            price = float(trade.get("price", 0))
            value = size * price
            total_value += value
            if value >= 200_000:
                big_prints += 1
        except Exception:
            continue

    score = (total_value / 1_000_000) + (big_prints * 2)
    accumulation = score >= 2 or big_prints >= 3

    return {
        "active":      accumulation,
        "score":       round(score, 2),
        "total_value": round(total_value, 2),
        "big_prints":  big_prints
    }


# ── Screener ──────────────────────────────────────────────────────────────────
def get_screener_tickers(min_market_cap: int = 1_000_000_000,
                         limit: int = 50) -> List[str]:
    """
    Fetch top tickers from EODHD screener based on market cap and volume.
    Returns list of ticker symbols.
    """
    api_key = EODHD_API_KEY or getattr(config, "EODHD_API_KEY", "")
    url = "https://eodhd.com/api/screener"
    params = {
        "api_token": api_key,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume",                ">=", 1_000_000],
            ["exchange",              "=",  "US"]
        ]),
        "limit": limit,
        "sort":  "volume.desc"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        tickers = []
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                code = item.get("code", "")
                if code:
                    tickers.append(code.replace(".US", ""))

        print(f"[SCREENER] Fetched {len(tickers)} tickers")
        return tickers[:limit]

    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []


# ── Legacy Compatibility Shims ────────────────────────────────────────────────
# These aliases keep old call sites working without changes

def fetch_new_bars_from_eodhd(ticker: str, limit: int = 200,
                               interval: str = "1m") -> List[Dict]:
    """Legacy alias → fetch_intraday_bars"""
    return fetch_intraday_bars(ticker, interval=interval)


def get_intraday_bars_for_logger(ticker: str, limit: int = 400,
                                  interval: str = "1m") -> List[Dict]:
    """Legacy smart loader: fetch fresh + store + return from DB."""
    new_bars = fetch_intraday_bars(ticker, interval=interval)
    if new_bars:
        insert_bars_to_memory(ticker, new_bars)
    return get_recent_bars_from_memory(ticker, limit=limit)


def store_bars(ticker: str, bars: List[Dict]):
    """Legacy alias → insert_bars_to_memory"""
    insert_bars_to_memory(ticker, bars)


def load_recent_from_db(ticker: str, limit: int = 400) -> List[Dict]:
    """Legacy alias → get_recent_bars_from_memory"""
    return get_recent_bars_from_memory(ticker, limit=limit)
