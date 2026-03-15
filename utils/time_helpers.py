"""
utils/time_helpers.py — Shared timezone-aware time utilities
Extracted from app/core/sniper.py so all modules can import without
creating circular dependencies back into sniper.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def _now_et():
    """Return current datetime in US/Eastern timezone."""
    return datetime.now(ZoneInfo("America/New_York"))


def _bar_time(bar):
    """Return the time portion of a bar's datetime field, or None."""
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def _strip_tz(dt):
    """Strip timezone info from a datetime, or return None if input is None."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if hasattr(dt, "tzinfo") and dt.tzinfo else dt
