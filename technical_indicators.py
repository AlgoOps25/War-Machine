"""
Technical Indicators Module
Uses EODHD server-side technical indicators API for RSI, MACD, SMA, EMA.

EODHD Technical Indicators API:
  GET https://eodhd.com/api/technical/{TICKER}.US?function=RSI&period=14
  
  Included in: All-World Extended / All-In-One plans
  
Supported Indicators:
  - RSI (Relative Strength Index)
  - MACD (Moving Average Convergence Divergence)
  - SMA (Simple Moving Average)
  - EMA (Exponential Moving Average)
  - STOCH (Stochastic Oscillator)
  - ATR (Average True Range)
  - BBANDS (Bollinger Bands)

Advantages over local calculation:
  - Server-side computation (zero CPU overhead)
  - Pre-calculated and cached by EODHD
  - Consistent with institutional data providers
  - No need to maintain historical bars for long lookback periods

Integration:
  - Called by signal_generator.py for RSI/MACD confirmation
  - Cached for 5 minutes to reduce API calls
"""
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import config

# Cache to avoid redundant API calls
_indicator_cache = {}  # {"ticker:function:params": {"timestamp": ..., "data": ...}}
_CACHE_TTL_MINUTES = 5


def _get_cache_key(ticker: str, function: str, **params) -> str:
    """Generate cache key from ticker, function, and parameters."""
    param_str = ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{ticker}:{function}:{param_str}"


def _is_cache_valid(cache_key: str) -> bool:
    """Check if cached indicator data is still fresh."""
    if cache_key not in _indicator_cache:
        return False
    
    cached_time = _indicator_cache[cache_key].get("timestamp")
    if not cached_time:
        return False
    
    age = datetime.now() - cached_time
    return age < timedelta(minutes=_CACHE_TTL_MINUTES)


def get_technical_indicator(
    ticker: str,
    function: str,
    period: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    **kwargs
) -> Optional[List[Dict]]:
    """
    Fetch technical indicator from EODHD API.
    
    Args:
        ticker: Stock symbol (e.g., "AAPL")
        function: Indicator name (e.g., "RSI", "MACD", "SMA", "EMA")
        period: Lookback period (e.g., 14 for RSI-14, 20 for SMA-20)
        from_date: Start date in YYYY-MM-DD format (optional)
        to_date: End date in YYYY-MM-DD format (optional)
        **kwargs: Additional parameters specific to the indicator
    
    Returns:
        List of indicator values:
        [{"date": "2026-02-22", "rsi": 45.32}, ...]
        
        Returns None if API error or no data available
    
    EODHD Docs:
        https://eodhd.com/financial-apis/technical-indicators-api
    """
    # Build cache key
    params = {"period": period, "from": from_date, "to": to_date, **kwargs}
    params = {k: v for k, v in params.items() if v is not None}  # Remove None values
    cache_key = _get_cache_key(ticker, function, **params)
    
    # Check cache
    if _is_cache_valid(cache_key):
        return _indicator_cache[cache_key]["data"]
    
    # Build API request
    url = f"https://eodhd.com/api/technical/{ticker}.US"
    api_params = {
        "api_token": config.EODHD_API_KEY,
        "function": function,
        "fmt": "json"
    }
    
    # Add optional parameters
    if period is not None:
        api_params["period"] = period
    if from_date:
        api_params["from"] = from_date
    if to_date:
        api_params["to"] = to_date
    
    # Add function-specific parameters
    for key, value in kwargs.items():
        api_params[key] = value
    
    try:
        response = requests.get(url, params=api_params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not isinstance(data, list):
            print(f"[INDICATORS] Unexpected response format for {ticker} {function}: {type(data)}")
            return None
        
        # Cache the results
        _indicator_cache[cache_key] = {
            "timestamp": datetime.now(),
            "data": data
        }
        
        return data
    
    except Exception as e:
        print(f"[INDICATORS] Error fetching {function} for {ticker}: {e}")
        return None


def get_rsi(ticker: str, period: int = 14, days: int = 30) -> Optional[float]:
    """
    Get current RSI (Relative Strength Index) value for a ticker.
    
    Args:
        ticker: Stock symbol
        period: RSI period (default 14)
        days: Number of days of historical data to fetch (default 30)
    
    Returns:
        Current RSI value (0-100) or None if error
    
    Example:
        rsi = get_rsi("AAPL", period=14)
        if rsi and rsi < 30:
            print("Oversold condition")
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    data = get_technical_indicator(
        ticker=ticker,
        function="rsi",
        period=period,
        from_date=from_date
    )
    
    if not data:
        return None
    
    # Return most recent RSI value
    latest = data[-1]
    return float(latest.get("rsi", 0)) if "rsi" in latest else None


def get_macd(
    ticker: str,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    days: int = 60
) -> Optional[Dict]:
    """
    Get current MACD values for a ticker.
    
    Args:
        ticker: Stock symbol
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line period (default 9)
        days: Number of days of historical data (default 60)
    
    Returns:
        Dict with MACD values or None if error:
        {
            "macd": 2.34,
            "signal": 1.89,
            "histogram": 0.45
        }
    
    Example:
        macd = get_macd("AAPL")
        if macd and macd["histogram"] > 0:
            print("Bullish momentum")
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    data = get_technical_indicator(
        ticker=ticker,
        function="macd",
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
        from_date=from_date
    )
    
    if not data:
        return None
    
    # Return most recent MACD values
    latest = data[-1]
    return {
        "macd": float(latest.get("macd", 0)),
        "signal": float(latest.get("signal", 0)),
        "histogram": float(latest.get("histogram", 0))
    } if "macd" in latest else None


def get_sma(ticker: str, period: int = 20, days: int = 60) -> Optional[float]:
    """
    Get current Simple Moving Average for a ticker.
    
    Args:
        ticker: Stock symbol
        period: SMA period (default 20)
        days: Number of days of historical data (default 60)
    
    Returns:
        Current SMA value or None if error
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    data = get_technical_indicator(
        ticker=ticker,
        function="sma",
        period=period,
        from_date=from_date
    )
    
    if not data:
        return None
    
    latest = data[-1]
    return float(latest.get("sma", 0)) if "sma" in latest else None


def get_ema(ticker: str, period: int = 20, days: int = 60) -> Optional[float]:
    """
    Get current Exponential Moving Average for a ticker.
    
    Args:
        ticker: Stock symbol
        period: EMA period (default 20)
        days: Number of days of historical data (default 60)
    
    Returns:
        Current EMA value or None if error
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    data = get_technical_indicator(
        ticker=ticker,
        function="ema",
        period=period,
        from_date=from_date
    )
    
    if not data:
        return None
    
    latest = data[-1]
    return float(latest.get("ema", 0)) if "ema" in latest else None


def check_rsi_confirmation(ticker: str, direction: str, rsi_oversold: int = 30, rsi_overbought: int = 70) -> bool:
    """
    Check if RSI confirms a trade direction.
    
    Args:
        ticker: Stock symbol
        direction: "bullish" or "bearish"
        rsi_oversold: RSI threshold for oversold (default 30)
        rsi_overbought: RSI threshold for overbought (default 70)
    
    Returns:
        True if RSI confirms the direction, False otherwise
    
    Logic:
        - Bullish: RSI should be recovering from oversold (30 < RSI < 50)
        - Bearish: RSI should be declining from overbought (50 < RSI < 70)
    """
    rsi = get_rsi(ticker, period=14)
    
    if rsi is None:
        return False  # No confirmation if data unavailable
    
    if direction.lower() == "bullish":
        # Bullish: RSI recovering from oversold, not yet overbought
        return rsi_oversold < rsi < 60
    
    elif direction.lower() == "bearish":
        # Bearish: RSI declining from overbought, not yet oversold
        return 40 < rsi < rsi_overbought
    
    return False


def check_macd_confirmation(ticker: str, direction: str) -> bool:
    """
    Check if MACD confirms a trade direction.
    
    Args:
        ticker: Stock symbol
        direction: "bullish" or "bearish"
    
    Returns:
        True if MACD confirms the direction, False otherwise
    
    Logic:
        - Bullish: MACD histogram positive (MACD line above signal line)
        - Bearish: MACD histogram negative (MACD line below signal line)
    """
    macd = get_macd(ticker)
    
    if not macd:
        return False
    
    histogram = macd.get("histogram", 0)
    
    if direction.lower() == "bullish":
        return histogram > 0  # MACD above signal line
    
    elif direction.lower() == "bearish":
        return histogram < 0  # MACD below signal line
    
    return False


def get_multi_indicator_score(ticker: str, direction: str) -> Dict:
    """
    Get comprehensive technical indicator score for a ticker.
    Used by signal_generator.py for additional confirmation.
    
    Args:
        ticker: Stock symbol
        direction: "bullish" or "bearish"
    
    Returns:
        Dict with indicator scores:
        {
            "rsi_confirmed": True/False,
            "macd_confirmed": True/False,
            "total_score": 0-2,  # Number of confirmations
            "details": {
                "rsi": 45.2,
                "macd_histogram": 0.23
            }
        }
    """
    rsi_confirmed = check_rsi_confirmation(ticker, direction)
    macd_confirmed = check_macd_confirmation(ticker, direction)
    
    rsi_value = get_rsi(ticker)
    macd_data = get_macd(ticker)
    
    return {
        "rsi_confirmed": rsi_confirmed,
        "macd_confirmed": macd_confirmed,
        "total_score": int(rsi_confirmed) + int(macd_confirmed),
        "details": {
            "rsi": rsi_value,
            "macd_histogram": macd_data.get("histogram") if macd_data else None
        }
    }


def clear_indicator_cache():
    """Clear indicator cache. Called at EOD in main.py."""
    global _indicator_cache
    _indicator_cache = {}
    print("[INDICATORS] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    total_entries = len(_indicator_cache)
    valid_entries = sum(1 for key in _indicator_cache if _is_cache_valid(key))
    
    return {
        "total_entries": total_entries,
        "valid_entries": valid_entries,
        "cache_ttl_minutes": _CACHE_TTL_MINUTES
    }
