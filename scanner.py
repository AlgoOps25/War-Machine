# scanner.py — WAR MACHINE GOD MODE: Elite Active Sniper + STRICT FVG filter
import requests
import os
import time
import json
import threading
from datetime import datetime, date, time as dtime, timedelta
import pytz

print("⚔️ WAR MACHINE GOD MODE — SNIPER v1 (STRICT FVG) STARTING")

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# MAIN SCHEDULE / TUNING
SCAN_INTERVAL = 300            # 5 min main scan
RETEST_POLL = 15               # seconds for armed tickers (fast monitor)
MARKET_CAP_MIN = 2_000_000_000
MAX_UNIVERSE = 1000
TOP_SCAN_COUNT = 350           # how many to evaluate each cycle

# retest arm limits
MAX_ARMED = 10                 # how many tickers to monitor at once
RETEST_TIMEOUT_MINUTES = 45    # prune armed tickers after N minutes if no confirmation

# confirmation tuning (video-derived)
RETEST_MIN_RELVOL = 1.2
CONFIRM_CLOSE_ABOVE_RATIO = 0.5   # require close inside upper half of OR range for bull (tuned)
CONFIRM_CANDLE_BODY_MIN = 0.25    # body relative to OR range minimum for strong flip

est = pytz.timezone("US/Eastern")
RETEST_STATE_FILE = "retest_state.json"

# -------------------------
# discord helper
# -------------------------
def send(msg):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook configured")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# -------------------------
# time helpers
# -------------------------
def now_est():
    return datetime.now(est)

def market_phase():
    n = now_est()
    h = n.hour
    m = n.minute
    if h < 8:
        return "sleep"
    if 8 <= h < 9 or (h == 9 and m < 30):
        return "premarket"
    if (h > 9 or (h == 9 and m >= 30)) and h < 16:
        return "market"
    if 16 <= h < 20:
        return "afterhours"
    return "sleep"

# -------------------------
# persistent retest state
# -------------------------
def load_retest_state():
    try:
        with open(RETEST_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_retest_state(state):
    try:
        with open(RETEST_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("Error saving retest state:", e)

retest_state = load_retest_state()

# -------------------------
# EODHD wrappers
# -------------------------
def screener_top_by_marketcap(limit=MAX_UNIVERSE):
    try:
        url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{MARKET_CAP_MIN}&limit={limit}&exchange=US"
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            print("Screener failed:", r.status_code, r.text[:200])
            return []
        return r.json().get("data", [])
    except Exception as e:
        print("EODHD screener error:", e)
        return []

def get_intraday_bars(ticker, limit=240):
    # 1-minute bars (adjust endpoint if your EODHD plan uses a different path)
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval=1m&limit={limit}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            # fallback: return []
            return []
        bars = r.json()
        if isinstance(bars, dict) and "data" in bars:
            bars = bars["data"]
        return bars
    except Exception as e:
        print("get_intraday_bars error for", ticker, e)
        return []

def get_realtime_quote(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

# -------------------------
# timestamp parsing helper
# -------------------------
def parse_eodhd_timestamp(ts):
    # Try multiple formats defensively and return timezone-aware datetime in EST
    try:
        if isinstance(ts, str):
            # common format: "2026-02-13 09:31:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                # assume UTC if no tzinfo (EODHD often returns UTC) -> convert to EST
                dt = dt.replace(tzinfo=pytz.UTC).astimezone(est)
            else:
                dt = dt.astimezone(est)
            return dt
    except Exception:
        pass
    return None

# -------------------------
# Opening range computation
# -------------------------
def compute_opening_range_from_bars(bars):
    if not bars:
        return None, None
    today = now_est().date()
    or_start = datetime.combine(today, dtime(hour=9, minute=30)).astimezone(est)
    or_end   = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
    highs = []
    lows = []
    for b in bars:
        ts = b.get("date") or b.get("datetime") or b.get("timestamp") or b.get("time")
        if not ts:
            continue
        dt = parse_eodhd_timestamp(ts)
        if not dt:
            continue
        if dt >= or_start and dt <= or_end:
            try:
                highs.append(float(b.get("high") or b.get("High") or 0))
                lows.append(float(b.get("low") or b.get("Low") or 0))
            except:
                continue
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)

# -------------------------
# Breakout detection
# -------------------------
def detect_breakout_after_or(bars, or_high, or_low):
    if not bars or or_high is None or or_low is None:
        return None, None  # (direction, breakout_index)
    today = now_est().date()
    or_end = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
    for idx, b in enumerate(bars):
        ts = b.get("date") or b.get("datetime") or b.get("timestamp")
        if not ts:
            continue
        dt = parse_eodhd_timestamp(ts)
        if not dt or dt <= or_end:
            continue
        try:
            h = float(b.get("high") or b.get("High") or 0)
            l = float(b.get("low") or b.get("Low") or 0)
        except:
            continue
        if h > or_high:
            return "bull", idx
        if l < or_low:
            return "bear", idx
    return None, None

# -------------------------
# FVG detection AFTER breakout
# -------------------------
def detect_fvg_after_break(bars, breakout_idx, direction):
    """
    bars: list of bars (assumed ascending time order)
    breakout_idx: index where breakout occurred (0-based)
    direction: 'bull' or 'bear'
    Returns (fvg_low, fvg_high) for zone or (None, None) if not found.
    Logic (defensive and simple):
      For bullish FVG: find i >= breakout_idx where bars[i+2].low > bars[i].high => FVG = (bars[i].high, bars[i+2].low)
      For bearish FVG: find i >= breakout_idx where bars[i+2].high < bars[i].low => FVG = (bars[i+2].high, bars[i].low)
    """
    try:
        n = len(bars)
        for i in range(breakout_idx, n - 2):
            try:
                b0 = bars[i]
                b2 = bars[i + 2]
                h0 = float(b0.get("high") or b0.get("High") or 0)
                l0 = float(b0.get("low") or b0.get("Low") or 0)
                h2 = float(b2.get("high") or b2.get("High") or 0)
                l2 = float(b2.get("low") or b2.get("Low") or 0)
            except:
                continue
            if direction == "bull":
                # bullish imbalance: later low above earlier high
                if l2 > h0:
                    fvg_low = h0
                    fvg_high = l2
                    # ensure reasonable width
                    if (fvg_high - fvg_low) > 0:
                        return fvg_low, fvg_high
            else:  # bear
                if h2 < l0:
                    fvg_low = h2
                    fvg_high = l0
                    if (fvg_high - fvg_low) > 0:
                        return fvg_low, fvg_high
    except Exception as e:
        print("FVG detection error:", e)
    return None, None

# -------------------------
# Pre-alert publishing
# -------------------------
def publish_prealert(ticker, direction, zone_low, zone_high, or_low, or_high):
    if direction == "bull":
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BULL)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"FVG Zone: {zone_low:.2f} - {zone_high:.2f}\n"
                f"If {ticker} retraces into {zone_low:.2f}-{zone_high:.2f} and then shows a strong green flip, ENTER CALL. Waiting for confirmation...")
    else:
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BEAR)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"FVG Zone: {zone_low:.2f} - {zone_high:.2f}\n"
                f"If {ticker} retraces into {zone_low:.2f}-{zone_high:.2f} and then shows a strong red flip, ENTER PUT. Waiting for confirmation...")
    send(text)

# -------------------------
# Confirmation check (video-like rules)
# -------------------------
def check_confirmation_for_ticker(ticker, entry):
    bars = get_intraday_bars(ticker, limit=40)
    if not bars:
        return False
    rlow = entry["zone_low"]
    rhigh = entry["zone_high"]
    rsize = max(rhigh - rlow, 1e-9)
    # check newest bars for a retest+flip candle
    for b in reversed(bars[-12:]):  # only recent bars
        try:
            low = float(b.get("low") or b.get("Low") or 0)
            high = float(b.get("high") or b.get("High") or 0)
            openp = float(b.get("open") or b.get("Open") or 0)
            closep = float(b.get("close") or b.get("Close") or b.get("close", 0))
        except:
            continue
        body = abs(closep - openp)
        # bullish confirmation
        if entry["direction"] == "bull":
            tapped = low <= rhigh and closep > openp  # touched FVG and closed green
            if tapped and (closep >= (rlow + CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                # optional stronger body check
                if body >= CONFIRM_CANDLE_BODY_MIN * rsize:
                    return True
                return True
        else:
            tapped = high >= rlow and closep < openp
            if tapped and (closep <= (rhigh - CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                if body >= CONFIRM_CANDLE_BODY_MIN * rsize:
                    return True
                return True
    return False

# -------------------------
# Arm ticker for monitoring (only after strict FVG found)
# -------------------------
def arm_ticker_for_retest(ticker, direction, zone_low, zone_high, or_low, or_high):
    global retest_state
    if ticker in retest_state:
        return
    if len(retest_state) >= MAX_ARMED:
        return
    retest_state[ticker] = {
        "direction": direction,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "or_low": or_low,
        "or_high": or_high,
        "armed_at": datetime.utcnow().isoformat(),
        "confirmed": False
    }
    save_retest_state(retest_state)
    publish_prealert(ticker, direction, zone_low, zone_high, or_low, or_high)
    print(f"Armed {ticker} for retest with FVG ({direction})")

# -------------------------
# Fast monitor thread
# -------------------------
def fast_monitor_loop():
    global retest_state
    print("Fast monitor started")
    while True:
        try:
            keys = list(retest_state.keys())
            for ticker in keys:
                entry = retest_state.get(ticker)
                if not entry or entry.get("confirmed"):
                    continue
                # prune old
                armed_at = datetime.fromisoformat(entry["armed_at"])
                if datetime.utcnow() - armed_at > timedelta(minutes=RETEST_TIMEOUT_MINUTES):
                    try:
                        del retest_state[ticker]
                        save_retest_state(retest_state)
                    except:
                        pass
                    continue
                confirmed = check_confirmation_for_ticker(ticker, entry)
                if confirmed:
                    if entry["direction"] == "bull":
                        msg = (f"✅ CONFIRMED: {ticker} bounced off {entry['zone_low']:.2f}-{entry['zone_high']:.2f}. ENTER CALL.\n"
                               f"Suggested stop: {entry['or_low'] - 0.5:.2f} (example). Time UTC: {datetime.utcnow().isoformat()}")
                    else:
                        msg = (f"✅ CONFIRMED: {ticker} bounced off {entry['zone_low']:.2f}-{entry['zone_high']:.2f}. ENTER PUT.\n"
                               f"Suggested stop: {entry['or_high'] + 0.5:.2f} (example). Time UTC: {datetime.utcnow().isoformat()}")
                    send(msg)
                    entry["confirmed"] = True
                    entry["confirmed_at"] = datetime.utcnow().isoformat()
                    save_retest_state(retest_state)
                    try:
                        del retest_state[ticker]
                        save_retest_state(retest_state)
                    except:
                        pass
            time.sleep(RETEST_POLL)
        except Exception as e:
            print("fast_monitor error:", e)
            time.sleep(RETEST_POLL)

# -------------------------
# scoring (same momentum filter)
# -------------------------
def score_stock_quick(stock):
    try:
        price = float(stock.get("close", 0))
        change = float(stock.get("change_p", 0) or 0)
        volume = float(stock.get("volume", 0) or 0)
        avgvol = float(stock.get("avgVolume", 1) or 1)
        relvol = volume / avgvol if avgvol > 0 else 0
        score = abs(change) * 1.8 + relvol * 2.2
        return score, relvol, change, price
    except:
        return 0,0,0,0

# -------------------------
# main scan: build universe, find top, detect breakout+FVG
# -------------------------
def build_universe():
    print("Building universe...")
    data = screener_top_by_marketcap(MAX_UNIVERSE)
    tickers = [x.get("code") for x in data if x.get("code")]
    print(f"Universe size: {len(tickers)}")
    return tickers

def run_scan(universe, phase):
    print("Running main scan:", phase)
    data = screener_top_by_marketcap(limit=MAX_UNIVERSE)
    pool = []
    for rec in data[:TOP_SCAN_COUNT]:
        try:
            s, rv, ch, price = score_stock_quick(rec)
            if s > 6 and rv > RETEST_MIN_RELVOL:
                pool.append((rec.get("code"), s, rv, ch, price))
        except Exception:
            continue

    pool.sort(key=lambda x: x[1], reverse=True)
    top = pool[:5]
    if not top:
        print("No elite movers this cycle")
        return

    header = "🔥 WAR MACHINE — ELITE ACTIVE TOP 5"
    if phase == "premarket":
        header = "🌅 PREMARKET WATCH (ELITE)"
    elif phase == "afterhours":
        header = "🌙 AFTER HOURS WATCH (ELITE)"
    msg = header + "\n\n"
    for t in top:
        msg += f"{t[0]} | Score {round(t[1],2)} | RelVol {round(t[2],2)} | Move {round(t[3],2)}% | ${round(t[4],2)}\n"
    send(msg)

    # For each top ticker, compute OR, detect breakout, then strict FVG, then arm only if FVG found
    for t in top:
        ticker = t[0]
        bars = get_intraday_bars(ticker, limit=240)
        if not bars:
            continue
        or_high, or_low = compute_opening_range_from_bars(bars)
        if or_high is None or or_low is None:
            continue
        direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
        if direction and breakout_idx is not None:
            # find FVG after breakout index
            fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
            if fvg_low and fvg_high:
                # arm only when strict FVG exists
                arm_ticker_for_retest(ticker, direction, fvg_low, fvg_high, or_low, or_high)
            else:
                print(f"{ticker} breakout but NO FVG found — skipping")

# -------------------------
# startup
# -------------------------
if __name__ == "__main__":
    send("⚔️ WAR MACHINE GOD MODE SNIPER v1 ONLINE — strict FVG enabled")
    universe = build_universe()
    monitor_thread = threading.Thread(target=fast_monitor_loop, daemon=True)
    monitor_thread.start()
    while True:
        phase = market_phase()
        if phase == "sleep":
            print("Sleeping until 8AM EST")
            time.sleep(600)
            continue
        print(f"Main scan phase: {phase} | {now_est().isoformat()}")
        if not universe:
            universe = build_universe()
        try:
            run_scan(universe, phase)
        except Exception as e:
            print("Main run_scan error:", e)
        time.sleep(SCAN_INTERVAL)
