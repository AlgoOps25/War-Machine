"""
Adaptive Parameter System - CFW6 Enhanced
Dynamically adjusts FVG thresholds and breakout parameters based on volatility
"""
import numpy as np
from typing import List, Dict

def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range for volatility measurement."""
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

def get_adaptive_fvg_threshold(bars: List[Dict], ticker: str) -> float:
    """
    CFW6 RULE: FVG must form AFTER breakout
    
    Adaptive FVG size based on ticker volatility:
    - High volatility (ATR > 2.0): 0.3% minimum FVG
    - Medium volatility (ATR 1.0-2.0): 0.2% minimum FVG  
    - Low volatility (ATR < 1.0): 0.15% minimum FVG
    """
    atr = calculate_atr(bars, period=14)
    current_price = bars[-1]["close"]
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
    
    # Adaptive thresholds based on volatility
    if atr_pct > 2.0:
        fvg_threshold = 0.003  # 0.3% for high volatility
        confidence_adjustment = 0.95  # Slightly reduce confidence
    elif atr_pct > 1.0:
        fvg_threshold = 0.002  # 0.2% for medium volatility
        confidence_adjustment = 1.0   # Standard confidence
    else:
        fvg_threshold = 0.0015  # 0.15% for low volatility
        confidence_adjustment = 1.05  # Boost confidence for clean setups
    
    print(f"[ADAPTIVE] {ticker} ATR: {atr:.2f} ({atr_pct:.2f}%) → FVG threshold: {fvg_threshold*100:.2f}%")
    
    return fvg_threshold, confidence_adjustment

def get_adaptive_orb_threshold(bars: List[Dict], volume_multiplier: float) -> float:
    """
    CFW6 RULE: Break must be strong
    
    Volume-weighted ORB breakout confirmation:
    - High volume breakout (2x+ avg): 0.08% threshold (more aggressive)
    - Standard volume (1.5-2x avg): 0.10% threshold (default)
    - Low volume (<1.5x avg): 0.15% threshold (more conservative)
    """
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

def calculate_volume_multiplier(bars: List[Dict], breakout_idx: int) -> float:
    """Calculate volume multiplier at breakout candle."""
    if breakout_idx < 20 or len(bars) <= breakout_idx:
        return 1.0
    
    # Average volume of 20 candles before breakout
    avg_volume = np.mean([b["volume"] for b in bars[breakout_idx-20:breakout_idx]])
    
    # Breakout candle volume
    breakout_volume = bars[breakout_idx]["volume"]
    
    return breakout_volume / avg_volume if avg_volume > 0 else 1.0

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
        print(f"[DECAY] Waited {candles_waited} candles → Confidence reduced by {decay*100:.1f}% → {adjusted_confidence:.2f}")
    
    return max(adjusted_confidence, 0.50)  # Floor at 50% confidence
