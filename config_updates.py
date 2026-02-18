"""
CFW6 Configuration Updates - HIGH PRIORITY OPTIMIZATIONS
Add these to your existing config.py file
"""

# ══════════════════════════════════════════════════════════════════════════════
# CFW6 ENHANCED PARAMETERS (HIGH PRIORITY)
# ══════════════════════════════════════════════════════════════════════════════

# Confirmation Wait Times (REDUCED from 20 to 15)
MAX_WAIT_CANDLES = 15  # Maximum candles to wait for confirmation after FVG
OPTIMAL_CONFIRMATION_WINDOW = 5  # Ideal: confirmation within 5 candles

# Confidence Decay Parameters
CONFIDENCE_DECAY_ENABLED = True
DECAY_START_CANDLE = 6  # Start penalizing after candle 5
DECAY_RATE_EARLY = 0.02  # 2% per candle (candles 6-10)
DECAY_RATE_MID = 0.03    # 3% per candle (candles 11-15)
DECAY_RATE_LATE = 0.05   # 5% per candle (candles 16+)

# Grade-Based Stop Loss Multipliers
STOP_MULTIPLIERS = {
    "A+": 1.2,  # Tightest stop for highest quality
    "A": 1.5,   # Standard stop
    "A-": 1.8   # Wider stop for marginal setups
}

# Adaptive Scan Intervals (by time of day)
SCAN_INTERVALS = {
    "opening_range": 30,   # 9:30-9:45
    "morning": 60,         # 9:45-11:00
    "midday": 180,         # 11:00-2:00
    "afternoon": 60,       # 2:00-3:30
    "power_hour": 45,      # 3:30-4:00
    "after_hours": 300     # Outside market hours
}

# Multi-Timeframe Settings
MTF_ENABLED = True  # Enable multi-timeframe scanning
MTF_CONVERGENCE_BONUS = {
    "three_plus": 0.15,  # +15% confidence for 3+ timeframes
    "two": 0.05          # +5% confidence for 2 timeframes
}

# Adaptive FVG Thresholds (ATR-based)
ADAPTIVE_FVG_ENABLED = True
FVG_THRESHOLDS_BY_VOLATILITY = {
    "high": 0.003,    # 0.3% for ATR > 2.0%
    "medium": 0.002,  # 0.2% for ATR 1.0-2.0%
    "low": 0.0015     # 0.15% for ATR < 1.0%
}

# Volume-Based ORB Thresholds
ADAPTIVE_ORB_ENABLED = True
ORB_THRESHOLDS_BY_VOLUME = {
    "high": 0.0008,   # 0.08% for 2x+ volume
    "medium": 0.001,  # 0.10% for 1.5-2x volume
    "low": 0.0015     # 0.15% for <1.5x volume
}

# Confirmation Candle Types (from video)
CONFIRMATION_TYPES = {
    "perfect": "A+",  # Strong directional candle, minimal wicks
    "flip": "A",      # Opens opposite, flips to direction
    "wick": "A-"      # Strong wick rejection, doesn't flip
}

# Watchlist Size by Time
ADAPTIVE_WATCHLIST_SIZE = {
    "early_morning": 30,   # 9:30-10:30
    "mid_morning": 50,     # 10:30-15:00
    "late_day": 35,        # 15:00-16:00
    "default": 40
}
