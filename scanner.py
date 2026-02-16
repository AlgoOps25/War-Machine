# scanner.py - War Machine premarket+market top-mover scanner (options-aware)
import os
import time
import requests
import sqlite3
import math
from datetime import datetime, time as dtime
import pytz

# existing modules in your repo
import incremental_fetch
import sniper
from memory_reader import get_recent_bars_from_memory

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
    params = {
        "api_token": EODHD_API_KEY,
        "limit": limit,
        "exchange": "US",
        "sort": "change_percent",  # momentum sorter
        "order": "desc",
        "filters": f"market_cap>{min_market_cap}"
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
    """
    Heuristic to detect 'unusual' options flow:
    - total options volume across strikes in recent time window
    - proportion of buys vs sells (if available)
    Returns True if unusual activity detected and a score.
    """
    if not opt_bars:
        return False, 0.0

    # Example heuristic: sum volumes for last N entries
    total_vol = 0.0
    recent_count = 0
    for o in opt_bars[:120]:  # walk most recent records (depending on EODHD shape)
        try:
            vol = float(o.get("volume") or o.get("Volume") or 0)
            total_vol += vol
            recent_count += 1
        except:
            continue

    if recent_count == 0:
        return False, 0.0

    avg_vol = total_vol / recent_count
    # treat > OPTIONS_VOL_MULT as unusual
    score = avg_vol
    unusual = avg_vol >= OPTIONS_VOL_MULT
    return unusual, score

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
    """
    candidates = get_top_candidates()
    if not candidates:
        return []

    strong = []
    for t in candidates:
        try:
            # ensure memory has bars
            incremental_fetch.update_ticker(t)
            # underlying vol check
            vol_ok, ratio = has_volume_surge_underlying(t)
            if not vol_ok:
                # skip weak underlying volume
                continue
            # options flow check
            opts = fetch_options_for_ticker(t)
            unusual, opt_score = analyze_options_flow(opts)
            # Keep if options activity OR strong underlying vol
            if unusual or ratio >= (MIN_REL_VOL * 1.4):
                strong.append((t, ratio, opt_score))
            # throttle to avoid limit
            time.sleep(PER_TICKER_SLEEP)
        except Exception as e:
            print("watchlist build error for", t, e)
            continue

    # sort by combined strength (underlying ratio * options score)
    strong.sort(key=lambda x: (x[1] * (x[2] or 1.0)), reverse=True)
    final = [s[0] for s in strong[:TOP_SCAN_COUNT]]
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
