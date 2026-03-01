"""
rth_filter.py — Regular Trading Hours (RTH) Filter with Market Calendar Support

Provides market calendar-aware RTH validation using pandas_market_calendars.
Handles holidays, early closes, and intraday RTH boundaries.

NYSE Regular Trading Hours: 9:30 AM - 4:00 PM ET
Early Close Days: 1:00 PM ET (day before/after major holidays)

Usage:
    from app.analytics.rth_filter import is_rth_now, is_market_open, get_market_hours_today
    
    if not is_market_open():
        print("Market closed today (holiday or weekend)")
        return
    
    if not is_rth_now():
        print("Outside RTH - blocking signal")
        return
    
    hours = get_market_hours_today()
    # {'open': datetime(...), 'close': datetime(...), 'early_close': False}
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import threading
from typing import Optional, Dict

try:
    import pandas_market_calendars as mcal
    _HAS_MARKET_CALENDARS = True
except ImportError:
    _HAS_MARKET_CALENDARS = False

ET = ZoneInfo("America/New_York")

# RTH boundaries (NYSE standard hours)
RTH_OPEN = time(9, 30)   # 9:30 AM ET
RTH_CLOSE = time(16, 0)  # 4:00 PM ET
EARLY_CLOSE = time(13, 0)  # 1:00 PM ET (early close days)

# Cache for daily market schedule (thread-safe)
_cache_lock = threading.Lock()
_cached_schedule: Optional[Dict] = None
_cached_date: Optional[str] = None


def _get_nyse_calendar():
    """Get NYSE calendar instance. Returns None if pandas_market_calendars not installed."""
    if not _HAS_MARKET_CALENDARS:
        return None
    try:
        return mcal.get_calendar('NYSE')
    except Exception as e:
        print(f"[RTH] Failed to load NYSE calendar: {e}")
        return None


def _fetch_market_schedule_today() -> Optional[Dict]:
    """
    Fetch today's market schedule from NYSE calendar.
    Returns dict with 'open', 'close', 'early_close' if market is open today.
    Returns None if market is closed (holiday/weekend).
    
    Cached for entire day to avoid repeated calendar lookups.
    """
    global _cached_schedule, _cached_date
    
    now_et = datetime.now(ET)
    today_str = now_et.strftime("%Y-%m-%d")
    
    # Check cache
    with _cache_lock:
        if _cached_date == today_str and _cached_schedule is not None:
            return _cached_schedule
    
    # Fetch schedule
    nyse = _get_nyse_calendar()
    if nyse is None:
        # Fallback: assume market open Mon-Fri 9:30-16:00 if calendar unavailable
        if now_et.weekday() < 5:  # Mon-Fri
            schedule = {
                'open': now_et.replace(hour=9, minute=30, second=0, microsecond=0),
                'close': now_et.replace(hour=16, minute=0, second=0, microsecond=0),
                'early_close': False,
            }
            with _cache_lock:
                _cached_schedule = schedule
                _cached_date = today_str
            return schedule
        else:
            with _cache_lock:
                _cached_schedule = None
                _cached_date = today_str
            return None
    
    try:
        # Get schedule for today
        schedule_df = nyse.schedule(start_date=today_str, end_date=today_str)
        
        if schedule_df.empty:
            # Market closed today (holiday or weekend)
            with _cache_lock:
                _cached_schedule = None
                _cached_date = today_str
            return None
        
        # Extract open/close times
        market_open = schedule_df.iloc[0]['market_open'].to_pydatetime()
        market_close = schedule_df.iloc[0]['market_close'].to_pydatetime()
        
        # Convert to ET timezone-aware if needed
        if market_open.tzinfo is None:
            market_open = market_open.replace(tzinfo=ET)
        else:
            market_open = market_open.astimezone(ET)
        
        if market_close.tzinfo is None:
            market_close = market_close.replace(tzinfo=ET)
        else:
            market_close = market_close.astimezone(ET)
        
        # Detect early close (close time before 4:00 PM)
        is_early = market_close.time() < RTH_CLOSE
        
        schedule = {
            'open': market_open,
            'close': market_close,
            'early_close': is_early,
        }
        
        with _cache_lock:
            _cached_schedule = schedule
            _cached_date = today_str
        
        return schedule
    
    except Exception as e:
        print(f"[RTH] Error fetching market schedule: {e}")
        # Fallback: assume normal hours if error
        if now_et.weekday() < 5:
            schedule = {
                'open': now_et.replace(hour=9, minute=30, second=0, microsecond=0),
                'close': now_et.replace(hour=16, minute=0, second=0, microsecond=0),
                'early_close': False,
            }
            with _cache_lock:
                _cached_schedule = schedule
                _cached_date = today_str
            return schedule
        else:
            with _cache_lock:
                _cached_schedule = None
                _cached_date = today_str
            return None


def is_market_open() -> bool:
    """
    Check if the market is open today (not a holiday or weekend).
    
    Returns:
        bool: True if market is open today, False if closed (holiday/weekend)
    
    Example:
        if not is_market_open():
            print("Market closed - no trading today")
    """
    schedule = _fetch_market_schedule_today()
    return schedule is not None


def is_rth_now() -> bool:
    """
    Check if current time is within Regular Trading Hours (9:30 AM - 4:00 PM ET).
    Respects early closes (e.g., 1:00 PM on half days).
    
    Returns:
        bool: True if currently in RTH, False otherwise
    
    Example:
        if not is_rth_now():
            print("Outside RTH - blocking signal")
            return
    """
    schedule = _fetch_market_schedule_today()
    if schedule is None:
        return False  # Market closed today
    
    now_et = datetime.now(ET)
    return schedule['open'] <= now_et <= schedule['close']


def get_market_hours_today() -> Optional[Dict]:
    """
    Get today's market hours.
    
    Returns:
        dict: {'open': datetime, 'close': datetime, 'early_close': bool}
        None: If market is closed today
    
    Example:
        hours = get_market_hours_today()
        if hours:
            print(f"Market open: {hours['open']} to {hours['close']}")
            if hours['early_close']:
                print("Early close today!")
    """
    return _fetch_market_schedule_today()


def is_early_close_today() -> bool:
    """
    Check if today is an early close day (1:00 PM close).
    
    Returns:
        bool: True if early close, False otherwise
    
    Example:
        if is_early_close_today():
            print("Early close at 1:00 PM today")
    """
    schedule = _fetch_market_schedule_today()
    if schedule is None:
        return False
    return schedule['early_close']


def get_next_market_open() -> Optional[datetime]:
    """
    Get the next market open time (useful for pre-market checks).
    
    Returns:
        datetime: Next market open time (ET timezone-aware)
        None: If unable to determine
    
    Example:
        next_open = get_next_market_open()
        if next_open:
            print(f"Next market open: {next_open}")
    """
    schedule = _fetch_market_schedule_today()
    if schedule:
        return schedule['open']
    
    # Market closed today - try tomorrow (simplified)
    # In production, you'd loop through calendar to find next open day
    return None


def clear_cache():
    """
    Clear the cached market schedule.
    Useful for testing or if you need to force a refresh.
    """
    global _cached_schedule, _cached_date
    with _cache_lock:
        _cached_schedule = None
        _cached_date = None


# ── Diagnostic / Testing Functions ──────────────────────────────────────────

def get_rth_status() -> Dict:
    """
    Get comprehensive RTH status for diagnostics.
    
    Returns:
        dict: {
            'market_open': bool,
            'in_rth': bool,
            'early_close': bool,
            'current_time': datetime,
            'market_hours': dict or None,
            'has_calendar': bool,
        }
    """
    now_et = datetime.now(ET)
    schedule = _fetch_market_schedule_today()
    
    return {
        'market_open': schedule is not None,
        'in_rth': is_rth_now(),
        'early_close': is_early_close_today(),
        'current_time': now_et,
        'market_hours': schedule,
        'has_calendar': _HAS_MARKET_CALENDARS,
    }


if __name__ == "__main__":
    # Diagnostic output when run directly
    print("\n" + "="*60)
    print("RTH FILTER - Market Status Check")
    print("="*60)
    
    status = get_rth_status()
    
    print(f"\nCurrent Time (ET): {status['current_time'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Calendar Available: {status['has_calendar']}")
    print(f"\nMarket Open Today: {status['market_open']}")
    
    if status['market_hours']:
        hours = status['market_hours']
        print(f"Market Hours: {hours['open'].strftime('%H:%M')} - {hours['close'].strftime('%H:%M')} ET")
        print(f"Early Close: {hours['early_close']}")
    
    print(f"\nCurrently in RTH: {status['in_rth']}")
    
    if not status['market_open']:
        print("\n⚠️ Market is CLOSED today (holiday or weekend)")
    elif not status['in_rth']:
        print("\n⚠️ Currently OUTSIDE regular trading hours")
    else:
        print("\n✅ Market is OPEN and in RTH")
    
    print("\n" + "="*60 + "\n")
