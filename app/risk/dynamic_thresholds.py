"""
Dynamic Confidence Threshold Manager
Optimization #3: Adaptive thresholds based on performance and market conditions

Replaces static config thresholds with dynamic adjustments based on:
- Rolling win rate (last 20 trades per signal type/grade)
- Market volatility (VIX level)
- Intraday ATR volatility bucket (47.P6-2 Sprint 1)
- Time of day (morning vs afternoon vs power hour)
- Recent signal quality (last 5 signals) [STUB — Issue #25, not yet implemented]

FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
UPDATED (Mar 19 2026): get_dynamic_threshold() wires live intraday ATR (47.P6-2).
FIXED (Mar 25 2026): _get_winrate_adjustment() now uses ph() instead of hardcoded %s —
  raw %s caused ProgrammingError on SQLite, silently falling back to 0.00 and disabling
  win-rate influence on thresholds during local dev/testing.
FIXED (Mar 26 2026): _get_winrate_adjustment() now filters by BOTH grade AND signal_type
  (previously signal_type parameter was accepted but never used in the query — Issue #27).
FIXED (Mar 26 2026): evaluate_signal() in risk_manager.py now passes bars_session + ticker
  into get_dynamic_threshold() so the ATR bucket adjustment is live (Issue #26).
BUG-EOD-1 (Apr 02 2026): _get_winrate_adjustment() queried positions.signal_type but that
  column did not exist on the positions table (only on ml_signals), causing a silent
  exception and permanent 0.00 return — win-rate adjustment was permanently disabled.
  Fix: column now added by position_manager._migrate_signal_type_column() on every
  startup. Also added logger.info() so win-rate influence is visible in session logs.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from utils import config
import logging
logger = logging.getLogger(__name__)


def _now_et():
    """Get current time in Eastern timezone."""
    return datetime.now(ZoneInfo("America/New_York"))


def _get_time_of_day_adjustment():
    """
    Adjust thresholds based on time of day.

    Morning (9:30-11:00): -0.03 (more lenient, catch momentum)
    Midday (11:00-14:00): +0.05 (stricter, choppy period)
    Afternoon (14:00-15:30): +0.00 (neutral)
    Power Hour (15:30-16:00): -0.02 (slightly lenient, end-of-day urgency)
    """
    now = _now_et().time()

    if time(9, 30) <= now < time(11, 0):
        return -0.03  # Morning: more opportunities
    elif time(11, 0) <= now < time(14, 0):
        return +0.05  # Midday: stricter filter
    elif time(14, 0) <= now < time(15, 30):
        return 0.00   # Afternoon: neutral
    elif time(15, 30) <= now < time(16, 0):
        return -0.02  # Power hour: slight leniency
    else:
        return +0.05  # After hours: very strict


def _get_vix_adjustment():
    """
    Adjust thresholds based on VIX level.

    VIX < 15: -0.02 (low volatility, be selective)
    VIX 15-20: +0.00 (normal conditions)
    VIX 20-30: +0.03 (elevated volatility, tighten standards)
    VIX > 30: +0.05 (high volatility, very selective)

    Returns 0.00 if VIX data unavailable.
    """
    try:
        from app.data.data_manager import data_manager
        vix_data = data_manager.get_vix_level()

        if vix_data is None:
            return 0.00

        # get_vix_level() may return a plain float OR a dict with 'close' key
        if isinstance(vix_data, dict):
            vix = float(vix_data.get("close", 0) or 0)
        else:
            vix = float(vix_data)

        if vix <= 0:
            return 0.00

        if vix < 15:
            return -0.02
        elif vix < 20:
            return 0.00
        elif vix < 30:
            return +0.03
        else:
            return +0.05
    except Exception as e:
        logger.warning(f"[DYNAMIC-THRESH] VIX lookup error: {e}")
        return 0.00


def _get_atr_volatility_adjustment(bars_session: list, ticker: str = "") -> tuple:
    """
    47.P6-2: Adjust confidence threshold based on live intraday ATR bucket.

    Uses get_atr_for_breakout() (Wilder ATR on today's 1m bars).
    Returns (adjustment: float, atr_label: str).

    ATR% > 2.0  -> +0.03  high-vol tape, raise the bar
    ATR% 1.0-2.0 -> +0.00  normal
    ATR% < 1.0  -> -0.01  tight tape, be slightly more permissive
    """
    try:
        from app.data.intraday_atr import get_atr_for_breakout
        if not bars_session:
            return 0.00, "ATR-NO-BARS"

        atr_val, atr_source = get_atr_for_breakout(bars_session, ticker)
        if atr_val <= 0:
            return 0.00, "ATR-ZERO"

        current_price = bars_session[-1].get("close", 0)
        if current_price <= 0:
            return 0.00, "ATR-NO-PRICE"

        atr_pct = (atr_val / current_price) * 100

        if atr_pct > 2.0:
            return +0.03, f"ATR-HIGH({atr_pct:.1f}%/{atr_source})"
        elif atr_pct >= 1.0:
            return +0.00, f"ATR-NORMAL({atr_pct:.1f}%/{atr_source})"
        else:
            return -0.01, f"ATR-LOW({atr_pct:.1f}%/{atr_source})"

    except Exception as e:
        logger.warning(f"[DYNAMIC-THRESH] ATR adjustment error (non-fatal): {e}")
        return 0.00, "ATR-ERROR"


def _get_winrate_adjustment(signal_type, grade):
    """
    FIX #27 (Mar 26 2026): Query now filters on BOTH grade AND signal_type.
    Previously signal_type was accepted as a parameter but never used in the
    SQL query, so CFW6_OR A+ and CFW6_INTRADAY A+ returned identical win rates.

    BUG-EOD-1 (Apr 02 2026): The positions table previously had no signal_type
    column, so every call raised an OperationalError / ProgrammingError which
    was silently swallowed by the except block, permanently returning 0.00 and
    disabling win-rate influence on dynamic thresholds entirely.
    Column is now added by position_manager._migrate_signal_type_column().
    """
    try:
        from app.data.db_connection import get_conn, return_conn, dict_cursor, ph

        p    = ph()
        conn = None
        try:
            conn   = get_conn()
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT pnl FROM positions
                WHERE grade = {p}
                  AND signal_type = {p}
                  AND status = 'CLOSED'
                ORDER BY id DESC
                LIMIT 20
            """, (grade, signal_type))

            rows = cursor.fetchall()
        finally:
            if conn:
                return_conn(conn)

        if len(rows) < 10:
            logger.debug(
                f"[DYNAMIC-THRESH] WR skipped ({signal_type}/{grade}): "
                f"only {len(rows)} closed trades (need 10)"
            )
            return 0.00

        wins = sum(1 for row in rows if (row["pnl"] or 0) > 0)
        total = len(rows)
        winrate = wins / total if total > 0 else 0.0

        if winrate > 0.70:
            adj = -0.05
        elif winrate > 0.60:
            adj = -0.02
        elif winrate > 0.50:
            adj = 0.00
        elif winrate > 0.40:
            adj = +0.03
        else:
            adj = +0.07

        # BUG-EOD-1: log win-rate influence so it's visible in session logs
        logger.info(
            f"[DYNAMIC-THRESH] WR({signal_type}/{grade}): "
            f"{wins}/{total} = {winrate:.0%} → adj={adj:+.2f}"
        )
        return adj

    except Exception as e:
        logger.warning(f"[DYNAMIC-THRESH] Win rate lookup error: {e}")
        return 0.00

def get_dynamic_threshold(signal_type: str, grade: str,
                          bars_session: list = None, ticker: str = "") -> float:
    """
    Calculate dynamic confidence threshold for a signal.

    Args:
        signal_type  : "CFW6_OR" or "CFW6_INTRADAY"
        grade        : "A+", "A", "A-", "B+", "B"
        bars_session : today's 1m bars (optional — enables intraday ATR adj)
        ticker       : ticker symbol for logging (optional)

    Returns:
        float: Dynamic threshold (typically 0.60-0.85)
    """
    if signal_type == "CFW6_OR":
        baseline = config.MIN_CONFIDENCE_OR
    else:
        baseline = config.MIN_CONFIDENCE_INTRADAY

    grade_baseline = config.MIN_CONFIDENCE_BY_GRADE.get(grade, baseline)
    baseline = max(baseline, grade_baseline)

    time_adj    = _get_time_of_day_adjustment()
    vix_adj     = _get_vix_adjustment()
    winrate_adj = _get_winrate_adjustment(signal_type, grade)
    atr_adj, atr_label = _get_atr_volatility_adjustment(bars_session or [], ticker)

    final_threshold = baseline + time_adj + vix_adj + winrate_adj + atr_adj
    final_threshold = max(config.CONFIDENCE_ABSOLUTE_FLOOR, min(final_threshold, 0.85))

    logger.info(
        f"[DYNAMIC-THRESH] {signal_type}/{grade}: "
        f"base={baseline:.2f} + time={time_adj:+.2f} + vix={vix_adj:+.2f} "
        f"+ wr={winrate_adj:+.2f} + {atr_label}={atr_adj:+.2f} = {final_threshold:.2f}"
    )

    return final_threshold


def get_threshold_stats():
    """Return current threshold adjustments for monitoring/debugging."""
    return {
        "time_of_day_adj": _get_time_of_day_adjustment(),
        "vix_adj":         _get_vix_adjustment(),
        "timestamp":       _now_et().isoformat()
    }
