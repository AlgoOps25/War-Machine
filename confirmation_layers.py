"""
Multi-Factor Confirmation System
All layers must align for maximum signal quality
"""

import requests
from typing import Dict, List
import config


def calculate_vwap(bars: List[Dict]) -> float:
    """Calculate Volume-Weighted Average Price."""
    total_pv = sum(bar["close"] * bar["volume"] for bar in bars)
    total_volume = sum(bar["volume"] for bar in bars)
    
    return total_pv / total_volume if total_volume > 0 else 0


def check_vwap_alignment(bars: List[Dict], direction: str, current_price: float) -> bool:
    """Check if price is aligned with VWAP."""
    vwap = calculate_vwap(bars)
    
    if direction == "bull":
        return current_price > vwap
    else:
        return current_price < vwap


def get_previous_day_ohlc(ticker: str) -> Dict:
    """Fetch previous day's OHLC data."""
    from datetime import datetime, timedelta
    
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"https://eodhd.com/api/eod/{ticker}.US"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from": yesterday,
        "to": yesterday,
        "fmt": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data:
            return {
                "open": data[0]["open"],
                "high": data[0]["high"],
                "low": data[0]["low"],
                "close": data[0]["close"]
            }
    except Exception as e:
        print(f"[CONFIRM] Error fetching prev day data: {e}")
    
    return {"open": 0, "high": 0, "low": 0, "close": 0}


def check_previous_day_levels(ticker: str, current_price: float, direction: str) -> Dict:
    """Check proximity to PDH/PDL."""
    prev_day = get_previous_day_ohlc(ticker)
    
    pdh = prev_day["high"]
    pdl = prev_day["low"]
    
    if direction == "bull":
        breaking_pdh = current_price > pdh
        distance = ((current_price - pdh) / pdh) * 100 if pdh > 0 else 0
        
        return {
            "aligned": breaking_pdh,
            "level": "PDH",
            "level_price": pdh,
            "distance_pct": distance
        }
    else:
        breaking_pdl = current_price < pdl
        distance = ((pdl - current_price) / pdl) * 100 if pdl > 0 else 0
        
        return {
            "aligned": breaking_pdl,
            "level": "PDL",
            "level_price": pdl,
            "distance_pct": distance
        }


def check_institutional_volume(bars: List[Dict], breakout_idx: int) -> bool:
    """Detect institutional block trades near breakout."""
    if len(bars) < 20 or breakout_idx < 20:
        return False
    
    # Calculate average volume
    avg_volume = sum(b["volume"] for b in bars[breakout_idx-20:breakout_idx]) / 20
    
    # Check breakout candle volume
    breakout_volume = bars[breakout_idx]["volume"]
    
    # Block trade = 3x+ average volume
    return breakout_volume >= avg_volume * 3


def get_options_flow(ticker: str) -> Dict:
    """Fetch current day options flow data."""
    url = f"https://eodhd.com/api/options/{ticker}.US"
    params = {"api_token": config.EODHD_API_KEY}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        call_volume = 0
        put_volume = 0
        
        # Aggregate volumes from all strikes/expirations
        for expiry, chains in data.get("data", {}).items():
            for strike, call_data in chains.get("calls", {}).items():
                call_volume += call_data.get("volume", 0)
            for strike, put_data in chains.get("puts", {}).items():
                put_volume += put_data.get("volume", 0)
        
        return {
            "call_volume": call_volume,
            "put_volume": put_volume
        }
    
    except Exception as e:
        print(f"[CONFIRM] Options flow error: {e}")
        return {"call_volume": 0, "put_volume": 0}


def check_options_flow(ticker: str, direction: str) -> Dict:
    """Check if options flow aligns with signal direction."""
    flow = get_options_flow(ticker)
    
    call_volume = flow["call_volume"]
    put_volume = flow["put_volume"]
    
    if call_volume == 0 and put_volume == 0:
        return {"aligned": False, "ratio": 0, "call_volume": 0, "put_volume": 0}
    
    call_put_ratio = call_volume / put_volume if put_volume > 0 else 999
    
    if direction == "bull":
        aligned = call_put_ratio > 1.5  # Heavy call buying
    else:
        aligned = call_put_ratio < 0.67  # Heavy put buying
    
    return {
        "aligned": aligned,
        "call_put_ratio": round(call_put_ratio, 2),
        "call_volume": call_volume,
        "put_volume": put_volume
    }


def grade_signal_with_confirmations(
    ticker: str,
    direction: str,
    bars: List[Dict],
    current_price: float,
    breakout_idx: int,
    base_grade: str
) -> Dict:
    """
    Apply all confirmation layers and enhance grade.
    
    Returns upgraded/downgraded grade based on confirmations.
    """
    print(f"[CONFIRM] Checking confirmation layers for {ticker}...")
    
    confirmations = {
        "vwap": check_vwap_alignment(bars, direction, current_price),
        "prev_day": check_previous_day_levels(ticker, current_price, direction),
        "institutional": check_institutional_volume(bars, breakout_idx),
        "options_flow": check_options_flow(ticker, direction)
    }
    
    # Count aligned confirmations
    aligned = [
        confirmations["vwap"],
        confirmations["prev_day"]["aligned"],
        confirmations["institutional"],
        confirmations["options_flow"]["aligned"]
    ]
    
    aligned_count = sum(aligned)
    
    print(f"[CONFIRM] Aligned: {aligned_count}/4")
    print(f"  VWAP: {'✅' if confirmations['vwap'] else '❌'}")
    print(f"  Prev Day: {'✅' if confirmations['prev_day']['aligned'] else '❌'}")
    print(f"  Institutional: {'✅' if confirmations['institutional'] else '❌'}")
    print(f"  Options Flow: {'✅' if confirmations['options_flow']['aligned'] else '❌'}")
    
    # Grade adjustment logic
    final_grade = base_grade
    
    if aligned_count == 4:
        # Perfect alignment - upgrade
        if base_grade == "A":
            final_grade = "A+"
        elif base_grade == "A-":
            final_grade = "A"
        print(f"[CONFIRM] ⬆️ Upgraded {base_grade} → {final_grade} (perfect alignment)")
    
    elif aligned_count <= 1:
        # Poor alignment - downgrade or reject
        if base_grade == "A+":
            final_grade = "A"
        elif base_grade == "A":
            final_grade = "A-"
        else:
            final_grade = "reject"
        print(f"[CONFIRM] ⬇️ Downgraded {base_grade} → {final_grade} (poor alignment)")
    
    else:
        print(f"[CONFIRM] Grade maintained: {final_grade}")
    
    return {
        "final_grade": final_grade,
        "base_grade": base_grade,
        "aligned_count": aligned_count,
        "confirmations": confirmations
    }
