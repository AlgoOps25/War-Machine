"""
Technical Indicators Module - EODHD API Integration

Fetches pre-calculated technical indicators from EODHD API.
Includes aggressive caching to minimize API calls (each indicator = 5 API credits).

Supported Indicators:
  - ADX (Average Directional Index) - trend strength
  - Bollinger Bands - volatility and squeeze detection
  - Average Volume - volume confirmation
  - CCI (Commodity Channel Index) - momentum
  - DMI (Directional Movement Index) - trend direction
  - MACD - trend following
  - Parabolic SAR - trailing stops
  - Stochastic - momentum oscillator

Cache Strategy:
  - Pre-market (4:00-9:30): 5-minute TTL (slow-moving)
  - Market hours (9:30-16:00): 2-minute TTL (faster updates)
  - After hours: 10-minute TTL (minimal changes)
"""
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import config

ET = ZoneInfo("America/New_York")


# ══════════════════════════════════════════════════════════════════════════════
# CACHING LAYER
# ══════════════════════════════════════════════════════════════════════════════

class IndicatorCache:
    """Time-aware cache for technical indicators with adaptive TTL."""
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}  # {cache_key: {data, timestamp}}
    
    def _get_ttl_seconds(self) -> int:
        """Return TTL based on time of day."""
        now = datetime.now(ET).time()
        
        if dtime(4, 0) <= now < dtime(9, 30):
            return 300  # 5 minutes pre-market
        elif dtime(9, 30) <= now < dtime(16, 0):
            return 120  # 2 minutes during market hours
        else:
            return 600  # 10 minutes after hours
    
    def get(self, cache_key: str) -> Optional[Any]:
        """Get cached indicator if still valid."""
        if cache_key not in self.cache:
            return None
        
        entry = self.cache[cache_key]
        cache_time = entry['timestamp']
        age = (datetime.now(ET) - cache_time).total_seconds()
        
        if age > self._get_ttl_seconds():
            del self.cache[cache_key]
            return None
        
        return entry['data']
    
    def set(self, cache_key: str, data: Any):
        """Cache indicator data with timestamp."""
        self.cache[cache_key] = {
            'data': data,
            'timestamp': datetime.now(ET)
        }
    
    def clear(self):
        """Clear all cached indicators."""
        self.cache = {}
        print("[INDICATORS] Cache cleared")
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        now = datetime.now(ET)
        ttl = self._get_ttl_seconds()
        
        valid = sum(
            1 for entry in self.cache.values()
            if (now - entry['timestamp']).total_seconds() <= ttl
        )
        
        return {
            'total_entries': len(self.cache),
            'valid_entries': valid,
            'current_ttl': ttl
        }


# Global cache instance
_indicator_cache = IndicatorCache()


# ══════════════════════════════════════════════════════════════════════════════
# CORE FETCH FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_technical_indicator(
    ticker: str,
    function: str,
    use_cache: bool = True,
    **params
) -> Optional[List[Dict]]:
    """
    Fetch technical indicator from EODHD API.
    
    Args:
        ticker: Stock symbol (without .US suffix)
        function: Indicator name (adx, bbands, avgvol, etc.)
        use_cache: Use cached data if available (default: True)
        **params: Additional indicator parameters (period, etc.)
    
    Returns:
        List of indicator dicts with timestamps, or None on error.
        Data is returned in DESCENDING order (newest first) due to order=d param.
    
    Example:
        adx_data = fetch_technical_indicator('AAPL', 'adx', period=14)
        if adx_data:
            latest_adx = adx_data[0]['adx']  # First element is newest
    """
    # Build cache key
    param_str = '_'.join(f"{k}={v}" for k, v in sorted(params.items()))
    cache_key = f"{ticker}_{function}_{param_str}"
    
    # Check cache first
    if use_cache:
        cached = _indicator_cache.get(cache_key)
        if cached is not None:
            return cached
    
    # Fetch from EODHD API
    url = f"https://eodhd.com/api/technical/{ticker}.US"
    
    api_params = {
        'api_token': config.EODHD_API_KEY,
        'function': function,
        'fmt': 'json',
        'order': 'd',  # Descending (newest first)
        **params
    }
    
    try:
        response = requests.get(url, params=api_params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data or not isinstance(data, list):
            return None
        
        # Cache the result
        if use_cache:
            _indicator_cache.set(cache_key, data)
        
        return data
    
    except requests.exceptions.HTTPError as e:
        print(f"[INDICATORS] API error for {ticker} {function}: {e}")
        return None
    except Exception as e:
        print(f"[INDICATORS] Unexpected error for {ticker} {function}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPERS - Specific Indicators
# ══════════════════════════════════════════════════════════════════════════════

def fetch_adx(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch Average Directional Index (ADX) - trend strength indicator.
    
    Returns:
        List of dicts with keys: date, adx
        ADX values: 0-100 (>25 = trending, >40 = strong trend)
    """
    return fetch_technical_indicator(ticker, 'adx', use_cache=use_cache, period=period)


def fetch_bbands(ticker: str, period: int = 20, deviation: float = 2.0, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch Bollinger Bands - volatility indicator.
    
    Returns:
        List of dicts with keys: date, uband, mband, lband
    """
    return fetch_technical_indicator(
        ticker, 'bbands', use_cache=use_cache,
        period=period, deviation=deviation
    )


def fetch_avgvol(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch Average Volume - volume confirmation.
    
    Returns:
        List of dicts with keys: date, avgvol
    """
    return fetch_technical_indicator(ticker, 'avgvol', use_cache=use_cache, period=period)


def fetch_cci(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch Commodity Channel Index (CCI) - momentum oscillator.
    
    Returns:
        List of dicts with keys: date, cci
        CCI values: Typically -200 to +200 (>100 overbought, <-100 oversold)
    """
    return fetch_technical_indicator(ticker, 'cci', use_cache=use_cache, period=period)


def fetch_dmi(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch Directional Movement Index (DMI) - trend direction.
    
    Returns:
        List of dicts with keys: date, plus_di, minus_di
        plus_di > minus_di = bullish, minus_di > plus_di = bearish
    """
    return fetch_technical_indicator(ticker, 'dmi', use_cache=use_cache, period=period)


def fetch_macd(
    ticker: str,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """
    Fetch MACD (Moving Average Convergence Divergence).
    
    Returns:
        List of dicts with keys: date, macd, signal, histogram
    """
    return fetch_technical_indicator(
        ticker, 'macd', use_cache=use_cache,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period
    )


def fetch_sar(
    ticker: str,
    acceleration: float = 0.02,
    maximum: float = 0.20,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """
    Fetch Parabolic SAR - trailing stop and trend indicator.
    
    Returns:
        List of dicts with keys: date, sar
    """
    return fetch_technical_indicator(
        ticker, 'sar', use_cache=use_cache,
        acceleration=acceleration, maximum=maximum
    )


def fetch_stochastic(
    ticker: str,
    fast_kperiod: int = 14,
    slow_kperiod: int = 3,
    slow_dperiod: int = 3,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """
    Fetch Stochastic Oscillator - momentum indicator.
    
    Returns:
        List of dicts with keys: date, k, d
        Values 0-100 (>80 overbought, <20 oversold)
    """
    return fetch_technical_indicator(
        ticker, 'stochastic', use_cache=use_cache,
        fast_kperiod=fast_kperiod,
        slow_kperiod=slow_kperiod,
        slow_dperiod=slow_dperiod
    )


# ══════════════════════════════════════════════════════════════════════════════
# BATCH FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def batch_fetch_indicators(
    tickers: List[str],
    indicators: List[str],
    use_cache: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch multiple indicators for multiple tickers.
    
    Args:
        tickers: List of stock symbols
        indicators: List of indicator names ['adx', 'bbands', 'avgvol']
        use_cache: Use cached data when available
    
    Returns:
        {
            'AAPL': {'adx': [...], 'bbands': [...]},
            'TSLA': {'adx': [...], 'bbands': [...]}
        }
    """
    results = {}
    
    indicator_map = {
        'adx': fetch_adx,
        'bbands': fetch_bbands,
        'avgvol': fetch_avgvol,
        'cci': fetch_cci,
        'dmi': fetch_dmi,
        'macd': fetch_macd,
        'sar': fetch_sar,
        'stochastic': fetch_stochastic
    }
    
    for ticker in tickers:
        results[ticker] = {}
        
        for indicator_name in indicators:
            fetch_func = indicator_map.get(indicator_name)
            if not fetch_func:
                print(f"[INDICATORS] Unknown indicator: {indicator_name}")
                continue
            
            try:
                data = fetch_func(ticker, use_cache=use_cache)
                results[ticker][indicator_name] = data
            except Exception as e:
                print(f"[INDICATORS] Error fetching {indicator_name} for {ticker}: {e}")
                results[ticker][indicator_name] = None
    
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_value(indicator_data: Optional[List[Dict]], key: str) -> Optional[float]:
    """
    Extract latest value from indicator data.
    
    Args:
        indicator_data: List of indicator dicts from fetch functions (descending order)
        key: Key to extract (e.g., 'adx', 'cci', 'uband')
    
    Returns:
        Latest value as float, or None if data unavailable
        
    Note:
        EODHD returns data in descending order (newest first) due to order=d param,
        so we use index [0] to get the most recent value.
    """
    if not indicator_data or not isinstance(indicator_data, list):
        return None
    
    # Fix: EODHD returns descending order (newest first), so use [0] not [-1]
    latest = indicator_data[0]
    return float(latest.get(key, 0)) if latest.get(key) is not None else None


def check_bollinger_squeeze(ticker: str, threshold: float = 0.04) -> tuple[bool, Optional[float]]:
    """
    Check if ticker is in a Bollinger Band squeeze (low volatility).
    
    Args:
        ticker: Stock symbol
        threshold: Band width threshold (default 4% = potential breakout setup)
    
    Returns:
        (is_squeezed, band_width_pct)
    """
    bbands_data = fetch_bbands(ticker)
    if not bbands_data:
        return False, None
    
    latest = bbands_data[0]
    upper = latest.get('uband')
    lower = latest.get('lband')
    middle = latest.get('mband')
    
    if not all([upper, lower, middle]):
        return False, None
    
    band_width = (upper - lower) / middle
    is_squeezed = band_width < threshold
    
    return is_squeezed, round(band_width, 4)


def check_trend_strength(ticker: str, min_adx: float = 25.0) -> tuple[bool, Optional[float]]:
    """
    Check if ticker has sufficient trend strength.
    
    Args:
        ticker: Stock symbol
        min_adx: Minimum ADX value for valid trend (default 25)
    
    Returns:
        (is_trending, adx_value)
    """
    adx_data = fetch_adx(ticker)
    if not adx_data:
        return False, None
    
    latest_adx = get_latest_value(adx_data, 'adx')
    if latest_adx is None:
        return False, None
    
    is_trending = latest_adx >= min_adx
    return is_trending, round(latest_adx, 2)


def check_volume_confirmation(ticker: str, current_volume: int, min_ratio: float = 1.5) -> tuple[bool, Optional[float]]:
    """
    Check if current volume exceeds average volume.
    
    Args:
        ticker: Stock symbol
        current_volume: Current bar's volume
        min_ratio: Minimum volume ratio (default 1.5x average)
    
    Returns:
        (is_confirmed, volume_ratio)
    """
    avgvol_data = fetch_avgvol(ticker)
    if not avgvol_data:
        return False, None
    
    avg_volume = get_latest_value(avgvol_data, 'avgvol')
    if not avg_volume or avg_volume == 0:
        return False, None
    
    volume_ratio = current_volume / avg_volume
    is_confirmed = volume_ratio >= min_ratio
    
    return is_confirmed, round(volume_ratio, 2)


def get_trend_direction(ticker: str) -> Optional[str]:
    """
    Determine trend direction using DMI.
    
    Returns:
        'BULLISH', 'BEARISH', or None
    """
    dmi_data = fetch_dmi(ticker)
    if not dmi_data:
        return None
    
    latest = dmi_data[0]
    plus_di = latest.get('plus_di')
    minus_di = latest.get('minus_di')
    
    if plus_di is None or minus_di is None:
        return None
    
    if plus_di > minus_di:
        return 'BULLISH'
    elif minus_di > plus_di:
        return 'BEARISH'
    else:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CACHE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def clear_indicator_cache():
    """Clear all cached indicators. Call at EOD."""
    _indicator_cache.clear()


def get_cache_stats() -> Dict:
    """Get cache statistics for monitoring."""
    return _indicator_cache.get_stats()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test indicators
    test_ticker = "AAPL"
    
    print(f"Testing technical indicators for {test_ticker}...\n")
    
    # Test ADX
    print("=" * 60)
    print("ADX (Trend Strength)")
    print("=" * 60)
    is_trending, adx_value = check_trend_strength(test_ticker)
    if adx_value:
        status = "✅ TRENDING" if is_trending else "❌ WEAK TREND"
        print(f"{status} | ADX: {adx_value:.1f}")
    else:
        print("⚠️  ADX data unavailable")
    
    # Test Bollinger Bands
    print("\n" + "=" * 60)
    print("Bollinger Bands (Volatility Squeeze)")
    print("=" * 60)
    is_squeezed, band_width = check_bollinger_squeeze(test_ticker)
    if band_width:
        status = "🎯 SQUEEZE DETECTED" if is_squeezed else "📊 NORMAL VOLATILITY"
        print(f"{status} | Band Width: {band_width*100:.2f}%")
    else:
        print("⚠️  Bollinger Bands data unavailable")
    
    # Test DMI
    print("\n" + "=" * 60)
    print("DMI (Trend Direction)")
    print("=" * 60)
    direction = get_trend_direction(test_ticker)
    if direction:
        emoji = "🟢" if direction == 'BULLISH' else "🔴"
        print(f"{emoji} {direction}")
    else:
        print("⚠️  DMI data unavailable")
    
    # Cache stats
    print("\n" + "=" * 60)
    print("Cache Statistics")
    print("=" * 60)
    stats = get_cache_stats()
    print(f"Total entries: {stats['total_entries']}")
    print(f"Valid entries: {stats['valid_entries']}")
    print(f"Current TTL: {stats['current_ttl']}s")
