"""
Dynamic Confidence Threshold Manager
Optimization #3: Adaptive thresholds based on performance and market conditions

Replaces static config thresholds with dynamic adjustments based on:
- Rolling win rate (last 20 trades per signal type/grade)
- Market volatility (VIX level)
- Time of day (morning vs afternoon vs power hour)
- Recent signal quality (last 5 signals)

FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from utils import config
import logging
logger = logging.getLogger(__name__)
from app.data.intraday_atr import get_atr_for_breakout

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
        logger.info(f"[DYNAMIC-THRESH] VIX lookup error: {e}")
        return 0.00
    
def _get_winrate_adjustment(signal_type, grade):
    try:
        from app.data.db_connection import get_conn, return_conn, dict_cursor

        conn = None
        try:
            conn = get_conn()
            cursor = dict_cursor(conn)

            cursor.execute("""
                SELECT pnl FROM positions
                WHERE grade = %s
                  AND status = 'CLOSED'
                ORDER BY id DESC
                LIMIT 20
            """, (grade,))

            rows = cursor.fetchall()
        finally:
            if conn:
                return_conn(conn)

        if len(rows) < 10:
            return 0.00

        wins = sum(1 for row in rows if (row["pnl"] or 0) > 0)
        total = len(rows)
        winrate = wins / total if total > 0 else 0.0

        if winrate > 0.70:
            return -0.05
        elif winrate > 0.60:
            return -0.02
        elif winrate > 0.50:
            return 0.00
        elif winrate > 0.40:
            return +0.03
        else:
            return +0.07

    except Exception as e:
        logger.info(f"[DYNAMIC-THRESH] Win rate lookup error: {e}")
        return 0.00

def _get_recent_quality_adjustment():
    """
    Adjust based on quality of last 5 signals (any type/grade).
    Returns 0.00 if insufficient data.
    """
    try:
        from app.data.db_connection import get_conn, return_conn, dict_cursor

        conn = None
        rows = []
        try:
            conn = get_conn()
            cursor = dict_cursor(conn)

            two_hours_ago = _now_et() - timedelta(hours=2)

            cursor.execute("""
                SELECT confidence FROM ml_signals
                WHERE created_at > %s
                  AND status = 'PENDING'
                ORDER BY created_at DESC
                LIMIT 5
            """, (two_hours_ago,))

            rows = cursor.fetchall()
        finally:
            if conn:
                return_conn(conn)

        if len(rows) < 3:
            return 0.00

        low_quality = sum(1 for row in rows if (row["confidence"] or 1.0) < 0.65)

        if low_quality <= 1:
            return 0.00
        elif low_quality <= 3:
            return +0.02
        else:
            return +0.04

    except Exception as e:
        logger.info(f"[DYNAMIC-THRESH] Recent quality lookup error: {e}")
        return 0.00

def get_dynamic_threshold(signal_type, grade):
    """
    Calculate dynamic confidence threshold for a signal.

    Args:
        signal_type: "CFW6_OR" or "CFW6_INTRADAY"
        grade: "A+", "A", or "A-"

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
    quality_adj = _get_recent_quality_adjustment()

    final_threshold = baseline + time_adj + vix_adj + winrate_adj + quality_adj
    final_threshold = max(config.CONFIDENCE_ABSOLUTE_FLOOR, min(final_threshold, 0.85))

    print(
        f"[DYNAMIC-THRESH] {signal_type}/{grade}: "
        f"base={baseline:.2f} + time={time_adj:+.2f} + vix={vix_adj:+.2f} "
        f"+ wr={winrate_adj:+.2f} + qual={quality_adj:+.2f} = {final_threshold:.2f}"
    )

    return final_threshold


def get_threshold_stats():
    """Return current threshold adjustments for monitoring/debugging."""
    return {
        "time_of_day_adj": _get_time_of_day_adjustment(),
        "vix_adj":         _get_vix_adjustment(),
        "timestamp":       _now_et().isoformat()
    }
