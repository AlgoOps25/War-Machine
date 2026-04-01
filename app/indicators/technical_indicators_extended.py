"""
Extended Technical Indicators - Critical additions for optimization

Adds 4 essential indicators:
  - ATR      - Average True Range (volatility, stops, position sizing)
  - StochRSI - Stochastic RSI (ultra-sensitive momentum)
  - SLOPE    - Linear regression slope (trend angle/strength)
  - STDDEV   - Standard Deviation (volatility clustering)

These integrate with existing technical_indicators.py

MOVED: app/analytics/technical_indicators_extended.py -> app/indicators/technical_indicators_extended.py
IMPORT UPDATED: app.analytics.technical_indicators -> app.indicators.technical_indicators
"""

import logging
from typing import Dict, List, Optional, Tuple
from app.indicators.technical_indicators import (
    fetch_technical_indicator,
    get_latest_value,
    _indicator_cache
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# NEW INDICATOR FETCH FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════

def fetch_atr(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    ATR - Average True Range. Measures volatility (dollars per bar).
    
    Critical for:
    - Stop-loss placement (ATR * 2 = trailing stop)
    - Position sizing (risk / (ATR * 2) = shares)
    - Breakout validation (move > 1.5 * ATR = real breakout)
    
    Typical values:
    - Low volatility: ATR < 1% of price
    - Medium: 1-3% of price  
    - High: > 3% of price
    
    Returns:
        List of dicts with keys: date, atr
    """
    return fetch_technical_indicator(ticker, 'atr', use_cache=use_cache, period=period)


def fetch_stochrsi(
    ticker: str,
    period: int = 14,
    fast_kperiod: int = 3,
    fast_dperiod: int = 3,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """
    StochRSI - Stochastic of RSI. Ultra-sensitive momentum oscillator.
    
    Combines Stochastic + RSI for earlier signals:
    - Faster than regular Stochastic
    - More responsive than RSI alone
    - Best for short-term reversals
    
    Values: 0-1 (0-100 scale)
    - > 0.8 (80) = overbought
    - < 0.2 (20) = oversold
    
    Warning: Can whipsaw in choppy markets. Use with trend filter.
    
    Returns:
        List of dicts with keys: date, k, d
    """
    return fetch_technical_indicator(
        ticker, 'stochrsi', use_cache=use_cache,
        period=period, fast_kperiod=fast_kperiod, fast_dperiod=fast_dperiod
    )


def fetch_slope(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    SLOPE - Linear regression slope. Measures trend angle/strength.
    
    Positive slope = uptrend
    Negative slope = downtrend
    Magnitude = trend strength
    
    Use cases:
    - Filter for trending markets (|slope| > threshold)
    - Detect trend acceleration/deceleration
    - Combine with ADX for trend validation
    
    Interpretation:
    - Slope > 0.5 = strong uptrend
    - -0.5 < Slope < 0.5 = consolidation
    - Slope < -0.5 = strong downtrend
    
    Returns:
        List of dicts with keys: date, slope
    """
    return fetch_technical_indicator(ticker, 'slope', use_cache=use_cache, period=period)


def fetch_stddev(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    STDDEV - Standard Deviation. Statistical volatility measure.
    
    Measures price dispersion:
    - High STDDEV = volatile (wide swings)
    - Low STDDEV = stable (tight range)
    
    Use cases:
    - Volatility clustering detection
    - Position sizing (reduce size in high STDDEV)
    - Breakout setup (low STDDEV -> high STDDEV = expansion)
    
    Complements ATR:
    - ATR = range-based volatility
    - STDDEV = statistical volatility
    
    Returns:
        List of dicts with keys: date, stddev
    """
    return fetch_technical_indicator(ticker, 'stddev', use_cache=use_cache, period=period)


# ═════════════════════════════════════════════════════════════════════════
# ANALYSIS HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════

def get_atr_percentage(ticker: str, current_price: float, period: int = 14) -> Optional[float]:
    """
    Get ATR as percentage of current price.
    
    Useful for:
    - Position sizing: shares = risk_amount / (atr_pct * price / 100)
    - Stop placement: stop_distance = atr_pct
    - Volatility comparison across stocks
    
    Args:
        ticker: Stock symbol
        current_price: Current price
        period: ATR period (default 14)
    
    Returns:
        ATR as % of price (e.g., 2.5 = 2.5%)
    """
    atr_data = fetch_atr(ticker, period=period)
    if not atr_data:
        return None
    
    atr_value = get_latest_value(atr_data, 'atr')
    if not atr_value or current_price == 0:
        return None
    
    return round((atr_value / current_price) * 100, 2)


def calculate_atr_stop(
    entry_price: float,
    atr_value: float,
    multiplier: float = 2.0,
    direction: str = 'LONG'
) -> float:
    """
    Calculate ATR-based stop-loss.
    
    Args:
        entry_price: Entry price
        atr_value: ATR value (in dollars)
        multiplier: ATR multiplier (default 2.0)
        direction: 'LONG' or 'SHORT'
    
    Returns:
        Stop-loss price
    """
    stop_distance = atr_value * multiplier
    
    if direction == 'LONG':
        return round(entry_price - stop_distance, 2)
    else:  # SHORT
        return round(entry_price + stop_distance, 2)


def calculate_position_size(
    account_balance: float,
    risk_per_trade: float,
    entry_price: float,
    atr_value: float,
    atr_multiplier: float = 2.0
) -> int:
    """
    Calculate position size using ATR-based risk management.
    
    Args:
        account_balance: Total account value
        risk_per_trade: Risk % per trade (e.g., 0.01 = 1%)
        entry_price: Entry price
        atr_value: ATR value (dollars)
        atr_multiplier: Stop distance multiplier
    
    Returns:
        Number of shares to buy
    """
    risk_amount = account_balance * risk_per_trade
    stop_distance = atr_value * atr_multiplier
    
    if stop_distance == 0:
        return 0
    
    shares = int(risk_amount / stop_distance)
    return max(1, shares)  # At least 1 share


def validate_breakout_strength(
    ticker: str,
    move_size: float,
    min_atr_multiple: float = 1.5,
    atr_value: float = None,
) -> Tuple[bool, Optional[Dict]]:
    """
    Validate if price move is significant vs ATR.

    Real breakouts should move > 1.5 ATR to avoid false breaks.

    Args:
        ticker: Stock symbol
        move_size: Price move in dollars (e.g., high - breakout_level)
        min_atr_multiple: Minimum ATR multiplier (default 1.5)
        atr_value: Optional intraday ATR override. When provided, skips the
                   daily EODHD API fetch entirely. Pass BreakoutDetector.calculate_atr()
                   result here to avoid daily vs intraday timeframe mismatch.

    Returns:
        (is_strong_breakout, details_dict)
    """
    if atr_value is None:
        atr_data = fetch_atr(ticker)
        if not atr_data:
            return False, None
        atr_value = get_latest_value(atr_data, 'atr')
        if not atr_value:
            return False, None
    
    atr_multiples = move_size / atr_value if atr_value > 0 else 0
    is_strong = atr_multiples >= min_atr_multiple
    
    details = {
        'move_size': round(move_size, 2),
        'atr': round(atr_value, 2),
        'atr_multiples': round(atr_multiples, 2),
        'threshold': min_atr_multiple,
        'is_strong': is_strong
    }
    
    return is_strong, details


def check_stochrsi_signal(
    ticker: str,
    signal_direction: str,
    overbought: float = 0.8,
    oversold: float = 0.2
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Check StochRSI for reversal signals.
    
    Args:
        ticker: Stock symbol
        signal_direction: 'CALL' or 'PUT'
        overbought: Upper threshold (default 0.8)
        oversold: Lower threshold (default 0.2)
    
    Returns:
        (signal_zone, details_dict)
        signal_zone: 'FAVORABLE' | 'UNFAVORABLE' | 'NEUTRAL'
    """
    stochrsi_data = fetch_stochrsi(ticker)
    if not stochrsi_data:
        return None, None
    
    k_value = get_latest_value(stochrsi_data, 'k')
    d_value = get_latest_value(stochrsi_data, 'd')
    
    if k_value is None or d_value is None:
        return None, None
    
    details = {
        'k': round(k_value, 3),
        'd': round(d_value, 3)
    }
    
    if signal_direction == 'CALL':
        if k_value < oversold:
            return 'FAVORABLE', details  # Oversold, good for calls
        elif k_value > overbought:
            return 'UNFAVORABLE', details  # Overbought, avoid calls
    else:  # PUT
        if k_value > overbought:
            return 'FAVORABLE', details  # Overbought, good for puts
        elif k_value < oversold:
            return 'UNFAVORABLE', details  # Oversold, avoid puts
    
    return 'NEUTRAL', details


def check_trend_slope(
    ticker: str,
    min_slope: float = 0.3
) -> Tuple[Optional[str], Optional[float]]:
    """
    Check trend direction and strength via slope.
    
    Args:
        ticker: Stock symbol
        min_slope: Minimum absolute slope for trend (default 0.3)
    
    Returns:
        (trend_direction, slope_value)
        trend_direction: 'UPTREND' | 'DOWNTREND' | 'SIDEWAYS'
    """
    slope_data = fetch_slope(ticker)
    if not slope_data:
        return None, None
    
    slope_value = get_latest_value(slope_data, 'slope')
    if slope_value is None:
        return None, None
    
    if slope_value > min_slope:
        return 'UPTREND', round(slope_value, 3)
    elif slope_value < -min_slope:
        return 'DOWNTREND', round(slope_value, 3)
    else:
        return 'SIDEWAYS', round(slope_value, 3)


def check_volatility_regime(
    ticker: str,
    low_threshold: float = 0.5,
    high_threshold: float = 2.0,
    stddev_value: float = None,
    current_price: float = None,
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Classify volatility regime using STDDEV.

    Args:
        ticker: Stock symbol
        low_threshold: Low volatility cutoff (% of price)
        high_threshold: High volatility cutoff (% of price)
        stddev_value: Optional intraday STDDEV override (avoids daily API fetch).
        current_price: Optional price override (required when stddev_value provided).

    Returns:
        (regime, details_dict)
        regime: 'LOW_VOL' | 'MEDIUM_VOL' | 'HIGH_VOL'
    """
    try:
        if stddev_value is None or current_price is None:
            from app.data.data_manager import data_manager
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            if not bars:
                return None, None
            current_price = bars[0]['close']
            stddev_data = fetch_stddev(ticker)
            if not stddev_data:
                return None, None
            stddev_value = get_latest_value(stddev_data, 'stddev')
            if not stddev_value or current_price == 0:
                return None, None
        
        stddev_pct = (stddev_value / current_price) * 100
        
        details = {
            'stddev': round(stddev_value, 2),
            'stddev_pct': round(stddev_pct, 2),
            'price': round(current_price, 2)
        }
        
        if stddev_pct < low_threshold:
            return 'LOW_VOL', details
        elif stddev_pct > high_threshold:
            return 'HIGH_VOL', details
        else:
            return 'MEDIUM_VOL', details
    
    except Exception as e:
        return None, None


def check_volatility_expansion(
    ticker: str,
    expansion_threshold: float = 1.5
) -> Tuple[bool, Optional[Dict]]:
    """
    Detect volatility expansion (breakout setup).

    Compares current STDDEV to average of the 10 bars immediately prior.
    EODHD returns stddev_data newest-first (index 0 = today), so:
      - current  = stddev_data[0]
      - baseline = stddev_data[1:11]  (bars 1-10, i.e. prior 10 sessions)

    Expansion signals potential breakout.

    Args:
        ticker: Stock symbol
        expansion_threshold: Multiplier for expansion (default 1.5)

    Returns:
        (is_expanding, details_dict)
    """
    stddev_data = fetch_stddev(ticker, period=20)
    if not stddev_data or len(stddev_data) < 11:
        return False, None

    current_stddev = get_latest_value(stddev_data, 'stddev')
    if not current_stddev:
        return False, None

    # stddev_data is newest-first; [1:11] = the 10 sessions prior to today
    recent_stddevs = [d.get('stddev') for d in stddev_data[1:11] if d.get('stddev')]
    if not recent_stddevs:
        return False, None

    avg_stddev = sum(recent_stddevs) / len(recent_stddevs)

    expansion_ratio = current_stddev / avg_stddev if avg_stddev > 0 else 0
    is_expanding = expansion_ratio >= expansion_threshold

    details = {
        'current_stddev': round(current_stddev, 2),
        'avg_stddev': round(avg_stddev, 2),
        'expansion_ratio': round(expansion_ratio, 2),
        'threshold': expansion_threshold,
        'is_expanding': is_expanding
    }

    return is_expanding, details


# ═════════════════════════════════════════════════════════════════════════
# UPDATE BATCH FETCH TO INCLUDE NEW INDICATORS
# ═════════════════════════════════════════════════════════════════════════

EXTENDED_INDICATOR_MAP = {
    'atr': fetch_atr,
    'stochrsi': fetch_stochrsi,
    'slope': fetch_slope,
    'stddev': fetch_stddev,
}


if __name__ == "__main__":
    # Test new indicators
    test_ticker = "AAPL"
    test_price = 175.50
    
    logger.info(f"Testing extended indicators for {test_ticker}...\n")
    
    # ATR
    atr_pct = get_atr_percentage(test_ticker, test_price)
    logger.info(f"ATR: {atr_pct}% of price")
    
    if atr_pct:
        atr_value = test_price * (atr_pct / 100)
        stop_long = calculate_atr_stop(test_price, atr_value, 2.0, 'LONG')
        logger.info(f"  Long stop (2x ATR): ${stop_long:.2f}")
        
        position = calculate_position_size(10000, 0.01, test_price, atr_value, 2.0)
        logger.info(f"  Position size (1% risk): {position} shares")
    
    # StochRSI
    stochrsi_signal, stochrsi_details = check_stochrsi_signal(test_ticker, 'CALL')
    logger.info(f"\nStochRSI: {stochrsi_signal}")
    if stochrsi_details:
        logger.info(f"  K={stochrsi_details['k']:.3f}, D={stochrsi_details['d']:.3f}")
    
    # Slope
    trend, slope_val = check_trend_slope(test_ticker, min_slope=0.3)
    logger.info(f"\nSlope: {slope_val} -> {trend}")
    
    # STDDEV
    vol_regime, vol_details = check_volatility_regime(test_ticker)
    logger.info(f"\nVolatility Regime: {vol_regime}")
    if vol_details:
        logger.info(f"  STDDEV: {vol_details['stddev_pct']:.2f}% of price")
    
    # Expansion
    is_expanding, exp_details = check_volatility_expansion(test_ticker)
    logger.info(f"\nVolatility Expansion: {is_expanding}")
    if exp_details:
        logger.info(f"  Ratio: {exp_details['expansion_ratio']:.2f}x average")
