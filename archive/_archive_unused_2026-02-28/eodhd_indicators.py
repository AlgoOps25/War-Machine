#!/usr/bin/env python3
"""
EODHD Technical Indicators Module

Fetches technical indicators directly from EODHD API:
- RSI (Relative Strength Index)
- EMA (Exponential Moving Average)
- SMA (Simple Moving Average)
- MACD (Moving Average Convergence Divergence)
- ATR (Average True Range)
- Bollinger Bands
- Stochastic Oscillator
- ADX (Average Directional Index)
- Parabolic SAR
- CCI (Commodity Channel Index)

Cache-enabled for performance.
"""

import requests
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import config

ET = ZoneInfo("America/New_York")


class EODHDIndicators:
    """
    EODHD Technical Indicators API wrapper.
    
    All methods return list of dicts with datetime and indicator values.
    Results are cached per ticker/function/period to minimize API calls.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.EODHD_API_KEY
        self.cache = {}  # {cache_key: {"data": [], "timestamp": datetime}}
        self.cache_ttl = timedelta(minutes=15)  # Cache for 15 minutes
        self.rate_limit_delay = 0.5  # 500ms between API calls
        self.last_call_time = 0
    
    def _rate_limit(self):
        """Ensure minimum delay between API calls."""
        now = time.time()
        elapsed = now - self.last_call_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_call_time = time.time()
    
    def _get_cache_key(self, ticker: str, function: str, **kwargs) -> str:
        """Generate cache key from parameters."""
        params_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{ticker}_{function}_{params_str}"
    
    def _check_cache(self, cache_key: str) -> Optional[List[Dict]]:
        """Check if cached data is still valid."""
        if cache_key not in self.cache:
            return None
        
        cached = self.cache[cache_key]
        age = datetime.now() - cached["timestamp"]
        
        if age < self.cache_ttl:
            return cached["data"]
        
        # Expired
        del self.cache[cache_key]
        return None
    
    def _save_cache(self, cache_key: str, data: List[Dict]):
        """Save data to cache."""
        self.cache[cache_key] = {
            "data": data,
            "timestamp": datetime.now()
        }
    
    def _fetch_indicator(self, ticker: str, function: str, from_date: datetime, to_date: datetime, **params) -> List[Dict]:
        """
        Core EODHD indicator fetch.
        
        Args:
            ticker: Stock symbol (without .US suffix)
            function: Technical indicator function name
            from_date: Start date
            to_date: End date
            **params: Additional parameters (period, etc.)
        
        Returns:
            List of dicts with datetime and indicator values
        """
        cache_key = self._get_cache_key(ticker, function, from_ts=int(from_date.timestamp()), to_ts=int(to_date.timestamp()), **params)
        
        # Check cache
        cached = self._check_cache(cache_key)
        if cached is not None:
            return cached
        
        # Rate limit
        self._rate_limit()
        
        # Build request
        url = f"https://eodhd.com/api/technical/{ticker}.US"
        
        request_params = {
            "api_token": self.api_key,
            "function": function,
            "from": int(from_date.timestamp()),
            "to": int(to_date.timestamp()),
            "fmt": "json"
        }
        
        # Add additional params
        request_params.update(params)
        
        try:
            response = requests.get(url, params=request_params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return []
            
            # Parse response
            results = []
            for item in data:
                try:
                    dt = datetime.fromtimestamp(item["timestamp"], tz=ET).replace(tzinfo=None)
                    
                    # Build result dict with all available values
                    result = {"datetime": dt}
                    
                    # Add all numeric fields from response
                    for key, value in item.items():
                        if key != "timestamp" and value is not None:
                            try:
                                result[key] = float(value)
                            except (ValueError, TypeError):
                                pass
                    
                    results.append(result)
                
                except (KeyError, ValueError, TypeError) as e:
                    continue
            
            # Cache results
            self._save_cache(cache_key, results)
            
            return results
        
        except requests.exceptions.HTTPError as e:
            print(f"[EODHD] API Error for {ticker} {function}: {e}")
            return []
        except Exception as e:
            print(f"[EODHD] Unexpected error for {ticker} {function}: {e}")
            return []
    
    # =====================================================
    # MOMENTUM INDICATORS
    # =====================================================
    
    def fetch_rsi(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 14) -> List[Dict]:
        """
        Fetch RSI (Relative Strength Index).
        
        Returns:
            List of {"datetime": dt, "rsi": float}
        """
        return self._fetch_indicator(ticker, "rsi", from_date, to_date, period=period)
    
    def fetch_macd(self, ticker: str, from_date: datetime, to_date: datetime, 
                   fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> List[Dict]:
        """
        Fetch MACD (Moving Average Convergence Divergence).
        
        Returns:
            List of {"datetime": dt, "macd": float, "signal": float, "histogram": float}
        """
        return self._fetch_indicator(ticker, "macd", from_date, to_date, 
                                    fast_period=fast_period, slow_period=slow_period, signal_period=signal_period)
    
    def fetch_stoch(self, ticker: str, from_date: datetime, to_date: datetime, 
                    k_period: int = 14, d_period: int = 3) -> List[Dict]:
        """
        Fetch Stochastic Oscillator.
        
        Returns:
            List of {"datetime": dt, "k": float, "d": float}
        """
        return self._fetch_indicator(ticker, "stoch", from_date, to_date, 
                                    k_period=k_period, d_period=d_period)
    
    def fetch_cci(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 20) -> List[Dict]:
        """
        Fetch CCI (Commodity Channel Index).
        
        Returns:
            List of {"datetime": dt, "cci": float}
        """
        return self._fetch_indicator(ticker, "cci", from_date, to_date, period=period)
    
    # =====================================================
    # TREND INDICATORS
    # =====================================================
    
    def fetch_ema(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 20) -> List[Dict]:
        """
        Fetch EMA (Exponential Moving Average).
        
        Returns:
            List of {"datetime": dt, "ema": float}
        """
        return self._fetch_indicator(ticker, "ema", from_date, to_date, period=period)
    
    def fetch_sma(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 20) -> List[Dict]:
        """
        Fetch SMA (Simple Moving Average).
        
        Returns:
            List of {"datetime": dt, "sma": float}
        """
        return self._fetch_indicator(ticker, "sma", from_date, to_date, period=period)
    
    def fetch_adx(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 14) -> List[Dict]:
        """
        Fetch ADX (Average Directional Index) - Trend Strength.
        
        Returns:
            List of {"datetime": dt, "adx": float, "plus_di": float, "minus_di": float}
        """
        return self._fetch_indicator(ticker, "adx", from_date, to_date, period=period)
    
    def fetch_sar(self, ticker: str, from_date: datetime, to_date: datetime, 
                  acceleration: float = 0.02, maximum: float = 0.2) -> List[Dict]:
        """
        Fetch Parabolic SAR.
        
        Returns:
            List of {"datetime": dt, "sar": float}
        """
        return self._fetch_indicator(ticker, "sar", from_date, to_date, 
                                    acceleration=acceleration, maximum=maximum)
    
    # =====================================================
    # VOLATILITY INDICATORS
    # =====================================================
    
    def fetch_atr(self, ticker: str, from_date: datetime, to_date: datetime, period: int = 14) -> List[Dict]:
        """
        Fetch ATR (Average True Range).
        
        Returns:
            List of {"datetime": dt, "atr": float}
        """
        return self._fetch_indicator(ticker, "atr", from_date, to_date, period=period)
    
    def fetch_bbands(self, ticker: str, from_date: datetime, to_date: datetime, 
                     period: int = 20, deviation: float = 2.0) -> List[Dict]:
        """
        Fetch Bollinger Bands.
        
        Returns:
            List of {"datetime": dt, "upper": float, "middle": float, "lower": float}
        """
        return self._fetch_indicator(ticker, "bbands", from_date, to_date, 
                                    period=period, deviation=deviation)
    
    # =====================================================
    # VOLUME INDICATORS
    # =====================================================
    
    def fetch_obv(self, ticker: str, from_date: datetime, to_date: datetime) -> List[Dict]:
        """
        Fetch OBV (On Balance Volume).
        
        Returns:
            List of {"datetime": dt, "obv": float}
        """
        return self._fetch_indicator(ticker, "obv", from_date, to_date)
    
    def fetch_ad(self, ticker: str, from_date: datetime, to_date: datetime) -> List[Dict]:
        """
        Fetch A/D Line (Accumulation/Distribution).
        
        Returns:
            List of {"datetime": dt, "ad": float}
        """
        return self._fetch_indicator(ticker, "ad", from_date, to_date)
    
    # =====================================================
    # MULTI-INDICATOR BATCH FETCH
    # =====================================================
    
    def fetch_multi_indicators(self, ticker: str, from_date: datetime, to_date: datetime, 
                              indicators: List[str]) -> Dict[str, List[Dict]]:
        """
        Fetch multiple indicators at once.
        
        Args:
            ticker: Stock symbol
            from_date: Start date
            to_date: End date
            indicators: List of indicator names (e.g., ["rsi", "ema_9", "ema_21"])
        
        Returns:
            Dict mapping indicator name to list of values
        
        Example:
            results = fetcher.fetch_multi_indicators("SPY", start, end, ["rsi", "ema_9", "macd"])
            # results = {"rsi": [...], "ema_9": [...], "macd": [...]}
        """
        results = {}
        
        for indicator in indicators:
            # Parse indicator name and parameters
            parts = indicator.split("_")
            function = parts[0].lower()
            
            # Extract period if specified (e.g., "ema_9" -> period=9)
            period = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            
            # Fetch based on function type
            if function == "rsi":
                results[indicator] = self.fetch_rsi(ticker, from_date, to_date, period or 14)
            elif function == "ema":
                results[indicator] = self.fetch_ema(ticker, from_date, to_date, period or 20)
            elif function == "sma":
                results[indicator] = self.fetch_sma(ticker, from_date, to_date, period or 20)
            elif function == "macd":
                results[indicator] = self.fetch_macd(ticker, from_date, to_date)
            elif function == "atr":
                results[indicator] = self.fetch_atr(ticker, from_date, to_date, period or 14)
            elif function == "adx":
                results[indicator] = self.fetch_adx(ticker, from_date, to_date, period or 14)
            elif function == "bbands":
                results[indicator] = self.fetch_bbands(ticker, from_date, to_date, period or 20)
            elif function == "stoch":
                results[indicator] = self.fetch_stoch(ticker, from_date, to_date)
            elif function == "obv":
                results[indicator] = self.fetch_obv(ticker, from_date, to_date)
            else:
                print(f"[EODHD] Unknown indicator: {indicator}")
        
        return results
    
    def get_indicator_at_time(self, indicator_data: List[Dict], target_time: datetime) -> Optional[Dict]:
        """
        Get indicator value at specific datetime.
        
        Args:
            indicator_data: List of indicator dicts from fetch methods
            target_time: Datetime to lookup
        
        Returns:
            Indicator dict at that time, or None if not found
        """
        if not indicator_data:
            return None
        
        # Find closest match (within 5 minutes)
        closest = None
        min_diff = timedelta(minutes=5)
        
        for item in indicator_data:
            diff = abs(item["datetime"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest = item
        
        return closest
    
    def clear_cache(self):
        """Clear all cached indicator data."""
        self.cache = {}
        print("[EODHD] Cache cleared")


# =====================================================
# GLOBAL SINGLETON
# =====================================================
eodhd_indicators = EODHDIndicators()


# =====================================================
# CONVENIENCE FUNCTIONS
# =====================================================

def get_rsi(ticker: str, from_date: datetime, to_date: datetime, period: int = 14) -> List[Dict]:
    """Convenience function for RSI."""
    return eodhd_indicators.fetch_rsi(ticker, from_date, to_date, period)


def get_ema(ticker: str, from_date: datetime, to_date: datetime, period: int = 20) -> List[Dict]:
    """Convenience function for EMA."""
    return eodhd_indicators.fetch_ema(ticker, from_date, to_date, period)


def get_macd(ticker: str, from_date: datetime, to_date: datetime) -> List[Dict]:
    """Convenience function for MACD."""
    return eodhd_indicators.fetch_macd(ticker, from_date, to_date)


def get_multiple_indicators(ticker: str, from_date: datetime, to_date: datetime, 
                           indicators: List[str]) -> Dict[str, List[Dict]]:
    """Convenience function for multiple indicators."""
    return eodhd_indicators.fetch_multi_indicators(ticker, from_date, to_date, indicators)


if __name__ == "__main__":
    # Test the module
    print("Testing EODHD Indicators Module...")
    print()
    
    now = datetime.now(ET)
    start = now - timedelta(days=5)
    
    # Test RSI
    print("Fetching RSI for SPY...")
    rsi_data = get_rsi("SPY", start, now)
    if rsi_data:
        latest = rsi_data[-1]
        print(f"  Latest RSI: {latest.get('rsi', 'N/A'):.2f} at {latest['datetime']}")
    else:
        print("  No data")
    print()
    
    # Test multiple indicators
    print("Fetching multiple indicators for SPY...")
    indicators = get_multiple_indicators("SPY", start, now, ["rsi", "ema_9", "ema_21", "macd"])
    for name, data in indicators.items():
        if data:
            print(f"  {name}: {len(data)} data points")
    print()
    
    print("Test complete!")
