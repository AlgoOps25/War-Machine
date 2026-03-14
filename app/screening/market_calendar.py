"""
Market Calendar Guard - Phase 1.27

Provides is_market_day() and is_market_hours() helpers used throughout
the scanning pipeline to prevent wasted API calls on weekends/holidays.

US Market Holidays 2026 (NYSE observed dates):
  Jan 1  - New Year's Day
  Jan 19 - MLK Day
  Feb 16 - Presidents Day
  Apr 3  - Good Friday
  May 25 - Memorial Day
  Jun 19 - Juneteenth
  Jul 3  - Independence Day (observed)
  Sep 7  - Labor Day
  Nov 26 - Thanksgiving
  Dec 25 - Christmas
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# NYSE holidays for 2026 — add future years as needed
_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}

# NYSE holidays for 2027 (included proactively)
_HOLIDAYS_2027 = {
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed)
    date(2027, 7, 5),   # Independence Day (observed)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 24), # Christmas (observed)
}

ALL_HOLIDAYS = _HOLIDAYS_2026 | _HOLIDAYS_2027


def is_market_day(dt: datetime = None) -> bool:
    """
    Return True if `dt` (ET) falls on a trading day (Mon-Fri, not a holiday).
    Defaults to current ET time if not provided.
    """
    if dt is None:
        dt = datetime.now(tz=ET)
    d = dt.date() if hasattr(dt, 'date') else dt
    # Weekend check (Mon=0 ... Sun=6)
    if d.weekday() >= 5:
        return False
    # Holiday check
    if d in ALL_HOLIDAYS:
        return False
    return True


def is_premarket_window(dt: datetime = None) -> bool:
    """
    Return True if we are in the pre-market scanning window (4:00-9:30 AM ET)
    on a trading day.
    """
    if dt is None:
        dt = datetime.now(tz=ET)
    if not is_market_day(dt):
        return False
    t = dt.time()
    return time(4, 0) <= t < time(9, 30)


def is_market_hours(dt: datetime = None) -> bool:
    """
    Return True if we are in regular trading hours (9:30 AM - 4:00 PM ET)
    on a trading day.
    """
    if dt is None:
        dt = datetime.now(tz=ET)
    if not is_market_day(dt):
        return False
    t = dt.time()
    return time(9, 30) <= t < time(16, 0)


def is_active_session(dt: datetime = None) -> bool:
    """
    Return True if the system should be actively scanning.
    Covers pre-market + regular hours: 4:00 AM - 4:00 PM ET on trading days.
    """
    if dt is None:
        dt = datetime.now(tz=ET)
    if not is_market_day(dt):
        return False
    t = dt.time()
    return time(4, 0) <= t < time(16, 0)


def next_market_open(dt: datetime = None) -> datetime:
    """
    Return the datetime of the next market open (9:30 AM ET) on a trading day.
    """
    from datetime import timedelta
    if dt is None:
        dt = datetime.now(tz=ET)
    candidate = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    if dt >= candidate:
        candidate += timedelta(days=1)
    while not is_market_day(candidate):
        candidate += timedelta(days=1)
    return candidate


print("[CALENDAR] Market calendar loaded — weekend/holiday guard active")
