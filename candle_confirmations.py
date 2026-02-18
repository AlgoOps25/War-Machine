"""
CFW6-style candle confirmation patterns for FVG retest entries.
Implements the 3-tier confirmation system: A+, A, A-
"""

def analyze_confirmation_candle(candle: dict, direction: str, fvg_zone: tuple) -> tuple:
    """
    Analyze if a candle provides valid confirmation for entry.
    
    Args:
        candle: dict with 'open', 'high', 'low', 'close'
        direction: "bull" or "bear"
        fvg_zone: (zone_low, zone_high)
    
    Returns:
        (is_valid: bool, grade: str, pattern_type: int)
        - grade: "A+", "A", "A-", or "reject"
        - pattern_type: 1, 2, 3, or 0 (invalid)
    """
    zone_low, zone_high = fvg_zone
    open_price = candle["open"]
    close_price = candle["close"]
    high = candle["high"]
    low = candle["low"]
    
    # Check if candle touched the FVG zone
    touched_zone = (low <= zone_high and high >= zone_low)
    if not touched_zone:
        return False, "reject", 0
    
    body = abs(close_price - open_price)
    total_range = high - low
    
    # Avoid division by zero
    if total_range == 0:
        return False, "reject", 0
    
    if direction == "bull":
        is_green = close_price > open_price
        lower_wick = open_price - low if is_green else close_price - low
        upper_wick = high - close_price if is_green else high - open_price
        
        # Pattern 1: Strong green candle, minimal wicks (A+)
        if is_green and body >= total_range * 0.80:
            print(f"[CONFIRM] Pattern 1 (A+): Strong green candle")
            return True, "A+", 1
        
        # Pattern 2: Red-to-green flip with long lower wick (A)
        if is_green and lower_wick >= body * 0.5:
            print(f"[CONFIRM] Pattern 2 (A): Red-to-green flip")
            return True, "A", 2
        
        # Pattern 3: Strong rejection wick but stays red (A-)
        if not is_green and lower_wick >= total_range * 0.60:
            print(f"[CONFIRM] Pattern 3 (A-): Rejection wick")
            return True, "A-", 3
            
    elif direction == "bear":
        is_red = close_price < open_price
        upper_wick = high - open_price if is_red else high - close_price
        lower_wick = close_price - low if is_red else open_price - low
        
        # Pattern 1: Strong red candle, minimal wicks (A+)
        if is_red and body >= total_range * 0.80:
            print(f"[CONFIRM] Pattern 1 (A+): Strong red candle")
            return True, "A+", 1
        
        # Pattern 2: Green-to-red flip with long upper wick (A)
        if is_red and upper_wick >= body * 0.5:
            print(f"[CONFIRM] Pattern 2 (A): Green-to-red flip")
            return True, "A", 2
        
        # Pattern 3: Strong rejection wick but stays green (A-)
        if not is_red and upper_wick >= total_range * 0.60:
            print(f"[CONFIRM] Pattern 3 (A-): Rejection wick")
            return True, "A-", 3
    
    return False, "reject", 0


def wait_for_confirmation(bars: list, direction: str, fvg_zone: tuple, 
                         start_idx: int, max_wait_candles: int = 20) -> tuple:
    """
    Wait for valid confirmation candle after FVG forms.
    
    Returns:
        (found: bool, entry_price: float, grade: str, candle_idx: int)
    """
    zone_low, zone_high = fvg_zone
    
    print(f"[CONFIRM] Waiting for confirmation in FVG zone: ${zone_low:.2f} - ${zone_high:.2f}")
    
    for i in range(start_idx, min(start_idx + max_wait_candles, len(bars))):
        candle = bars[i]
        
        # Check if price is testing the FVG zone
        if direction == "bull":
            in_zone = candle["low"] <= zone_high and candle["low"] >= zone_low
        else:
            in_zone = candle["high"] >= zone_low and candle["high"] <= zone_high
        
        if in_zone:
            is_valid, grade, pattern = analyze_confirmation_candle(candle, direction, fvg_zone)
            
            if is_valid:
                entry_price = candle["close"]
                print(f"✅ [CONFIRM] {grade} confirmation (Pattern {pattern}) at ${entry_price:.2f}")
                return True, entry_price, grade, i
    
    print(f"[CONFIRM] No valid confirmation found")
    return False, 0, "reject", -1
