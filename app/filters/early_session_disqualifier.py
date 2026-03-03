# Early Session Disqualifier - Phase 4 Enhancement
# MISSION: Prevent premature signal generation from 9:30-9:40 AM opening range formation.
#
# PROBLEM: OR-anchored signals require the OR to be fully formed (9:40 AM+).
#          Current logic allows signals to arm during 9:30-9:40 if BOS+FVG conditions
#          are met on incomplete OR data, leading to poor entries and false signals.
#
# SOLUTION: Hard gate on all CFW6_OR signal generation from 9:30:00-9:39:59 AM ET.
#          Returns False with explanatory rejection reason during window.
#          After 9:40 AM, returns True (gate open) and allows normal signal flow.
#
# INTEGRATION POINT: Call is_or_complete() in sniper.py before running
#                    _run_signal_pipeline() for CFW6_OR signals.
#
# EDGE CASES:
# - If system starts after 9:40 AM: gate always returns True (no blocking).
# - If bars_session is empty: gate returns False with data error reason.
# - If latest bar timestamp can't be determined: gate returns False (safe default).
#
# PHASE 4 TRACKING: Logs rejection events for signal funnel analytics.

from datetime import time
from zoneinfo import ZoneInfo
from typing import Tuple

# Opening range formation window
OR_START = time(9, 30)
OR_END = time(9, 40)


def is_or_complete(bars_session: list, ticker: str = "") -> Tuple[bool, str]:
    """
    Check if opening range formation is complete (9:40 AM or later).
    
    Returns:
        (True, "OR complete") if current time >= 9:40 AM
        (False, reason) if still in OR formation window or data error
    
    Args:
        bars_session: List of intraday bars with 'datetime' field
        ticker: Optional ticker symbol for logging context
    """
    ticker_label = f"[{ticker}]" if ticker else "[OR-GATE]"
    
    # Validate input data
    if not bars_session:
        reason = "No session bars available"
        print(f"{ticker_label} 🚫 OR GATE: {reason}")
        return False, reason
    
    # Get latest bar timestamp
    latest_bar = bars_session[-1]
    bar_datetime = latest_bar.get("datetime")
    
    if bar_datetime is None:
        reason = "Bar datetime missing"
        print(f"{ticker_label} 🚫 OR GATE: {reason}")
        return False, reason
    
    # Extract time component (handle both datetime and time objects)
    try:
        current_time = bar_datetime.time() if hasattr(bar_datetime, "time") else bar_datetime
    except Exception as e:
        reason = f"Timestamp extraction error: {e}"
        print(f"{ticker_label} 🚫 OR GATE: {reason}")
        return False, reason
    
    # Check if still in OR formation window
    if OR_START <= current_time < OR_END:
        reason = f"OR forming (current: {current_time.strftime('%H:%M:%S')}, need: {OR_END.strftime('%H:%M')}+)"
        print(f"{ticker_label} 🚫 OR GATE: {reason}")
        return False, reason
    
    # OR complete - gate open
    print(f"{ticker_label} ✅ OR GATE: Opening range complete (time: {current_time.strftime('%H:%M:%S')})")
    return True, "OR complete"


def print_gate_status(bars_session: list):
    """
    Print current gate status for monitoring/debugging.
    """
    if not bars_session:
        print("[OR-GATE] ⚠️  No session data available")
        return
    
    latest_bar = bars_session[-1]
    bar_datetime = latest_bar.get("datetime")
    
    if bar_datetime is None:
        print("[OR-GATE] ⚠️  Missing timestamp")
        return
    
    try:
        current_time = bar_datetime.time() if hasattr(bar_datetime, "time") else bar_datetime
        is_complete, reason = is_or_complete(bars_session)
        
        status_emoji = "🟢" if is_complete else "🔴"
        print(f"[OR-GATE] {status_emoji} Status: {reason}")
        
        if not is_complete:
            # Calculate time remaining
            if OR_START <= current_time < OR_END:
                current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
                end_seconds = OR_END.hour * 3600 + OR_END.minute * 60
                remaining_seconds = end_seconds - current_seconds
                remaining_minutes = remaining_seconds // 60
                print(f"[OR-GATE]    Time remaining: {remaining_minutes} min until OR complete")
    
    except Exception as e:
        print(f"[OR-GATE] ⚠️  Status check error: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# PHASE 4 TRACKING INTEGRATION
# ════════════════════════════════════════════════════════════════════════════════

def record_or_gate_rejection(ticker: str, reason: str):
    """
    Log OR gate rejection to Phase 4 signal funnel analytics.
    Non-fatal: if Phase 4 is disabled, this is a no-op.
    """
    try:
        from signal_analytics import signal_tracker
        if signal_tracker:
            # Record as a pre-validation filter (before signal generation)
            signal_tracker.record_pre_validation_filter(
                ticker=ticker,
                filter_name="OR_GATE",
                rejection_reason=reason
            )
    except ImportError:
        pass  # Phase 4 not available - silent no-op
    except Exception as e:
        print(f"[OR-GATE] Phase 4 tracking error (non-fatal): {e}")
