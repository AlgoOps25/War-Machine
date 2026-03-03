# Sniper Module - CFW6 Strategy Implementation
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers, Multi-Indicator Validator
# TWO-PATH SCANNING: OR-Anchored + Intraday BOS+FVG fallback
# TWO-PHASE ALERTS: Watch Alert (BOS detected) + Confirmed Signal (FVG+confirm)
# EARNINGS GUARD: Skips tickers with earnings within 2 days
# IV RANK: Confidence multiplier based on historical IV cheapness/expensiveness
# UOA: Confidence multiplier based on unusual options activity alignment
# GEX: Confidence multiplier based on gamma exposure environment + pin alignment
# VALIDATOR: Multi-indicator confirmation (ADX, Volume, DMI, CCI, Bollinger, VPVR) - TEST MODE
# CONFIDENCE GATE: Hard minimum floors by signal type + grade after all multipliers
# OR WIDTH FILTER: OR range < MIN_OR_RANGE_PCT skips OR path (choppy), falls to intraday BOS
# WATCH PERSISTENCE: watching_signals + armed_signals tables survive Railway redeploys;
#                    Smart expiration auto-cleans stale entries on load.
# OPTIONS PRE-GATE: Early options validation before confirmation — kills bad setups
#                   before CPU-heavy confirmation runs (Step 6.5, SOFT/HARD modes).
# PHASE 4 TRACKING: Signal funnel analytics for optimization visibility
# MTF CONVERGENCE: Multi-timeframe FVG alignment boost (5m + 3m convergence)
# CANDLE CONFIRMATION: 3-tier Nitro Trades candle quality model (A+/A/A- grading)
# MTF FVG PRIORITY: Highest timeframe FVG selection (5m > 3m > 2m > 1m)
# REGIME FILTER: VIX/SPY market condition detection — avoids bad tape
# EXPLOSIVE MOVER OVERRIDE: Score ≥80 + RVOL ≥4.0x bypasses regime filter for extreme opportunities
# CORRELATION CHECK: Sector-aware over-leverage prevention
# PHASE 4 MONITORING: Live performance dashboard, circuit breaker, risk alerts
# HOURLY GATE: Time-based confidence adjustment from historical win rates
import traceback
import requests
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from app.discord_helpers import send_options_signal_alert, send_simple_message
from app.validation.validation import get_options_recommendation, get_validator, get_regime_filter
# # # from app.ai.ai_learning import learning_engine  # Archived - not currently used  # ARCHIVED - Feature not currently in use  # ARCHIVED - not currently used
from app.validation.cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from app.data.data_manager import data_manager
from app.risk.position_manager import position_manager
# # from app.ai.ai_learning import compute_confidence  # ARCHIVED - Feature not currently in use  # ARCHIVED - not currently used
from utils import config
from app.mtf.bos_fvg_engine import scan_bos_fvg, is_force_close_time

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 INTEGRATION - Signal Analytics & Performance Monitoring
# ══════════════════════════════════════════════════════════════════════════════
try:
    from signal_analytics import signal_tracker
    from performance_monitor import performance_monitor
    from performance_alerts import alert_manager
    PHASE_4_ENABLED = True
    print("[SIGNALS] ✅ Phase 4 monitoring enabled (analytics + performance + alerts)")
except ImportError as import_err:
    signal_tracker = None
    performance_monitor = None
    alert_manager = None
    PHASE_4_ENABLED = False
    print(f"[SIGNALS] ⚠️  Phase 4 monitoring disabled: {import_err}")

# Production hardening helpers (Phase 3H)
try:
    from production_helpers import _send_alert_safe, _fetch_data_safe, _db_operation_safe
    PRODUCTION_HELPERS_ENABLED = True
    print("[SNIPER] ✅ Production hardening enabled")
except ImportError:
    PRODUCTION_HELPERS_ENABLED = False
    print("[SNIPER] ⚠️  Production helpers not available")

# Phase 4 tracking state
_last_dashboard_check = datetime.now()
_last_alert_check = datetime.now()
DASHBOARD_UPDATE_INTERVAL_MINUTES = 30
ALERT_CHECK_INTERVAL_MINUTES = 15

# ══════════════════════════════════════════════════════════════════════════════
# HOURLY CONFIDENCE GATE - Time-based adjustment from historical performance
# ══════════════════════════════════════════════════════════════════════════════
try:
    from hourly_gate import get_hourly_confidence_multiplier, get_current_hour_context, print_hourly_gate_stats
    HOURLY_GATE_ENABLED = True
    print("[SIGNALS] ✅ Hourly confidence gate enabled (time-based WR adjustment)")
except ImportError:
    HOURLY_GATE_ENABLED = False
    print("[SIGNALS] ⚠️  Hourly gate disabled (module not found)")
    def get_hourly_confidence_multiplier():
        return 1.0
    def get_current_hour_context():
        return {'hour': 0, 'win_rate': None, 'multiplier': 1.0, 'classification': 'no_data'}
    def print_hourly_gate_stats():
        pass

# Multi-indicator validator
VALIDATOR_ENABLED = True
VALIDATOR_TEST_MODE = False  # Set to False to enable filtering
_validator_stats = {'tested': 0, 'passed': 0, 'filtered': 0, 'boosted': 0, 'penalized': 0}
print("[SIGNALS] ✅ Multi-indicator validator ACTIVE (filtering enabled)")

# ────────────────────────────────────────────────────────────────────────────────
# OPTIONS PRE-VALIDATION GATE - Now integrated into validation.py
# ────────────────────────────────────────────────────────────────────────────────
OPTIONS_PRE_GATE_ENABLED = True
print("[SNIPER] ✅ Options pre-validation gate enabled (via validation.py)")

# ────────────────────────────────────────────────────────────────────────────────
# MTF INTEGRATION - Multi-timeframe FVG convergence
# Non-fatal import: sniper works normally if MTF system unavailable.
# ────────────────────────────────────────────────────────────────────────────────
try:
    from mtf_integration import enhance_signal_with_mtf, print_mtf_stats
    MTF_ENABLED = True
    print("[SNIPER] ✅ MTF convergence boost enabled")
except ImportError:
    MTF_ENABLED = False
    print("[SNIPER] ⚠️  MTF system not available — single-timeframe mode")
    def enhance_signal_with_mtf(*args, **kwargs):
        return {'enabled': False, 'convergence': False, 'boost': 0.0, 'reason': 'MTF disabled'}
    def print_mtf_stats():
        pass

# ────────────────────────────────────────────────────────────────────────────────
# MTF FVG PRIORITY - Highest timeframe FVG selection
# Non-fatal import: sniper works normally if priority resolver unavailable.
# ────────────────────────────────────────────────────────────────────────────────
try:
    from mtf_fvg_priority import get_highest_priority_fvg, get_full_mtf_analysis, print_priority_stats
    MTF_PRIORITY_ENABLED = True
    print("[SNIPER] ✅ MTF FVG priority resolver enabled")
except ImportError:
    MTF_PRIORITY_ENABLED = False
    print("[SNIPER] ⚠️  MTF priority resolver not available — single-TF FVG mode")
    def get_highest_priority_fvg(*args, **kwargs):
        return None
    def get_full_mtf_analysis(*args, **kwargs):
        return {'primary_fvg': None, 'secondary_fvgs': [], 'confluence_count': 0}
    def print_priority_stats():
        pass

# ────────────────────────────────────────────────────────────────────────────────
# CAPITAL PROTECTION SYSTEMS - Now using validation.py
# ────────────────────────────────────────────────────────────────────────────────
REGIME_FILTER_ENABLED = True
print("[SNIPER] ✅ Regime filter enabled (VIX/SPY market condition detection - via validation.py)")

# ════════════════════════════════════════════════════════════════════════════════
# EXPLOSIVE MOVER OVERRIDE - Bypass regime filter for extreme opportunities
# ════════════════════════════════════════════════════════════════════════════════
EXPLOSIVE_SCORE_THRESHOLD = 80     # Screener score threshold
EXPLOSIVE_RVOL_THRESHOLD = 4.0     # Relative volume threshold
print(f"[SNIPER] ✅ Explosive mover override enabled (score≥{EXPLOSIVE_SCORE_THRESHOLD} + RVOL≥{EXPLOSIVE_RVOL_THRESHOLD}x)")

try:
    from correlation_check import correlation_checker
    CORRELATION_CHECK_ENABLED = True
    print("[SNIPER] ✅ Correlation check enabled (prevents over-leverage)")
except ImportError:
    correlation_checker = None
    CORRELATION_CHECK_ENABLED = False
    print("[SNIPER] ⚠️  Correlation check not available")

# ── Global State ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
armed_signals    = {}
watching_signals   = {}
_watches_loaded    = False   # True after first DB load attempt this session
_armed_loaded      = False   # True after first armed signals load

MAX_WATCH_BARS      = 12  # 60 min optimal momentum window
INTRADAY_MIN_GRADES = {"A+", "A"}

# Options pre-gate mode:
#   "SOFT" — log result but never filter (data collection phase, safe default)
#   "HARD" — filter signals with no tradeable options or GEX headwinds
# Switch to "HARD" after confirming gate logic is sound against real signals.
OPTIONS_PRE_GATE_MODE = "HARD"


# ────────────────────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────────────────────

def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))

def _bar_time(bar):
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt

def _strip_tz(dt):
    """Normalise a datetime to a naive (tz-stripped) object for safe comparison."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if hasattr(dt, "tzinfo") and dt.tzinfo else dt

# ════════════════════════════════════════════════════════════════════════════════
# EXPLOSIVE MOVER DETECTION - Fetch screener metadata
# ════════════════════════════════════════════════════════════════════════════════
def _get_ticker_screener_metadata(ticker: str) -> dict:
    """
    Fetch screener score and RVOL for a ticker.
    Returns dict with 'score', 'rvol', 'qualified' keys.
    Caches result for 15 minutes to avoid repeated API calls.
    """
    try:
        from app.screening.watchlist_funnel import get_watchlist_with_metadata
        
        # Get current watchlist with metadata
        watchlist_data = get_watchlist_with_metadata(force_refresh=False)
        metadata = watchlist_data.get('metadata', {})
        all_tickers = watchlist_data.get('all_tickers_with_scores', [])
        
        # Find ticker in screener results
        for entry in all_tickers:
            if entry.get('ticker') == ticker:
                score = entry.get('score', 0)
                rvol = entry.get('rvol', 0.0)
                qualified = score >= EXPLOSIVE_SCORE_THRESHOLD and rvol >= EXPLOSIVE_RVOL_THRESHOLD
                return {
                    'score': score,
                    'rvol': rvol,
                    'qualified': qualified,
                    'tier': entry.get('tier', 'C')
                }
        
        # Ticker not in screener results
        return {'score': 0, 'rvol': 0.0, 'qualified': False, 'tier': 'N/A'}
    
    except Exception as e:
        print(f"[EXPLOSIVE] Metadata fetch error for {ticker}: {e}")
        return {'score': 0, 'rvol': 0.0, 'qualified': False, 'tier': 'N/A'}

def log_proposed_trade(ticker, signal_type, direction, price, confidence, grade):
    try:
        from app.data.db_connection import get_conn, ph, serial_pk
        conn = get_conn()
        cursor = conn.cursor()
        p = ph()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS proposed_trades (
                id {serial_pk()}, ticker TEXT, signal_type TEXT,
                direction TEXT, price REAL, confidence REAL, grade TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            f"INSERT INTO proposed_trades (ticker, signal_type, direction, price, confidence, grade) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (ticker, signal_type, direction, price, confidence, grade)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[TRACKER] Error: {e}")

def print_validation_stats():
    """Print end-of-day validation statistics."""
    if not VALIDATOR_ENABLED or _validator_stats['tested'] == 0:
        return
    
    stats = _validator_stats
    total = stats['tested']
    pass_pct = (stats['passed'] / total * 100) if total > 0 else 0
    filter_pct = (stats['filtered'] / total * 100) if total > 0 else 0
    boost_pct = (stats['boosted'] / total * 100) if total > 0 else 0
    
    print("\n" + "="*80)
    print("VALIDATOR DAILY STATISTICS")
    print("="*80)
    print(f"Total Signals Tested: {total}")
    print(f"Passed: {stats['passed']} ({pass_pct:.1f}%)")
    print(f"Filtered: {stats['filtered']} ({filter_pct:.1f}%)")
    print(f"Confidence Boosted: {stats['boosted']} ({boost_pct:.1f}%)")
    print(f"Confidence Penalized: {stats['penalized']}")
    print("="*80)
    if VALIDATOR_TEST_MODE:
        print("⚠️  TEST MODE ACTIVE - Signals NOT being filtered")
    print("="*80 + "\n")


# [REST OF THE FILE CONTINUES WITH THE SAME CONTENT AS BEFORE...]