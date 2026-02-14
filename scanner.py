# scanner.py — War Machine v3 + Pre-alert + Confirmation (Opening Range -> Breakout -> Retest)
import requests
import os
import time
import json
import threading
from datetime import datetime, date, time as dtime, timedelta
import pytz

print("⚔️ WAR MACHINE ELITE ACTIVE v3 + SNIPER RETEST LAYER STARTING")

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# MAIN SCHEDULE
SCAN_INTERVAL = 300            # 5 min main scan (universe)
RETEST_POLL = 15               # poll seconds for armed tickers (fast monitor)
MARKET_CAP_MIN = 2_000_000_000
MAX_UNIVERSE = 1000
TOP_SCAN_COUNT = 350           # how many to score per scan cycle

est = pytz.timezone("US/Eastern")

# persistent retest state filename (so restarts keep state)
RETEST_STATE_FILE = "retest_state.json"

# thresholds & tuning (adjust later)
RETEST_MIN_RELVOL = 1.2       # minimum rel vol to consider
CONFIRM_CLOSE_ABOVE_RATIO = 0.5  # confirmation candle must close above midpoint of the opening range
CONFIRM_CANDLE_BODY_MIN = 0.25   # minimum body relative to range for strong flip
MAX_ARMED = 10                   # only arm up to this many tickers for frequent monitoring

# -------------------------
# helpers - discord
# -------------------------
def send(msg):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# -------------------------
# helpers - time/phase
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

retest_state = load_retest_state()  # dict keyed by ticker

# -------------------------
# EODHD API wrappers
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

def get_intraday_bars(ticker, limit=120):
    """
    Try to fetch recent 1-minute bars for today.
    Endpoint used: /api/intraday/{symbol}.US?interval=1m&limit=...
    If your EODHD plan uses a different path, update this function accordingly.
    Returns list of bars: each {'datetime':..., 'open':..,'high':..,'low':..,'close':..,'volume':..}
    """
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval=1m&limit={limit}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            # fallback to realtime endpoint with minimal info (may not have bars)
            return []
        bars = r.json()  # adjust if response structure differs
        # Ensure bars are in ascending time order and have expected keys
        # EODHD may return a list of objects; be defensive
        if isinstance(bars, dict) and 'data' in bars:
            bars = bars['data']
        return bars
    except Exception as e:
        print("get_intraday_bars error:", e)
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
# Opening range computation
# -------------------------
def compute_opening_range_from_bars(bars):
    """
    Input: bars — list of intraday bars (should include today 1m bars)
    Compute high/low between 09:30 and 09:40 EST for today's date.
    Bars timestamps must be parseable - we assume each bar has 'date' or 'datetime' fields.
    """
    if not bars:
        return None, None

    today = now_est().date()
    or_start = datetime.combine(today, dtime(hour=9, minute=30)).astimezone(est)
    or_end   = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)

    highs = []
    lows = []
    for b in bars:
        # try several timestamp keys defensively
        ts = b.get("date") or b.get("datetime") or b.get("timestamp") or b.get("time")
        if not ts:
            continue
        # normalize string timestamp to datetime if needed
        try:
            # EODHD timestamps often look like "2026-02-13 09:31:00"
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts)
                # assume returned timezone is UTC or local — adjust if needed
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC).astimezone(est)
                else:
                    dt = dt.astimezone(est)
            else:
                continue
        except Exception:
            continue

        if dt >= or_start and dt <= or_end:
            # get high/low fields defensively
            h = float(b.get("high") or b.get("High") or b.get("h", 0))
            l = float(b.get("low") or b.get("Low") or b.get("l", 0))
            highs.append(h)
            lows.append(l)

    if not highs or not lows:
        return None, None
    return max(highs), min(lows)  # OR high, OR low

# -------------------------
# Breakout detection after OR
# -------------------------
def detect_breakout_after_or(bars, or_high, or_low):
    """
    Returns 'bull' if high > or_high anywhere after OR time,
            'bear' if low < or_low,
            None if no breakout.
    """
    if not bars or or_high is None:
        return None
    # find bars after 09:40
    today = now_est().date()
    or_end = datetime.combine(today, dtime(hour=9, minute=40)).astimezone(est)
    for b in bars:
        ts = b.get("date") or b.get("datetime") or b.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC).astimezone(est)
            elif dt:
                dt = dt.astimezone(est)
        except:
            continue
        if dt and dt > or_end:
            h = float(b.get("high") or b.get("High") or 0)
            l = float(b.get("low") or b.get("Low") or 0)
            if h > or_high:
                return "bull"
            if l < or_low:
                return "bear"
    return None

# -------------------------
# Pre-alert formatting
# -------------------------
def publish_prealert(ticker, direction, or_low, or_high):
    if direction == "bull":
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BULL)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"If {ticker} retraces into {or_low:.2f}-{or_high:.2f} and then shows a strong green flip (open red -> close green),"
                f" ENTER CALL. Waiting for confirmation...")
    else:
        text = (f"🔔 PRE-ALERT — {ticker} BREAKOUT (BEAR)\n"
                f"Opening Range: {or_low:.2f} - {or_high:.2f}\n"
                f"If {ticker} retraces into {or_low:.2f}-{or_high:.2f} and then shows a strong red flip (open green -> close red),"
                f" ENTER PUT. Waiting for confirmation...")

    send(text)

# -------------------------
# Confirmation detection (video-like rules)
# -------------------------
def check_confirmation_for_ticker(ticker, entry):
    """
    entry dict contains:
      { 'direction': 'bull'/'bear', 'or_high':.., 'or_low':.., 'armed_at': 'timestamp' }
    Returns True if confirmed.
    Logic (simplified translation of video):
      - For bull: detect a 1-min candle that has low <= or_high (retest), and then closes green.
        For higher confidence require the candle close > low + CONFIRM_CLOSE_ABOVE_RATIO * (or_high - or_low)
      - For bear: symmetric
    """
    bars = get_intraday_bars(ticker, limit=20)
    if not bars:
        return False

    # compute range size
    rlow = entry["or_low"]
    rhigh = entry["or_high"]
    rsize = max(rhigh - rlow, 1e-9)
    for b in reversed(bars):  # check newest-first
        # parse bar time and ensure it's after the breakout time if necessary (we assume bars are recent)
        low = float(b.get("low") or b.get("Low") or 0)
        high = float(b.get("high") or b.get("High") or 0)
        openp = float(b.get("open") or b.get("Open") or 0)
        closep = float(b.get("close") or b.get("Close") or b.get("close", 0))
        body = abs(closep - openp)

        # indicator: candle tapped into the range (retest)
        if entry["direction"] == "bull":
            tapped = low <= rhigh and closep > openp  # green flip that touched range
            # require close be inside upper half, to ensure strength
            if tapped and (closep >= (rlow + CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                # optional stronger body check
                if (body >= CONFIRM_CANDLE_BODY_MIN * rsize):
                    return True
                else:
                    # still allow smaller flip if green and tapped
                    return True
        else:  # bear
            tapped = high >= rlow and closep < openp  # red flip that touched range
            if tapped and (closep <= (rhigh - CONFIRM_CLOSE_ABOVE_RATIO * rsize)):
                if (body >= CONFIRM_CANDLE_BODY_MIN * rsize):
                    return True
                else:
                    return True
    return False

# -------------------------
# Arm ticker for retest monitoring
# -------------------------
def arm_ticker_for_retest(ticker, direction, or_low, or_high):
    # limit how many we arm at once
    global retest_state
    if ticker in retest_state:
        return
    if len(retest_state) >= MAX_ARMED:
        # skip arming if too many already
        return
    retest_state[ticker] = {
        "direction": direction,
        "or_low": or_low,
        "or_high": or_high,
        "armed_at": datetime.utcnow().isoformat(),
        "confirmed": False
    }
    save_retest_state(retest_state)
    publish_prealert(ticker, direction, or_low, or_high)
    print(f"Armed {ticker} for retest ({direction})")

# -------------------------
# Fast monitoring thread for retest confirmations
# -------------------------
def fast_monitor_loop():
    global retest_state
    print("Fast monitor thread started")
    while True:
        try:
            # make a shallow copy to iterate
            keys = list(retest_state.keys())
            for ticker in keys:
                entry = retest_state.get(ticker)
                if not entry or entry.get("confirmed"):
                    continue
                # confirm logic
                confirmed = check_confirmation_for_ticker(ticker, entry)
                if confirmed:
                    # publish confirmation
                    if entry["direction"] == "bull":
                        msg = (f"✅ CONFIRMED: {ticker} bounced off {entry['or_low']:.2f}-{entry['or_high']:.2f}. ENTER CALL.\n"
                               f"Suggested stop: {entry['or_low'] - 0.5:.2f} (example). Use your RR rules.\n"
                               f"Time: {datetime.utcnow().isoformat()} UTC")
                    else:
                        msg = (f"✅ CONFIRMED: {ticker} bounced off {entry['or_low']:.2f}-{entry['or_high']:.2f}. ENTER PUT.\n"
                               f"Suggested stop: {entry['or_high'] + 0.5:.2f} (example). Use your RR rules.\n"
                               f"Time: {datetime.utcnow().isoformat()} UTC")
                    send(msg)
                    # mark confirmed and persist then stop monitoring this ticker
                    entry["confirmed"] = True
                    entry["confirmed_at"] = datetime.utcnow().isoformat()
                    save_retest_state(retest_state)
                    # optionally remove after confirmation so we free the slot:
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
# Scoring engine (keeps current momentum scoring)
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
# Main scan loop (universe builder + top N publish)
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
        except Exception as e:
            continue

    pool.sort(key=lambda x: x[1], reverse=True)
    top = pool[:5]
    if not top:
        print("No elite movers this cycle")
        return

    # Publish top 5 (summary)
    header = "🔥 WAR MACHINE — ELITE ACTIVE TOP 5"
    if phase == "premarket":
        header = "🌅 PREMARKET WATCH (ELITE)"
    elif phase == "afterhours":
        header = "🌙 AFTER HOURS WATCH (ELITE)"

    msg = header + "\n\n"
    for t in top:
        msg += f"{t[0]} | Score {round(t[1],2)} | RelVol {round(t[2],2)} | Move {round(t[3],2)}% | ${round(t[4],2)}\n"
    send(msg)

    # For each top ticker, compute opening range & detect post-OR breakout; if breakout, arm for retest
    for t in top:
        ticker = t[0]
        bars = get_intraday_bars(ticker, limit=180)
        or_high, or_low = compute_opening_range_from_bars(bars)
        if or_high is None or or_low is None:
            continue
        breakout = detect_breakout_after_or(bars, or_high, or_low)
        if breakout:
            # arm
            arm_ticker_for_retest(ticker, breakout, or_low, or_high)

# -------------------------
# Start up
# -------------------------
if __name__ == "__main__":
    send("⚔️ WAR MACHINE ELITE ACTIVE v3 ONLINE — SNIPER LAYER ARMED")
    # build universe once up front
    universe = build_universe()

    # start fast monitor thread
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
