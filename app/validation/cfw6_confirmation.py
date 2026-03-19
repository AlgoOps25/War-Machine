"""
CFW6 Confirmation System - Consolidated Confirmation Logic
Replaces: confirmation_layers.py, cfw6_confirmation_enhanced.py, candle_confirmation.py
Implements exact CFW6 video rules for candle confirmation + multi-factor validation

FIXED (Mar 16 2026): Removed private calculate_vwap() (used close price only — wrong formula).
                     Now imports compute_vwap() + passes_vwap_gate() from app.filters.vwap_gate
                     which uses correct typical price formula: (H+L+C)/3.
"""
from typing import Dict, List, Tuple
from datetime import datetime
import time
from utils import config
from app.filters.vwap_gate import compute_vwap, passes_vwap_gate


def _parse_bar_datetime(bar: Dict):
    """
    Safely extract a comparable datetime from a bar dict.
    Handles three shapes:
      1. bar["datetime"] is already a datetime object  -> return as-is
      2. bar["datetime"] is a dict with a 'value' or 'date' key -> parse it
      3. bar["datetime"] is an ISO string -> parse it
    Returns None if unparseable.
    """
    raw = bar.get("datetime")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, dict):
        # Common shapes: {"value": "2026-03-12T09:30:00"} or {"date": "..."}
        raw = raw.get("value") or raw.get("date") or raw.get("datetime")
        if raw is None:
            return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return None


# =============================================================================
# CFW6 CANDLE CONFIRMATION (From Video)
# =============================================================================

def analyze_confirmation_candle(
    candle: Dict,
    direction: str,
    zone_low: float,
    zone_high: float
) -> Tuple[str, str]:
    """
    CFW6 VIDEO RULES: 3-Tier Candle Confirmation

    Type 1 (A+): Strong directional candle, minimal wicks
    Type 2 (A):  Opens opposite, flips to direction (strong wick)
    Type 3 (A-): Long wick rejection, doesn't flip

    Returns: (confirmation_type, grade)
    """
    open_price  = candle["open"]
    close_price = candle["close"]
    high_price  = candle["high"]
    low_price   = candle["low"]

    candle_range = high_price - low_price

    if close_price > open_price:  # Green candle
        upper_wick = high_price - close_price
        lower_wick = open_price - low_price
    else:                         # Red candle
        upper_wick = high_price - open_price
        lower_wick = close_price - low_price

    if direction == "bull":
        in_zone = low_price <= zone_high and low_price >= zone_low
        if not in_zone:
            return "reject", "reject"

        if close_price > open_price:
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
            if wick_ratio < 0.15:
                print(f"[CFW6] TYPE 1 (A+): Perfect green candle - minimal wick ({wick_ratio*100:.1f}%)")
                return "perfect", "A+"
            if wick_ratio >= 0.25:
                print(f"[CFW6] TYPE 2 (A): Flip candle - strong lower wick ({wick_ratio*100:.1f}%)")
                return "flip", "A"

        elif close_price < open_price:
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
            if wick_ratio >= 0.50:
                print(f"[CFW6] TYPE 3 (A-): Wick rejection - didn't flip green ({wick_ratio*100:.1f}%)")
                return "wick", "A-"

        print("[CFW6] REJECT: No valid confirmation pattern")
        return "reject", "reject"

    else:  # Bear direction
        in_zone = high_price >= zone_low and high_price <= zone_high
        if not in_zone:
            return "reject", "reject"

        if close_price < open_price:
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
            if wick_ratio < 0.15:
                print(f"[CFW6] TYPE 1 (A+): Perfect red candle - minimal wick ({wick_ratio*100:.1f}%)")
                return "perfect", "A+"
            if wick_ratio >= 0.25:
                print(f"[CFW6] TYPE 2 (A): Flip candle - strong upper wick ({wick_ratio*100:.1f}%)")
                return "flip", "A"

        elif close_price > open_price:
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
            if wick_ratio >= 0.50:
                print(f"[CFW6] TYPE 3 (A-): Wick rejection - didn't flip red ({wick_ratio*100:.1f}%)")
                return "wick", "A-"

        print("[CFW6] REJECT: No valid confirmation pattern")
        return "reject", "reject"


def wait_for_confirmation(
    ticker: str,
    direction: str,
    fvg_zone: Tuple[float, float],
    start_time: datetime,
    max_wait_candles: int = 15
) -> Tuple[bool, float, str, int, str]:
    """
    CFW6 Real-time confirmation wait loop.

    Refactored to re-fetch bars each cycle instead of scanning a static array.
    This ensures we catch confirmations that arrive AFTER the initial signal.

    Args:
        ticker: Stock symbol
        direction: "bull" or "bear"
        fvg_zone: (zone_low, zone_high)
        start_time: Datetime when signal was first detected
        max_wait_candles: Maximum 5m candles to wait (default 15 = 75 minutes)

    Returns:
        (found, entry_price, grade, confirm_idx, confirmation_type)
    """
    zone_low, zone_high = fvg_zone
    print(f"[CFW6] Waiting for {direction.upper()} confirmation in zone ${zone_low:.2f}-${zone_high:.2f}")

    candles_waited = 0

    while candles_waited < max_wait_candles:
        try:
            from app.data.data_manager import data_manager
            bars = data_manager.get_today_5m_bars(ticker)
        except Exception as e:
            print(f"[CFW6] Error fetching bars: {e}")
            time.sleep(60)
            candles_waited += 1
            continue

        if not bars:
            print("[CFW6] No bars available, waiting...")
            time.sleep(60)
            candles_waited += 1
            continue

        new_bars = []
        for i, bar in enumerate(bars):
            bar_dt = _parse_bar_datetime(bar)
            if bar_dt is None:
                continue
            cmp_start = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
            cmp_bar   = bar_dt.replace(tzinfo=None) if bar_dt.tzinfo else bar_dt
            if cmp_bar > cmp_start:
                new_bars.append((i, bar))

        if not new_bars:
            print(f"[CFW6] No new bars yet, waiting... (cycle {candles_waited+1}/{max_wait_candles})")
            time.sleep(60)
            candles_waited += 1
            continue

        # Scan ALL new bars — catches multi-bar confirmation patterns
        confirmed = False
        for bar_idx, bar in new_bars:
            if direction == "bull":
                touches_zone = bar["low"] <= zone_high and bar["low"] >= zone_low
            else:
                touches_zone = bar["high"] >= zone_low and bar["high"] <= zone_high

            if touches_zone:
                confirmation_type, grade = analyze_confirmation_candle(
                    bar, direction, zone_low, zone_high
                )
                if grade != "reject":
                    entry_price = bar["close"]
                    candle_time = bar.get("datetime", "N/A")
                    print(f"[CFW6] CONFIRMED: {grade} setup at ${entry_price:.2f} "
                        f"(candle {candles_waited}, {candle_time})")
                    return True, entry_price, grade, bar_idx, confirmation_type

    if not confirmed:
        pass  # fall through to sleep below
    
        time.sleep(60)
        candles_waited += 1

    print(f"[CFW6] TIMEOUT: No confirmation after {max_wait_candles} cycles")
    return False, 0, "reject", -1, "timeout"


# =============================================================================
# MULTI-FACTOR CONFIRMATION LAYERS
# =============================================================================
# NOTE: VWAP helpers previously defined here (calculate_vwap, check_vwap_alignment)
#       used close price only — incorrect formula. Removed Mar 16 2026.
#       Now delegates to app.filters.vwap_gate: compute_vwap (typical price H+L+C/3)
#       and passes_vwap_gate (directional alignment check).


def check_previous_day_levels(ticker: str, current_price: float, direction: str) -> Dict:
    """
    Check proximity to PDH/PDL using centralized data_manager.

    Phase 1.7 refactor: delegates to data_manager.get_previous_day_ohlc()
    for DRY single-source-of-truth PDH/PDL data.
    """
    from app.data.data_manager import data_manager

    prev_day = data_manager.get_previous_day_ohlc(ticker)
    pdh = prev_day["high"]
    pdl = prev_day["low"]

    if direction == "bull":
        breaking_pdh = current_price > pdh
        distance = ((current_price - pdh) / pdh) * 100 if pdh > 0 else 0
        return {"aligned": breaking_pdh, "level": "PDH", "level_price": pdh, "distance_pct": distance}
    else:
        breaking_pdl = current_price < pdl
        distance = ((pdl - current_price) / pdl) * 100 if pdl > 0 else 0
        return {"aligned": breaking_pdl, "level": "PDL", "level_price": pdl, "distance_pct": distance}


def check_institutional_volume(bars: List[Dict], breakout_idx: int) -> bool:
    """Detect institutional block trades near breakout."""
    if len(bars) < 20 or breakout_idx < 20:
        return False
    avg_volume      = sum(b["volume"] for b in bars[breakout_idx-20:breakout_idx]) / 20
    breakout_volume = bars[breakout_idx]["volume"]
    return breakout_volume >= avg_volume * 3


def grade_signal_with_confirmations(
    ticker: str,
    direction: str,
    bars: List[Dict],
    current_price: float,
    breakout_idx: int,
    base_grade: str
) -> Dict:
    """
    Apply 3 active confirmation layers and adjust grade.

    Layers:
    1. VWAP alignment  — via app.filters.vwap_gate.passes_vwap_gate() (correct H+L+C/3 formula)
    2. Previous day levels (PDH/PDL)
    3. Institutional volume
    (Options flow removed until real data source is wired in)

    Grade logic (out of 3):
    - 3/3 aligned  -> upgrade
    - 0/3 aligned  -> downgrade / reject
    - 1-2/3 aligned -> maintain
    """
    print(f"[CONFIRM] Checking confirmation layers for {ticker}...")

    vwap_ok, vwap_reason = passes_vwap_gate(bars, direction, current_price)
    pd_result            = check_previous_day_levels(ticker, current_price, direction)
    inst_ok              = check_institutional_volume(bars, breakout_idx)

    aligned_count = sum([vwap_ok, pd_result["aligned"], inst_ok])

    vwap_emoji = "OK" if vwap_ok else "FAIL"
    pd_emoji   = "OK" if pd_result["aligned"] else "FAIL"
    inst_emoji = "OK" if inst_ok else "FAIL"

    print(f"[CONFIRM] Aligned: {aligned_count}/3")
    print(f"  VWAP:          {vwap_emoji} | {vwap_reason}")
    print(f"  Prev Day:      {pd_emoji} ({pd_result.get('level','?')} @ ${pd_result.get('level_price',0):.2f})")
    print(f"  Institutional: {inst_emoji}")

    final_grade = base_grade

    if aligned_count == 3:
        if base_grade == "A":
            final_grade = "A+"
        elif base_grade == "A-":
            final_grade = "A"
        print(f"[CONFIRM] Upgraded {base_grade} -> {final_grade} (perfect 3/3 alignment)")

    elif aligned_count == 0:
        if base_grade == "A+":
            final_grade = "A"
        elif base_grade == "A":
            final_grade = "A-"
        else:
            final_grade = "reject"
        print(f"[CONFIRM] Downgraded {base_grade} -> {final_grade} (0/3 alignment)")

    else:
        print(f"[CONFIRM] Grade maintained: {final_grade} ({aligned_count}/3 aligned)")

    return {
        "final_grade":   final_grade,
        "base_grade":    base_grade,
        "aligned_count": aligned_count,
        "confirmations": {
            "vwap":          vwap_ok,
            "prev_day":      pd_result,
            "institutional": inst_ok
        }
    }
