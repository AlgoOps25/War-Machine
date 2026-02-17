# scanner.py - War Machine premarket+market top-mover scanner (options-aware)
import os
import time
import requests
import sqlite3
import math
from datetime import datetime, time as dtime
import pytz
import json

# existing modules in your repo
import incremental_fetch
import sniper
from memory_reader import get_recent_bars_from_memory

def init_prerank_db():
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

init_prerank_db()

def save_preranker(ticker, score, opt_score, relvol):
    conn = sqlite3.connect("market_memory.db")
    c = conn.cursor()
    c.execute("""
    INSERT INTO prerankers (ticker, score, options_score, relvol, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """, (ticker, score, opt_score, relvol, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def load_hot_prerankers(limit=10):
    conn = sqlite3.connect("market_memory.db")
    c = conn.cursor()
    c.execute("""
    SELECT ticker, AVG(score) as s
    FROM prerankers
    GROUP BY ticker
    ORDER BY s DESC
    LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# centralize config convenience (if you have config.py)
try:
    import config
except Exception:
    config = None

EODHD_API_KEY = os.getenv("EODHD_API_KEY") or (getattr(config, "EODHD_API_KEY", "") if config else "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK") or (getattr(config, "DISCORD_WEBHOOK", "") if config else "")

# Operation params (override in config.py or env)
TOP_SCAN_COUNT = int(os.getenv("TOP_SCAN_COUNT", getattr(config, "TOP_SCAN_COUNT", 10) if config else 10))
MARKET_CAP_MIN = int(os.getenv("MARKET_CAP_MIN", getattr(config, "MARKET_CAP_MIN", 10_000_000_000) if config else 10_000_000_000))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", getattr(config, "SCAN_INTERVAL", 60) if config else 60))
PREMARKET_START_HOUR = int(os.getenv("PREMARKET_START_HOUR", getattr(config, "PREMARKET_START_HOUR", 3) if config else 3))  # 3 => 03:00
PREMARKET_START_MIN = int(os.getenv("PREMARKET_START_MIN", getattr(config, "PREMARKET_START_MIN", 30) if config else 30))  # 03:30
MARKET_CLOSE_HOUR = int(os.getenv("MARKET_CLOSE_HOUR", getattr(config, "MARKET_CLOSE_HOUR", 16) if config else 16))
MIN_REL_VOL = float(os.getenv("MIN_REL_VOL", "1.5"))  # underlying relative volume threshold
OPTIONS_VOL_MULT = float(os.getenv("OPTIONS_VOL_MULT", "2.0"))  # options vol multiplier threshold
OPTIONS_CACHE_TTL = int(os.getenv("OPTIONS_CACHE_TTL", "60"))  # seconds to cache options response per ticker
EODHD_BASE = "https://eodhd.com/api"
ELITE_LIMIT = 3
WATCHLIST_LIMIT = 10

# timezone
EST = pytz.timezone("US/Eastern")

# small throttle to avoid hitting limits when scanning many tickers
PER_TICKER_SLEEP = float(os.getenv("PER_TICKER_SLEEP", "0.35"))

# simple in-memory cache for options data {ticker: (fetched_at_epoch, data)}
_options_cache = {}

def send_discord(msg: str):
    if not DISCORD_WEBHOOK:
        print(msg)
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception as e:
        print("discord send error:", e)

def market_is_open_or_premarket():
    now = datetime.now(EST).time()
    pre_start = dtime(PREMARKET_START_HOUR, PREMARKET_START_MIN)
    market_open = dtime(9, 30)
    market_close = dtime(MARKET_CLOSE_HOUR, 0)
    # active window: pre_start .. market_close
    return pre_start <= now <= market_close

def screener_top_by_marketcap(limit=200, min_market_cap=MARKET_CAP_MIN):
    """
    Use EODHD screener to pull US large caps ordered by % change / volume.
    """
    if not EODHD_API_KEY:
        print("No EODHD_API_KEY set")
        return []

    url = f"{EODHD_BASE}/screener"
    filters = [
        ["market_cap", ">", min_market_cap],
        ["exchange", "=", "US"]
    ]

    params = {
        "api_token": EODHD_API_KEY,
        "limit": limit,
        "sort": "change_percent",
        "order": "desc",
        "filters": json.dumps(filters)
    }
    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            print("screener http", r.status_code, r.text[:200])
            return []
        data = r.json()
        # some responses return list, some return dict->data
        if isinstance(data, dict) and "data" in data:
            recs = data["data"] or []
        elif isinstance(data, list):
            recs = data
        else:
            recs = []
        return recs
    except Exception as e:
        print("screener error:", e)
        return []

def score_stock_quick(rec):
    """
    Quick heuristic score using pct change and relative volume if available in screener result.
    """
    try:
        change = float(rec.get("change_p", 0) or 0)
        volume = float(rec.get("volume", 0) or 0)
        avgvol = float(rec.get("avgVolume", 1) or 1)
        relvol = volume / avgvol if avgvol > 0 else 0
        score = abs(change) * 1.8 + relvol * 2.2
        return score, relvol, change
    except:
        return 0, 0, 0

def get_top_candidates():
    """
    Build candidate list from screener, filtered by relative volume threshold.
    Returns list of tickers (strings).
    """
    recs = screener_top_by_marketcap(limit=500, min_market_cap=MARKET_CAP_MIN)
    pool = []
    for rec in recs:
        try:
            code = rec.get("code")
            s, rv, ch = score_stock_quick(rec)
            # prefer large relative volume or decent change
            if rv >= MIN_REL_VOL or abs(ch) >= 0.5:
                pool.append((code, s, rv, ch))
        except:
            continue
    pool.sort(key=lambda x: x[1], reverse=True)
    top = [p[0] for p in pool[:TOP_SCAN_COUNT * 3]]  # fetch extra for options filter
    return list(dict.fromkeys(top))[:TOP_SCAN_COUNT]  # dedupe preserve order, crop to TOP_SCAN_COUNT

def fetch_options_for_ticker(ticker):
    """
    Fetch options summary for ticker from EODHD Options API.
    Caches results for OPTIONS_CACHE_TTL seconds to avoid hammering.
    """
    if not EODHD_API_KEY:
        return None

    now_ts = time.time()
    cached = _options_cache.get(ticker)
    if cached and (now_ts - cached[0]) < OPTIONS_CACHE_TTL:
        return cached[1]

    # Example endpoint (EODHD docs): /options/{symbol}.US?api_token=...
    # Adjust to your plan endpoints if different.
    url = f"{EODHD_BASE}/options/{ticker}.US"
    params = {"api_token": EODHD_API_KEY, "fmt": "json", "limit": 100}
    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            print(f"options http {r.status_code} for {ticker} -> {r.text[:200]}")
            _options_cache[ticker] = (now_ts, None)
            return None
        data = r.json()
        # shape may be {"data":[...]} or list
        if isinstance(data, dict) and "data" in data:
            opt = data["data"] or []
        elif isinstance(data, list):
            opt = data
        else:
            opt = []
        _options_cache[ticker] = (now_ts, opt)
        # small throttle
        time.sleep(PER_TICKER_SLEEP)
        return opt
    except Exception as e:
        print("options fetch error:", e)
        _options_cache[ticker] = (now_ts, None)
        return None

def analyze_options_flow(opt_bars):
    if not opt_bars:
        return False, 0, False

    total_vol = 0
    call_vol = 0
    put_vol = 0
    sweep_detected = False
    large_trade = 0

    for o in opt_bars[:200]:
        try:
            vol = float(o.get("volume") or o.get("Volume") or 0)
            typ = str(o.get("type") or o.get("optionType") or "").lower()
            premium = float(o.get("premium") or o.get("lastPrice") or 0) * vol

            total_vol += vol

            if "call" in typ:
                call_vol += vol
            if "put" in typ:
                put_vol += vol

            # sweep detection
            if premium > 50000 or vol > 1000:
                sweep_detected = True
                large_trade += premium

        except:
            continue

    if total_vol == 0:
        return False, 0, False

    flow_ratio = (call_vol + 1) / (put_vol + 1)
    bullish_flow = flow_ratio > 1.5
    bearish_flow = flow_ratio < 0.6

    score = math.log10(total_vol + 10) + (large_trade / 100000)

    unusual = score > 2 or sweep_detected

    return unusual, score, sweep_detected

# ===== DARK POOL =====
from scanner_helpers import get_darkpool_trades, analyze_darkpool

dark_trades = get_darkpool_trades()
dark_accum, dark_score = analyze_darkpool(dark_trades)

def has_volume_surge_underlying(ticker):
    """
    Compute recent relative volume from memory DB (compare last 5 bars vs prior 25).
    """
    try:
        conn = sqlite3.connect("market_memory.db")
        c = conn.cursor()
        c.execute("SELECT volume FROM candles WHERE ticker=? ORDER BY datetime DESC LIMIT 30", (ticker,))
        rows = c.fetchall()
        conn.close()
        if len(rows) < 12:
            return False, 0.0
        vols = [r[0] for r in rows]
        recent = sum(vols[:5]) / 5
        baseline = sum(vols[5:30]) / max(1, len(vols[5:30]))
        if baseline == 0:
            return False, 0.0
        ratio = recent / baseline
        return (ratio >= MIN_REL_VOL), ratio
    except Exception as e:
        print("volume surge error:", e)
        return False, 0.0

def build_watchlist():
    """
    Build top-N watchlist using screener + underlying vol + options flow heuristics.
    ALWAYS returns something.
    """

    candidates = get_top_candidates()

    # fallback if screener fails
    if not candidates:
        print("⚠️ Screener returned nothing — using fallback list")
        candidates = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "META"]

    # inject historical winners
    historical_hot = load_hot_prerankers(6)
    for h in historical_hot:
        if h not in candidates:
            candidates.insert(0, h)

    strong = []

    for t in candidates:
        try:
            incremental_fetch.update_ticker(t)

            # underlying volume check
            vol_ok, ratio = has_volume_surge_underlying(t)

            # options flow
            opts = fetch_options_for_ticker(t)
            unusual, opt_score, sweep = analyze_options_flow(opts)

            if sweep:
                send_discord(f"🐳 OPTIONS SWEEP detected: {t}")

            if vol_ok or unusual or sweep:
                final_score = ratio * (opt_score + 1)
                strong.append((t, final_score))
                save_preranker(t, final_score, opt_score, ratio)

            time.sleep(PER_TICKER_SLEEP)

        except Exception as e:
            print("watchlist error:", t, e)

    strong.sort(key=lambda x: x[1], reverse=True)

    final = [s[0] for s in strong[:TOP_SCAN_COUNT]]

    # final fallback
    if not final:
        final = candidates[:TOP_SCAN_COUNT]

    return final

def scan_cycle():
    # enforce time gate
    if not market_is_open_or_premarket():
        send_discord("Captain Hook: Waiting for premarket (system sleeping)")
        return

    now = datetime.utcnow().isoformat()
    send_discord(f"🔥 Building watchlist @ {now}")
    watch = build_watchlist()
    if not watch:
        send_discord("Captain Hook: No strong movers detected.")
        return

    send_discord("🔥 Top Watchlist: " + ", ".join(watch))

    # hand over to sniper for each symbol
    for t in watch:
        try:
            incremental_fetch.update_ticker(t)
            sniper.process_ticker(t)
        except Exception as e:
            print("process_ticker error for", t, e)
            send_discord(f"❌ ERROR processing {t}: {e}")

def start_scanner_loop():
    print("Scanner loop started (premarket+market)")
    send_discord("⚔️ WAR MACHINE SCANNER STARTING (premarket+market)")

    while True:
        try:
            scan_cycle()
        except Exception as e:
            print("scan loop error:", e)
            send_discord(f"Scanner loop error: {e}")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_scanner_loop()
