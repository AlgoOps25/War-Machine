# ... (keeping all the file content up to line 94 exactly as-is)
"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
CANDLE CACHE: Cache-aware startup with 95%+ API reduction
OUTCOME TRACKING: Signal deduplication, ML predictions, EOD reports
DYNAMIC WS SUBSCRIPTION: Live session ticker subscription with bar prefetch

PHASE 1.11 (MAR 5, 2026):
  - Critical database connection with explicit logging
  - Startup health check banner integration
  - Validation/Options integration wiring
  - Structured logging with component tags
  - Data storage spam reduction (periodic summaries)
  - Explicit zero-watchlist alerts

PHASE 1.12 (MAR 5, 2026):
  - Database SSL hotfix for Railway connections
  - Parse DATABASE_URL and inject sslmode=require

PHASE 1.13 (MAR 6, 2026):
  - Removed deprecated signal_generator imports (check_and_alert, monitor_signals, etc.)
  - Scanner now relies entirely on sniper.py for signal processing
"""
import os
import time
import threading
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils import config

from app.data.data_manager import data_manager
from app.risk.position_manager import position_manager
from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from app.data.ws_quote_feed import start_quote_feed, subscribe_quote_tickers
from app.core.scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)
from app.screening.watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel
)

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: STRUCTURED LOGGING SETUP
# ────────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.12: DATABASE CONNECTION WITH RAILWAY SSL SUPPORT
# ────────────────────────────────────────────────────────────────────────────────────
ANALYTICS_AVAILABLE = False
analytics_conn = None
DATABASE_URL = os.getenv('DATABASE_URL')

logger.info("=" * 50)
logger.info("DATABASE Attempting connection...")
if DATABASE_URL:
    try:
        import psycopg2
        # Railway requires SSL for proxy connections
        # Add sslmode=require if not already present
        conn_url = DATABASE_URL
        if 'sslmode=' not in conn_url.lower():
            separator = '&' if '?' in conn_url else '?'
            conn_url = f"{conn_url}{separator}sslmode=require"
        
        analytics_conn = psycopg2.connect(conn_url)
        logger.info("DATABASE ✓ Connected - Analytics ONLINE")
        ANALYTICS_AVAILABLE = True
    except Exception as e:
        logger.error(f"DATABASE ✗ FAILED: {e}")
        logger.error("DATABASE Analytics DISABLED - continuing without tracking")
        ANALYTICS_AVAILABLE = False
else:
    logger.warning("DATABASE ✗ DATABASE_URL not set - Analytics DISABLED")
    ANALYTICS_AVAILABLE = False
logger.info("=" * 50)

# ────────────────────────────────────────────────────────────────────────────────────
# LEGACY SIGNAL ANALYTICS (Quality scoring, Sharpe, expectancy)
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
    logger.info("[SCANNER] ✅ Legacy signal analytics enabled")
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None
    logger.info("[SCANNER] ⚠️  signal_analytics not available")

# ────────────────────────────────────────────────────────────────────────────────────
# SIGNAL OUTCOME TRACKING (Deduplication, ML, Discord Reports)
# ────────────────────────────────────────────────────────────────────────────────────
analytics = None
if ANALYTICS_AVAILABLE and analytics_conn:
    try:
        from app.analytics import AnalyticsIntegration
        # HOTFIX: Guard against None import
        if AnalyticsIntegration is not None:
            analytics = AnalyticsIntegration(
                analytics_conn,
                enable_ml=True,
                enable_discord=True
            )
            logger.info("[SCANNER] ✅ Signal outcome tracking enabled (Deduplication + ML + Reports)")
        else:
            analytics = None
            logger.warning("[SCANNER] ⚠️  Outcome tracking disabled: AnalyticsIntegration not available")
    except Exception as e:
        analytics = None
        logger.warning(f"[SCANNER] ⚠️  Outcome tracking disabled: {e}")

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: VALIDATION & OPTIONS INTEGRATION
# ────────────────────────────────────────────────────────────────────────────────────
VALIDATION_AVAILABLE = False
OPTIONS_AVAILABLE = False

try:
    from app.validation import validate_signal
    VALIDATION_AVAILABLE = True
    logger.info("[SCANNER] ✅ Validation gates loaded")
except ImportError:
    logger.warning("[SCANNER] ⚠️  Validation module not available")
    validate_signal = None

try:
    from app.options import build_options_trade
    OPTIONS_AVAILABLE = True
    logger.info("[SCANNER] ✅ Options intelligence loaded")
except ImportError:
    logger.warning("[SCANNER] ⚠️  Options module not available")
    build_options_trade = None

API_KEY = os.getenv("EODHD_API_KEY", "")

# Minimal fallback (only used if funnel completely fails)
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: DATA STORAGE SPAM REDUCTION
# ────────────────────────────────────────────────────────────────────────────────────
data_update_counter = 0
data_update_symbols = set()
last_data_summary_time = time.time()

# ... (rest of file continues exactly as-is)