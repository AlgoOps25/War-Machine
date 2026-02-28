"""
Dynamic Confidence Threshold Manager
Optimization #3: Adaptive thresholds based on performance and market conditions

Replaces static config thresholds with dynamic adjustments based on:
- Rolling win rate (last 20 trades per signal type/grade)
- Market volatility (VIX level)
- Time of day (morning vs afternoon vs power hour)
- Recent signal quality (last 5 signals)
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from utils import config


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

        vix = vix_data.get("close", 0)

        if vix < 15:
            return -0.02
        elif vix < 20:
            return 0.00
        elif vix < 30:
            return +0.03
        else:
            return +0.05
    except Exception as e:
        print(f"[DYNAMIC-THRESH] VIX lookup error: {e}")
        return 0.00


def _get_winrate_adjustment(signal_type, grade):
    """
    Adjust thresholds based on recent win rate for this signal type + grade combo.

    Win rate > 70%: -0.05 (performing well, be more aggressive)
    Win rate 60-70%: -0.02 (good performance, slight leniency)
    Win rate 50-60%: +0.00 (neutral)
    Win rate 40-50%: +0.03 (underperforming, tighten up)
    Win rate < 40%: +0.07 (poor performance, very strict)

    Lookback: Last 20 trades for this type+grade combo.
    Returns 0.00 if insufficient data (<10 trades).
    """
    try:
        from app.data.db_connection import get_conn, dict_cursor

        conn = get_conn()
        cursor = dict_cursor(conn)

        # Get last 20 closed trades for this signal_type + grade
        cursor.execute("""
            SELECT outcome FROM trades
            WHERE signal_type = ? AND grade = ?
            AND status = 'CLOSED'
            ORDER BY id DESC
            LIMIT 20
        """, (signal_type, grade))

        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 10:
            # Insufficient data - use neutral adjustment
            return 0.00

        wins = sum(1 for row in rows if row["outcome"] in ("WIN", "PARTIAL_WIN"))
        total = len(rows)
        winrate = wins / total if total > 0 else 0.0

        # Map win rate to adjustment
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
        print(f"[DYNAMIC-THRESH] Win rate lookup error: {e}")
        return 0.00


def _get_recent_quality_adjustment():
    """
    Adjust based on quality of last 5 signals (any type/grade).

    If recent signals have been low quality (many filtered/gated),
    raise threshold temporarily.

    Last 5 signals:
    - 0-1 filtered: +0.00 (good quality flow)
    - 2-3 filtered: +0.02 (some quality issues)
    - 4-5 filtered: +0.04 (poor quality flow, tighten up)

    Checks proposed_trades table for signals proposed in last 2 hours.
    Returns 0.00 if insufficient data.
    """
    try:
        from app.data.db_connection import get_conn, dict_cursor

        conn = get_conn()
        cursor = dict_cursor(conn)

        # Get last 5 proposed signals (regardless of whether they were armed)
        two_hours_ago = _now_et() - timedelta(hours=2)

        cursor.execute("""
            SELECT confidence FROM proposed_trades
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT 5
        """, (two_hours_ago,))

        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 3:
            # Insufficient data
            return 0.00

        # Count how many were below their effective threshold
        # (proxy: confidence < 0.65 suggests it was filtered/marginal)
        low_quality = sum(1 for row in rows if row["confidence"] < 0.65)

        if low_quality <= 1:
            return 0.00
        elif low_quality <= 3:
            return +0.02
        else:
            return +0.04

    except Exception as e:
        print(f"[DYNAMIC-THRESH] Recent quality lookup error: {e}")
        return 0.00


def get_dynamic_threshold(signal_type, grade):
    """
    Calculate dynamic confidence threshold for a signal.

    Args:
        signal_type: "CFW6_OR" or "CFW6_INTRADAY"
        grade: "A+", "A", or "A-"

    Returns:
        float: Dynamic threshold (typically 0.60-0.85)

    Formula:
        baseline (from config)
        + time_of_day_adj (Â±0.05)
        + vix_adj (Â±0.05)
        + winrate_adj (Â±0.07)
        + quality_adj (Â±0.04)

        Clamped to: [ABSOLUTE_FLOOR, 0.85]
    """
    # Get baseline from config (these are now "default" values)
    if signal_type == "CFW6_OR":
        baseline = config.MIN_CONFIDENCE_OR
    else:
        baseline = config.MIN_CONFIDENCE_INTRADAY

    # Apply grade-specific baseline override if lower
    grade_baseline = config.MIN_CONFIDENCE_BY_GRADE.get(grade, baseline)
    baseline = max(baseline, grade_baseline)

    # Apply dynamic adjustments
    time_adj = _get_time_of_day_adjustment()
    vix_adj = _get_vix_adjustment()
    winrate_adj = _get_winrate_adjustment(signal_type, grade)
    quality_adj = _get_recent_quality_adjustment()

    # Calculate final threshold
    final_threshold = baseline + time_adj + vix_adj + winrate_adj + quality_adj

    # Clamp to reasonable bounds
    final_threshold = max(config.CONFIDENCE_ABSOLUTE_FLOOR, min(final_threshold, 0.85))

    # Log the calculation for transparency
    print(
        f"[DYNAMIC-THRESH] {signal_type}/{grade}: "
        f"base={baseline:.2f} + time={time_adj:+.2f} + vix={vix_adj:+.2f} "
        f"+ wr={winrate_adj:+.2f} + qual={quality_adj:+.2f} = {final_threshold:.2f}"
    )

    return final_threshold


def get_threshold_stats():
    """
    Return current threshold adjustments for monitoring/debugging.

    Returns:
        dict with current adjustment values
    """
    return {
        "time_of_day_adj": _get_time_of_day_adjustment(),
        "vix_adj": _get_vix_adjustment(),
        "timestamp": _now_et().isoformat()
    }




