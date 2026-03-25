"""
Volume-Based Technical Indicators

Calculates VWAP, MFI, and OBV directly from price/volume bars.
These are LOCAL calculations (not EODHD API) to maximize flexibility for backtesting.

Indicators:
  - VWAP (Volume-Weighted Average Price) - institutional fair value
  - MFI (Money Flow Index) - volume-weighted RSI
  - OBV (On-Balance Volume) - cumulative volume direction
  - Confluence scoring - all three indicators aligned

MOVED: app/analytics/volume_indicators.py → app/indicators/volume_indicators.py
"""

from typing import List, Dict, Optional, Tuple
import logging
logger = logging.getLogger(__name__)


def calculate_vwap(bars: List[Dict]) -> float:
    """
    Volume-Weighted Average Price - institutional average entry price.
    Used to detect if price is trading above/below fair value.
    
    Args:
        bars: List of price/volume bars with keys: high, low, close, volume
    
    Returns:
        VWAP value (float), or 0.0 if insufficient data
    """
    if not bars or len(bars) == 0:
        return 0.0
    
    total_tp_volume = 0.0
    total_volume = 0
    
    for bar in bars:
        typical_price = (bar['high'] + bar['low'] + bar['close']) / 3
        total_tp_volume += typical_price * bar['volume']
        total_volume += bar['volume']
    
    return total_tp_volume / total_volume if total_volume > 0 else bars[-1]['close']


def calculate_vwap_deviation(bars: List[Dict]) -> float:
    """
    Returns percentage deviation from VWAP.
    
    Positive = trading above VWAP (bullish)
    Negative = trading below VWAP (bearish)
    
    Args:
        bars: List of price/volume bars
    
    Returns:
        Percentage deviation (e.g., 2.5 = 2.5% above VWAP)
    """
    if not bars or len(bars) == 0:
        return 0.0
    
    vwap = calculate_vwap(bars)
    current_price = bars[-1]['close']
    
    return ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0.0


def calculate_mfi(bars: List[Dict], period: int = 14) -> float:
    """
    Money Flow Index - volume-weighted RSI.
    Measures buying/selling pressure with volume consideration.
    
    Args:
        bars: List of price/volume bars (must have at least period+1 bars)
        period: Lookback period (default 14)
    
    Returns:
        0-100 scale
        > 80 = overbought (potential reversal down)
        < 20 = oversold (potential reversal up)
        50 = neutral
    """
    if not bars or len(bars) < period + 1:
        return 50.0  # Neutral if insufficient data
    
    typical_prices = []
    money_flows = []
    
    for bar in bars:
        tp = (bar['high'] + bar['low'] + bar['close']) / 3
        typical_prices.append(tp)
        money_flows.append(tp * bar['volume'])
    
    positive_flow = 0.0
    negative_flow = 0.0
    
    # Calculate positive/negative flow over the period
    for i in range(len(typical_prices) - period, len(typical_prices)):
        if i < 1:
            continue
            
        if typical_prices[i] > typical_prices[i-1]:
            positive_flow += money_flows[i]
        elif typical_prices[i] < typical_prices[i-1]:
            negative_flow += money_flows[i]
    
    if negative_flow == 0:
        return 100.0
    
    money_ratio = positive_flow / negative_flow if negative_flow > 0 else 0
    mfi = 100 - (100 / (1 + money_ratio))
    
    return mfi


def calculate_obv(bars: List[Dict]) -> List[float]:
    """
    On-Balance Volume - cumulative volume direction indicator.
    Tracks smart money flow by adding volume on up days, subtracting on down days.
    
    Args:
        bars: List of price/volume bars
    
    Returns:
        List of OBV values (one per bar)
    """
    if not bars or len(bars) < 2:
        return [0.0]
    
    obv_values = [0.0]  # Start at 0
    current_obv = 0.0
    
    for i in range(1, len(bars)):
        if bars[i]['close'] > bars[i-1]['close']:
            current_obv += bars[i]['volume']
        elif bars[i]['close'] < bars[i-1]['close']:
            current_obv -= bars[i]['volume']
        # If equal, OBV unchanged
        
        obv_values.append(current_obv)
    
    return obv_values


def calculate_obv_trend(bars: List[Dict], lookback: int = 5) -> str:
    """
    Determines OBV trend direction over lookback period.
    
    Args:
        bars: List of price/volume bars
        lookback: Number of bars to analyze for trend (default 5)
    
    Returns:
        'bullish' - OBV rising (accumulation)
        'bearish' - OBV falling (distribution)
        'neutral' - OBV flat
    """
    if not bars or len(bars) < lookback + 1:
        return 'neutral'
    
    obv_values = calculate_obv(bars)
    recent_obv = obv_values[-lookback:]
    
    if len(recent_obv) < 2:
        return 'neutral'
    
    # Calculate trend: compare first half vs second half
    mid = len(recent_obv) // 2
    first_half_avg = sum(recent_obv[:mid]) / mid if mid > 0 else 0
    second_half_avg = sum(recent_obv[mid:]) / (len(recent_obv) - mid)
    
    change_pct = ((second_half_avg - first_half_avg) / abs(first_half_avg)) * 100 if first_half_avg != 0 else 0
    
    if change_pct > 5:
        return 'bullish'
    elif change_pct < -5:
        return 'bearish'
    else:
        return 'neutral'


def check_indicator_confluence(bars: List[Dict], direction: str = 'bullish') -> Dict:
    """
    Check if VWAP, MFI, and OBV all confirm the same direction.
    
    Args:
        bars: Price/volume bars
        direction: 'bullish' or 'bearish'
    
    Returns:
        Dict with:
          - confluence_score: 0.0-1.0 (0=none, 1.0=all three confirm)
          - signals: Individual indicator values and confirmations
    """
    if not bars or len(bars) < 14:
        return {'confluence_score': 0.0, 'signals': {}}
    
    # Calculate indicators
    vwap_dev = calculate_vwap_deviation(bars)
    mfi = calculate_mfi(bars, period=14)
    obv_trend = calculate_obv_trend(bars, lookback=5)
    
    signals = {
        'vwap_deviation': vwap_dev,
        'mfi': mfi,
        'obv_trend': obv_trend
    }
    
    # Check confluence for bullish signals
    if direction == 'bullish':
        vwap_bullish = vwap_dev > 0  # Price above VWAP
        mfi_bullish = 20 <= mfi <= 80  # Not overbought, ideally building
        obv_bullish = obv_trend == 'bullish'  # Accumulation
        
        signals['vwap_confirms'] = vwap_bullish
        signals['mfi_confirms'] = mfi_bullish
        signals['obv_confirms'] = obv_bullish
        
        # Count confirmations
        confirmations = sum([vwap_bullish, mfi_bullish, obv_bullish])
        confluence_score = confirmations / 3.0
    
    # Check confluence for bearish signals
    else:  # bearish
        vwap_bearish = vwap_dev < 0  # Price below VWAP
        mfi_bearish = 20 <= mfi <= 80  # Not oversold
        obv_bearish = obv_trend == 'bearish'  # Distribution
        
        signals['vwap_confirms'] = vwap_bearish
        signals['mfi_confirms'] = mfi_bearish
        signals['obv_confirms'] = obv_bearish
        
        confirmations = sum([vwap_bearish, mfi_bearish, obv_bearish])
        confluence_score = confirmations / 3.0
    
    return {
        'confluence_score': confluence_score,
        'signals': signals
    }


def validate_signal_with_volume_indicators(
    bars: List[Dict],
    signal_direction: str,
    params: Dict = None
) -> Tuple[bool, Dict]:
    """
    Validate a trading signal using VWAP, MFI, and OBV.
    
    Args:
        bars: Price/volume bars
        signal_direction: 'CALL' or 'PUT'
        params: Optional dict with thresholds:
          - vwap_min_deviation: Min % above/below VWAP (default 0.0)
          - mfi_overbought: MFI threshold for overbought (default 80)
          - mfi_oversold: MFI threshold for oversold (default 20)
          - obv_lookback: OBV trend lookback (default 5)
          - require_vwap_confirm: Must price be on correct side of VWAP? (default False)
          - require_mfi_confirm: Must MFI be in neutral zone? (default False)
          - require_obv_confirm: Must OBV trend match direction? (default False)
    
    Returns:
        (passes_validation, details_dict)
    """
    if params is None:
        params = {}
    
    # Default thresholds
    vwap_min_dev = params.get('vwap_min_deviation', 0.0)
    mfi_overbought = params.get('mfi_overbought', 80)
    mfi_oversold = params.get('mfi_oversold', 20)
    obv_lookback = params.get('obv_lookback', 5)
    require_vwap = params.get('require_vwap_confirm', False)
    require_mfi = params.get('require_mfi_confirm', False)
    require_obv = params.get('require_obv_confirm', False)
    
    # Calculate indicators
    vwap_dev = calculate_vwap_deviation(bars)
    mfi = calculate_mfi(bars, period=14)
    obv_trend = calculate_obv_trend(bars, lookback=obv_lookback)
    
    details = {
        'vwap_deviation': round(vwap_dev, 2),
        'mfi': round(mfi, 1),
        'obv_trend': obv_trend,
        'vwap_pass': True,
        'mfi_pass': True,
        'obv_pass': True
    }
    
    # VWAP validation
    if require_vwap:
        if signal_direction == 'CALL' and vwap_dev < vwap_min_dev:
            details['vwap_pass'] = False
            details['vwap_reason'] = f'Price only {vwap_dev:.1f}% above VWAP (need >{vwap_min_dev}%)'
        elif signal_direction == 'PUT' and vwap_dev > -vwap_min_dev:
            details['vwap_pass'] = False
            details['vwap_reason'] = f'Price only {vwap_dev:.1f}% below VWAP (need <-{vwap_min_dev}%)'
    
    # MFI validation
    if require_mfi:
        if signal_direction == 'CALL' and mfi > mfi_overbought:
            details['mfi_pass'] = False
            details['mfi_reason'] = f'MFI overbought at {mfi:.0f} (>{mfi_overbought})'
        elif signal_direction == 'PUT' and mfi < mfi_oversold:
            details['mfi_pass'] = False
            details['mfi_reason'] = f'MFI oversold at {mfi:.0f} (<{mfi_oversold})'
    
    # OBV validation
    if require_obv:
        if signal_direction == 'CALL' and obv_trend != 'bullish':
            details['obv_pass'] = False
            details['obv_reason'] = f'OBV trend is {obv_trend}, not bullish'
        elif signal_direction == 'PUT' and obv_trend != 'bearish':
            details['obv_pass'] = False
            details['obv_reason'] = f'OBV trend is {obv_trend}, not bearish'
    
    # Overall validation
    passes = details['vwap_pass'] and details['mfi_pass'] and details['obv_pass']
    
    return passes, details


if __name__ == "__main__":
    # Test with sample data
    test_bars = [
        {'high': 100, 'low': 98, 'close': 99, 'volume': 1000000},
        {'high': 101, 'low': 99, 'close': 100, 'volume': 1100000},
        {'high': 102, 'low': 100, 'close': 101, 'volume': 1200000},
        {'high': 103, 'low': 101, 'close': 102, 'volume': 1300000},
        {'high': 104, 'low': 102, 'close': 103, 'volume': 1400000},
    ]
    
    logger.info("Testing volume indicators...\n")
    
    vwap = calculate_vwap(test_bars)
    logger.info(f"VWAP: ${vwap:.2f}")
    
    vwap_dev = calculate_vwap_deviation(test_bars)
    logger.info(f"VWAP Deviation: {vwap_dev:.2f}%")
    
    mfi = calculate_mfi(test_bars, period=3)
    logger.info(f"MFI: {mfi:.1f}")
    
    obv_values = calculate_obv(test_bars)
    logger.info(f"OBV values: {obv_values}")
    
    obv_trend = calculate_obv_trend(test_bars, lookback=3)
    logger.info(f"OBV Trend: {obv_trend}")
    
    confluence = check_indicator_confluence(test_bars, direction='bullish')
    logger.info(f"\nConfluence Score: {confluence['confluence_score']:.0%}")
    logger.info(f"Signals: {confluence['signals']}")
