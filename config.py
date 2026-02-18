"""
War Machine Configuration - Complete CFW6 + Options Integration
Consolidates: config.py + config_updates.py
Single source of truth for all system parameters
"""
import os
from datetime import time
from dotenv import load_dotenv


# ══════════════════════════════════════════════════════════════════════════════
# API & DISCORD CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
EODHD_API_KEY      = os.getenv("EODHD_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ══════════════════════════════════════════════════════════════════════════════
# MARKET TIMING
# ══════════════════════════════════════════════════════════════════════════════
MARKET_OPEN             = time(9, 30)
MARKET_CLOSE            = time(16, 0)
OPENING_RANGE_START     = time(9, 30)
OPENING_RANGE_END       = time(9, 40)   # CFW6: 10-minute OR window
OPENING_RANGE_MINUTES   = 10
PREMARKET_START         = time(4, 0)    # CFW6: Advanced pre-market levels

# ══════════════════════════════════════════════════════════════════════════════
# SCANNER SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
TOP_SCAN_COUNT    = 50                  # Max tickers per scan cycle
MARKET_CAP_MIN    = 1_000_000_000       # $1B minimum market cap

# Adaptive scan intervals by time of day (seconds)
SCAN_INTERVALS = {
    "opening_range": 30,    # 9:30-9:45 - catch early setups fast
    "morning":       60,    # 9:45-11:00 - active morning session
    "midday":        180,   # 11:00-14:00 - slow choppy period
    "afternoon":     60,    # 14:00-15:30 - afternoon momentum
    "power_hour":    45,    # 15:30-16:00 - power hour urgency
    "after_hours":   300    # Outside market - minimal scanning
}

# Adaptive watchlist size by time of day
WATCHLIST_SIZE = {
    "early_morning": 30,    # 9:30-10:30 - focused list
    "mid_session":   50,    # 10:30-15:00 - full list
    "late_day":      35,    # 15:00-16:00 - reduced list
    "default":       40
}

# Volume & liquidity filters
MIN_REL_VOL      = 1.5     # Minimum relative volume threshold
OPTIONS_VOL_MULT = 2.0     # Options volume multiplier for boost

# ══════════════════════════════════════════════════════════════════════════════
# CFW6 SIGNAL DETECTION PARAMETERS
# ══════════════════════════════════════════════════════════════════════════════

# ORB (Opening Range Breakout) settings
ORB_BREAK_THRESHOLD = 0.001             # 0.1% default breakout threshold

# Adaptive ORB thresholds by volume (overrides ORB_BREAK_THRESHOLD)
ORB_THRESHOLDS = {
    "high_volume":   0.0008,            # 0.08% for 2x+ volume breakouts
    "normal_volume": 0.001,             # 0.10% for 1.5-2x volume
    "low_volume":    0.0015             # 0.15% for weak volume breakouts
}

# FVG (Fair Value Gap) settings
FVG_MIN_SIZE_PCT = 0.002               # 0.2% default minimum FVG size

# Adaptive FVG thresholds by volatility (overrides FVG_MIN_SIZE_PCT)
FVG_THRESHOLDS = {
    "high_volatility":   0.003,         # 0.3% for ATR > 2.0%
    "medium_volatility": 0.002,         # 0.2% for ATR 1.0-2.0%
    "low_volatility":    0.0015         # 0.15% for ATR < 1.0%
}

# CFW6 Confirmation settings
MAX_WAIT_CANDLES            = 15        # Reduced from 20 (optimization)
OPTIMAL_CONFIRMATION_WINDOW = 5        # Ideal: confirmed within 5 candles

# Confirmation candle types (from CFW6 video)
CONFIRMATION_TYPES = {
    "perfect": "A+",    # Strong directional candle, minimal wicks
    "flip":    "A",     # Opens opposite, flips to direction
    "wick":    "A-"     # Strong wick rejection, doesn't flip
}

# Multi-timeframe confirmation
CONFIRMATION_TIMEFRAMES = ["5m", "3m", "2m", "1m"]  # Priority: highest to lowest

# MTF convergence confidence boosts
MTF_CONVERGENCE_BOOST = {
    "three_plus": 0.15,                 # +15% for 3+ timeframes aligned
    "two":        0.05                  # +5% for 2 timeframes aligned
}

# ══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

# Grade-based ATR stop loss multipliers
STOP_MULTIPLIERS = {
    "A+": 1.2,      # Tightest stop for highest quality signals
    "A":  1.5,      # Standard stop
    "A-": 1.8       # Wider stop for marginal signals
}

# Target risk:reward ratios (CFW6 video rules)
TARGET_1_RR = 2.0   # T1 = 2R for all grades
TARGET_2_RR = 3.5   # T2 = 3.5R for all grades

# Position sizing (% of account at risk per trade)
POSITION_RISK = {
    "A+_high_confidence": 0.030,        # 3.0% for A+ with 85%+ confidence
    "A_high_confidence":  0.024,        # 2.4% for A with 75%+ confidence
    "standard":           0.020,        # 2.0% standard risk
    "conservative":       0.014         # 1.4% for marginal signals
}

# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE DECAY SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
CONFIDENCE_DECAY_ENABLED  = True
DECAY_START_CANDLE        = 6           # No penalty for candles 1-5
DECAY_RATE_EARLY          = 0.02        # 2% per candle (candles 6-10)
DECAY_RATE_MID            = 0.03        # 3% per candle (candles 11-15)
DECAY_RATE_LATE           = 0.05        # 5% per candle (candles 16+)
CONFIDENCE_FLOOR          = 0.50        # Minimum confidence floor

# ══════════════════════════════════════════════════════════════════════════════
# AI LEARNING ENGINE SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
LEARNING_LOOKBACK_DAYS      = 30
MIN_TRADES_FOR_LEARNING     = 10
CONFIDENCE_SMOOTHING        = 0.7       # EMA smoothing factor
INITIAL_MIN_CONFIDENCE      = 0.75
INITIAL_TARGET_WIN_RATE     = 0.65

# Baseline win rate for confirmation weight calculation
BASELINE_WIN_RATE           = 0.65

# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS TRADING SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

# IV filters
IV_RANK_MIN = 20            # Minimum IV rank for consideration
IV_RANK_MAX = 80            # Maximum IV rank (avoid IV crush)

# Liquidity filters
MIN_OPTION_OI           = 500           # Minimum open interest
MIN_OPTION_VOLUME       = 100           # Minimum daily volume
MAX_BID_ASK_SPREAD_PCT  = 0.10          # 10% max spread as % of mid

# Delta targets by grade (higher confidence = more aggressive delta)
DELTA_TARGETS = {
    "A+": (0.50, 0.60),     # ATM for highest quality
    "A":  (0.40, 0.50),     # Standard range
    "A-": (0.35, 0.45)      # OTM for marginal signals
}

# DTE (Days to Expiration) preferences
MIN_DTE   = 7               # Minimum days to expiration
MAX_DTE   = 45              # Maximum days to expiration
IDEAL_DTE = 21              # Target DTE for signals

# Theta decay limits
MAX_THETA_DECAY_PCT = 0.05  # Max daily theta decay as % of premium

# Dark pool integration
DARKPOOL_BOOST_THRESHOLD = 1_000_000    # $1M+ dark pool adds confidence
DARKPOOL_BOOST_FACTOR    = 0.05         # +5% confidence for dark pool

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE & LOGGING
# ══════════════════════════════════════════════════════════════════════════════
DB_PATH          = "market_memory.db"   # Main market data database
TRADES_DB_PATH   = "war_machine_trades.db"  # Trade history database
LOG_LEVEL        = "INFO"
BARS_RETENTION_DAYS = 7                 # Auto-cleanup bars older than 7 days

# ══════════════════════════════════════════════════════════════════════════════
# DEPLOYMENT SETTINGS (Railway)
# ══════════════════════════════════════════════════════════════════════════════
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
IS_PRODUCTION = ENVIRONMENT == "production"
