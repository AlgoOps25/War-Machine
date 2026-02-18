"""
CFW6 Confirmation Enhanced - Exact Video Rules
Implements the 3-tier candle confirmation ranking system:
1. A+ (BEST): Strong green candle, no wicks
2. A (GOOD): Red opens, flips to green (strong wick down)
3. A- (OK): Long wick rejection, stays red
"""
from typing import Dict, Tuple, List
from datetime import datetime

def analyze_confirmation_candle(
    candle: Dict,
    direction: str,
    zone_low: float,
    zone_high: float
) -> Tuple[str, str]:
    """
    CFW6 VIDEO RULES: Analyze retest candle quality
    
    Returns: (confirmation_type, grade)
    - confirmation_type: "perfect", "flip", "wick", "reject"
    - grade: "A+", "A", "A-", "reject"
    """
    open_price = candle["open"]
    close_price = candle["close"]
    high_price = candle["high"]
    low_price = candle["low"]
    
    body_size = abs(close_price - open_price)
    candle_range = high_price - low_price
    
    # Calculate wick sizes
    if close_price > open_price:  # Green candle
        upper_wick = high_price - close_price
        lower_wick = open_price - low_price
    else:  # Red candle
        upper_wick = high_price - open_price
        lower_wick = close_price - low_price
    
    if direction == "bull":
        # Check if candle touched FVG zone
        in_zone = low_price <= zone_high and low_price >= zone_low
        
        if not in_zone:
            return "reject", "reject"
        
        # TYPE 1 (A+): Strong green candle, minimal wicks
        if close_price > open_price:
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
            
            if wick_ratio < 0.15:  # Less than 15% wick
                print(f"[CONFIRM] ✅ TYPE 1 (A+): Perfect green candle - minimal wick ({wick_ratio*100:.1f}%)")
                return "perfect", "A+"
            
            # TYPE 2 (A): Opens red/neutral, flips to green (wick present)
            if wick_ratio >= 0.25:  # Significant lower wick
                print(f"[CONFIRM] ✅ TYPE 2 (A): Flip candle - strong lower wick ({wick_ratio*100:.1f}%)")
                return "flip", "A"
        
        # TYPE 3 (A-): Red candle with strong rejection wick
        elif close_price < open_price:
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
            
            if wick_ratio >= 0.50:  # Wick is 50%+ of candle
                print(f"[CONFIRM] ⚠️ TYPE 3 (A-): Wick rejection - didn't flip green ({wick_ratio*100:.1f}%)")
                return "wick", "A-"
        
        print(f"[CONFIRM] ❌ REJECT: No valid confirmation pattern")
        return "reject", "reject"
    
    else:  # Bear direction
        in_zone = high_price >= zone_low and high_price <= zone_high
        
        if not in_zone:
            return "reject", "reject"
        
        # TYPE 1 (A+): Strong red candle, minimal wicks
        if close_price < open_price:
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
            
            if wick_ratio < 0.15:
                print(f"[CONFIRM] ✅ TYPE 1 (A+): Perfect red candle - minimal wick ({wick_ratio*100:.1f}%)")
                return "perfect", "A+"
            
            # TYPE 2 (A): Opens green/neutral, flips to red (wick present)
            if wick_ratio >= 0.25:
                print(f"[CONFIRM] ✅ TYPE 2 (A): Flip candle - strong upper wick ({wick_ratio*100:.1f}%)")
                return "flip", "A"
        
        # TYPE 3 (A-): Green candle with strong rejection wick
        elif close_price > open_price:
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
            
            if wick_ratio >= 0.50:
                print(f"[CONFIRM] ⚠️ TYPE 3 (A-): Wick rejection - didn't flip red ({wick_ratio*100:.1f}%)")
                return "wick", "A-"
        
        print(f"[CONFIRM] ❌ REJECT: No valid confirmation pattern")
        return "reject", "reject"

def wait_for_confirmation_enhanced(
    bars: List[Dict],
    direction: str,
    fvg_zone: Tuple[float, float],
    start_idx: int,
    max_wait: int = 15
) -> Tuple[bool, float, str, int, str]:
    """
    CFW6 Enhanced confirmation wait - implements confidence decay
    
    Returns: (found, entry_price, grade, confirm_idx, confirmation_type)
    
    CRITICAL: Max wait reduced from 20 to 15 candles (video optimization)
    """
    zone_low, zone_high = fvg_zone
    
    print(f"[CFW6] Waiting for {direction.upper()} confirmation in zone ${zone_low:.2f}-${zone_high:.2f}")
    
    for i in range(start_idx, min(start_idx + max_wait, len(bars))):
        candle = bars[i]
        candles_waited = i - start_idx
        
        # Timeout after max_wait candles
        if candles_waited >= max_wait:
            print(f"[CFW6] ❌ TIMEOUT: No confirmation after {max_wait} candles")
            return False, 0, "reject", i, "timeout"
        
        # Check if candle interacts with FVG zone
        if direction == "bull":
            touches_zone = candle["low"] <= zone_high and candle["low"] >= zone_low
        else:
            touches_zone = candle["high"] >= zone_low and candle["high"] <= zone_high
        
        if touches_zone:
            confirmation_type, grade = analyze_confirmation_candle(candle, direction, zone_low, zone_high)
            
            if grade != "reject":
                entry_price = candle["close"]
                
                # Log confirmation details
                candle_time = candle.get("datetime", "N/A")
                print(f"[CFW6] ✅ CONFIRMED: {grade} setup at ${entry_price:.2f} (candle {candles_waited}, {candle_time})")
                
                return True, entry_price, grade, i, confirmation_type
    
    print(f"[CFW6] ❌ NO CONFIRMATION: Scanned {min(max_wait, len(bars)-start_idx)} candles")
    return False, 0, "reject", start_idx, "none"

def calculate_stop_loss_by_grade(
    entry_price: float,
    grade: str,
    direction: str,
    or_low: float,
    or_high: float,
    atr: float
) -> float:
    """
    Grade-based stop loss (HIGH PRIORITY OPTIMIZATION)
    
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
        
        print(f"[STOP] BULL {grade}: Entry ${entry_price:.2f} | ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} → Using ${stop_price:.2f}")
        
    else:  # Bear
        # Stop above entry OR use OR high (whichever is closer)
        atr_stop = entry_price + stop_distance
        or_stop = or_high * 1.001  # Just above OR high
        
        stop_price = min(atr_stop, or_stop)  # Use the tighter stop
        
        print(f"[STOP] BEAR {grade}: Entry ${entry_price:.2f} | ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} → Using ${stop_price:.2f}")
    
    return stop_price

def calculate_targets_by_grade(
    entry_price: float,
    stop_price: float,
    grade: str,
    direction: str
) -> Tuple[float, float]:
    """
    Calculate T1 and T2 targets based on grade
    
    All grades: T1 = 2R, T2 = 3.5R (from video)
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
    
    print(f"[TARGETS] {grade}: T1 = ${t1:.2f} (2R) | T2 = ${t2:.2f} (3.5R) | Risk = ${risk:.2f}")
    
    return t1, t2
