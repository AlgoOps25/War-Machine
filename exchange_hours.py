"""
Exchange Trading Hours & Holiday Detection
Uses EODHD exchange hours API to detect market holidays and early closures.

EODHD Exchange Hours API:
  GET https://eodhd.com/api/exchange-details/US?api_token=KEY
  
  Returns:
  - Trading hours (market open/close times)
  - Holidays list with dates
  - Early closure dates
  - Exchange timezone

Use Cases:
  - Detect market holidays (prevent scanner from running)
  - Identify early closure days (half days - close at 1 PM ET)
  - Adjust scan schedules automatically
  - Prevent false "market closed" errors on valid holidays

Integration:
  - Called at startup in main.py to check if today is a holiday
  - Called by scanner.py before starting scan loop
  - Cached for 24 hours (exchange hours don't change intraday)
"""
import requests
from datetime import datetime, date, time as dt_time
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import config

ET = ZoneInfo("America/New_York")

# Cache for exchange data (valid for 24 hours)
_exchange_cache = {}  # {"timestamp": datetime, "data": {...}}
_CACHE_TTL_HOURS = 24

# Known holidays (fallback if API fails)
KNOWN_HOLIDAYS_2026 = [
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
]

# Early closure days (1 PM close)
EARLY_CLOSE_2026 = [
    "2026-07-02",  # Day before Independence Day
    "2026-11-27",  # Day after Thanksgiving (Black Friday half day)
    "2026-12-24",  # Christmas Eve
]


def _is_cache_valid() -> bool:
    """Check if exchange data cache is still fresh."""
    if not _exchange_cache:
        return False
    
    cached_time = _exchange_cache.get("timestamp")
    if not cached_time:
        return False
    
    age = (datetime.now() - cached_time).total_seconds() / 3600
    return age < _CACHE_TTL_HOURS


def get_exchange_details(exchange: str = "US") -> Optional[Dict]:
    """
    Fetch exchange trading hours and holiday calendar from EODHD.
    
    Args:
        exchange: Exchange code (default "US" for NYSE/NASDAQ)
    
    Returns:
        Dict with exchange details:
        {
            "Name": "NYSE",
            "Code": "US",
            "OperatingMIC": "XNYS",
            "Country": "USA",
            "Currency": "USD",
            "CountryISO2": "US",
            "CountryISO3": "USA",
            "Timezone": "America/New_York",
            "TradingHours": {
                "OpeningTime": "09:30",
                "ClosingTime": "16:00",
                "Timezone": "America/New_York",
                "WorkingDays": ["Mon", "Tue", "Wed", "Thu", "Fri"]
            },
            "Holidays": [
                {"Date": "2026-01-01", "Name": "New Year's Day"},
                {"Date": "2026-12-25", "Name": "Christmas Day"},
                ...
            ]
        }
    
    EODHD Docs:
        https://eodhd.com/financial-apis/list-supported-exchanges-api
    """
    # Check cache first
    if _is_cache_valid():
        return _exchange_cache.get("data")
    
    url = f"https://eodhd.com/api/exchange-details/{exchange}"
    params = {
        "api_token": config.EODHD_API_KEY,
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, dict):
            print(f"[EXCHANGE] Unexpected response format: {type(data)}")
            return None
        
        # Cache the results
        _exchange_cache["timestamp"] = datetime.now()
        _exchange_cache["data"] = data
        
        print(f"[EXCHANGE] Loaded {exchange} exchange data")
        return data
    
    except Exception as e:
        print(f"[EXCHANGE] Error fetching exchange details: {e}")
        return None


def get_holidays(exchange: str = "US", year: Optional[int] = None) -> List[Dict]:
    """
    Get list of market holidays for an exchange.
    
    Args:
        exchange: Exchange code (default "US")
        year: Filter to specific year (default: current year)
    
    Returns:
        List of holiday dicts:
        [{"Date": "2026-01-01", "Name": "New Year's Day"}, ...]
    """
    exchange_data = get_exchange_details(exchange)
    
    if not exchange_data or "Holidays" not in exchange_data:
        # Fallback to known holidays
        print(f"[EXCHANGE] Using fallback holiday list")
        return [
            {"Date": d, "Name": "Market Holiday"}
            for d in KNOWN_HOLIDAYS_2026
        ]
    
    holidays = exchange_data.get("Holidays", [])
    
    # Filter by year if specified
    if year:
        holidays = [
            h for h in holidays
            if h.get("Date", "").startswith(str(year))
        ]
    
    return holidays


def is_market_holiday(check_date: Optional[date] = None, exchange: str = "US") -> Tuple[bool, Optional[str]]:
    """
    Check if a specific date is a market holiday.
    
    Args:
        check_date: Date to check (default: today)
        exchange: Exchange code (default "US")
    
    Returns:
        Tuple: (is_holiday, holiday_name)
        - is_holiday: True if the date is a holiday
        - holiday_name: Name of the holiday or None
    
    Example:
        is_holiday, name = is_market_holiday()
        if is_holiday:
            print(f"Market closed: {name}")
    """
    if check_date is None:
        check_date = datetime.now(ET).date()
    
    check_str = check_date.strftime("%Y-%m-%d")
    
    # Get holidays
    holidays = get_holidays(exchange, year=check_date.year)
    
    for holiday in holidays:
        holiday_date = holiday.get("Date", "")
        if holiday_date == check_str:
            return True, holiday.get("Name", "Market Holiday")
    
    return False, None


def is_early_close_day(check_date: Optional[date] = None) -> Tuple[bool, Optional[dt_time]]:
    """
    Check if a date is an early closure day (typically 1 PM ET close).
    
    Args:
        check_date: Date to check (default: today)
    
    Returns:
        Tuple: (is_early_close, close_time)
        - is_early_close: True if early close day
        - close_time: Closing time (e.g., 13:00) or None
    
    Example:
        is_early, close_time = is_early_close_day()
        if is_early:
            print(f"Early close at {close_time.strftime('%I:%M %p')}")
    """
    if check_date is None:
        check_date = datetime.now(ET).date()
    
    check_str = check_date.strftime("%Y-%m-%d")
    
    # Check against known early close days
    if check_str in EARLY_CLOSE_2026:
        return True, dt_time(13, 0)  # 1 PM ET
    
    return False, None


def get_market_hours(exchange: str = "US") -> Dict:
    """
    Get regular trading hours for an exchange.
    
    Args:
        exchange: Exchange code (default "US")
    
    Returns:
        Dict with trading hours:
        {
            "opening_time": "09:30",
            "closing_time": "16:00",
            "timezone": "America/New_York",
            "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"]
        }
    """
    exchange_data = get_exchange_details(exchange)
    
    if not exchange_data or "TradingHours" not in exchange_data:
        # Fallback to known US market hours
        return {
            "opening_time": "09:30",
            "closing_time": "16:00",
            "timezone": "America/New_York",
            "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"]
        }
    
    hours = exchange_data["TradingHours"]
    return {
        "opening_time": hours.get("OpeningTime", "09:30"),
        "closing_time": hours.get("ClosingTime", "16:00"),
        "timezone": hours.get("Timezone", "America/New_York"),
        "working_days": hours.get("WorkingDays", ["Mon", "Tue", "Wed", "Thu", "Fri"])
    }


def should_scanner_run() -> Tuple[bool, str]:
    """
    Determine if the scanner should run today.
    Main entry point called by scanner.py at startup.
    
    Returns:
        Tuple: (should_run, reason)
        - should_run: True if scanner should run
        - reason: Explanation string
    
    Example:
        should_run, reason = should_scanner_run()
        if not should_run:
            print(f"Scanner disabled: {reason}")
            sys.exit(0)
    """
    today = datetime.now(ET).date()
    
    # Check if weekend
    if today.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False, f"Weekend ({today.strftime('%A')})"
    
    # Check if market holiday
    is_holiday, holiday_name = is_market_holiday(today)
    if is_holiday:
        return False, f"Market Holiday: {holiday_name}"
    
    # Check if early close
    is_early, close_time = is_early_close_day(today)
    if is_early:
        return True, f"Early Close Day (closes at {close_time.strftime('%I:%M %p')} ET)"
    
    # Regular trading day
    return True, "Regular Trading Day"


def get_next_trading_day() -> date:
    """
    Get the next valid trading day (skips weekends and holidays).
    
    Returns:
        Date of next trading day
    """
    current = datetime.now(ET).date()
    
    # Start checking from tomorrow
    check_date = current + timedelta(days=1)
    
    # Check up to 10 days ahead (handles long holiday weekends)
    for _ in range(10):
        # Skip weekends
        if check_date.weekday() < 5:
            # Check if holiday
            is_holiday, _ = is_market_holiday(check_date)
            if not is_holiday:
                return check_date
        
        check_date += timedelta(days=1)
    
    # Fallback: return next Monday if we couldn't find a trading day
    return current + timedelta(days=(7 - current.weekday()))


def format_holiday_calendar(year: Optional[int] = None) -> str:
    """
    Format holiday calendar for display (e.g., Discord message).
    
    Args:
        year: Year to display (default: current year)
    
    Returns:
        Formatted string with holiday calendar
    """
    if year is None:
        year = datetime.now(ET).year
    
    holidays = get_holidays(year=year)
    
    if not holidays:
        return f"No holidays found for {year}"
    
    lines = [f"**📅 US Market Holidays {year}**\n"]
    
    for holiday in holidays:
        date_str = holiday.get("Date", "")
        name = holiday.get("Name", "Holiday")
        
        if date_str:
            # Format: Jan 01 - New Year's Day
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                formatted = dt.strftime("%b %d")
                lines.append(f"• {formatted} - {name}")
            except ValueError:
                lines.append(f"• {date_str} - {name}")
    
    return "\n".join(lines)


def clear_exchange_cache():
    """Clear exchange data cache. Called at EOD in main.py."""
    global _exchange_cache
    _exchange_cache = {}
    print("[EXCHANGE] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    if not _exchange_cache:
        return {"cached": False}
    
    cached_time = _exchange_cache.get("timestamp")
    
    return {
        "cached": True,
        "timestamp": cached_time.isoformat() if cached_time else None,
        "age_hours": (datetime.now() - cached_time).total_seconds() / 3600 if cached_time else None
    }


# Add missing import at top
from datetime import timedelta
