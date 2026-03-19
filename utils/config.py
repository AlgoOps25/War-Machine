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
import sys
import logging
from datetime import time as dtime

logger = logging.getLogger(__name__)

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

# ========================================
# OPENING RANGE THRESHOLDS
# ========================================

# Static regime-aware OR thresholds (used by _get_or_threshold in sniper.py)
MIN_OR_RANGE_PCT = 0.030          # default / BULL
MIN_OR_RANGE_PCT_BEAR = 0.027     # BEAR regime
MIN_OR_RANGE_PCT_STRONG_BEAR = 0.025  # STRONG_BEAR regime

# ── A1: VIX-Scaled OR Threshold ──────────────────────────────────────────────────────────────
VIX_OR_THRESHOLDS = [
    (15,  0.030),   # VIX <15  → 3.0%
    (20,  0.025),   # VIX <20  → 2.5%
    (28,  0.018),   # VIX <28  → 1.8%
    (35,  0.015),   # VIX <35  → 1.5%
    (999, 0.012),   # VIX ≥35  → 1.2%
]


def get_vix_or_threshold(vix: float, spy_regime: dict = None) -> float:
    """
    Return the VIX-scaled minimum OR range % threshold.
    """
    vix_threshold = MIN_OR_RANGE_PCT  # fallback
    for upper_bound, pct in VIX_OR_THRESHOLDS:
        if vix < upper_bound:
            vix_threshold = pct
            break

    if spy_regime:
        label = spy_regime.get("label", "")
        if label == "STRONG_BEAR":
            regime_floor = MIN_OR_RANGE_PCT_STRONG_BEAR
        elif label == "BEAR":
            regime_floor = MIN_OR_RANGE_PCT_BEAR
        else:
            regime_floor = MIN_OR_RANGE_PCT
        return min(vix_threshold, regime_floor)

    return vix_threshold


# ========================================
# SECONDARY RANGE (Power Hour — B1)
# ========================================

SECONDARY_RANGE_ENABLED = True
SECONDARY_RANGE_START = dtime(10, 0)   # 10:00 AM ET
SECONDARY_RANGE_END   = dtime(10, 30)  # 10:30 AM ET
SECONDARY_RANGE_MIN_BARS = 20
SECONDARY_RANGE_MIN_PCT = 0.005

# Options filtering thresholds
MIN_DTE = 0
MAX_DTE = 7
IDEAL_DTE = 2
MIN_OPTION_OI = 100
MIN_OPTION_VOLUME = 50
MAX_BID_ASK_SPREAD_PCT = 0.10
TARGET_DELTA_MIN = 0.40
TARGET_DELTA_MAX = 0.70
MAX_THETA_DECAY_PCT = 0.05

# ========================================
# MARKET HOURS
# ========================================

MARKET_OPEN  = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
PRE_MARKET_START = dtime(4, 0)
AFTER_HOURS_END  = dtime(20, 0)

# ========================================
# WEBSOCKET FEED
# ========================================

ENABLE_WEBSOCKET_FEED = True

# ========================================
# DISCORD ALERTS
# ========================================

DISCORD_SIGNALS_WEBHOOK_URL = os.getenv('DISCORD_SIGNALS_WEBHOOK_URL', '')

DISCORD_NEWS_WEBHOOK_URL = os.getenv('DISCORD_NEWS_WEBHOOK_URL', '')

DISCORD_WATCHLIST_WEBHOOK_URL = os.getenv('DISCORD_WATCHLIST_WEBHOOK_URL', '')

# ========================================
# BASELINE SCANNER CONFIGURATION
# ========================================

ORB_BREAK_THRESHOLD = 0.001
FVG_MIN_SIZE_PCT = 0.005
CONFIRMATION_TIMEOUT_BARS = 5

MIN_CONFIDENCE_OR = 0.75
MIN_CONFIDENCE_INTRADAY = 0.70
CONFIDENCE_ABSOLUTE_FLOOR = 0.65

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

MIN_PRICE = 5.0
MAX_PRICE = 500.0
MIN_VOLUME = 1_000_000
MIN_RELATIVE_VOLUME = 2.0
MIN_ATR_MULTIPLIER = 4.0

MFI_MIN = 60
OBV_BARS_MIN = 0
VWAP_ZONE = 'above_vwap'
TF_CONFIRM = '1m'

OR_START_TIME = dtime(9, 30)
OR_END_TIME = dtime(9, 45)
TRADING_START = dtime(9, 45)
TRADING_END = dtime(15, 45)
FORCE_CLOSE_TIME = dtime(15, 50)

# ========================================
# RISK MANAGEMENT
# ========================================

STOP_LOSS_MULTIPLIER = 1.5
TAKE_PROFIT_MULTIPLIER = 3.0
MAX_LOSS_PER_TRADE_PCT = 2.0
TRAILING_STOP_ACTIVATION = 1.0

# ========================================
# VALIDATION
# ========================================

VALIDATOR_MIN_SCORE = 0.6
VALIDATOR_ENABLED = True

OPTIONS_FILTER_ENABLED = True
OPTIONS_FILTER_MODE = "HARD"

REGIME_FILTER_ENABLED = True
MIN_VIX_LEVEL = 12.0
MAX_VIX_LEVEL = 35.0

# ========================================
# ADVANCED FEATURES
# ========================================

MTF_ENABLED = True
MTF_CONVERGENCE_BOOST = 0.05

CANDLE_CONFIRMATION_ENABLED = True

HOURLY_GATE_ENABLED = True

CORRELATION_CHECK_ENABLED = True

EXPLOSIVE_SCORE_THRESHOLD = 80
EXPLOSIVE_RVOL_THRESHOLD = 4.0

# ========================================
# BACKTEST CAMPAIGN CHAMPION REFERENCE
# ========================================

BACKTEST_CHAMPION = {
    'bos_strength' : 0.001,
    'tf_confirm'   : '1m',
    'vwap_zone'    : 'above_vwap',
    'rvol_min'     : 3.0,
    'mfi_min'      : 60,
    'obv_bars'     : 0,
    'session'      : 'all_day',
    'direction'    : 'call_only',
    'win_rate'     : 0.706,
    'avg_r'        : 0.44,
    'score'        : 0.3130,
    'trades'       : 34,
    'tickers'      : 'AAPL,AMD,META,MSFT,NVDA,TSLA,AMZN,ORCL,WMT,BAC,CSCO',
}

# ========================================
# DEVELOPMENT & TESTING
# ========================================

DEBUG_MODE = False
BACKTEST_MODE = False
PAPER_TRADING = False

# ========================================
# PRODUCTION SAFETY
# ========================================

MAX_DAILY_TRADES = 15
COOLDOWN_SAME_DIRECTION = 30
COOLDOWN_OPPOSITE_DIRECTION = 15


# ========================================
# STARTUP ENV-VAR VALIDATION
# ========================================

# Hard-required: missing any of these = immediate sys.exit(1) before market open
_REQUIRED_VARS = [
    ("EODHD_API_KEY",                  "Market data feed (EODHD WebSocket + REST)"),
    ("DATABASE_URL",                   "PostgreSQL analytics DB"),
    ("DISCORD_SIGNALS_WEBHOOK_URL",    "Primary signals Discord channel"),
    ("DISCORD_PERFORMANCE_WEBHOOK_URL","Performance alerts Discord channel"),
    ("DISCORD_EXIT_WEBHOOK_URL",       "Position exit alerts Discord channel"),
]

# Soft-required: missing = WARNING in logs, system continues degraded
_OPTIONAL_VARS = [
    ("DISCORD_REGIME_WEBHOOK_URL",    "SPY+QQQ regime visual channel"),
    ("DISCORD_WATCHLIST_WEBHOOK_URL", "Pre-market watchlist channel"),
    ("TRADIER_API_KEY",               "Options data (Greeks / chain)"),
    ("UNUSUAL_WHALES_API_KEY",        "Dark pool / UOA flow data"),
]


def validate_required_env_vars() -> None:
    """
    Validate all required and optional environment variables at startup.

    - REQUIRED vars: missing → prints error table and calls sys.exit(1).
    - OPTIONAL vars: missing → logs WARNING; system continues degraded.

    Call this once at the top of start_scanner_loop() before any
    blocking work (DB connect, WS init, etc.) so Railway surfaces a
    clear config error instead of a cryptic mid-boot crash.
    """
    logger.info("\n" + "=" * 62)
    logger.info("[CONFIG] Environment variable validation")
    logger.info("=" * 62)

    missing_required = []

    for var, description in _REQUIRED_VARS:
        value = os.getenv(var, "").strip()
        if value:
            masked = value[:6] + "..." if len(value) > 6 else "***"
            logger.info(f"  ✅ {var:<40} {masked}")
        else:
            logger.info(f"  ❌ {var:<40} MISSING  ← {description}")
            missing_required.append(var)

    for var, description in _OPTIONAL_VARS:
        value = os.getenv(var, "").strip()
        if value:
            masked = value[:6] + "..." if len(value) > 6 else "***"
            logger.info(f"  ✅ {var:<40} {masked}")
        else:
            logger.info(f"  ⚠️  {var:<39} not set  ({description})")

    logger.info("=" * 62)

    if missing_required:
        logger.info("\n[CONFIG] ❌ FATAL — Missing required environment variables:")
        for var in missing_required:
            logger.info(f"         • {var}")
        print(
            "\n         Set these in Railway → Variables before deploying.\n",
            flush=True
        )
        sys.exit(1)

    logger.info("[CONFIG] ✅ All required vars present — boot continuing\n")


if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("WAR MACHINE CONFIGURATION")
    logger.info("=" * 70)
    logger.info(f"Account Size: ${ACCOUNT_SIZE:,.0f}")
    logger.info(f"Max Open Positions: {MAX_OPEN_POSITIONS}")
    logger.info(f"Max Daily Loss: {MAX_DAILY_LOSS_PCT}%")
    logger.info(f"Min Confidence (OR): {MIN_CONFIDENCE_OR*100:.0f}%")
    logger.info(f"Min Confidence (Intraday): {MIN_CONFIDENCE_INTRADAY*100:.0f}%")
    logger.info(f"Opening Range Window: {OR_START_TIME} - {OR_END_TIME}")
    logger.info(f"Trading Window: {TRADING_START} - {TRADING_END}")
    logger.info(f"Force Close: {FORCE_CLOSE_TIME}")
    logger.info(f"\nVIX-Scaled OR Thresholds:")
    for upper, pct in VIX_OR_THRESHOLDS:
        label = f"VIX < {upper}" if upper < 999 else "VIX ≥ 35"
        logger.info(f"  {label:<12} → {pct*100:.1f}%")
    logger.info(f"\nSecondary Range (Power Hour):")
    logger.info(f"  Window  : {SECONDARY_RANGE_START} - {SECONDARY_RANGE_END}")
    logger.info(f"  Enabled : {SECONDARY_RANGE_ENABLED}")
    logger.info(f"  Min Bars: {SECONDARY_RANGE_MIN_BARS}")
    logger.info(f"  Min Pct : {SECONDARY_RANGE_MIN_PCT*100:.1f}%")
    logger.info(f"\nAdvanced Features:")
    logger.info(f"  Validator: {'Enabled' if VALIDATOR_ENABLED else 'Disabled'}")
    logger.info(f"  Options Filter: {'Enabled (' + OPTIONS_FILTER_MODE + ')' if OPTIONS_FILTER_ENABLED else 'Disabled'}")
    logger.info(f"  Regime Filter: {'Enabled' if REGIME_FILTER_ENABLED else 'Disabled'}")
    logger.info(f"  MTF Convergence: {'Enabled' if MTF_ENABLED else 'Disabled'}")
    logger.info(f"  Hourly Gate: {'Enabled' if HOURLY_GATE_ENABLED else 'Disabled'}")
    logger.info(f"  Correlation Check: {'Enabled' if CORRELATION_CHECK_ENABLED else 'Disabled'}")
    logger.info(f"\nCampaign Champion (2026-03-10):")
    logger.info(f"  BOS Threshold : {ORB_BREAK_THRESHOLD*100:.2f}%")
    logger.info(f"  Min RVOL      : {MIN_RELATIVE_VOLUME}x")
    logger.info(f"  MFI Floor     : {MFI_MIN}")
    logger.info(f"  VWAP Zone     : {VWAP_ZONE}")
    logger.info(f"  TF Confirm    : {TF_CONFIRM}")
    logger.info("=" * 70)
    validate_required_env_vars()
