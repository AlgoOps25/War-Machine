"""
War Machine Configuration
Complete CFW6 + Options Integration
"""

import os
from datetime import time

# ══════════════════════════════════════════════════════════════════════════════
# API & DISCORD CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ══════════════════════════════════════════════════════════════════════════════
# MARKET TIMING
# ══════════════════════════════════════════════════════════════════════════════
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
OPENING_RANGE_MINUTES = 10  # CFW6: 9:30 - 9:40 (10 minutes)

# ══════════════════════════════════════════════════════════════════════════════
# SCANNER SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
SCAN_INTERVAL = 120  # seconds between full scanner cycles
TOP_SCAN_COUNT = 50  # number of top tickers to process
MARKET_CAP_MIN = 1_000_000_000  # $1B minimum market cap

# Volume & liquidity filters
MIN_REL_VOL = 1.5  # minimum relative volume threshold
OPTIONS_VOL_MULT = 2.0  # options volume multiplier for boost

# ══════════════════════════════════════════════════════════════════════════════
# CFW6 SIGNAL DETECTION PARAMETERS
# ══════════════════════════════════════════════════════════════════════════════
# ORB (Opening Range Breakout) settings
ORB_BREAK_THRESHOLD = 0.001  # 0.1% minimum breakout threshold

# FVG (Fair Value Gap) settings
FVG_MIN_SIZE_PCT = 0.002  # 0.2% minimum FVG size

# CFW6 Confirmation settings
MAX_WAIT_CANDLES = 20  # Maximum candles to wait for confirmation after FVG

# Multi-timeframe confirmation
CONFIRMATION_TIMEFRAMES = ["5m", "3m", "2m", "1m"]  # Priority order: highest to lowest

# ══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
STOP_ATR_MULT = 1.5  # ATR multiplier for stop loss
TARGET_1_RR = 2.0    # Risk:Reward for first target
TARGET_2_RR = 3.5    # Risk:Reward for second target

# ══════════════════════════════════════════════════════════════════════════════
# LEARNING ENGINE SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
LEARNING_LOOKBACK_DAYS = 30
MIN_TRADES_FOR_LEARNING = 10
CONFIDENCE_SMOOTHING = 0.7  # EMA smoothing factor for confidence adjustments

# Initial confidence thresholds (will be adjusted by learning engine)
INITIAL_MIN_CONFIDENCE = 0.75
INITIAL_TARGET_WIN_RATE = 0.65

# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS TRADING SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
# IV filters
IV_RANK_MIN = 20  # minimum IV rank for consideration
IV_RANK_MAX = 80  # maximum IV rank (avoid IV crush scenarios)

# Liquidity filters
MIN_OPTION_OI = 500  # minimum open interest
MIN_OPTION_VOLUME = 100  # minimum daily volume
MAX_BID_ASK_SPREAD_PCT = 0.10  # 10% max spread as % of mid

# Greeks preferences
TARGET_DELTA_MIN = 0.35  # minimum delta for directional trades
TARGET_DELTA_MAX = 0.55  # maximum delta for directional trades
MAX_THETA_DECAY_PCT = 0.05  # max acceptable daily theta decay as % of premium

# DTE (Days to Expiration) preferences
MIN_DTE = 7   # minimum days to expiration
MAX_DTE = 45  # maximum days to expiration
IDEAL_DTE = 21  # target DTE for signals

# Dark pool integration
DARKPOOL_BOOST_THRESHOLD = 1000000  # $1M+ dark pool volume adds confidence boost
DARKPOOL_BOOST_FACTOR = 0.05  # +5% confidence boost for dark pool activity

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE & LOGGING
# ══════════════════════════════════════════════════════════════════════════════
DB_PATH = "market_memory.db"
LOG_LEVEL = "INFO"
