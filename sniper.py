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
# CORRELATION CHECK: Sector-aware over-leverage prevention
# PHASE 4 MONITORING: Live performance dashboard, circuit breaker, risk alerts
# HOURLY GATE: Time-based confidence adjustment from historical win rates
import traceback
import requests
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from discord_helpers import send_options_signal_alert, send_simple_message
from options_filter import get_options_recommendation
from ai_learning import learning_engine
from cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from data_manager import data_manager
from position_manager import position_manager
from learning_policy import compute_confidence
import config
from bos_fvg_engine import scan_bos_fvg, is_force_close_time

# ════════════════════════════════════════════════════════════════════════════════
# PHASE 4 INTEGRATION - Signal Analytics & Performance Monitoring
# ════════════════════════════════════════════════════════════════════════════════
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

# Phase 4 tracking state
_last_dashboard_check = datetime.now()
_last_alert_check = datetime.now()
DASHBOARD_UPDATE_INTERVAL_MINUTES = 30
ALERT_CHECK_INTERVAL_MINUTES = 15

# ════════════════════════════════════════════════════════════════════════════════
# HOURLY CONFIDENCE GATE - Time-based adjustment from historical performance
# ════════════════════════════════════════════════════════════════════════════════
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
try:
    from signal_validator import get_validator
    VALIDATOR_ENABLED = True
    VALIDATOR_TEST_MODE = False  # Set to False to enable filtering
    _validator_stats = {'tested': 0, 'passed': 0, 'filtered': 0, 'boosted': 0, 'penalized': 0}
    print("[SIGNALS] ✅ Multi-indicator validator ACTIVE (filtering enabled)")
except ImportError:
    VALIDATOR_ENABLED = False
    print("[SIGNALS] ⚠️  signal_validator not available - validation disabled")

# ────────────────────────────────────────────────────────────────────────
# OPTIONS PRE-VALIDATION GATE
# Non-fatal import: sniper works normally if options_data_manager is missing.
# ────────────────────────────────────────────────────────────────────────
try:
    from options_data_manager import options_dm
    OPTIONS_PRE_GATE_ENABLED = True
    print("[SNIPER] ✅ Options pre-validation gate enabled")
except ImportError:
    options_dm = None
    OPTIONS_PRE_GATE_ENABLED = False
    print("[SNIPER] ⚠️  options_data_manager not available — options gate disabled")

# ────────────────────────────────────────────────────────────────────────
# MTF INTEGRATION - Multi-timeframe FVG convergence
# Non-fatal import: sniper works normally if MTF system unavailable.
# ────────────────────────────────────────────────────────────────────────
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

# ────────────────────────────────────────────────────────────────────────
# MTF FVG PRIORITY - Highest timeframe FVG selection
# Non-fatal import: sniper works normally if priority resolver unavailable.
# ────────────────────────────────────────────────────────────────────────
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

# ────────────────────────────────────────────────────────────────────────
# CAPITAL PROTECTION SYSTEMS
# Non-fatal imports: sniper works normally if modules are missing.
# ────────────────────────────────────────────────────────────────────────
try:
    from regime_filter import regime_filter
    REGIME_FILTER_ENABLED = True
    print("[SNIPER] ✅ Regime filter enabled (VIX/SPY market condition detection)")
except ImportError:
    regime_filter = None
    REGIME_FILTER_ENABLED = False
    print("[SNIPER] ⚠️  Regime filter not available")

try:
    from correlation_check import correlation_checker
    CORRELATION_CHECK_ENABLED = True
    print("[SNIPER] ✅ Correlation check enabled (prevents over-leverage)")
except ImportError:
    correlation_checker = None
    CORRELATION_CHECK_ENABLED = False
    print("[SNIPER] ⚠️  Correlation check not available")

# ── Global State ─────────────────────────────────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

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

def log_proposed_trade(ticker, signal_type, direction, price, confidence, grade):
    try:
        from db_connection import get_conn, ph, serial_pk
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
    print("⚠️  TEST MODE ACTIVE - Signals NOT being filtered")
    print("="*80 + "\n")


# ─────────────────────────────────────────────────────────────
# ARMED SIGNALS DB PERSISTENCE
# Survives Railway redeploys: armed signals survive restarts and prevent
# duplicate Discord alerts for the same signal.
# ─────────────────────────────────────────────────────────────

def _ensure_armed_db():
    """Create armed_signals_persist table if it doesn't exist."""
    try:
        from db_connection import get_conn
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS armed_signals_persist (
                ticker          TEXT PRIMARY KEY,
                position_id     INTEGER     NOT NULL,
                direction       TEXT        NOT NULL,
                entry_price     REAL        NOT NULL,
                stop_price      REAL        NOT NULL,
                t1              REAL        NOT NULL,
                t2              REAL        NOT NULL,
                confidence      REAL        NOT NULL,
                grade           TEXT        NOT NULL,
                signal_type     TEXT        NOT NULL,
                validation_data TEXT,
                saved_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ARMED-DB] Init error: {e}")


def _persist_armed_signal(ticker: str, data: dict):
    """
    Upsert an armed signal entry to the DB.
    Serializes validation_result as JSON if present.
    """
    try:
        from db_connection import get_conn, ph as _ph
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        
        # Serialize validation data if present
        validation_json = None
        if data.get("validation"):
            try:
                validation_json = json.dumps(data["validation"])
            except:
                validation_json = None
        
        cursor.execute(
            f"""
            INSERT INTO armed_signals_persist
                (ticker, position_id, direction, entry_price, stop_price, t1, t2,
                 confidence, grade, signal_type, validation_data, saved_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                position_id     = EXCLUDED.position_id,
                direction       = EXCLUDED.direction,
                entry_price     = EXCLUDED.entry_price,
                stop_price      = EXCLUDED.stop_price,
                t1              = EXCLUDED.t1,
                t2              = EXCLUDED.t2,
                confidence      = EXCLUDED.confidence,
                grade           = EXCLUDED.grade,
                signal_type     = EXCLUDED.signal_type,
                validation_data = EXCLUDED.validation_data,
                saved_at        = CURRENT_TIMESTAMP
            """,
            (
                ticker,
                data["position_id"],
                data["direction"],
                data["entry_price"],
                data["stop_price"],
                data["t1"],
                data["t2"],
                data["confidence"],
                data["grade"],
                data["signal_type"],
                validation_json
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ARMED-DB] Persist error for {ticker}: {e}")


def _remove_armed_from_db(ticker: str):
    """Delete an armed signal entry from the DB."""
    try:
        from db_connection import get_conn, ph as _ph
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"DELETE FROM armed_signals_persist WHERE ticker = {p}", (ticker,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ARMED-DB] Remove error for {ticker}: {e}")


def _cleanup_stale_armed_signals():
    """
    Remove armed signal entries from DB that don't have corresponding open positions.
    This syncs the armed_signals table with position_manager state.
    """
    try:
        from db_connection import get_conn
        
        # Get list of open position IDs from position_manager
        open_positions = position_manager.get_open_positions()
        open_position_ids = {pos["id"] for pos in open_positions}
        
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get all armed signals from DB
        cursor.execute("SELECT ticker, position_id FROM armed_signals_persist")
        rows = cursor.fetchall()
        
        stale_tickers = []
        for row in rows:
            ticker = row[0] if isinstance(row, tuple) else row["ticker"]
            pos_id = row[1] if isinstance(row, tuple) else row["position_id"]
            
            # If position no longer exists, mark as stale
            if pos_id not in open_position_ids:
                stale_tickers.append(ticker)
        
        # Delete stale armed signals
        if stale_tickers:
            placeholders = ",".join(["?" if not hasattr(conn, "_use_postgres") else "%s"] * len(stale_tickers))
            cursor.execute(
                f"DELETE FROM armed_signals_persist WHERE ticker IN ({placeholders})",
                stale_tickers
            )
            conn.commit()
            print(f"[ARMED-DB] 🧹 Auto-cleaned {len(stale_tickers)} closed position(s): {', '.join(stale_tickers)}")
        
        conn.close()
        
    except Exception as e:
        print(f"[ARMED-DB] Cleanup error: {e}")


def _load_armed_signals_from_db() -> dict:
    """
    Load today's armed signal entries from the DB.
    Only loads signals that have corresponding open positions in position_manager.
    Stale signals (closed positions) are auto-cleaned before loading.
    """
    try:
        from db_connection import get_conn, dict_cursor as _dc, ph as _ph, USE_POSTGRES as _USE_PG
        
        # First, clean up stale armed signals
        _cleanup_stale_armed_signals()
        
        conn = get_conn()
        cursor = _dc(conn)
        p = _ph()
        today_et = _now_et().date()
        
        # Load only today's armed signals
        if _USE_PG:
            cursor.execute(
                f"""
                SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                       confidence, grade, signal_type, validation_data
                FROM   armed_signals_persist
                WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = {p}
                """,
                (today_et,),
            )
        else:
            cursor.execute(
                f"""
                SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                       confidence, grade, signal_type, validation_data
                FROM   armed_signals_persist
                WHERE  DATE(saved_at) = {p}
                """,
                (today_et,),
            )
        rows = cursor.fetchall()
        conn.close()
        
        loaded = {}
        for row in rows:
            # Deserialize validation data if present
            validation = None
            if row.get("validation_data"):
                try:
                    validation = json.loads(row["validation_data"])
                except:
                    validation = None
            
            loaded[row["ticker"]] = {
                "position_id":  row["position_id"],
                "direction":    row["direction"],
                "entry_price":  row["entry_price"],
                "stop_price":   row["stop_price"],
                "t1":           row["t1"],
                "t2":           row["t2"],
                "confidence":   row["confidence"],
                "grade":        row["grade"],
                "signal_type":  row["signal_type"],
                "validation":   validation
            }
        
        if loaded:
            print(
                f"[ARMED-DB] 🔄 Reloaded {len(loaded)} armed signal(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        print(f"[ARMED-DB] Load error: {e}")
        return {}


def _maybe_load_armed_signals():
    """
    Called once per session on the first process_ticker() invocation.
    Initialises the DB table and merges any surviving armed signals into memory.
    Auto-cleans stale armed signals (closed positions) before loading.
    """
    global _armed_loaded, armed_signals
    if _armed_loaded:
        return
    _armed_loaded = True
    _ensure_armed_db()
    loaded = _load_armed_signals_from_db()
    if loaded:
        armed_signals.update(loaded)


# ─────────────────────────────────────────────────────────────
# WATCH STATE DB PERSISTENCE
# Survives Railway redeploys: watches are written to the DB as they are set,
# and reloaded on the first process_ticker() call after a restart.
# breakout_idx is NOT stored directly (it's a positional array index and
# would be invalid after a restart). Instead, breakout_bar_dt (the datetime
# of the breakout candle) is stored and resolved back to an index at reload time.
#
# SMART EXPIRATION: On load, watches older than MAX_WATCH_BARS * 5min are
# automatically removed from DB. This handles Railway restarts gracefully
# without manual intervention.
# ─────────────────────────────────────────────────────────────

def _ensure_watch_db():
    """Create watching_signals_persist table if it doesn't exist."""
    try:
        from db_connection import get_conn
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watching_signals_persist (
                ticker          TEXT PRIMARY KEY,
                direction       TEXT        NOT NULL,
                breakout_bar_dt TIMESTAMP   NOT NULL,
                or_high         REAL        NOT NULL,
                or_low          REAL        NOT NULL,
                signal_type     TEXT        NOT NULL,
                saved_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WATCH-DB] Init error: {e}")


def _persist_watch(ticker: str, data: dict):
    """
    Upsert a watch entry to the DB.
    'data' must contain: direction, breakout_bar_dt, or_high, or_low, signal_type.
    """
    try:
        from db_connection import get_conn, ph as _ph
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"""
            INSERT INTO watching_signals_persist
                (ticker, direction, breakout_bar_dt, or_high, or_low, signal_type, saved_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker) DO UPDATE SET
                direction       = EXCLUDED.direction,
                breakout_bar_dt = EXCLUDED.breakout_bar_dt,
                or_high         = EXCLUDED.or_high,
                or_low          = EXCLUDED.or_low,
                signal_type     = EXCLUDED.signal_type,
                saved_at        = CURRENT_TIMESTAMP
            """,
            (
                ticker,
                data["direction"],
                data["breakout_bar_dt"],
                data["or_high"],
                data["or_low"],
                data["signal_type"],
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WATCH-DB] Persist error for {ticker}: {e}")


def _remove_watch_from_db(ticker: str):
    """Delete a single watch entry from the DB."""
    try:
        from db_connection import get_conn, ph as _ph
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"DELETE FROM watching_signals_persist WHERE ticker = {p}", (ticker,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WATCH-DB] Remove error for {ticker}: {e}")


def _cleanup_stale_watches():
    """
    Remove watch entries from DB that are older than the valid watch window.
    Watch window = MAX_WATCH_BARS * 5min bars.
    This runs on startup to clean up watches that expired during downtime/restarts.
    """
    try:
        from db_connection import get_conn, ph as _ph
        
        # Calculate expiration cutoff: current time - (MAX_WATCH_BARS * 5 minutes)
        watch_window_minutes = MAX_WATCH_BARS * 5
        cutoff_time = _now_et() - timedelta(minutes=watch_window_minutes)
        
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        
        # Delete watches where breakout_bar_dt is older than the cutoff
        cursor.execute(
            f"DELETE FROM watching_signals_persist WHERE breakout_bar_dt < {p}",
            (cutoff_time,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            print(f"[WATCH-DB] 🧹 Auto-cleaned {deleted_count} stale watch(es) (older than {watch_window_minutes}min)")
        
    except Exception as e:
        print(f"[WATCH-DB] Cleanup error: {e}")


def _load_watches_from_db() -> dict:
    """
    Load today's watch entries from the DB.
    Returns a dict of ticker -> watch entry with breakout_idx=None.
    The index is resolved lazily in process_ticker() when bars_session is available.
    Rows saved on a previous trading day are silently discarded.
    Stale watches (older than MAX_WATCH_BARS window) are auto-cleaned before loading.
    """
    try:
        from db_connection import get_conn, dict_cursor as _dc, ph as _ph, USE_POSTGRES as _USE_PG
        
        # First, clean up any stale watches
        _cleanup_stale_watches()
        
        conn = get_conn()
        cursor = _dc(conn)
        p = _ph()
        today_et = _now_et().date()
        
        # FIX #7: AT TIME ZONE is Postgres-only syntax — use DATE(saved_at) on SQLite
        if _USE_PG:
            cursor.execute(
                f"""
                SELECT ticker, direction, breakout_bar_dt, or_high, or_low, signal_type
                FROM   watching_signals_persist
                WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = {p}
                """,
                (today_et,),
            )
        else:
            cursor.execute(
                f"""
                SELECT ticker, direction, breakout_bar_dt, or_high, or_low, signal_type
                FROM   watching_signals_persist
                WHERE  DATE(saved_at) = {p}
                """,
                (today_et,),
            )
        rows = cursor.fetchall()
        conn.close()
        loaded = {}
        for row in rows:
            loaded[row["ticker"]] = {
                "direction":       row["direction"],
                "breakout_idx":    None,                        # resolved lazily
                "breakout_bar_dt": _strip_tz(row["breakout_bar_dt"]),
                "or_high":         row["or_high"],
                "or_low":          row["or_low"],
                "signal_type":     row["signal_type"],
            }
        if loaded:
            print(
                f"[WATCH-DB] 🔄 Reloaded {len(loaded)} watch state(s) from DB after restart: "
                f"{', '.join(loaded.keys())}"
            )
        return loaded
    except Exception as e:
        print(f"[WATCH-DB] Load error: {e}")
        return {}


def _maybe_load_watches():
    """
    Called once per session on the first process_ticker() invocation.
    Initialises the DB table and merges any surviving watch state into memory.
    Auto-cleans stale watches before loading.
    """
    global _watches_loaded, watching_signals
    if _watches_loaded:
        return
    _watches_loaded = True
    _ensure_watch_db()
    loaded = _load_watches_from_db()
    if loaded:
        watching_signals.update(loaded)


# ─────────────────────────────────────────────────────────────
# PHASE 4 PERIODIC CHECKS
# ─────────────────────────────────────────────────────────────

def _check_performance_dashboard():
    """
    Check if it's time to print live performance dashboard.
    Called periodically in process_ticker().
    """
    global _last_dashboard_check
    
    if not PHASE_4_ENABLED or performance_monitor is None:
        return
    
    now = datetime.now()
    minutes_since_last = (now - _last_dashboard_check).total_seconds() / 60
    
    if minutes_since_last >= DASHBOARD_UPDATE_INTERVAL_MINUTES:
        try:
            print(performance_monitor.get_live_dashboard())
            _last_dashboard_check = now
        except Exception as e:
            print(f"[PHASE 4] Dashboard error: {e}")


def _check_performance_alerts():
    """
    Check for performance alerts (win streaks, loss streaks, drawdown warnings).
    Called periodically in process_ticker().
    """
    global _last_alert_check
    
    if not PHASE_4_ENABLED or alert_manager is None:
        return
    
    now = datetime.now()
    minutes_since_last = (now - _last_alert_check).total_seconds() / 60
    
    if minutes_since_last >= ALERT_CHECK_INTERVAL_MINUTES:
        try:
            alerts = alert_manager.check_all_conditions()
            for alert in alerts:
                print(f"[ALERT] {alert['emoji']} {alert['title']}")
                print(f"        {alert['message']}")
                # Optionally send to Discord
                try:
                    send_simple_message(f"{alert['emoji']} **{alert['title']}**\n{alert['message']}")
                except:
                    pass
            _last_alert_check = now
        except Exception as e:
            print(f"[PHASE 4] Alert check error: {e}")


# ─────────────────────────────────────────────────────────────
# CORRELATION HELPERS (legacy Pearson — kept for fallback)
# ─────────────────────────────────────────────────────────────

def _pearson_corr(xs, ys) -> float:
    n = len(xs)
    if n < 5:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs)
    den_y = sum((y - mean_y) ** 2 for y in ys)
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return num / (den_x ** 0.5 * den_y ** 0.5)


def _is_highly_correlated(ticker: str, open_positions: list,
                          window_bars: int = 60, threshold: float = 0.9) -> bool:
    """Return True if 'ticker' is highly correlated with any open position."""
    bars_main = data_manager.get_today_5m_bars(ticker)
    if len(bars_main) < 10:
        return False

    for pos in open_positions:
        other = pos["ticker"]
        if other == ticker:
            continue
        bars_other = data_manager.get_today_5m_bars(other)
        if len(bars_other) < 10:
            continue

        by_time = {}
        for b in bars_main:
            by_time.setdefault(b["datetime"], {})["a"] = b
        for b in bars_other:
            by_time.setdefault(b["datetime"], {})["b"] = b

        paired = [
            (v["a"], v["b"])
            for v in by_time.values()
            if "a" in v and "b" in v
        ]
        if len(paired) < 10:
            continue

        xs = [pa[0]["close"] for pa in paired][-window_bars:]
        ys = [pa[1]["close"] for pa in paired][-window_bars:]
        if len(xs) != len(ys) or len(xs) < 5:
            continue

        xs_ret = [(xs[i] - xs[i-1]) / xs[i-1] for i in range(1, len(xs))]
        ys_ret = [(ys[i] - ys[i-1]) / ys[i-1] for i in range(1, len(ys))]
        m = min(len(xs_ret), len(ys_ret))
        if m < 5:
            continue
        corr = _pearson_corr(xs_ret[-m:], ys_ret[-m:])
        if corr >= threshold:
            print(f"[CORR] {ticker} vs {other} corr={corr:.2f} — blocking new signal")
            return True

    return False


# ─────────────────────────────────────────────────────────────
# PHASE 1 — WATCH ALERT
# ─────────────────────────────────────────────────────────────

def send_bos_watch_alert(ticker, direction, bos_price, struct_high, struct_low,
                          signal_type="CFW6_INTRADAY"):
    arrow    = "🟢" if direction == "bull" else "🔴"
    level    = f"${struct_high:.2f}" if direction == "bull" else f"${struct_low:.2f}"
    mode_tag = "[OR]" if signal_type == "CFW6_OR" else "[INTRADAY]"
    msg = (
        f"📡 **BOS ALERT {mode_tag}: {ticker}** — {arrow} {direction.upper()}\n"
        f"Break: **${bos_price:.2f}** | Level: {level}\n"
        f"⏳ Watching for FVG (up to {MAX_WATCH_BARS} min) | "
        f"🕐 {_now_et().strftime('%I:%M %p ET')}"
    )
    try:
        send_simple_message(msg)
        print(f"[WATCH] 📡 {ticker} {direction.upper()} BOS @ ${bos_price:.2f}")
    except Exception as e:
        print(f"[WATCH] Alert error: {e}")


# ─────────────────────────────────────────────────────────────
# OPENING RANGE
# ─────────────────────────────────────────────────────────────

def compute_opening_range_from_bars(bars):
    or_bars = [b for b in bars if _bar_time(b) and time(9,30) <= _bar_time(b) < time(9,40)]
    if len(or_bars) < 2:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)

def compute_premarket_range(bars):
    pm_bars = [b for b in bars if _bar_time(b) and time(4,0) <= _bar_time(b) < time(9,30)]
    if len(pm_bars) < 10:
        return None, None
    return max(b["high"] for b in pm_bars), min(b["low"] for b in pm_bars)


# ─────────────────────────────────────────────────────────────
# BREAKOUT & FVG (OR path)
# ─────────────────────────────────────────────────────────────

def detect_breakout_after_or(bars, or_high, or_low):
    for i, bar in enumerate(bars):
        bt = _bar_time(bar)
        if bt is None or bt < time(9, 40):
            continue
        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BULL idx {i} ${bar['close']:.2f}")
            return "bull", i
        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BEAR idx {i} ${bar['close']:.2f}")
            return "bear", i
    return None, None

def detect_fvg_after_break(bars, breakout_idx, direction):
    for i in range(breakout_idx + 3, len(bars)):
        if i < 2:
            continue
        c0, c2 = bars[i-2], bars[i]
        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= config.FVG_MIN_SIZE_PCT:
                print(f"[FVG] BULL ${c0['high']:.2f}–${c2['low']:.2f}")
                return c0["high"], c2["low"]
        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= config.FVG_MIN_SIZE_PCT:
                print(f"[FVG] BEAR ${c2['high']:.2f}–${c0['low']:.2f}")
                return c2["high"], c0["low"]
    return None, None


# ─────────────────────────────────────────────────────────────
# PHASE 2 — SIGNAL PIPELINE (Steps 6.5–12)
# ─────────────────────────────────────────────────────────────

def _run_signal_pipeline(ticker, direction, zone_low, zone_high,
                          or_high_ref, or_low_ref, signal_type,
                          bars_session, breakout_idx,
                          bos_confirmation=None, bos_candle_type=None):

    # ════════════════════════════════════════════════════════════
    # STEP 6.5 — OPTIONS PRE-VALIDATION GATE
    # ════════════════════════════════════════════════════════════
    _pre_options_data = None
    if OPTIONS_PRE_GATE_ENABLED and options_dm is not None:
        try:
            _proxy_entry = bars_session[-1]["close"]
            _opts_check  = options_dm.validate_for_trading(ticker, direction, _proxy_entry)
            _tradeable   = _opts_check.get("tradeable", True)
            _reason      = _opts_check.get("reason", "")
            _pre_options_data = _opts_check

            if OPTIONS_PRE_GATE_MODE == "HARD":
                if not _tradeable:
                    print(
                        f"[{ticker}] ❌ OPTIONS GATE [HARD]: {_reason} "
                        f"— signal dropped before confirmation"
                    )
                    return False
                print(f"[{ticker}] ✅ OPTIONS GATE [HARD]: passed — proceeding to confirmation")
            else:  # SOFT (default)
                _gate_emoji = "✅" if _tradeable else "⚠️"
                print(
                    f"[{ticker}] {_gate_emoji} OPTIONS GATE [SOFT]: "
                    f"tradeable={_tradeable} | {_reason}"
                )
                if _opts_check.get("gex_data") and _opts_check["gex_data"].get("has_data"):
                    _gd = _opts_check["gex_data"]
                    print(
                        f"[{ticker}]   GEX zone={('NEG' if _gd.get('neg_gex_zone') else 'POS')} "
                        f"pin=${_gd.get('gamma_pin', 'N/A')} "
                        f"flip=${_gd.get('gamma_flip', 'N/A')}"
                    )
        except Exception as _gate_err:
            print(f"[{ticker}] OPTIONS GATE error (non-fatal): {_gate_err}")
            _pre_options_data = None

    # STEP 7 — CONFIRMATION CANDLE
    result = wait_for_confirmation(
        bars_session, direction, (zone_low, zone_high), breakout_idx + 1
    )
    found, entry_price, base_grade, confirm_idx, confirm_type = result
    if not found or base_grade == "reject":
        print(f"[{ticker}] — No confirmation (found={found}, grade={base_grade})")
        return False

    if signal_type == "CFW6_INTRADAY" and base_grade not in INTRADAY_MIN_GRADES:
        print(f"[{ticker}] — Intraday grade {base_grade} below A threshold")
        return False

    # STEP 8 — CONFIRMATION LAYERS
    conf_result = grade_signal_with_confirmations(
        ticker=ticker, direction=direction, bars=bars_session,
        current_price=entry_price, breakout_idx=breakout_idx, base_grade=base_grade
    )
    if conf_result["final_grade"] == "reject":
        print(f"[{ticker}] — Rejected by confirmation layers")
        return False
    final_grade = conf_result["final_grade"]

    # ════════════════════════════════════════════════════════════
    # STEP 8.2 — MTF CONVERGENCE DETECTION
    # ════════════════════════════════════════════════════════════
    mtf_result = enhance_signal_with_mtf(
        ticker=ticker,
        direction=direction,
        bars_session=bars_session
    )
    
    if mtf_result['convergence']:
        print(
            f"[{ticker}] ✅ MTF CONVERGENCE: "
            f"{mtf_result['convergence_score']:.1%} across "
            f"{', '.join(mtf_result['timeframes'])} | "
            f"Boost: +{mtf_result['boost']:.2%}"
        )
    else:
        print(f"[{ticker}] MTF: {mtf_result['reason']}")

    # ════════════════════════════════════════════════════════════
    # PHASE 4 INTEGRATION POINT #2 - Track Signal Generated
    # ════════════════════════════════════════════════════════════
    _prelim_stop, _prelim_t1, _prelim_t2 = compute_stop_and_targets(
        bars_session, direction, or_high_ref, or_low_ref, entry_price,
        grade=final_grade
    )
    
    if PHASE_4_ENABLED and signal_tracker:
        try:
            signal_tracker.record_signal_generated(
                ticker=ticker,
                signal_type=signal_type,
                direction=direction,
                grade=final_grade,
                confidence=compute_confidence(final_grade, "5m", ticker),
                entry_price=entry_price,
                stop_price=_prelim_stop,
                t1_price=_prelim_t1,
                t2_price=_prelim_t2
            )
            print(f"[PHASE 4] 📊 {ticker} signal GENERATED - {signal_type} {direction.upper()} {final_grade}")
        except Exception as e:
            print(f"[PHASE 4] Signal tracking error: {e}")

    # STEP 8.5 — MULTI-INDICATOR VALIDATION
    latest_bar     = bars_session[-1]
    current_volume = latest_bar.get("volume", 0)
    signal_direction = "LONG" if direction == "bull" else "SHORT"
    base_confidence    = compute_confidence(final_grade, "5m", ticker)
    original_confidence = base_confidence

    validation_result = None
    if VALIDATOR_ENABLED:
        try:
            validator = get_validator()
            should_pass, adjusted_conf, metadata = validator.validate_signal(
                ticker=ticker,
                signal_direction=signal_direction,
                current_price=entry_price,
                current_volume=current_volume,
                base_confidence=original_confidence
            )

            validation_result = {
                'should_take':           should_pass,
                'original_confidence':   original_confidence * 100,
                'adjusted_confidence':   adjusted_conf * 100,
                'checks_passed':         len(metadata['summary']['passed_checks']),
                'total_checks':          len(metadata['summary']['passed_checks']) + len(metadata['summary']['failed_checks']),
                'checks':                metadata['checks'],
                'failed_checks':         metadata['summary']['failed_checks']
            }

            _validator_stats['tested'] += 1
            if validation_result['should_take']:
                _validator_stats['passed'] += 1
            else:
                _validator_stats['filtered'] += 1

            conf_change = validation_result['adjusted_confidence'] - validation_result['original_confidence']
            if conf_change > 0:
                _validator_stats['boosted'] += 1
            elif conf_change < 0:
                _validator_stats['penalized'] += 1

            status_emoji = "✅" if validation_result['should_take'] else "❌"
            trend_emoji  = "📈" if conf_change > 0 else "📉" if conf_change < 0 else "➡️"

            print(
                f"[VALIDATOR TEST] {ticker} {status_emoji} | "
                f"Conf: {validation_result['original_confidence']:.0f}% → "
                f"{validation_result['adjusted_confidence']:.0f}% {trend_emoji} "
                f"({conf_change:+.0f}%) | "
                f"Score: {validation_result['checks_passed']}/{validation_result['total_checks']}"
            )

            if not validation_result['should_take']:
                failed = [
                    k.upper() for k, v in validation_result['checks'].items()
                    if isinstance(v, dict) and not v.get('passed', True)
                ]
                if failed:
                    print(f"[VALIDATOR TEST]   Would filter: {', '.join(failed)}")
            
            # ════════════════════════════════════════════════════════════
            # PHASE 4 INTEGRATION POINT #3 - Track Validation Result
            # ════════════════════════════════════════════════════════════
            if PHASE_4_ENABLED and signal_tracker:
                try:
                    # Extract multiplier data from validation metadata
                    ivr_mult = 1.0  # Default if not available
                    uoa_mult = 1.0
                    gex_mult = 1.0
                    
                    signal_tracker.record_validation_result(
                        ticker=ticker,
                        passed=validation_result['should_take'],
                        confidence_after=adjusted_conf,
                        ivr_multiplier=ivr_mult,
                        uoa_multiplier=uoa_mult,
                        gex_multiplier=gex_mult,
                        mtf_boost=mtf_result.get('boost', 0.0),
                        ticker_multiplier=1.0,
                        checks_passed=[k for k, v in validation_result['checks'].items() 
                                     if isinstance(v, dict) and v.get('passed', True)],
                        rejection_reason=", ".join(validation_result['failed_checks']) if not validation_result['should_take'] else ""
                    )
                    status = "VALIDATED" if validation_result['should_take'] else "REJECTED"
                    print(f"[PHASE 4] ✅ {ticker} signal {status}")
                except Exception as e:
                    print(f"[PHASE 4] Validation tracking error: {e}")

            if VALIDATOR_TEST_MODE:
                base_confidence = adjusted_conf
            else:
                if not validation_result['should_take']:
                    print(f"[VALIDATOR] {ticker} FILTERED - {', '.join(validation_result['failed_checks'])}")
                    return False
                base_confidence = adjusted_conf

        except Exception as e:
            print(f"[VALIDATOR] Error validating {ticker}: {e}")
            import traceback
            traceback.print_exc()

    # STEP 9 — STOPS & TARGETS
    stop_price, t1, t2 = compute_stop_and_targets(
        bars_session, direction, or_high_ref, or_low_ref, entry_price,
        grade=final_grade
    )

    # STEP 10 — OPTIONS
    options_rec = get_options_recommendation(
        ticker=ticker, direction=direction,
        entry_price=entry_price, target_price=t1,
        stop_price=stop_price
    )
    if _pre_options_data and _pre_options_data.get("gex_data"):
        print(f"[{ticker}] [OPTIONS] GEX data reused from Step 6.5 cache")

    # STEP 11 — CONFIDENCE
    ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
    mtf_boost = mtf_result.get('boost', 0.0)
    mode_decay = 0.95 if signal_type == "CFW6_INTRADAY" else 1.0

    ivr_multiplier = options_rec.get("ivr_multiplier", 1.0) if options_rec else 1.0
    ivr_label      = options_rec.get("ivr_label",      "IVR-N/A") if options_rec else "IVR-N/A"
    uoa_multiplier = options_rec.get("uoa_multiplier", 1.0) if options_rec else 1.0
    uoa_label      = options_rec.get("uoa_label",      "UOA-N/A") if options_rec else "UOA-N/A"
    gex_multiplier = options_rec.get("gex_multiplier", 1.0) if options_rec else 1.0
    gex_label      = options_rec.get("gex_label",      "GEX-N/A") if options_rec else "GEX-N/A"
    
    def mult_to_adjustment(multiplier, base_conf):
        """Convert multiplier to bounded additive adjustment."""
        if multiplier >= 1.0:
            return min((multiplier - 1.0) * base_conf * 0.75, base_conf * 0.15)
        else:
            return max((multiplier - 1.0) * base_conf * 1.00, base_conf * -0.20)
    
    ticker_adj = mult_to_adjustment(ticker_multiplier, base_confidence)
    mode_adj   = mult_to_adjustment(mode_decay, base_confidence)
    ivr_adj    = mult_to_adjustment(ivr_multiplier, base_confidence)
    uoa_adj    = mult_to_adjustment(uoa_multiplier, base_confidence)
    gex_adj    = mult_to_adjustment(gex_multiplier, base_confidence)
    
    final_confidence = base_confidence + ticker_adj + mode_adj + ivr_adj + uoa_adj + gex_adj + mtf_boost
    final_confidence = max(0.40, min(final_confidence, 0.95))
    
    print(
        f"[CONFIDENCE-v2] Base:{base_confidence:.2f} "
        f"+ Ticker:{ticker_adj:+.3f}({ticker_multiplier:.2f}) "
        f"+ Mode:{mode_adj:+.3f}({mode_decay:.2f}) "
        f"+ IVR:{ivr_adj:+.3f}[{ivr_label}] "
        f"+ UOA:{uoa_adj:+.3f}[{uoa_label}] "
        f"+ GEX:{gex_adj:+.3f}[{gex_label}] "
        f"+ MTF:{mtf_boost:+.3f} "
        f"= {final_confidence:.2f}"
    )

    # ════════════════════════════════════════════════════════════
    # STEP 11b — CONFIDENCE THRESHOLD GATE (DYNAMIC + HOURLY)
    # ════════════════════════════════════════════════════════════
    try:
        from dynamic_thresholds import get_dynamic_threshold
        eff_min = get_dynamic_threshold(signal_type, final_grade)
    except ImportError:
        min_type  = (
            config.MIN_CONFIDENCE_INTRADAY
            if signal_type == "CFW6_INTRADAY"
            else config.MIN_CONFIDENCE_OR
        )
        min_grade = config.MIN_CONFIDENCE_BY_GRADE.get(final_grade, min_type)
        eff_min   = max(min_type, min_grade, config.CONFIDENCE_ABSOLUTE_FLOOR)

    # Apply hourly gate multiplier to threshold
    if HOURLY_GATE_ENABLED:
        try:
            hourly_mult = get_hourly_confidence_multiplier()
            hour_ctx = get_current_hour_context()
            
            if hourly_mult != 1.0:
                original_eff_min = eff_min
                eff_min *= hourly_mult
                
                ctx_label = hour_ctx['classification'].upper()
                ctx_emoji = "🟢" if ctx_label == "STRONG" else ("🔴" if ctx_label == "WEAK" else "🟡")
                
                print(
                    f"[HOURLY GATE] {ctx_emoji} {hour_ctx['hour']}:00 {ctx_label} "
                    f"(WR: {hour_ctx['win_rate']:.1f}% / {hour_ctx['trades']} trades) | "
                    f"Threshold: {original_eff_min:.2f} → {eff_min:.2f} ({hourly_mult:.2f}x)"
                )
        except Exception as hourly_err:
            print(f"[HOURLY GATE] Error (non-fatal): {hourly_err}")

    if final_confidence < eff_min:
        print(
            f"[{ticker}] 🚫 GATED: confidence {final_confidence:.2f} < "
            f"dynamic threshold {eff_min:.2f} "
            f"[{signal_type}/{final_grade}] — signal dropped"
        )
        return False

    print(f"[{ticker}] ✅ GATE PASSED: {final_confidence:.2f} >= {eff_min:.2f} (dynamic)")
    
    # ════════════════════════════════════════════════════════════
    # PHASE 4 INTEGRATION POINT #4 - Track Signal Armed
    # ════════════════════════════════════════════════════════════
    if PHASE_4_ENABLED and signal_tracker:
        try:
            bars_to_confirmation = len(bars_session) - confirm_idx if confirm_idx else 0
            signal_tracker.record_signal_armed(
                ticker=ticker,
                final_confidence=final_confidence,
                bars_to_confirmation=bars_to_confirmation,
                confirmation_type=confirm_type or 'retest'
            )
            print(f"[PHASE 4] 🎯 {ticker} signal ARMED - confidence={final_confidence:.2f}")
        except Exception as e:
            print(f"[PHASE 4] Armed tracking error: {e}")
    
    # STEP 12 — ARM
    arm_ticker(
        ticker, direction, zone_low, zone_high,
        or_low_ref, or_high_ref,
        entry_price, stop_price, t1, t2,
        final_confidence, final_grade, options_rec,
        signal_type=signal_type,
        validation_result=validation_result,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type
    )
    return True


# ─────────────────────────────────────────────────────────────
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade,
               options_rec=None, signal_type="CFW6_OR", validation_result=None,
               bos_confirmation=None, bos_candle_type=None):
    # Minimum risk threshold check
    if abs(entry_price - stop_price) < entry_price * 0.001:
        print(f"[ARM] ⚠️ {ticker} stop too tight — skipping")
        return

    # ════════════════════════════════════════════════════════════
    # PHASE 4 INTEGRATION POINT #5 - Circuit Breaker Check
    # ════════════════════════════════════════════════════════════
    if PHASE_4_ENABLED and performance_monitor:
        try:
            cb_status = performance_monitor.get_circuit_breaker_status()
            if cb_status['triggered']:
                print(
                    f"[ARM] 🛑 CIRCUIT BREAKER TRIGGERED: {ticker} signal blocked\n"
                    f"      Daily loss: {cb_status['current_loss_pct']:.2f}% / "
                    f"trigger at {cb_status['trigger_threshold_pct']:.2f}%"
                )
                return  # Block this signal
            
            # Warn if approaching trigger
            if cb_status['warning_level'] in ['WARNING', 'CRITICAL']:
                print(
                    f"[ARM] ⚠️  CIRCUIT BREAKER {cb_status['warning_level']}: "
                    f"{cb_status['distance_to_trigger_pct']:.2f}% from trigger"
                )
        except Exception as e:
            print(f"[PHASE 4] Circuit breaker check error: {e}")

    open_positions = position_manager.get_open_positions()

    # ════════════════════════════════════════════════════════════
    # CORRELATION CHECK — sector-aware over-leverage prevention
    # Replaces legacy _is_highly_correlated() with sector + ETF overlap detection
    # ════════════════════════════════════════════════════════════
    if CORRELATION_CHECK_ENABLED and correlation_checker:
        safe, warning = correlation_checker.is_safe_to_add_position(
            ticker=ticker,
            open_positions=open_positions
        )
        if not safe:
            print(
                f"[ARM] 🚫 CORRELATION FILTER: {ticker} — {warning.reason}"
            )
            if warning.correlated_tickers:
                print(
                    f"[ARM]   Correlated open positions: {', '.join(warning.correlated_tickers)}"
                )
            return  # Block this signal
        if warning:
            # Safe but worth flagging (e.g. QQQ constituent overlap)
            print(f"[ARM] ⚠️  CORRELATION WARNING: {ticker} — {warning.reason}")
    else:
        # Fallback to legacy Pearson correlation check
        if _is_highly_correlated(ticker, open_positions, window_bars=60, threshold=0.9):
            print(f"[CORR] Skipping {ticker} — highly correlated with open book")
            return

    mode_label = " [INTRADAY]" if signal_type == "CFW6_INTRADAY" else " [OR]"
    print(
        f"✅ {ticker} ARMED{mode_label}: {direction.upper()} | "
        f"Entry:${entry_price:.2f} Stop:${stop_price:.2f} "
        f"T1:${t1:.2f} T2:${t2:.2f} | {confidence*100:.1f}% ({grade})"
    )

    log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade)
    send_options_signal_alert(
        ticker=ticker, direction=direction,
        entry=entry_price, stop=stop_price, t1=t1, t2=t2,
        confidence=confidence, timeframe="5m", grade=grade, options_data=options_rec,
        confirmation=bos_confirmation, candle_type=bos_candle_type
    )
    position_id = position_manager.open_position(
        ticker=ticker, direction=direction,
        zone_low=zone_low, zone_high=zone_high,
        or_low=or_low, or_high=or_high,
        entry_price=entry_price, stop_price=stop_price,
        t1=t1, t2=t2, confidence=confidence, grade=grade, options_rec=options_rec
    )

    armed_signal_data = {
        "position_id": position_id, "direction": direction,
        "entry_price": entry_price, "stop_price": stop_price,
        "t1": t1, "t2": t2, "confidence": confidence,
        "grade": grade, "signal_type": signal_type,
        "validation": validation_result
    }
    armed_signals[ticker]     = armed_signal_data
    _persist_armed_signal(ticker, armed_signal_data)

    print(f"[ARMED] {ticker} ID:{position_id}")
    
    # ════════════════════════════════════════════════════════════
    # PHASE 4 INTEGRATION POINT #6 - Check Alerts After Position Opens
    # ════════════════════════════════════════════════════════════
    if PHASE_4_ENABLED and alert_manager:
        try:
            alerts = alert_manager.check_all_conditions()
            for alert in alerts:
                print(f"[ALERT] {alert['emoji']} {alert['title']}")
                # Optionally send to Discord
                try:
                    send_simple_message(f"{alert['emoji']} **{alert['title']}**\n{alert['message']}")
                except:
                    pass
        except Exception as e:
            print(f"[PHASE 4] Alert check error: {e}")


def clear_armed_signals():
    """Clear in-memory armed signals AND the DB persistence table."""
    global _armed_loaded
    armed_signals.clear()
    _armed_loaded = False
    try:
        from db_connection import get_conn
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM armed_signals_persist")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ARMED-DB] Clear error: {e}")
    print("[ARMED] Cleared")


def clear_watching_signals():
    """Clear in-memory watch state AND the DB persistence table."""
    global _watches_loaded
    watching_signals.clear()
    _watches_loaded = False
    try:
        from db_connection import get_conn
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watching_signals_persist")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WATCH-DB] Clear error: {e}")
    print("[WATCHING] Cleared")


# ─────────────────────────────────────────────────────────────
# MAIN PROCESS TICKER
# ─────────────────────────────────────────────────────────────

def process_ticker(ticker: str):
    try:
        # On the very first call after startup/restart, load any surviving
        # watch and armed signal state from the DB.
        _maybe_load_watches()
        _maybe_load_armed_signals()
        
        # ════════════════════════════════════════════════════════════
        # PHASE 4 PERIODIC CHECKS - Dashboard & Alerts
        # ════════════════════════════════════════════════════════════
        _check_performance_dashboard()
        _check_performance_alerts()

        # ════════════════════════════════════════════════════════════
        # REGIME FILTER — skip ALL new signals in unfavorable tape
        # Checks VIX level, ADX trend strength, and whipsaw frequency.
        # 5-minute cache: evaluates once per cycle, not once per ticker.
        # ════════════════════════════════════════════════════════════
        if REGIME_FILTER_ENABLED and regime_filter:
            if not regime_filter.is_favorable_regime():
                state = regime_filter.get_regime_state()
                print(
                    f"[{ticker}] 🚫 REGIME FILTER: {state.regime} "
                    f"(VIX:{state.vix:.1f}) — {state.reason}"
                )
                return  # Skip this ticker entirely

        if ticker in armed_signals:
            return

        data_manager.update_ticker(ticker)
        bars_session = data_manager.get_today_session_bars(ticker)
        if not bars_session:
            print(f"[{ticker}] No session bars")
            return

        print(
            f"[{ticker}] {_now_et().date()} ({len(bars_session)} bars) "
            f"{_bar_time(bars_session[0])} → {_bar_time(bars_session[-1])}"
        )

        if is_force_close_time(bars_session[-1]):
            position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
            print_validation_stats()
            print_mtf_stats()
            print_priority_stats()
            
            # ════════════════════════════════════════════════════════════
            # PHASE 4 EOD REPORTS
            # ════════════════════════════════════════════════════════════
            if PHASE_4_ENABLED:
                try:
                    # Signal funnel analytics
                    if signal_tracker:
                        print(signal_tracker.get_daily_summary())
                    
                    # Performance dashboard
                    if performance_monitor:
                        print(performance_monitor.get_daily_performance_report())
                except Exception as e:
                    print(f"[PHASE 4] EOD report error: {e}")
            
            # ════════════════════════════════════════════════════════════
            # HOURLY GATE EOD STATS
            # ════════════════════════════════════════════════════════════
            if HOURLY_GATE_ENABLED:
                try:
                    print_hourly_gate_stats()
                except Exception as e:
                    print(f"[HOURLY GATE] EOD stats error: {e}")
            
            # EOD regime summary
            if REGIME_FILTER_ENABLED and regime_filter:
                try:
                    regime_filter.print_regime_summary()
                except Exception as e:
                    print(f"[EOD] Regime summary error: {e}")
            
            # EOD correlation matrix
            if CORRELATION_CHECK_ENABLED and correlation_checker:
                try:
                    eod_positions = position_manager.get_open_positions()
                    if eod_positions:
                        correlation_checker.print_correlation_matrix(eod_positions)
                except Exception as e:
                    print(f"[EOD] Correlation matrix error: {e}")
            
            return

        # ── WATCHING STATE ────────────────────────────────────────────────────────
        if ticker in watching_signals:
            w = watching_signals[ticker]

            # Resolve breakout_idx for entries reloaded from DB after a restart.
            if w.get("breakout_idx") is None:
                bar_dt_target = _strip_tz(w.get("breakout_bar_dt"))
                resolved_idx  = None
                if bar_dt_target is not None:
                    for i, bar in enumerate(bars_session):
                        if _strip_tz(bar["datetime"]) == bar_dt_target:
                            resolved_idx = i
                            break
                if resolved_idx is None:
                    print(
                        f"[{ticker}] ⚠️ Watch DB entry: breakout bar "
                        f"{bar_dt_target} not found in today's session — discarding"
                    )
                    del watching_signals[ticker]
                    _remove_watch_from_db(ticker)
                else:
                    w["breakout_idx"] = resolved_idx
                    print(
                        f"[{ticker}] 🔄 Watch restored from DB: "
                        f"breakout_idx={resolved_idx} ({bar_dt_target})"
                    )

        if ticker in watching_signals:
            w          = watching_signals[ticker]
            bars_since = len(bars_session) - w["breakout_idx"]
            if bars_since > MAX_WATCH_BARS:
                print(f"[{ticker}] ⏰ Watch expired — clearing")
                del watching_signals[ticker]
                _remove_watch_from_db(ticker)
            else:
                print(f"[{ticker}] 👁️ WATCHING [{bars_since}/{MAX_WATCH_BARS}]")
                zl, zh = detect_fvg_after_break(bars_session, w["breakout_idx"], w["direction"])
                if zl is None:
                    return
                _run_signal_pipeline(
                    ticker, w["direction"], zl, zh,
                    w["or_high"], w["or_low"], w["signal_type"],
                    bars_session, w["breakout_idx"]
                )
                del watching_signals[ticker]
                _remove_watch_from_db(ticker)
                return

        # ── FRESH SCAN ────────────────────────────────────────────────────────────
        direction = breakout_idx = zone_low = zone_high = None
        or_high_ref = or_low_ref = scan_mode = None
        bos_confirmation = bos_candle_type = None

        or_high, or_low = compute_opening_range_from_bars(bars_session)
        if or_high is not None:
            or_range_pct = (or_high - or_low) / or_low
            if or_range_pct < config.MIN_OR_RANGE_PCT:
                print(
                    f"[{ticker}] OR too narrow "
                    f"({or_range_pct:.2%} < {config.MIN_OR_RANGE_PCT:.2%}) "
                    f"— skipping OR path, trying intraday BOS"
                )
            else:
                print(f"[{ticker}] OR: ${or_low:.2f}–${or_high:.2f} ({or_range_pct:.2%})")
                direction, breakout_idx = detect_breakout_after_or(bars_session, or_high, or_low)
                if direction:
                    zone_low, zone_high = detect_fvg_after_break(
                        bars_session, breakout_idx, direction
                    )
                    if zone_low is not None:
                        scan_mode = "OR_ANCHORED"
                        or_high_ref, or_low_ref = or_high, or_low
                    else:
                        if ticker not in watching_signals:
                            w_entry = {
                                "direction":       direction,
                                "breakout_idx":    breakout_idx,
                                "breakout_bar_dt": _strip_tz(bars_session[breakout_idx]["datetime"]),
                                "or_high":         or_high,
                                "or_low":          or_low,
                                "signal_type":     "CFW6_OR",
                            }
                            watching_signals[ticker] = w_entry
                            _persist_watch(ticker, w_entry)
                            send_bos_watch_alert(
                                ticker, direction,
                                bars_session[breakout_idx]["close"],
                                or_high, or_low, "CFW6_OR"
                            )
                        return
                else:
                    print(f"[{ticker}] No ORB")
        else:
            print(f"[{ticker}] No OR bars")

        # ── INTRADAY BOS+FVG PATH (with MTF priority resolver) ───────────────────
        if scan_mode is None:
            if len(bars_session) < 30:
                return

            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
            if bos_signal is None:
                print(f"[{ticker}] — No BOS+FVG signal")
                return

            direction    = bos_signal["direction"]
            breakout_idx = bos_signal["bos_idx"]
            bos_confirmation = bos_signal.get("confirmation")
            bos_candle_type = bos_signal.get("candle_type")
            
            if MTF_PRIORITY_ENABLED:
                try:
                    mtf_analysis = get_full_mtf_analysis(
                        ticker=ticker,
                        direction=direction,
                        bars_5m=bars_session,
                        min_pct=fvg_threshold
                    )
                    primary_fvg = mtf_analysis['primary_fvg']
                    if primary_fvg is None:
                        print(f"[{ticker}] — No FVGs found on any timeframe (MTF scan)")
                        return
                    zone_low  = primary_fvg['fvg_low']
                    zone_high = primary_fvg['fvg_high']
                    if mtf_analysis['has_conflict']:
                        print(
                            f"[{ticker}] 🎯 MTF PRIORITY: {primary_fvg['timeframe']} FVG selected | "
                            f"Confluence: {mtf_analysis['confluence_count']} timeframe(s) | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                    else:
                        print(
                            f"[{ticker}] 📍 Single FVG on {primary_fvg['timeframe']} | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                except Exception as priority_err:
                    print(f"[{ticker}] MTF priority error (falling back to 5m): {priority_err}")
                    zone_low  = bos_signal["fvg_low"]
                    zone_high = bos_signal["fvg_high"]
            else:
                zone_low  = bos_signal["fvg_low"]
                zone_high = bos_signal["fvg_high"]
            
            if direction == "bull":
                or_high_ref = bos_signal["bos_price"]
                or_low_ref  = zone_low
            else:
                or_high_ref = zone_high
                or_low_ref  = bos_signal["bos_price"]

            scan_mode = "INTRADAY_BOS"

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        print(f"[{ticker}] {scan_mode} | FVG ${zone_low:.2f}–${zone_high:.2f}")
        _run_signal_pipeline(
            ticker, direction, zone_low, zone_high,
            or_high_ref, or_low_ref, signal_type,
            bars_session, breakout_idx,
            bos_confirmation=bos_confirmation,
            bos_candle_type=bos_candle_type
        )

    except Exception as e:
        print(f"process_ticker error {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={"content": message}, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
