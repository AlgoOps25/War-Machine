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
from dotenv import load_dotenv
load_dotenv()
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
OR_RANGE_MIN_PCT = 0.2   # keep — has zero effect but documents intent
OR_RANGE_MAX_PCT = 99.0  # was 3.0 — remove the cap

# ── OR Range Upper Cap ────────────────────────────────────────────────────────
# OR_RANGE_MAX_PCT: upper bound for OR range filter in scanner/sniper.
#
# Grid search finding (2026-03-24, 312 tickers × 90 days, 582 filtered trades):
#   OR range distribution: 0% of trades < 1%, 51.5% of trades > 5%
#   or_max=3.0  → 130 trades | 33.1% WR | +5.08 Total R  (old cap)
#   or_max=∞    → 581 trades | 33.7% WR | +8.99 Total R  ← OPTIMAL
#   or_max=2.5  →  86 trades | 30.2% WR | -6.83 Total R
#   or_max=2.0  →  43 trades | 25.6% WR | -10.00 Total R
# Conclusion: wide-range sessions trade at the same quality but provide 4.5x
# more opportunity. The upper cap was filtering out 77% of valid setups.
# Set to 99.0 (effectively no cap). or_min is irrelevant (0 trades < 1% OR).
OR_RANGE_MAX_PCT = 99.0   # grid search optimal — no upper cap (was 3.0)
OR_RANGE_MIN_PCT = 0.2    # no effect in practice — 0 trades below 1% OR

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

# ========================================
# OPTIONS FILTERING THRESHOLDS
# ========================================

MIN_DTE = 0
MAX_DTE = 7
IDEAL_DTE = 2          # default; overridden dynamically by get_ideal_dte() (P2-3)

MIN_OPTION_OI = 100
MIN_OPTION_VOLUME = 50
MAX_BID_ASK_SPREAD_PCT = 0.10
MAX_THETA_DECAY_PCT = 0.05

# ── P2-2: Delta range tightened to target 0.35–0.45Δ sweet spot ──────────────
# Previous: MIN=0.40, MAX=0.70 (too wide — often selected deep ITM contracts)
# New:      MIN=0.30, MAX=0.55, IDEAL=0.40
# find_best_strike() scores delta proximity to IDEAL_DELTA so the nearest-ATM
# contract in the 0.35–0.45Δ range wins vs a 0.55Δ contract with same liquidity.
TARGET_DELTA_MIN = 0.30
TARGET_DELTA_MAX = 0.55
IDEAL_DELTA      = 0.40   # P2-2: target delta for strike proximity scoring

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
FVG_MIN_SIZE_PCT = 0.0003
FVG_SOFT_PCT      = 0.0015   # soft/partial FVG tolerance (0.8%)
CONFIRMATION_TIMEOUT_BARS = 5

# ⚠️  BACKTEST INTELLIGENCE WARNING (2026-03-24):
# confidence is INVERSELY correlated with wins (p=0.006, n=107 trades).
# Higher confidence scores → MORE losses. Confidence scoring must be audited.
# These floors may be over-filtering good setups until confidence is fixed.
# See: docs/BACKTEST_INTELLIGENCE.md — Feature Significance section.
MIN_CONFIDENCE_OR = 0.00
MIN_CONFIDENCE_INTRADAY = 0.00
CONFIDENCE_ABSOLUTE_FLOOR = 0.55

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

# Phase 1.37: Per-grade confidence ceiling — prevents multiplier stack inflation
# Backtest finding: confidence is inversely correlated with wins (p=0.006)
CONFIDENCE_CAP_BY_GRADE = {
    "A+": 0.88,
    "A":  0.82,
    "A-": 0.76,
    "B+": 0.70,
    "B":  0.64,
    "B-": 0.58,
    "C+": 0.52,
    "C":  0.46,
    "C-": 0.40,
}

# Phase 1.37b: T1/T2 multipliers — grid search optimized (2026-03-24)
# Grid search over 107 trades (2,512 parameter combinations):
#   T1=2.0R → Total R=14.1 on RVOL>=1.2 cohort (59.6% WR, avg R=0.300)
#   T1=1.3R → Total R=11.9 on same cohort — losing trades run through 1.3 anyway
#   T2: only 1 T2 hit in entire dataset — insensitive, kept at 3.5R for future runners
T1_MULTIPLIER = 2.0   # grid search optimal (was 1.3 in Phase 1.37)
T2_MULTIPLIER = 3.5   # restored — no T2 sensitivity in current dataset

MIN_PRICE = 5.0
MAX_PRICE = 500.0
MIN_VOLUME = 1_000_000

# ── RVOL GATES ────────────────────────────────────────────────────────────────
# Backtest audit (2026-03-24, 582 trades, 312 tickers × 90 days):
#   RVOL 1.2–2.0 → 214 trades | 36.9% WR | +0.162 avg R | +34.59 Total R  ← BEST
#   RVOL 2.0–3.0 → 153 trades | 35.3% WR | +0.056 avg R |  +8.63 Total R
#   RVOL 3.0–4.0 →  61 trades | 31.1% WR | -0.169 avg R | -10.30 Total R
#   RVOL >=4.0   → 154 trades | 29.2% WR | -0.142 avg R | -21.93 Total R  ← WORST
#
# MIN_RELATIVE_VOLUME : screener-level gate (pre-market scan)
#   Was 2.0x — this was filtering out the 1.2–2.0x cohort (+34.59R) entirely.
#   Lowered to 1.2x to capture best-performing RVOL band.
#
# RVOL_SIGNAL_GATE    : signal-level gate (applied per-signal in scanner.py)
#   Kept at 1.2x — minimum viable RVOL for positive expectancy.
#
# RVOL_CEILING        : NEW — upper bound added per audit findings.
#   Signals with RVOL >= 3.0x destroy P&L (-32.23 Total R combined).
#   3.0x chosen as ceiling: 2.0–3.0 cohort is marginal (+8.63R) but acceptable;
#   3.0x+ is clearly negative and should be blocked.
MIN_RELATIVE_VOLUME = 1.2   # was 2.0 — lowered to capture 1.2–2.0x sweet spot
RVOL_SIGNAL_GATE    = 1.2   # grid search optimal (was 1.28 — Phase 1.37b)
RVOL_CEILING        = 3.0   # NEW (Phase 1.38b) — RVOL >= 3.0x destroys P&L

MIN_ATR_MULTIPLIER = 4.0

MFI_MIN = 60
OBV_BARS_MIN = 0
VWAP_ZONE = 'above_vwap'
TF_CONFIRM = '1m'

OR_START_TIME = dtime(9, 30)
OR_END_TIME = dtime(9, 45)
TRADING_START = dtime(9, 45)

# ── TRADING HOURS (Phase 1.38b) ───────────────────────────────────────────────
# Time-of-day audit (2026-03-24, 582 trades):
#   09:45–10:15 → 126 trades | 36.5% WR | +14.31 Total R  ✅
#   10:15–11:30 → 344 trades | 34.6% WR | +19.01 Total R  ✅
#   11:30–14:00 → 105 trades | 27.6% WR | -14.54 Total R  ❌
#   14:00–15:30 →   7 trades | 42.9% WR |  -7.80 Total R  ❌
# Morning sessions (+33.32R) vs afternoon (-22.34R).
# TRADING_END moved from 15:45 → 11:30. FORCE_CLOSE_TIME → 11:35.
TRADING_END      = dtime(11, 30)  # was 15:45 — afternoon is -22R net
FORCE_CLOSE_TIME = dtime(11, 35)  # was 15:50

# ========================================
# RISK MANAGEMENT
# ========================================

STOP_LOSS_MULTIPLIER = 1.5
TAKE_PROFIT_MULTIPLIER = 3.0
MAX_LOSS_PER_TRADE_PCT = 2.0
TRAILING_STOP_ACTIVATION = 1.0

# ========================================
# DIRECTION FILTER (Phase 1.38b)
# ========================================

# Direction audit (2026-03-24, 582 trades):
#   bull → 315 trades | 34.0% WR | +0.035 avg R | +11.14 Total R
#   bear → 267 trades | 33.7% WR | -0.001 avg R |  -0.15 Total R
# Bears are statistically worthless over 267 trades. Disabled until
# a bear-specific edge is identified via dedicated bear signal audit.
BEAR_SIGNALS_ENABLED = False   # NEW — re-enable only with evidence of bear edge

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

# NOTE (2026-03-24): ORCL removed from champion tickers.
# Backtest analysis (107 trades): ORCL avg R = -0.67, WR = 0%, 3 trades.
# NOTE (2026-03-24): Champion ticker list underperforms in 582-trade audit.
# Champion cohort: 33 trades | 21.2% WR | -0.273 avg R | -9.00 Total R
# Other tickers:  549 trades | 34.6% WR | +0.036 avg R | +19.99 Total R
# BACKTEST_CHAMPION reflects prior campaign params — not a live filter.
# See: docs/BACKTEST_INTELLIGENCE.md — Ticker Tier List.
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
    'tickers'      : 'AAPL,AMD,META,MSFT,NVDA,TSLA,AMZN,WMT,BAC,CSCO',
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
    logger.info(f"Bear Signals: {'Enabled' if BEAR_SIGNALS_ENABLED else 'Disabled (Phase 1.38b)'}")
    logger.info(f"\nVIX-Scaled OR Thresholds:")
    for upper, pct in VIX_OR_THRESHOLDS:
        label = f"VIX < {upper}" if upper < 999 else "VIX ≥ 35"
        logger.info(f"  {label:<12} → {pct*100:.1f}%")
    logger.info(f"\nSecondary Range (Power Hour):")
    logger.info(f"  Window  : {SECONDARY_RANGE_START} - {SECONDARY_RANGE_END}")
    logger.info(f"  Enabled : {SECONDARY_RANGE_ENABLED}")
    logger.info(f"  Min Bars: {SECONDARY_RANGE_MIN_BARS}")
    logger.info(f"  Min Pct : {SECONDARY_RANGE_MIN_PCT*100:.1f}%")
    logger.info(f"\nOptions Thresholds (P2-2):")
    logger.info(f"  Delta Range : {TARGET_DELTA_MIN:.2f} – {TARGET_DELTA_MAX:.2f} (ideal {IDEAL_DELTA:.2f})")
    logger.info(f"  DTE Range   : {MIN_DTE} – {MAX_DTE} (default ideal {IDEAL_DTE})")
    logger.info(f"\nOR Range Gate (Phase 1.38):")
    logger.info(f"  Min : {OR_RANGE_MIN_PCT}% (no practical effect — 0 trades below 1%)")
    logger.info(f"  Max : {OR_RANGE_MAX_PCT}% (no cap — grid search optimal 2026-03-24)")
    logger.info(f"\nRVOL Gates (Phase 1.38b):")
    logger.info(f"  Screener gate  : {MIN_RELATIVE_VOLUME}x (was 2.0x — lowered to capture 1.2–2.0x sweet spot)")
    logger.info(f"  Signal gate    : {RVOL_SIGNAL_GATE}x (grid search optimal, 2026-03-24)")
    logger.info(f"  Ceiling        : {RVOL_CEILING}x (NEW — RVOL >= 3.0x destroys P&L)")
    logger.info(f"\nTarget Multipliers (Phase 1.37b):")
    logger.info(f"  T1: {T1_MULTIPLIER}R | T2: {T2_MULTIPLIER}R")
    logger.info(f"\nAdvanced Features:")
    logger.info(f"  Validator: {'Enabled' if VALIDATOR_ENABLED else 'Disabled'}")
    logger.info(f"  Options Filter: {'Enabled (' + OPTIONS_FILTER_MODE + ')' if OPTIONS_FILTER_ENABLED else 'Disabled'}")
    logger.info(f"  Regime Filter: {'Enabled' if REGIME_FILTER_ENABLED else 'Disabled'}")
    logger.info(f"  MTF Convergence: {'Enabled' if MTF_ENABLED else 'Disabled'}")
    logger.info(f"  Hourly Gate: {'Enabled' if HOURLY_GATE_ENABLED else 'Disabled'}")
    logger.info(f"  Correlation Check: {'Enabled' if CORRELATION_CHECK_ENABLED else 'Disabled'}")
    logger.info(f"\nCampaign Champion:")
    logger.info(f"  BOS Threshold : {ORB_BREAK_THRESHOLD*100:.2f}%")
    logger.info(f"  Min RVOL      : {MIN_RELATIVE_VOLUME}x")
    logger.info(f"  MFI Floor     : {MFI_MIN}")
    logger.info(f"  VWAP Zone     : {VWAP_ZONE}")
    logger.info(f"  TF Confirm    : {TF_CONFIRM}")
    logger.info("=" * 70)
    validate_required_env_vars()
