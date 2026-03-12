"""
Scanner Optimizer - Adaptive Scan Intervals
Dynamically adjusts scan frequency and watchlist size based on time of day (ET).

NOTE: This module will be merged into scanner.py in Phase 1.
For now, it remains standalone for backward compatibility.

New code should use scanner.py directly after Phase 1 consolidation.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

# Module-level cache to avoid printing on every call
_last_logged_interval = None
_last_logged_watchlist_size = None


def _now_et():
    return datetime.now(ZoneInfo("America/New_York")).time()


def get_adaptive_scan_interval() -> int:
    """
    CFW6 OPTIMIZATION: Scan more frequently during high-activity periods.

    OR Formation    (9:30-9:40):   5 seconds — capture every bar, no sleep during BOS build
    Post-OR Active  (9:40-11:00):  45 seconds
    Midday Chop     (11:00-14:00): 180 seconds
    Afternoon Setup (14:00-15:30): 60 seconds
    Power Hour      (15:30-16:00): 45 seconds
    Outside market:                300 seconds
    """
    global _last_logged_interval
    now = _now_et()

    # OR Formation window — scan every 5s to catch every 1m bar as it closes
    if time(9, 30) <= now < time(9, 40):
        interval = 5
        label = "OR Formation (BOS build)"

    # Post-OR morning activity (9:40-11:00)
    elif time(9, 40) <= now < time(11, 0):
        interval = 45
        label = "Post-OR Morning"

    # Midday Chop (11:00-14:00)
    elif time(11, 0) <= now < time(14, 0):
        interval = 180
        label = "Midday Chop"

    # Afternoon Setup (14:00-15:30)
    elif time(14, 0) <= now < time(15, 30):
        interval = 60
        label = "Afternoon Activity"

    # Power Hour (15:30-16:00)
    elif time(15, 30) <= now < time(16, 0):
        interval = 45
        label = "Power Hour"

    # Outside market hours
    else:
        interval = 300
        label = "Outside Market Hours"

    # Only print when interval changes
    if interval != _last_logged_interval:
        print(f"[SCANNER] {label} -> Scanning every {interval}s")
        _last_logged_interval = interval

    return interval


def should_scan_now() -> bool:
    """
    CFW6 RULE: Scan during 9:30-9:40 ET at high frequency so BOS+FVG can be
    built from OR bars in real time.  At 9:40 the first confirmation candle
    is evaluated and the signal fires immediately.

    Returns True during 9:30-16:00 ET on weekdays.
    The OR window (9:30-9:40) returns True — get_adaptive_scan_interval()
    returns 5s so the loop spins fast but does NOT sleep for 15s.
    """
    now = _now_et()

    # Full active scanning window — includes OR formation
    if time(9, 30) <= now <= time(16, 0):
        return True

    return False


def calculate_optimal_watchlist_size() -> int:
    """
    Adjust watchlist size by time of day.

    OR window     (9:30-9:40):  30 tickers - same as early morning (focused)
    Early morning (9:40-10:30): 30 tickers - focused, highest conviction setups
    Mid-session   (10:30-15:00): 50 tickers - full watchlist
    Late day      (15:00-16:00): 35 tickers - reduce exposure into close
    Default:                     40 tickers
    """
    global _last_logged_watchlist_size
    now = _now_et()

    if time(9, 30) <= now < time(9, 40):
        size = 30
    elif time(9, 40) <= now < time(10, 30):
        size = 30
    elif time(10, 30) <= now < time(15, 0):
        size = 50
    elif time(15, 0) <= now <= time(16, 0):
        size = 35
    else:
        size = 40

    if size != _last_logged_watchlist_size:
        print(f"[SCANNER] Watchlist size adjusted to {size} tickers")
        _last_logged_watchlist_size = size

    return size
