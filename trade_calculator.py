"""
Trade Calculator - Consolidated Stop Loss, Targets, and Adaptive Parameters
Replaces: targets.py, adaptive_parameters.py
Implements CFW6 stop/target logic + ATR-based adaptive thresholds
"""
import numpy as np
from typing import List, Dict, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# ATR & VOLATILITY CALCULATIONS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range for volatility measurement"""
    if len(bars) < period:
        return 0
    
    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i-1]["close"]
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    return np.mean(true_ranges[-period:]) if true_ranges else 0


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE FVG THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════

def get_adaptive_fvg_threshold(bars: List[Dict], ticker: str) -> Tuple[float, float]:
    """
    CFW6 OPTIMIZATION: Adaptive FVG size based on ticker volatility
    
    Returns: (fvg_threshold, confidence_adjustment)
    
    - High volatility (ATR > 2.0%): 0.3% minimum FVG, 0.95x confidence
    - Medium volatility (ATR 1.0-2.0%): 0.2% minimum FVG, 1.0x confidence  
    - Low volatility (ATR < 1.0%): 0.15% minimum FVG, 1.05x confidence
    """
    atr = calculate_atr(bars, period=14)
    current_price = bars[-1]["close"]
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
    
    # Adaptive thresholds based on volatility
    if atr_pct > 2.0:
        fvg_threshold = 0.003  # 0.3% for high volatility
        confidence_adjustment = 0.95  # Slightly reduce confidence
        volatility_label = "HIGH"
    elif atr_pct > 1.0:
        fvg_threshold = 0.002  # 0.2% for medium volatility
        confidence_adjustment = 1.0   # Standard confidence
        volatility_label = "MEDIUM"
    else:
        fvg_threshold = 0.0015  # 0.15% for low volatility
        confidence_adjustment = 1.05  # Boost confidence for clean setups
        volatility_label = "LOW"
    
    print(f"[ADAPTIVE] {ticker} ATR: {atr:.2f} ({atr_pct:.2f}%) - {volatility_label} volatility")
    print(f"  → FVG threshold: {fvg_threshold*100:.2f}% | Confidence adj: {confidence_adjustment:.2f}x")
    
    return fvg_threshold, confidence_adjustment


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE ORB THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_volume_multiplier(bars: List[Dict], breakout_idx: int) -> float:
    """Calculate volume multiplier at breakout candle"""
    if breakout_idx < 20 or len(bars) <= breakout_idx:
        return 1.0
    
    # Average volume of 20 candles before breakout
    avg_volume = np.mean([b["volume"] for b in bars[breakout_idx-20:breakout_idx]])
    
    # Breakout candle volume
    breakout_volume = bars[breakout_idx]["volume"]
    
    return breakout_volume / avg_volume if avg_volume > 0 else 1.0


def get_adaptive_orb_threshold(bars: List[Dict], breakout_idx: int) -> float:
    """
    CFW6 OPTIMIZATION: Volume-weighted ORB breakout confirmation
    
    - High volume breakout (2x+ avg): 0.08% threshold (more aggressive)
    - Standard volume (1.5-2x avg): 0.10% threshold (default)
    - Low volume (<1.5x avg): 0.15% threshold (more conservative)
    """
    volume_multiplier = calculate_volume_multiplier(bars, breakout_idx)
    
    if volume_multiplier >= 2.0:
        orb_threshold = 0.0008  # 0.08% - strong volume confirms breakout
        print(f"[ADAPTIVE] High volume breakout ({volume_multiplier:.1f}x) → Using 0.08% threshold")
    elif volume_multiplier >= 1.5:
        orb_threshold = 0.001   # 0.10% - standard
        print(f"[ADAPTIVE] Standard volume ({volume_multiplier:.1f}x) → Using 0.10% threshold")
    else:
        orb_threshold = 0.0015  # 0.15% - weak volume, be conservative
        print(f"[ADAPTIVE] Low volume ({volume_multiplier:.1f}x) → Using 0.15% threshold")
    
    return orb_threshold


# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE DECAY
# ══════════════════════════════════════════════════════════════════════════════

def apply_confidence_decay(base_confidence: float, candles_waited: int) -> float:
    """
    CFW6 OPTIMIZATION: Penalize delayed confirmations
    
    Reduce confidence for late entries:
    - 0-5 candles: No penalty
    - 6-10 candles: -2% confidence per candle
    - 11-15 candles: -3% confidence per candle
    - 16+ candles: -5% confidence per candle (setup aging)
    """
    if candles_waited <= 5:
        decay = 0
    elif candles_waited <= 10:
        decay = (candles_waited - 5) * 0.02  # 2% per candle
    elif candles_waited <= 15:
        decay = 0.10 + (candles_waited - 10) * 0.03  # 3% per candle
    else:
        decay = 0.25 + (candles_waited - 15) * 0.05  # 5% per candle
    
    adjusted_confidence = base_confidence * (1 - decay)
    
    if candles_waited > 5:
        print(f"[DECAY] Waited {candles_waited} candles → Confidence reduced by {decay*100:.1f}%")
        print(f"  {base_confidence:.2%} → {adjusted_confidence:.2%}")
    
    return max(adjusted_confidence, 0.50)  # Floor at 50% confidence


# ══════════════════════════════════════════════════════════════════════════════
# STOP LOSS & TARGETS
# ══════════════════════════════════════════════════════════════════════════════

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
    
    A+ signals (highest quality): 1.2x ATR (tighter stop)
    A signals (good quality): 1.5x ATR (standard)
    A- signals (marginal): 1.8x ATR (wider stop)
    
    Also respects Opening Range boundaries
    """
    # Base ATR multipliers by grade
    atr_multipliers = {
        "A+": 1.2,
        "A": 1.5,
        "A-": 1.8
    }
    
    atr_mult = atr_multipliers.get(grade, 1.5)
    stop_distance = atr * atr_mult
    
    if direction == "bull":
        # Stop below entry OR use OR low (whichever is closer)
        atr_stop = entry_price - stop_distance
        or_stop = or_low * 0.999  # Just below OR low
        
        stop_price = max(atr_stop, or_stop)  # Use the tighter stop
        
        print(f"[STOP] BULL {grade}: Entry ${entry_price:.2f}")
        print(f"  ATR stop: ${atr_stop:.2f} ({atr_mult}x ATR)")
        print(f"  OR stop: ${or_stop:.2f}")
        print(f"  → Using: ${stop_price:.2f}")
        
    else:  # Bear
        # Stop above entry OR use OR high (whichever is closer)
        atr_stop = entry_price + stop_distance
        or_stop = or_high * 1.001  # Just above OR high
        
        stop_price = min(atr_stop, or_stop)  # Use the tighter stop
        
        print(f"[STOP] BEAR {grade}: Entry ${entry_price:.2f}")
        print(f"  ATR stop: ${atr_stop:.2f} ({atr_mult}x ATR)")
        print(f"  OR stop: ${or_stop:.2f}")
        print(f"  → Using: ${stop_price:.2f}")
    
    return stop_price


def calculate_targets_by_grade(
    entry_price: float,
    stop_price: float,
    grade: str,
    direction: str
) -> Tuple[float, float]:
    """
    Calculate T1 and T2 targets based on risk
    
    CFW6 VIDEO RULES:
    - T1 = 2R for all grades
    - T2 = 3.5R for all grades
    """
    risk = abs(entry_price - stop_price)
    
    t1_distance = risk * 2.0  # 2R for all grades
    t2_distance = risk * 3.5  # 3.5R for all grades
    
    if direction == "bull":
        t1 = entry_price + t1_distance
        t2 = entry_price + t2_distance
    else:
        t1 = entry_price - t1_distance
        t2 = entry_price - t2_distance
    
    print(f"[TARGETS] {grade}: T1 = ${t1:.2f} (2R) | T2 = ${t2:.2f} (3.5R)")
    print(f"  Risk per contract: ${risk:.2f}")
    
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
    Main function to calculate stop loss and targets
    
    Returns: (stop_price, t1, t2)
    """
    # Calculate ATR for stop loss
    atr = calculate_atr(bars, period=14)
    
    # Calculate grade-based stop loss
    stop_price = calculate_stop_loss_by_grade(
        entry_price, grade, direction, or_low, or_high, atr
    )
    
    # Calculate targets
    t1, t2 = calculate_targets_by_grade(entry_price, stop_price, grade, direction)
    
    return stop_price, t1, t2


def get_next_1hour_target(bars: List[Dict], direction: str) -> float:
    """
    ADVANCED: Get next 1-hour high/low for T2 target
    (Optional - use only if you want dynamic T2 instead of fixed 3.5R)
    
    This is the method from the video for experienced traders
    """
    # Find 1-hour bars (aggregate 60x 1-minute bars)
    hour_bars = []
    
    for i in range(0, len(bars), 60):
        chunk = bars[i:i+60]
        if len(chunk) < 60:
            break
        
        hour_bar = {
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
        }
        hour_bars.append(hour_bar)
    
    if not hour_bars:
        return 0
    
    # Get the most recent 1-hour level
    if direction == "bull":
        # Next 1-hour high
        return hour_bars[-1]["high"] if hour_bars else 0
    else:
        # Next 1-hour low
        return hour_bars[-1]["low"] if hour_bars else 0
