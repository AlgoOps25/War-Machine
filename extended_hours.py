"""
Extended Hours Manager
Handles pre-market (4:00 AM - 9:30 AM) and after-hours (4:00 PM - 8:00 PM) monitoring.

Your EODHD plan includes extended hours data — this module makes use of it.

Features:
  - Track pre-market price action (4 AM - 9:30 AM)
  - Detect early breakouts/breakdowns before market open
  - Monitor after-hours continuation moves (4 PM - 8 PM)
  - Send Discord alerts for significant extended hours moves

Integration:
  - Called by scanner.py to determine if we're in extended hours
  - WebSocket already streams extended hours data — we just need to act on it
"""
from datetime import time as dt_time, datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional
import config

ET = ZoneInfo("America/New_York")

# Extended hours windows (ET)
PREMARKET_START  = dt_time(4, 0)    # 4:00 AM ET
MARKET_OPEN      = dt_time(9, 30)   # 9:30 AM ET
MARKET_CLOSE     = dt_time(16, 0)   # 4:00 PM ET
AFTERHOURS_END   = dt_time(20, 0)   # 8:00 PM ET

# Thresholds for extended hours alerts
PREMARKET_MOVE_THRESHOLD    = 0.03  # 3% move in pre-market triggers alert
AFTERHOURS_MOVE_THRESHOLD   = 0.025 # 2.5% move after hours triggers alert
MIN_PREMARKET_VOLUME        = 10000 # Minimum volume to consider move significant


def get_market_session() -> str:
    """
    Return current market session.
    
    Returns:
        "premarket" | "regular" | "afterhours" | "closed"
    """
    now = datetime.now(ET).time()
    
    if PREMARKET_START <= now < MARKET_OPEN:
        return "premarket"
    elif MARKET_OPEN <= now < MARKET_CLOSE:
        return "regular"
    elif MARKET_CLOSE <= now < AFTERHOURS_END:
        return "afterhours"
    else:
        return "closed"


def is_extended_hours() -> bool:
    """Return True if currently in pre-market or after-hours."""
    session = get_market_session()
    return session in ["premarket", "afterhours"]


def is_premarket() -> bool:
    """Return True if currently in pre-market (4 AM - 9:30 AM ET)."""
    return get_market_session() == "premarket"


def is_afterhours() -> bool:
    """Return True if currently in after-hours (4 PM - 8 PM ET)."""
    return get_market_session() == "afterhours"


def should_monitor_ticker(ticker: str) -> bool:
    """
    Determine if we should actively monitor a ticker in extended hours.
    
    Criteria:
      - High-volume stocks (avoid illiquid extended hours moves)
      - Core watchlist members
      - Stocks with >10% gap from previous close
    
    Args:
        ticker: Stock symbol
    
    Returns:
        True if ticker should be monitored in extended hours
    """
    # Core tickers always monitored
    core_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "MSFT", "META"]
    if ticker in core_tickers:
        return True
    
    # Check if ticker has significant gap (would be added by gap scanner)
    # This is a placeholder - real implementation would check current price vs prev close
    return False


def analyze_premarket_action(ticker: str, current_bar: Dict) -> Optional[Dict]:
    """
    Analyze pre-market price action for a ticker.
    
    Args:
        ticker: Stock symbol
        current_bar: Current 1-minute bar from WebSocket feed
                     {"datetime": ..., "open": ..., "high": ..., "low": ..., 
                      "close": ..., "volume": ...}
    
    Returns:
        Alert dict if significant move detected, None otherwise:
        {
            "ticker": "AAPL",
            "session": "premarket",
            "move_pct": 3.2,
            "price": 185.50,
            "volume": 25000,
            "time": "07:45 AM ET",
            "alert_type": "breakout" | "breakdown"
        }
    """
    if not current_bar:
        return None
    
    # Get previous day's close (would come from data_manager in real implementation)
    # Placeholder: assume we have prev_close stored somewhere
    # prev_close = get_previous_close(ticker)  # TODO: implement
    
    # For now, return None (this is a framework)
    # Real implementation would:
    # 1. Get prev close from data_manager
    # 2. Calculate % move from prev close
    # 3. Check volume threshold
    # 4. Return alert dict if thresholds met
    
    return None


def get_extended_hours_summary() -> Dict:
    """
    Generate summary of extended hours activity.
    Called at market open (9:30 AM) to summarize pre-market.
    Called at market close (4:00 PM) for after-hours preview.
    
    Returns:
        {
            "session": "premarket" | "afterhours",
            "movers": [{"ticker": ..., "move_pct": ..., "volume": ...}, ...],
            "breakouts": ["AAPL", "TSLA", ...],
            "breakdowns": ["NVDA", ...],
        }
    """
    session = get_market_session()
    
    # Placeholder - real implementation would:
    # 1. Query data_manager for extended hours bars
    # 2. Compare to previous close
    # 3. Identify significant movers
    # 4. Detect breakout/breakdown patterns
    
    return {
        "session": session,
        "movers": [],
        "breakouts": [],
        "breakdowns": [],
    }


def format_extended_hours_alert(ticker: str, move_data: Dict) -> str:
    """
    Format Discord alert message for extended hours move.
    
    Args:
        ticker: Stock symbol
        move_data: Dict from analyze_premarket_action()
    
    Returns:
        Formatted Discord message string
    """
    session = move_data["session"].upper()
    move_pct = move_data["move_pct"]
    price = move_data["price"]
    volume = move_data["volume"]
    time_str = move_data["time"]
    alert_type = move_data["alert_type"]
    
    emoji = "🚀" if alert_type == "breakout" else "📉"
    direction = "UP" if move_pct > 0 else "DOWN"
    
    message = (
        f"{emoji} **{session} ALERT: {ticker}**\n\n"
        f"Move: **{move_pct:+.2f}%** {direction}\n"
        f"Price: ${price:.2f}\n"
        f"Volume: {volume:,} shares\n"
        f"Time: {time_str}\n\n"
        f"Type: {alert_type.upper()}"
    )
    
    return message


# ── Configuration for scanner.py integration ────────────────────────────

def get_scan_interval() -> int:
    """
    Return appropriate scan interval based on current session.
    
    Returns:
        Seconds between scans:
        - Pre-market: 60s (less frequent, lower volume)
        - Regular hours: from config.SCAN_INTERVALS
        - After-hours: 120s (even less frequent)
    """
    session = get_market_session()
    
    if session == "premarket":
        return 60  # 1 minute
    elif session == "afterhours":
        return 120  # 2 minutes
    else:
        # Regular hours - use adaptive intervals from config
        now = datetime.now(ET).time()
        
        if dt_time(9, 30) <= now < dt_time(9, 45):
            return config.SCAN_INTERVALS.get("opening_range", 30)
        elif dt_time(9, 45) <= now < dt_time(11, 0):
            return config.SCAN_INTERVALS.get("morning", 60)
        elif dt_time(11, 0) <= now < dt_time(14, 0):
            return config.SCAN_INTERVALS.get("midday", 180)
        elif dt_time(14, 0) <= now < dt_time(15, 30):
            return config.SCAN_INTERVALS.get("afternoon", 60)
        elif dt_time(15, 30) <= now < dt_time(16, 0):
            return config.SCAN_INTERVALS.get("power_hour", 45)
        else:
            return 300  # 5 minutes (shouldn't reach here during regular hours)


def should_run_scanner() -> bool:
    """
    Determine if scanner should be running based on current time.
    
    Returns:
        True if scanner should run (pre-market, regular, or after-hours)
        False if market closed (8 PM - 4 AM ET)
    """
    session = get_market_session()
    return session != "closed"
