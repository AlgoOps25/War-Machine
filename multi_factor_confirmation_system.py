"""
Multi-Factor Confirmation System
All layers must align for A+ signal
"""

def check_vwap_alignment(bars: list, direction: str, current_price: float) -> bool:
    """Check if price is aligned with VWAP."""
    # Calculate VWAP
    vwap = calculate_vwap(bars)
    
    if direction == "bull":
        return current_price > vwap  # Price above VWAP for longs
    else:
        return current_price < vwap  # Price below VWAP for shorts


def check_previous_day_levels(ticker: str, current_price: float, direction: str) -> Dict:
    """Check proximity to PDH/PDL (Previous Day High/Low)."""
    prev_day_data = get_previous_day_ohlc(ticker)
    
    pdh = prev_day_data["high"]
    pdl = prev_day_data["low"]
    pdc = prev_day_data["close"]
    
    # Check if breaking above PDH (bull) or below PDL (bear)
    if direction == "bull":
        breaking_pdh = current_price > pdh
        return {
            "aligned": breaking_pdh,
            "level": "PDH",
            "level_price": pdh,
            "distance_pct": ((current_price - pdh) / pdh) * 100
        }
    else:
        breaking_pdl = current_price < pdl
        return {
            "aligned": breaking_pdl,
            "level": "PDL",
            "level_price": pdl,
            "distance_pct": ((pdl - current_price) / pdl) * 100
        }


def check_institutional_volume(bars: list, fvg_idx: int) -> bool:
    """Detect institutional block trades near FVG."""
    # Block trade = volume spike 3x+ average
    avg_volume = sum(b["volume"] for b in bars[-20:]) / 20
    
    # Check volume around FVG formation
    fvg_volume = bars[fvg_idx]["volume"]
    
    return fvg_volume >= avg_volume * 3


def check_options_flow(ticker: str, direction: str) -> Dict:
    """Check unusual options activity (calls vs puts)."""
    # Fetch options flow from EODHD
    flow_data = get_options_flow(ticker)
    
    call_volume = flow_data.get("call_volume", 0)
    put_volume = flow_data.get("put_volume", 0)
    
    total_volume = call_volume + put_volume
    if total_volume == 0:
        return {"aligned": False, "ratio": 0}
    
    call_put_ratio = call_volume / put_volume if put_volume > 0 else 999
    
    # For bull: want high call volume (ratio > 1.5)
    # For bear: want high put volume (ratio < 0.67)
    if direction == "bull":
        aligned = call_put_ratio > 1.5
    else:
        aligned = call_put_ratio < 0.67
    
    return {
        "aligned": aligned,
        "call_put_ratio": round(call_put_ratio, 2),
        "call_volume": call_volume,
        "put_volume": put_volume
    }


def grade_signal_with_confirmations(
    ticker: str,
    direction: str,
    bars: list,
    current_price: float,
    fvg_idx: int,
    base_grade: str
) -> Dict:
    """
    Apply all confirmation layers and upgrade/downgrade signal.
    
    Returns enhanced grade and confirmation details.
    """
    confirmations = {
        "vwap": check_vwap_alignment(bars, direction, current_price),
        "prev_day": check_previous_day_levels(ticker, current_price, direction),
        "institutional": check_institutional_volume(bars, fvg_idx),
        "options_flow": check_options_flow(ticker, direction)
    }
    
    # Count aligned confirmations
    aligned_count = sum([
        confirmations["vwap"],
        confirmations["prev_day"]["aligned"],
        confirmations["institutional"],
        confirmations["options_flow"]["aligned"]
    ])
    
    # Upgrade/downgrade logic
    final_grade = base_grade
    
    if aligned_count == 4:
        # Perfect alignment - upgrade
        if base_grade == "A":
            final_grade = "A+"
        elif base_grade == "A-":
            final_grade = "A"
    elif aligned_count <= 1:
        # Poor alignment - downgrade or reject
        if base_grade == "A+":
            final_grade = "A"
        elif base_grade == "A":
            final_grade = "A-"
        else:
            final_grade = "reject"
    
    return {
        "final_grade": final_grade,
        "base_grade": base_grade,
        "aligned_count": aligned_count,
        "confirmations": confirmations
    }
