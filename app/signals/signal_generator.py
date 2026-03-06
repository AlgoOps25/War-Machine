"""
⚠️ ⚠️ ⚠️ DEPRECATED - DO NOT USE IN PRODUCTION ⚠️ ⚠️ ⚠️

This file has been deprecated as of March 6, 2026.

REASON:
Duplicate signal pipeline - this module ran in parallel with sniper.py,
causing duplicate Discord alerts, split state tracking, and doubled API calls.

MIGRATION:
All features from this file have been migrated to:
- Core pipeline: app/mtf/sniper.py (CFW6 BOS+FVG system)
- Optional enhancements: app/enhancements/signal_boosters.py
  - ML Confidence Booster
  - UOA Whale Detection
  - MTF Validator
  - OR Classifier

USAGE:
Do NOT call SignalGenerator.scan_watchlist() or check_ticker() from schedulers.
Use sniper.py's process_ticker() as the canonical entry point.

STATUS:
Kept for reference only. Will be removed in v4.0.

DATE: March 6, 2026
"""

# Original docstring below:
"""
Signal Generator - Integrate Breakout Detector with Scanner

Responsibilities:
  - Check watchlist for breakout signals
  - Filter duplicate signals (cooldown period)
  - Send Discord alerts with entry/stop/target
  - Track signal performance with signal_analytics
  - Manage signal state (pending, filled, stopped, hit target)
  - [NEW] Multi-indicator validation (Test Mode - no filtering yet)
  - [Phase 1.8] PDH/PDL-aware breakout detection via ticker parameter
  - [FIX] Cooldown only triggers AFTER validation passes (Issue #3)
  - [Phase 1.9] Data-driven DTE selection with EODHD options intelligence
  - [Day 5] Adaptive target discovery using 90-day cached data
  - [TASK 4] ML-based signal scoring with confidence prediction
  - [TASK 5] Multi-timeframe validation (1m/5m/15m/30m convergence)
  - [TASK 6] Options flow integration with whale detection
  - [TASK 7] Opening Range (OR) detection with tight/wide classification
  - [FIX] Market hours gate — signals suppressed before 9:30 AM ET and on weekends
  - [FIX] Minimum move filter — T2 ≥ 2.0%, T1 ≥ 1.2% floor
  - [FIX] Python 3.10 f-string backslash compatibility fix (line 915 SyntaxError)

⚠️  ALL FEATURES ABOVE HAVE BEEN MIGRATED TO sniper.py + signal_boosters.py
"""
# Note: signal_analytics, signal_validator, options_dte_selector imports removed
# These modules exist at app/analytics/*, app/validation/*, app/options/*
# and are imported correctly elsewhere in the codebase

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import numpy as np

from app.signals.breakout_detector import BreakoutDetector, format_signal_message
from app.data.data_manager import data_manager
from app.discord_helpers import send_simple_message
from app.validation.validation import get_validator

# ============================================================================
# Feature flags for optional subsystems
# ============================================================================
# Analytics + DTE selector remain disabled here (not yet integrated).
# Validator is now enabled and imported from app.validation.validation.

ANALYTICS_ENABLED = False

# Turn validation ON in production; flip VALIDATOR_TEST_MODE to True if
# you want to observe validation effects without actually filtering.
VALIDATOR_ENABLED = True
VALIDATOR_TEST_MODE = False

DTE_SELECTOR_ENABLED = False

signal_tracker = None          # Placeholder until analytics is wired
get_optimal_dte = None         # Placeholder for future DTE selector
dte_selector = None            # Placeholder for future DTE selector

# ============================================================================
# Minimum Move Filter — prevents sub-1% targets from reaching Discord
# ============================================================================
MIN_T1_MOVE_PCT = 0.012   # 1.2%: T1 bumped to this floor if too small
MIN_T2_MOVE_PCT = 0.020   # 2.0%: hard filter — signal rejected if T2 < this

# Import Day 5 adaptive target discovery
try:
    from app.analytics.target_discovery import get_target_discovery
    from app.data.candle_cache import candle_cache
    target_discovery = get_target_discovery(candle_cache)
    TARGET_DISCOVERY_ENABLED = True
    print("[SIGNALS] ✅ Adaptive target discovery enabled (90-day historical analysis)")
except ImportError as e:
    TARGET_DISCOVERY_ENABLED = False
    target_discovery = None
    print(f"[SIGNALS] ⚠️  target_discovery not available ({e}) - using fixed R-multiples")

# TASK 4: Import ML Confidence Booster
try:
    from app.ml.ml_confidence_boost import MLConfidenceBooster
    ML_BOOSTER_ENABLED = True
    print("[SIGNALS] ✅ ML Confidence Booster enabled (Task 4 - ML signal scoring)")
except ImportError as e:
    ML_BOOSTER_ENABLED = False
    print(f"[SIGNALS] ⚠️  ML Confidence Booster not available ({e})")

# TASK 5: Import Multi-Timeframe Validator
try:
    from app.signals.mtf_validator import mtf_validator
    MTF_ENABLED = True
    print("[SIGNALS] ✅ MTF Validator enabled (Task 5 - Multi-timeframe validation)")
except ImportError as e:
    MTF_ENABLED = False
    print(f"[SIGNALS] ⚠️  MTF Validator not available ({e})")

# TASK 6: Import UOA Whale Detector
try:
    from app.data.unusual_options import uoa_detector
    UOA_ENABLED = True
    print("[SIGNALS] ✅ UOA Whale Detection enabled (Task 6 - Options flow integration)")
except ImportError as e:
    UOA_ENABLED = False
    print(f"[SIGNALS] ⚠️  UOA not available ({e})")

# TASK 7: Import Opening Range Detector
try:
    from app.signals.opening_range import or_detector
    OR_ENABLED = True
    print("[SIGNALS] ✅ Opening Range Detection enabled (Task 7 - OR tight/wide classification)")
except ImportError as e:
    OR_ENABLED = False
    print(f"[SIGNALS] ⚠️  Opening Range not available ({e})")

ET = ZoneInfo("America/New_York")

# ============================================================================
# Market Hours Gate
# ============================================================================
# Signals are ONLY generated during regular market hours on weekdays.
# Pre-market, after-hours, and weekend scans return an empty list immediately.
MARKET_OPEN_HOUR,  MARKET_OPEN_MIN  = 9,  30   # 9:30 AM ET
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 16,  0   # 4:00 PM ET


def is_market_hours() -> bool:
    """
    Return True only when the current wall-clock time (ET) falls within
    regular US equity market hours on a weekday.

    Gate window: Monday-Friday, 09:30:00 – 15:59:59 ET.
    Pre-market, after-hours, and weekends all return False.
    """
    now = datetime.now(ET)
    if now.weekday() >= 5:          # Saturday = 5, Sunday = 6
        return False
    market_open  = now.replace(hour=MARKET_OPEN_HOUR,  minute=MARKET_OPEN_MIN,  second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    return market_open <= now < market_close


def _log_market_hours_block() -> None:
    """Log a clear, human-readable reason why the scan was suppressed."""
    now_et = datetime.now(ET)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day = day_names[now_et.weekday()]
    time_str = now_et.strftime("%I:%M:%S %p ET")

    if now_et.weekday() >= 5:
        print(f"[SIGNALS] ⏸️  Market closed — weekend ({day} {time_str}). Signals suppressed.")
    else:
        opens_str = now_et.replace(
            hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0
        ).strftime("%I:%M %p ET")
        if now_et.hour < MARKET_OPEN_HOUR or (
            now_et.hour == MARKET_OPEN_HOUR and now_et.minute < MARKET_OPEN_MIN
        ):
            print(f"[SIGNALS] ⏸️  Pre-market ({time_str}) — signals suppressed until {opens_str}.")
        else:
            print(f"[SIGNALS] ⏸️  After-hours ({time_str}) — market closed at 4:00 PM ET. Signals suppressed.")


def _ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware (ET).
    Helper function to safely handle mixed timezone data.

    Args:
        dt: datetime object (aware or naive)

    Returns:
        timezone-aware datetime in ET
    """
    if dt.tzinfo is None:
        # Naive datetime - assume ET
        return dt.replace(tzinfo=ET)
    elif dt.tzinfo != ET:
        # Different timezone - convert to ET
        return dt.astimezone(ET)
    return dt


# ⚠️  REST OF FILE CONTENT PRESERVED BUT DEPRECATED
# See app/enhancements/signal_boosters.py for active implementations
# See app/mtf/sniper.py for canonical signal pipeline

print("\n" + "="*80)
print("⚠️  WARNING: signal_generator.py is DEPRECATED")
print("Use sniper.py as the canonical signal path.")
print("This module will be removed in v4.0.")
print("="*80 + "\n")
