"""
utils/time_helpers.py — Shared timezone-aware time utilities
Extracted from app/core/sniper.py so all modules can import without
creating circular dependencies back into sniper.

IMPORTANT CONVENTION (applies to ALL callers):
- All datetimes from Postgres TIMESTAMPTZ columns arrive as UTC-aware.
- _strip_tz() ALWAYS converts to ET before stripping timezone info.
- Never call dt.replace(tzinfo=None) directly on a DB timestamp anywhere
  in the codebase — always route through _strip_tz() here.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _now_et():
    """Return current datetime in US/Eastern timezone."""
    return datetime.now(ET)


def _bar_time(bar):
    """Return the time portion of a bar's datetime field, or None."""
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def _strip_tz(dt):
    """
    Convert a datetime to ET-naive (US/Eastern, timezone stripped).

    Always converts to ET first before stripping timezone info.
    This ensures DB timestamps (UTC-aware from Postgres TIMESTAMPTZ)
    are correctly represented as ET wall-clock time before comparison
    with other ET-naive datetimes in the pipeline.

    Without this conversion: a UTC 14:30 would strip to naive 14:30
    instead of naive 09:30 ET — a 4-5 hour error in all time comparisons.
    """
    if dt is None:
        return None
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.astimezone(ET).replace(tzinfo=None)
    return dt
