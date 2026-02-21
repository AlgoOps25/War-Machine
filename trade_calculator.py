"""
Trade Calculator - Consolidated Stop Loss, Targets, and Adaptive Parameters
Replaces: targets.py, adaptive_parameters.py
Implements CFW6 stop/target logic + ATR-based adaptive thresholds
"""
import numpy as np
from datetime import time as dtime
from typing import List, Dict, Tuple

# ============================================================================
# ATR & VOLATILITY CALCULATIONS
# ============================================================================

def _filter_session_bars(bars: List[Dict]) -> List[Dict]:
    """
    Filter bars to regular session hours only (09:30 - 16:00 ET).
    Pre-market and after-hours bars have artificially wide spreads that
    inflate ATR and push stops too far from entry.
    Falls back to all bars if none pass the filter.
    """
    SESSION_START = dtime(9, 30)
    SESSION_END   = dtime(16, 0)
    filtered = []
    for b in bars:
        dt = b.get("datetime")
        if dt is None:
            continue
        t = dt.time() if hasattr(dt, "time") else None
        if t is not None and SESSION_START <= t <= SESSION_END:
            filtered.append(b)
    return filtered if filtered else bars


def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range using session-only bars (09:30-16:00 ET).

    Pre-market candles are excluded so wide overnight spreads do not
    inflate the ATR and push stops artificially far from entry.
    """
    session_bars = _filter_session_bars(bars)
    if len(session_bars) < period:
        return 0

    true_ranges = []
    for i in range(1, len(session_bars)):
        high       = session_bars[i]["high"]
        low        = session_bars[i]["low"]
        prev_close = session_bars[i-1]["close"]
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close)
        )
        true_ranges.append(tr)

    return np.mean(true_ranges[-period:]) if true_ranges else 0

# ============================================================================
# ADAPTIVE FVG THRESHOLDS
# ============================================================================

def get_adaptive_fvg_threshold(bars: List[Dict], ticker: str) -> Tuple[float, float]:
    """
    CFW6 OPTIMIZATION: Adaptive FVG size based on ticker volatility
    Returns: (fvg_threshold, confidence_adjustment)
    - High volatility (ATR > 2.0%): 0.3% minimum FVG, 0.95x confidence
    - Medium volatility (ATR 1.0-2.0%): 0.2% minimum FVG, 1.0x confidence
    - Low volatility (ATR < 1.0%): 0.15% minimum FVG, 1.05x confidence
    """
    atr           = calculate_atr(bars, period=14)
    current_price = bars[-1]["close"]
    atr_pct       = (atr / current_price) * 100 if current_price > 0 else 0

    if atr_pct > 2.0:
        fvg_threshold         = 0.003
        confidence_adjustment = 0.95
        volatility_label      = "HIGH"
    elif atr_pct > 1.0:
        fvg_threshold         = 0.002
        confidence_adjustment = 1.0
        volatility_label      = "MEDIUM"
    else:
        fvg_threshold         = 0.0015
        confidence_adjustment = 1.05
        volatility_label      = "LOW"

    print(f"[ADAPTIVE] {ticker} ATR: {atr:.2f} ({atr_pct:.2f}%) - {volatility_label} volatility")
    print(f"  FVG threshold: {fvg_threshold*100:.2f}% | Confidence adj: {confidence_adjustment:.2f}x")
    return fvg_threshold, confidence_adjustment

# ============================================================================
# ADAPTIVE ORB THRESHOLDS
# ============================================================================

def calculate_volume_multiplier(bars: List[Dict], breakout_idx: int) -> float:
    """Calculate volume multiplier at breakout candle"""
    if breakout_idx < 20 or len(bars) <= breakout_idx:
        return 1.0
    avg_volume      = np.mean([b["volume"] for b in bars[breakout_idx-20:breakout_idx]])
    breakout_volume = bars[breakout_idx]["volume"]
    return breakout_volume / avg_volume if avg_volume > 0 else 1.0


def get_adaptive_orb_threshold(bars: List[Dict], breakout_idx: int) -> float:
    """
    CFW6 OPTIMIZATION: Volume-weighted ORB breakout confirmation
    - High volume breakout (2x+ avg): 0.08% threshold
    - Standard volume (1.5-2x avg):   0.10% threshold
    - Low volume (<1.5x avg):         0.15% threshold
    """
    volume_multiplier = calculate_volume_multiplier(bars, breakout_idx)
    if volume_multiplier >= 2.0:
        orb_threshold = 0.0008
        print(f"[ADAPTIVE] High volume breakout ({volume_multiplier:.1f}x) - Using 0.08% threshold")
    elif volume_multiplier >= 1.5:
        orb_threshold = 0.001
        print(f"[ADAPTIVE] Standard volume ({volume_multiplier:.1f}x) - Using 0.10% threshold")
    else:
        orb_threshold = 0.0015
        print(f"[ADAPTIVE] Low volume ({volume_multiplier:.1f}x) - Using 0.15% threshold")
    return orb_threshold

# ============================================================================
# CONFIDENCE DECAY
# ============================================================================

def apply_confidence_decay(base_confidence: float, candles_waited: int) -> float:
    """
    CFW6 OPTIMIZATION: Penalize delayed confirmations
    - 0-5 candles:   No penalty
    - 6-10 candles:  -2% per candle
    - 11-15 candles: -3% per candle
    - 16+ candles:   -5% per candle
    """
    if candles_waited <= 5:
        decay = 0
    elif candles_waited <= 10:
        decay = (candles_waited - 5) * 0.02
    elif candles_waited <= 15:
        decay = 0.10 + (candles_waited - 10) * 0.03
    else:
        decay = 0.25 + (candles_waited - 15) * 0.05

    adjusted_confidence = base_confidence * (1 - decay)
    if candles_waited > 5:
        print(f"[DECAY] Waited {candles_waited} candles - Confidence reduced by {decay*100:.1f}%")
        print(f"  {base_confidence:.2%} -> {adjusted_confidence:.2%}")
    return max(adjusted_confidence, 0.50)

# ============================================================================
# STOP LOSS & TARGETS
# ============================================================================

def calculate_stop_loss_by_grade(
    entry_price: float,
    grade: str,
    direction: str,
    or_low: float,
    or_high: float,
    atr: float
) -> float:
    """
    CFW6 OPTIMIZATION: Grade-based stop loss
    A+: 1.2x ATR | A: 1.5x ATR | A-: 1.8x ATR
    Also respects Opening Range boundaries.
    """
    atr_multipliers = {"A+": 1.2, "A": 1.5, "A-": 1.8}
    atr_mult        = atr_multipliers.get(grade, 1.5)
    stop_distance   = atr * atr_mult

    if direction == "bull":
        atr_stop   = entry_price - stop_distance
        or_stop    = or_low * 0.999
        stop_price = max(atr_stop, or_stop)
        print(f"[STOP] BULL {grade}: Entry ${entry_price:.2f} | ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} | Using ${stop_price:.2f}")
    else:
        atr_stop   = entry_price + stop_distance
        or_stop    = or_high * 1.001
        stop_price = min(atr_stop, or_stop)
        print(f"[STOP] BEAR {grade}: Entry ${entry_price:.2f} | ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} | Using ${stop_price:.2f}")

    return stop_price


def calculate_targets_by_grade(
    entry_price: float,
    stop_price: float,
    grade: str,
    direction: str
) -> Tuple[float, float]:
    """
    T1 = 2R, T2 = 3.5R for all grades (per CFW6 video rules).
    """
    risk        = abs(entry_price - stop_price)
    t1_distance = risk * 2.0
    t2_distance = risk * 3.5

    if direction == "bull":
        t1 = entry_price + t1_distance
        t2 = entry_price + t2_distance
    else:
        t1 = entry_price - t1_distance
        t2 = entry_price - t2_distance

    print(f"[TARGETS] {grade}: T1=${t1:.2f} (2R) | T2=${t2:.2f} (3.5R) | Risk/contract=${risk:.2f}")
    return t1, t2


def compute_stop_and_targets(
    bars: List[Dict],
    direction: str,
    or_high: float,
    or_low: float,
    entry_price: float,
    grade: str = "A"
) -> Tuple[float, float, float]:
    """
    Main entry point: compute stop and targets.
    ATR is derived from session-only bars (09:30-16:00 ET) so pre-market
    volatility does not widen stops.
    Returns: (stop_price, t1, t2)
    """
    atr        = calculate_atr(bars, period=14)
    stop_price = calculate_stop_loss_by_grade(
        entry_price, grade, direction, or_low, or_high, atr
    )
    t1, t2 = calculate_targets_by_grade(entry_price, stop_price, grade, direction)
    return stop_price, t1, t2


def get_next_1hour_target(bars: List[Dict], direction: str) -> float:
    """
    ADVANCED: Get next 1-hour high/low for dynamic T2 target.
    Optional alternative to fixed 3.5R.
    """
    hour_bars = []
    for i in range(0, len(bars), 60):
        chunk = bars[i:i+60]
        if len(chunk) < 60:
            break
        hour_bars.append({
            "high": max(b["high"] for b in chunk),
            "low":  min(b["low"]  for b in chunk),
        })
    if not hour_bars:
        return 0
    return hour_bars[-1]["high"] if direction == "bull" else hour_bars[-1]["low"]
