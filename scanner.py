# scanner.py (refactored, imports modules)
import os
import time
import threading
from datetime import datetime
import pytz
import requests

from targets import compute_stop_and_targets
from trade_logger import log_confirmed_trade, start_monitor_thread
from scanner_helpers import get_intraday_bars_for_logger, get_realtime_quote_for_logger
# existing helper functions (compute OR, detect breakout, detect FVG) are assumed same as previous scanner
# to save space, we will import or inline them; for now paste the OR/FVG functions you already use.

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SCAN_INTERVAL = 300
RETEST_POLL = 15
MARKET_CAP_MIN = 2_000_000_000
MAX_UNIVERSE = 1000
TOP_SCAN_COUNT = 350
est = pytz.timezone("US/Eastern")

def send(msg):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# ---------- (You should reuse your reliable OR/FVG functions here)
# For brevity, assume compute_opening_range_from_bars(), detect_breakout_after_or(), detect_fvg_after_break() exist
# paste those from your working scanner above exactly here.

# ---------- confirmation grading (per video)
def grade_confirmation_candle(bar, or_low, or_high, direction):
    """
    bar = single 1-min bar dict with open, close, high, low
    Returns 'A+'|'A'|'A-' based on:
      - A+: strong green (bull) with small/no lower wick and solid body, or strong red for bear
      - A: red->green flip (bull) or green->red flip (bear)
      - A-: wick rejection but not flip
    Implement video rules "to the T".
    """
    try:
        o = float(bar.get("open") or bar.get("Open") or 0)
        c = float(bar.get("close") or bar.get("Close") or 0)
        h = float(bar.get("high") or bar.get("High") or 0)
        l = float(bar.get("low") or bar.get("Low") or 0)
    except:
        return "A-"
    body = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l
    range_size = max(or_high - or_low, 1e-9)
    # A+ conditions (bull): green candle, body large relative to range, tiny lower wick
    if direction == "bull":
        if c > o and body >= 0.5 * range_size and lower_wick <= 0.15 * body:
            return "A+"
        # A: red open -> green close flip (open < close and lower wick large)
        if o < c and lower_wick >= 0.5 * (body + lower_wick):
            return "A"
        # A-: touched but didn't flip cleanly; still a rejection wick
        if lower_wick > 0 and body > 0:
            return "A-"
    else:
        if c < o and body >= 0.5 * range_size and upper_wick <= 0.15 * body:
            return "A+"
        if o > c and upper_wick >= 0.5 * (body + upper_wick):
            return "A"
        if upper_wick > 0 and body > 0:
            return "A-"
    return "A-"

# ---------- when confirmation triggered: compute stops/targets + log trade
def handle_confirmation(ticker, direction, or_low, or_high, confirmed_bar):
    entry_price = float(confirmed_bar.get("close") or confirmed_bar.get("Close") or confirmed_bar.get("close", 0))
    grade = grade_confirmation_candle(confirmed_bar, or_low, or_high, direction)
    # compute stops/targets
    calc = compute_stop_and_targets(entry_price, or_low, or_high, direction, ticker=ticker)
    stop = calc.get("stop")
    t1 = calc.get("t1")
    t2 = calc.get("t2")
    chosen = calc.get("chosen")
    entry_ts = datetime.utcnow().isoformat()
    # log trade to DB (trade_logger)
    trade_id = log_confirmed_trade(ticker, direction, grade, entry_price, entry_ts, stop, t1, t2, chosen)
    # publish confirmation message with stops/targets
    msg = (f"🚨 CONFIRMED ENTRY — {ticker} {direction.upper()}\n"
           f"Grade: {grade}\nEntry: {entry_price:.2f}\nStop: {stop:.2f}\nT1 (2R): {t1:.2f}\n"
           f"T2 (1H): {t2 if t2 else 'n/a'}\nTradeId: {trade_id}")
    send(msg)
    return trade_id

# ---------- main scan logic (reuse your run_scan but call handle_confirmation when confirmed)
# For brevity, integrate your previous run_scan loop and fast monitor thread, but replace confirmation action:
# when confirmed==True:
#    find the confirming bar (most recent bar that satisfied conditions) and pass to handle_confirmation()

# Start trade logger monitor
start_monitor_thread()
# rest of scanner main loop remains the same as earlier, except confirmation -> handle_confirmation(...)
