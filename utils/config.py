"""
War Machine Configuration - Core Settings
Simple, production-proven configuration for War Machine trading system.

Note: The WarMachineConfig class (500+ lines) was removed per Issue #20.
Reason: Well-designed but never integrated into the system. The simple
key-value configuration below has proven reliable in production.

If advanced filter configuration is needed in the future, see:
docs/ISSUE_20_WARMACHINECONFIG_ANALYSIS.md for the archived implementation.
"""

import os
from datetime import time as dtime


# ========================================
# API KEYS & CREDENTIALS
# ========================================

# EODHD API Key (required for data_manager, signal_generator, etc.)
EODHD_API_KEY = os.getenv('EODHD_API_KEY', '')  # Replace with your actual key

# Account Configuration
ACCOUNT_SIZE = 5000  # Your trading account size in USD

# Risk Management
MAX_SECTOR_EXPOSURE_PCT = 30.0  # Maximum exposure to any single sector (%)
MAX_POSITION_SIZE_PCT = 5.0     # Maximum % of account per position
MAX_DAILY_LOSS_PCT = 2.0        # Stop trading if daily loss exceeds this %
MAX_INTRADAY_DRAWDOWN_PCT = 5.0 # Max drawdown from intraday high water mark
MAX_OPEN_POSITIONS = 5          # Maximum concurrent positions
MAX_CONTRACTS = 10              # Maximum contracts per position
MIN_RISK_REWARD_RATIO = 1.5     # Minimum R:R for new positions

# Position Sizing Tiers (% of account risk per trade)
# These are BASE values before performance/VIX multipliers
POSITION_RISK = {
    "A+_high_confidence": 0.04,  # 4% risk for A+ grade + 85%+ confidence
    "A_high_confidence":  0.03,  # 3% risk for A/A+ grade + 75%+ confidence
    "standard":           0.02,  # 2% risk for 65%+ confidence
    "conservative":       0.01,  # 1% risk for lower confidence (<65%)
}

# Database Configuration (optional - uses SQLite if not set)
DATABASE_URL = None  # Set to PostgreSQL URL if using Railway/Heroku
# Database configuration
DB_PATH = os.getenv('DB_PATH', '/app/data/war_machine.db')
DBPATH = DB_PATH  # Alias used by WatchlistFunnel / VolumeAnalyzer

# Opening range filter - TASK 2 INTEGRATION
MIN_OR_RANGE_PCT = 0.03  # Minimum 3% OR range for early-session CFW6_OR gate (Task 2)

# Options filtering thresholds - TASK 3 INTEGRATION
MIN_DTE = 0  # Minimum days to expiration (0DTE allowed)
MAX_DTE = 7  # Maximum days to expiration (weekly options)
IDEAL_DTE = 2  # Ideal DTE for scoring (2 days out)
MIN_OPTION_OI = 100  # Minimum open interest
MIN_OPTION_VOLUME = 50  # Minimum daily volume
MAX_BID_ASK_SPREAD_PCT = 0.10  # Maximum 10% spread
TARGET_DELTA_MIN = 0.40  # Minimum delta (0.40-0.70 range)
TARGET_DELTA_MAX = 0.70  # Maximum delta
MAX_THETA_DECAY_PCT = 0.05  # Maximum 5% theta decay per day

# ========================================
# MARKET HOURS (datetime.time objects for proper comparisons)
# ========================================

# FIX: Must be datetime.time objects, NOT strings.
# scanner.py and data_manager.py compare these with datetime.time values.
MARKET_OPEN  = dtime(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dtime(16, 0)   # 4:00 PM ET
PRE_MARKET_START = dtime(4, 0)   # 4:00 AM ET (extended hours open)
AFTER_HOURS_END  = dtime(20, 0)  # 8:00 PM ET (extended hours close)

# ========================================
# WEBSOCKET FEED
# ========================================

ENABLE_WEBSOCKET_FEED = True  # Enable EODHD WebSocket real-time feed

# ========================================
# DISCORD ALERTS
# ========================================

# Primary signals channel
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# Dedicated news/catalyst channel (Phase 1.18)
DISCORD_NEWS_WEBHOOK_URL = os.getenv(
    'DISCORD_NEWS_WEBHOOK_URL',
    'https://discord.com/api/webhooks/1481012609158479992/3a0xzUeNK4hbWQPW3i_6uRrFeOb_nsOR3HoIOMFhoHwq4yRruEIEQ40aULSoRKPQvIhQ'
)

# ========================================
# BASELINE SCANNER CONFIGURATION
# ========================================

# ── Backtest Campaign Champion (2026-03-10) ────────────────────────────────────────────
# Run   : 32,400 combos × 15 tickers × 90 days (2025-12-10 → 2026-03-09)
# Result: 70.6% WR  |  +0.44 avg-R  |  34 trades  |  score=0.3130
# Filter: min_trades=30, min_wr=55%  (183 qualifying combos)
# Locked: BOS=0.10%, RVOL=2.0x, direction=call_only, MFI≥60
# Note  : put_only eliminated (no qualifying combos); extend to 180-day
#         dataset before updating bear-side params.
ORB_BREAK_THRESHOLD = 0.001     # 0.1% BOS threshold — campaign champion (was 0.002)
FVG_MIN_SIZE_PCT = 0.005        # 0.5% minimum FVG size
CONFIRMATION_TIMEOUT_BARS = 5   # Max bars to wait for confirmation

# Confidence thresholds
MIN_CONFIDENCE_OR = 0.75        # Minimum confidence for OR-anchored signals
MIN_CONFIDENCE_INTRADAY = 0.70  # Minimum confidence for intraday signals
CONFIDENCE_ABSOLUTE_FLOOR = 0.65  # Hard floor regardless of grade

# Grade-specific confidence floors
MIN_CONFIDENCE_BY_GRADE = {
    "A+": 0.75,
    "A":  0.70,
    "A-": 0.65,
    "B+": 0.60,
    "B":  0.55,
    "B-": 0.50,
    "C+": 0.45,
    "C":  0.40,
    "C-": 0.35,
}

# Scanner parameters
MIN_PRICE = 5.0                 # Minimum stock price
MAX_PRICE = 500.0               # Maximum stock price
MIN_VOLUME = 1_000_000          # Minimum daily volume
MIN_RELATIVE_VOLUME = 2.0       # Minimum RVOL — campaign confirmed (cliff at 3.0x)
MIN_ATR_MULTIPLIER = 4.0        # Minimum ATR for volatility

# Campaign-derived signal quality filters
MFI_MIN = 60                    # MFI floor — campaign winner (0=off, 60 best)
OBV_BARS_MIN = 0                # OBV rising bars — noise in backtest, disabled
VWAP_ZONE = 'above_vwap'        # VWAP zone — tied with 'none' but adds logic
TF_CONFIRM = '1m'               # TF confirmation tier — campaign winner at >=30 trades

# Time windows
OR_START_TIME = dtime(9, 30)    # Opening range start
OR_END_TIME = dtime(9, 45)      # Opening range end (widened from 9:40)
TRADING_START = dtime(9, 45)    # Start looking for signals
TRADING_END = dtime(15, 45)     # Stop new signals
FORCE_CLOSE_TIME = dtime(15, 50) # Force close all positions

# ========================================
# RISK MANAGEMENT
# ========================================

STOP_LOSS_MULTIPLIER = 1.5      # ATR multiplier for stop loss
TAKE_PROFIT_MULTIPLIER = 3.0    # Risk multiplier for take profit
MAX_LOSS_PER_TRADE_PCT = 2.0    # Maximum % loss per trade
TRAILING_STOP_ACTIVATION = 1.0  # R:R ratio to activate trailing stop

# ========================================
# VALIDATION
# ========================================

# Multi-indicator validator thresholds
VALIDATOR_MIN_SCORE = 0.6       # Minimum score to pass validator
VALIDATOR_ENABLED = True        # Enable multi-indicator validation

# Options validation
OPTIONS_FILTER_ENABLED = True   # Enable options pre-validation
OPTIONS_FILTER_MODE = "HARD"    # "SOFT" (log only) or "HARD" (filter)

# Regime filter
REGIME_FILTER_ENABLED = True    # Enable VIX/SPY market condition check
MIN_VIX_LEVEL = 12.0            # Minimum VIX for favorable regime
MAX_VIX_LEVEL = 35.0            # Maximum VIX for favorable regime

# ========================================
# ADVANCED FEATURES
# ========================================

# MTF (Multi-timeframe) settings
MTF_ENABLED = True              # Enable multi-timeframe FVG detection
MTF_CONVERGENCE_BOOST = 0.05    # +5% confidence for MTF convergence

# Candle confirmation settings
CANDLE_CONFIRMATION_ENABLED = True  # Enable 3-tier candle quality model

# Hourly gate settings
HOURLY_GATE_ENABLED = True      # Enable time-based confidence adjustment

# Correlation check settings
CORRELATION_CHECK_ENABLED = True  # Enable sector-aware correlation filter

# Explosive mover override
EXPLOSIVE_SCORE_THRESHOLD = 80    # Score threshold for regime bypass
EXPLOSIVE_RVOL_THRESHOLD = 4.0    # RVOL threshold for regime bypass

# ========================================
# BACKTEST CAMPAIGN CHAMPION REFERENCE
# ========================================
# Audit trail — do not use directly in live code; reference only.
# Update after each campaign run.

BACKTEST_CHAMPION = {
    # Run date  : 2026-03-10
    # Dataset   : 15 tickers, 90 days (2025-12-10 to 2026-03-09), 134,028 bars
    # Combos    : 32,400 tested → 4,760 saved → 183 qualifying (min 30 trades, 55% WR)
    'bos_strength' : 0.001,        # 0.10% — dominant, score drops 44% at 0.15%
    'tf_confirm'   : '1m',         # 1m — best at >=30 trade floor
    'vwap_zone'    : 'above_vwap', # tied with 'none'; kept for directional logic
    'rvol_min'     : 3.0,          # hard cliff at 3.0x
    'mfi_min'      : 60,           # marginal but consistent
    'obv_bars'     : 0,            # noise — disabled
    'session'      : 'all_day',    # no session segmentation in data
    'direction'    : 'call_only',  # put_only eliminated; bear params need own run
    # Stats
    'win_rate'     : 0.706,
    'avg_r'        : 0.44,
    'score'        : 0.3130,
    'trades'       : 34,
    'tickers'      : 'AAPL,AMD,META,MSFT,NVDA,TSLA,AMZN,ORCL,WMT,BAC,CSCO',
    # Next action: extend dataset to 180 days; run bear-specific campaign
}

# ========================================
# DEVELOPMENT & TESTING
# ========================================

DEBUG_MODE = False              # Enable verbose logging
BACKTEST_MODE = False           # Backtesting mode (no live trading)
PAPER_TRADING = False           # Paper trading mode

# ========================================
# PRODUCTION SAFETY
# ========================================

MAX_DAILY_TRADES = 15           # Maximum trades per day
COOLDOWN_SAME_DIRECTION = 30    # Minutes before same-direction signal (Issue #19)
COOLDOWN_OPPOSITE_DIRECTION = 15 # Minutes before opposite-direction signal (Issue #19)

if __name__ == "__main__":
    print("="*70)
    print("WAR MACHINE CONFIGURATION")
    print("="*70)
    print(f"Account Size: ${ACCOUNT_SIZE:,.0f}")
    print(f"Max Open Positions: {MAX_OPEN_POSITIONS}")
    print(f"Max Daily Loss: {MAX_DAILY_LOSS_PCT}%")
    print(f"Min Confidence (OR): {MIN_CONFIDENCE_OR*100:.0f}%")
    print(f"Min Confidence (Intraday): {MIN_CONFIDENCE_INTRADAY*100:.0f}%")
    print(f"Opening Range Window: {OR_START_TIME} - {OR_END_TIME}")
    print(f"Trading Window: {TRADING_START} - {TRADING_END}")
    print(f"Force Close: {FORCE_CLOSE_TIME}")
    print(f"\nAdvanced Features:")
    print(f"  Validator: {'Enabled' if VALIDATOR_ENABLED else 'Disabled'}")
    print(f"  Options Filter: {'Enabled (' + OPTIONS_FILTER_MODE + ')' if OPTIONS_FILTER_ENABLED else 'Disabled'}")
    print(f"  Regime Filter: {'Enabled' if REGIME_FILTER_ENABLED else 'Disabled'}")
    print(f"  MTF Convergence: {'Enabled' if MTF_ENABLED else 'Disabled'}")
    print(f"  Hourly Gate: {'Enabled' if HOURLY_GATE_ENABLED else 'Disabled'}")
    print(f"  Correlation Check: {'Enabled' if CORRELATION_CHECK_ENABLED else 'Disabled'}")
    print(f"\nCampaign Champion (2026-03-10):")
    print(f"  BOS Threshold : {ORB_BREAK_THRESHOLD*100:.2f}%")
    print(f"  Min RVOL      : {MIN_RELATIVE_VOLUME}x")
    print(f"  MFI Floor     : {MFI_MIN}")
    print(f"  VWAP Zone     : {VWAP_ZONE}")
    print(f"  TF Confirm    : {TF_CONFIRM}")
    print("="*70)
