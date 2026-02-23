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
from earnings_filter import has_earnings_soon
import config
from bos_fvg_engine import scan_bos_fvg, is_force_close_time

# Multi-indicator validator
try:
    from signal_validator import get_validator
    VALIDATOR_ENABLED = True
    VALIDATOR_TEST_MODE = True  # Set to False to enable filtering
    _validator_stats = {'tested': 0, 'would_pass': 0, 'would_filter': 0, 'boosted': 0, 'penalized': 0}
    print("[SIGNALS] ✅ Multi-indicator validator enabled - TEST MODE (no filtering)")
except ImportError:
    VALIDATOR_ENABLED = False
    print("[SIGNALS] ⚠️  signal_validator not available - validation disabled")

# ── Global State ─────────────────────────────────────────────────────────────────────────────────────────
armed_signals    = {}
watching_signals   = {}
_watches_loaded    = False   # True after first DB load attempt this session
_armed_loaded      = False   # True after first armed signals load

MAX_WATCH_BARS      = 30
INTRADAY_MIN_GRADES = {"A+", "A"}


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
    pass_pct = (stats['would_pass'] / total * 100) if total > 0 else 0
    filter_pct = (stats['would_filter'] / total * 100) if total > 0 else 0
    boost_pct = (stats['boosted'] / total * 100) if total > 0 else 0
    
    print("\n" + "="*80)
    print("VALIDATOR TEST MODE STATISTICS")
    print("="*80)
    print(f"Total Signals Tested: {total}")
    print(f"Would Pass: {stats['would_pass']} ({pass_pct:.1f}%)")
    print(f"Would Filter: {stats['would_filter']} ({filter_pct:.1f}%)")
    print(f"Confidence Boosted: {stats['boosted']} ({boost_pct:.1f}%)")
    print(f"Confidence Penalized: {stats['penalized']}")
    print("="*80)
    print("⚠️  TEST MODE ACTIVE - Signals NOT being filtered")
    print("Switch VALIDATOR_TEST_MODE to False to enable filtering")
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
# CORRELATION HELPERS
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
# PHASE 2 — SIGNAL PIPELINE (Steps 7-12)
# ─────────────────────────────────────────────────────────────

def _run_signal_pipeline(ticker, direction, zone_low, zone_high,
                          or_high_ref, or_low_ref, signal_type,
                          bars_session, breakout_idx):
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

    # STEP 8.5 — MULTI-INDICATOR VALIDATION (NEW)
    # Get latest bar for volume calculation
    latest_bar = bars_session[-1]
    current_volume = latest_bar.get("volume", 0)
    
    # Convert direction to signal direction for validator
    signal_direction = "LONG" if direction == "bull" else "SHORT"
    
    # Store original confidence for comparison
    base_confidence = compute_confidence(final_grade, "5m", ticker)
    original_confidence = base_confidence
    
    # Run validation if enabled
    validation_result = None
    if VALIDATOR_ENABLED:
        try:
            validator = get_validator()
            validation_result = validator.validate_signal(
                ticker=ticker,
                direction=signal_direction,
                price=entry_price,
                volume=current_volume,
                confidence=original_confidence * 100  # Convert to percentage
            )
            
            # Update statistics
            _validator_stats['tested'] += 1
            if validation_result['should_take']:
                _validator_stats['would_pass'] += 1
            else:
                _validator_stats['would_filter'] += 1
            
            conf_change = validation_result['adjusted_confidence'] - validation_result['original_confidence']
            if conf_change > 0:
                _validator_stats['boosted'] += 1
            elif conf_change < 0:
                _validator_stats['penalized'] += 1
            
            # Format test log message
            status_emoji = "✅" if validation_result['should_take'] else "❌"
            trend_emoji = "📈" if conf_change > 0 else "📉" if conf_change < 0 else "➡️"
            
            print(f"[VALIDATOR TEST] {ticker} {status_emoji} | "
                  f"Conf: {validation_result['original_confidence']:.0f}% → "
                  f"{validation_result['adjusted_confidence']:.0f}% {trend_emoji} "
                  f"({conf_change:+.0f}%) | "
                  f"Score: {validation_result['checks_passed']}/{validation_result['total_checks']}")
            
            if not validation_result['should_take']:
                # Show what would've been filtered
                failed = [k.upper() for k, v in validation_result['checks'].items() 
                         if isinstance(v, dict) and not v.get('passed', True)]
                if failed:
                    print(f"[VALIDATOR TEST]   Would filter: {', '.join(failed)}")
            
            # In TEST MODE, adjust confidence but don't filter
            if VALIDATOR_TEST_MODE:
                # Apply confidence adjustment but still send signal
                base_confidence = validation_result['adjusted_confidence'] / 100.0
            else:
                # FULL MODE - actually filter signals
                if not validation_result['should_take']:
                    print(f"[VALIDATOR] {ticker} FILTERED - {', '.join(validation_result['failed_checks'])}")
                    return False
                base_confidence = validation_result['adjusted_confidence'] / 100.0
                
        except Exception as e:
            print(f"[VALIDATOR] Error validating {ticker}: {e}")
            # On error, continue without validation
    
    # STEP 9 — STOPS & TARGETS
    # FIX #4: pass grade=final_grade — was missing, defaulting to "A" for all signals
    stop_price, t1, t2 = compute_stop_and_targets(
        bars_session, direction, or_high_ref, or_low_ref, entry_price,
        grade=final_grade
    )

    # STEP 10 — OPTIONS (stop_price now threaded through for accurate GEX context)
    options_rec = get_options_recommendation(
        ticker=ticker, direction=direction,
        entry_price=entry_price, target_price=t1,
        stop_price=stop_price
    )

    # STEP 11 — CONFIDENCE (now uses validator-adjusted base_confidence)
    ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
    try:
        from timeframe_manager import calculate_mtf_convergence_boost
        mtf_boost = calculate_mtf_convergence_boost(ticker)
    except ImportError:
        mtf_boost = 0.0

    mode_decay = 0.95 if signal_type == "CFW6_INTRADAY" else 1.0

    ivr_multiplier = options_rec.get("ivr_multiplier", 1.0) if options_rec else 1.0
    ivr_label      = options_rec.get("ivr_label",      "IVR-N/A") if options_rec else "IVR-N/A"
    uoa_multiplier = options_rec.get("uoa_multiplier", 1.0) if options_rec else 1.0
    uoa_label      = options_rec.get("uoa_label",      "UOA-N/A") if options_rec else "UOA-N/A"
    gex_multiplier = options_rec.get("gex_multiplier", 1.0) if options_rec else 1.0
    gex_label      = options_rec.get("gex_label",      "GEX-N/A") if options_rec else "GEX-N/A"

    final_confidence = min(
        (base_confidence * ticker_multiplier * mode_decay
         * ivr_multiplier * uoa_multiplier * gex_multiplier) + mtf_boost,
        1.0
    )
    print(
        f"[CONFIDENCE] Base:{base_confidence:.2f} × Ticker:{ticker_multiplier:.2f} "
        f"× Mode:{mode_decay:.2f} × IVR:{ivr_multiplier:.2f}[{ivr_label}] "
        f"× UOA:{uoa_multiplier:.2f}[{uoa_label}] "
        f"× GEX:{gex_multiplier:.2f}[{gex_label}] "
        f"+ MTF:{mtf_boost:.2f} = {final_confidence:.2f}"
    )

    # STEP 11b — CONFIDENCE THRESHOLD GATE
    min_type  = (config.MIN_CONFIDENCE_INTRADAY
                 if signal_type == "CFW6_INTRADAY"
                 else config.MIN_CONFIDENCE_OR)
    min_grade = config.MIN_CONFIDENCE_BY_GRADE.get(final_grade, min_type)
    eff_min   = max(min_type, min_grade, config.CONFIDENCE_ABSOLUTE_FLOOR)

    if final_confidence < eff_min:
        print(
            f"[{ticker}] 🚫 GATED: confidence {final_confidence:.2f} < "
            f"min {eff_min:.2f} "
            f"[type={min_type:.2f} grade={min_grade:.2f} abs={config.CONFIDENCE_ABSOLUTE_FLOOR:.2f}] "
            f"[{signal_type}/{final_grade}] — signal dropped"
        )
        return False

    print(f"[{ticker}] ✅ GATE PASSED: {final_confidence:.2f} >= {eff_min:.2f}")

    # STEP 12 — ARM (with validation result attached)
    arm_ticker(
        ticker, direction, zone_low, zone_high,
        or_low_ref, or_high_ref,
        entry_price, stop_price, t1, t2,
        final_confidence, final_grade, options_rec,
        signal_type=signal_type,
        validation_result=validation_result
    )
    return True


# ─────────────────────────────────────────────────────────────
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade,
               options_rec=None, signal_type="CFW6_OR", validation_result=None):
    if abs(entry_price - stop_price) < entry_price * 0.002:
        print(f"[ARM] ⚠️ {ticker} stop too tight — skipping")
        return

    open_positions = position_manager.get_open_positions()
    if _is_highly_correlated(ticker, open_positions, window_bars=60, threshold=0.9):
        print(f"[CORR] Skipping {ticker} — highly correlated with open book")
        return

    mode_label = " [INTRADAY]" if signal_type == "CFW6_INTRADAY" else " [OR]"
    print(f"✅ {ticker} ARMED{mode_label}: {direction.upper()} | "
          f"Entry:${entry_price:.2f} Stop:${stop_price:.2f} "
          f"T1:${t1:.2f} T2:${t2:.2f} | {confidence*100:.1f}% ({grade})")

    log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade)
    send_options_signal_alert(
        ticker=ticker, direction=direction,
        entry=entry_price, stop=stop_price, t1=t1, t2=t2,
        confidence=confidence, timeframe="5m", grade=grade, options_data=options_rec
    )
    position_id = position_manager.open_position(
        ticker=ticker, direction=direction,
        zone_low=zone_low, zone_high=zone_high,
        or_low=or_low, or_high=or_high,
        entry_price=entry_price, stop_price=stop_price,
        t1=t1, t2=t2, confidence=confidence, grade=grade, options_rec=options_rec
    )
    
    # Store armed signal in memory AND DB
    armed_signal_data = {
        "position_id": position_id, "direction": direction,
        "entry_price": entry_price, "stop_price": stop_price,
        "t1": t1, "t2": t2, "confidence": confidence,
        "grade": grade, "signal_type": signal_type,
        "validation": validation_result
    }
    armed_signals[ticker] = armed_signal_data
    _persist_armed_signal(ticker, armed_signal_data)
    
    print(f"[ARMED] {ticker} ID:{position_id}")


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
    _watches_loaded = False  # reset so next day reloads fresh
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

        if ticker in armed_signals:
            return

        data_manager.update_ticker(ticker)
        bars_session = data_manager.get_today_session_bars(ticker)
        if not bars_session:
            print(f"[{ticker}] No session bars")
            return

        print(f"[{ticker}] {_now_et().date()} ({len(bars_session)} bars) "
              f"{_bar_time(bars_session[0])} → {_bar_time(bars_session[-1])}")

        if is_force_close_time(bars_session[-1]):
            position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
            # Print validation stats before market close
            print_validation_stats()
            return

        has_earns, earns_date = has_earnings_soon(ticker)
        if has_earns:
            print(f"[{ticker}] ❌ Earnings {earns_date} — skip")
            return

        # ── WATCHING STATE ─────────────────────────────────────────────────────────
        if ticker in watching_signals:
            w = watching_signals[ticker]

            # Resolve breakout_idx for entries reloaded from DB after a restart.
            # breakout_idx is an array position and invalid across restarts, so
            # we store breakout_bar_dt and find the matching bar in today's session.
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
                    # fall through to fresh scan
                else:
                    w["breakout_idx"] = resolved_idx
                    print(f"[{ticker}] 🔄 Watch restored from DB: "
                          f"breakout_idx={resolved_idx} ({bar_dt_target})")

        if ticker in watching_signals:   # may have been removed in resolution block above
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

        # ── FRESH SCAN ──────────────────────────────────────────────────────────
        direction = breakout_idx = zone_low = zone_high = None
        or_high_ref = or_low_ref = scan_mode = None

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

        # ── INTRADAY BOS+FVG PATH (scan_bos_fvg from bos_fvg_engine) ───────────
        # Uses proper swing-point structure BOS detection and adaptive FVG
        # threshold from get_adaptive_fvg_threshold(). Called every bar —
        # no watch state needed because scan_bos_fvg() checks entry alignment
        # in real-time on the latest bar.
        if scan_mode is None:
            if len(bars_session) < 30:
                return

            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
            if bos_signal is None:
                print(f"[{ticker}] — No BOS+FVG signal")
                return

            direction    = bos_signal["direction"]
            zone_low     = bos_signal["fvg_low"]
            zone_high    = bos_signal["fvg_high"]
            breakout_idx = bos_signal["bos_idx"]

            # Structural reference levels for stop calculation.
            # Bull: broken resistance as upper ref; FVG low as support floor.
            # Bear: FVG high as resistance ceiling; broken support as lower ref.
            if direction == "bull":
                or_high_ref = bos_signal["bos_price"]
                or_low_ref  = bos_signal["fvg_low"]
            else:
                or_high_ref = bos_signal["fvg_high"]
                or_low_ref  = bos_signal["bos_price"]

            scan_mode = "INTRADAY_BOS"

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        print(f"[{ticker}] {scan_mode} | FVG ${zone_low:.2f}–${zone_high:.2f}")
        _run_signal_pipeline(ticker, direction, zone_low, zone_high,
                             or_high_ref, or_low_ref, signal_type,
                             bars_session, breakout_idx)

    except Exception as e:
        print(f"process_ticker error {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={"content": message}, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
