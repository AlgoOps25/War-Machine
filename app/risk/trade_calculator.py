"""
Trade Calculator - Consolidated Stop Loss, Targets, and Adaptive Parameters
Replaces: targets.py, adaptive_parameters.py
Implements CFW6 stop/target logic + ATR-based adaptive thresholds

UPDATED: Added T3 = 1-hour structure level (per YouTube video methodology)
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
    CFW6 OPTIMIZATION: Grade-based stop loss with wider ATR multipliers
    A+: 2.0x ATR | A: 2.5x ATR | A-: 3.0x ATR
    Increased from previous (1.2x, 1.5x, 1.8x) to prevent "too tight" stops.
    Also respects Opening Range boundaries.
    """
    atr_multipliers = {"A+": 2.0, "A": 2.5, "A-": 3.0}
    atr_mult        = atr_multipliers.get(grade, 2.5)
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
    T1 = 1R (1:1), T2 = 2R (2:1) for all grades.
    Updated from previous (2R, 3.5R) to match YouTube video methodology.
    T3 is calculated separately as 1-hour structure level.
    """
    risk        = abs(entry_price - stop_price)
    t1_distance = risk * 1.0  # 1R
    t2_distance = risk * 2.0  # 2R

    if direction == "bull":
        t1 = entry_price + t1_distance
        t2 = entry_price + t2_distance
    else:
        t1 = entry_price - t1_distance
        t2 = entry_price - t2_distance

    print(f"[TARGETS] {grade}: T1=${t1:.2f} (1R) | T2=${t2:.2f} (2R) | Risk/contract=${risk:.2f}")
    return t1, t2


def get_next_hourly_high(ticker: str, bars: List[Dict], current_price: float) -> float:
    """
    Find next 1-hour resistance level above current price.
    
    Matches video methodology: "I like to go for the next key level which is an hourly high"
    
    Algorithm:
    1. Group 5-minute bars into 1-hour candles
    2. Find nearest hourly high above current price
    3. Fallback to recent swing high if no clear resistance
    
    Args:
        ticker: Ticker symbol (for logging)
        bars: List of 5-minute bars
        current_price: Current entry price
    
    Returns:
        float: Next hourly high resistance level
    """
    try:
        # Group into 1-hour candles (12 x 5min bars = 1 hour)
        hour_bars = []
        for i in range(0, len(bars), 12):
            chunk = bars[i:i+12]
            if len(chunk) < 6:  # Need at least 30min of data
                continue
            hour_high = max(b["high"] for b in chunk)
            hour_low = min(b["low"] for b in chunk)
            hour_bars.append({"high": hour_high, "low": hour_low})
        
        if not hour_bars:
            # Fallback: use recent swing high
            recent_high = max(b["high"] for b in bars[-24:])
            print(f"[T3] {ticker} - No hourly bars, using recent swing high: ${recent_high:.2f}")
            return recent_high
        
        # Find nearest hourly high above current price
        resistance_levels = [bar["high"] for bar in hour_bars if bar["high"] > current_price]
        
        if resistance_levels:
            t3 = min(resistance_levels)  # Closest resistance
            print(f"[T3] {ticker} - Next 1H resistance: ${t3:.2f} (from {len(resistance_levels)} levels)")
            return t3
        
        # Fallback: use highest recent high + buffer
        recent_high = max(b["high"] for b in bars[-24:])
        t3 = recent_high * 1.005  # 0.5% above recent high
        print(f"[T3] {ticker} - No resistance above, using extended target: ${t3:.2f}")
        return t3
        
    except Exception as e:
        print(f"[T3] {ticker} - Error calculating 1H level: {e}")
        # Emergency fallback: 3R
        risk = abs(current_price - bars[-1]["low"])  # Rough risk estimate
        return current_price + (risk * 3.0)


def get_next_hourly_low(ticker: str, bars: List[Dict], current_price: float) -> float:
    """
    Find next 1-hour support level below current price.
    
    Same logic as get_next_hourly_high but for bearish targets.
    """
    try:
        # Group into 1-hour candles
        hour_bars = []
        for i in range(0, len(bars), 12):
            chunk = bars[i:i+12]
            if len(chunk) < 6:
                continue
            hour_high = max(b["high"] for b in chunk)
            hour_low = min(b["low"] for b in chunk)
            hour_bars.append({"high": hour_high, "low": hour_low})
        
        if not hour_bars:
            recent_low = min(b["low"] for b in bars[-24:])
            print(f"[T3] {ticker} - No hourly bars, using recent swing low: ${recent_low:.2f}")
            return recent_low
        
        # Find nearest hourly low below current price
        support_levels = [bar["low"] for bar in hour_bars if bar["low"] < current_price]
        
        if support_levels:
            t3 = max(support_levels)  # Closest support
            print(f"[T3] {ticker} - Next 1H support: ${t3:.2f} (from {len(support_levels)} levels)")
            return t3
        
        # Fallback: use lowest recent low - buffer
        recent_low = min(b["low"] for b in bars[-24:])
        t3 = recent_low * 0.995  # 0.5% below recent low
        print(f"[T3] {ticker} - No support below, using extended target: ${t3:.2f}")
        return t3
        
    except Exception as e:
        print(f"[T3] {ticker} - Error calculating 1H level: {e}")
        # Emergency fallback: 3R
        risk = abs(current_price - bars[-1]["high"])
        return current_price - (risk * 3.0)


def compute_stop_and_targets(
    ticker: str,
    bars: List[Dict],
    direction: str,
    or_high: float,
    or_low: float,
    entry_price: float,
    grade: str = "A"
) -> Tuple[float, float, float, float]:
    """
    Main entry point: compute stop and targets.
    
    Returns: (stop_price, t1, t2, t3)
    - stop_price: Stop loss level
    - t1: Target 1 (1R - 1:1 risk/reward)
    - t2: Target 2 (2R - 2:1 risk/reward)
    - t3: Target 3 (1-hour structure level)
    
    ATR is derived from session-only bars (09:30-16:00 ET) so pre-market
    volatility does not widen stops.
    """
    atr        = calculate_atr(bars, period=14)
    stop_price = calculate_stop_loss_by_grade(
        entry_price, grade, direction, or_low, or_high, atr
    )
    
    # T1 = 1R, T2 = 2R (fixed R-multiples)
    t1, t2 = calculate_targets_by_grade(entry_price, stop_price, grade, direction)
    
    # T3 = Next 1-hour structure level (dynamic)
    if direction == "bull":
        t3 = get_next_hourly_high(ticker, bars, entry_price)
    else:
        t3 = get_next_hourly_low(ticker, bars, entry_price)
    
    # Validation: Ensure T3 is beyond T2 (otherwise use T2 + 20%)
    if direction == "bull":
        if t3 <= t2:
            t3 = t2 * 1.002  # 0.2% above T2
            print(f"[T3] {ticker} - Adjusted to ${t3:.2f} (1H level was below T2)")
    else:
        if t3 >= t2:
            t3 = t2 * 0.998  # 0.2% below T2
            print(f"[T3] {ticker} - Adjusted to ${t3:.2f} (1H level was above T2)")
    
    return stop_price, t1, t2, t3


# ============================================================================
# BACKWARD COMPATIBILITY (Deprecated - use compute_stop_and_targets)
# ============================================================================

def get_next_1hour_target(bars: List[Dict], direction: str) -> float:
    """
    DEPRECATED: Use get_next_hourly_high/low instead.
    Kept for backward compatibility.
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
