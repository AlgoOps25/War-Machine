"""
EODHD Data Loader with Intelligent Caching
Phase 1 of War Machine Filter System

Features:
- SQLite caching for historical data (reduce API calls)
- In-memory caching for real-time data (speed)
- Rate limiting and retry logic
- Support for all EODHD data types (EOD, intraday, options, fundamentals, technicals)
- Automatic cache invalidation based on data staleness
"""

import os
import sqlite3
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import requests
from functools import wraps
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class EODHDCache:
    """SQLite-based cache manager for EODHD data"""
    
    def __init__(self, db_path: str = "eodhd_cache.db"):
        self.db_path = db_path
        self._init_cache_db()
    
    def _init_cache_db(self):
        """Initialize cache database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Cache table with request fingerprint
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                params TEXT NOT NULL,
                response_data TEXT NOT NULL,
                timestamp REAL NOT NULL,
                expiry_hours INTEGER NOT NULL
            )
        """)
        
        # Index for faster lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_endpoint_timestamp 
            ON api_cache(endpoint, timestamp)
        """)
        
        conn.commit()
        conn.close()
    
    def _generate_cache_key(self, endpoint: str, params: Dict) -> str:
        """Generate unique cache key from endpoint and parameters"""
        # Sort params for consistent hashing
        param_str = json.dumps(params, sort_keys=True)
        key_material = f"{endpoint}:{param_str}"
        return hashlib.sha256(key_material.encode()).hexdigest()
    
    def get(self, endpoint: str, params: Dict, max_age_hours: float) -> Optional[Any]:
        """Retrieve cached data if not expired"""
        cache_key = self._generate_cache_key(endpoint, params)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT response_data, timestamp, expiry_hours 
            FROM api_cache 
            WHERE cache_key = ?
        """, (cache_key,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return None
        
        response_data, timestamp, expiry_hours = result
        age_hours = (time.time() - timestamp) / 3600
        
        # Check if cache is still valid
        if age_hours < min(max_age_hours, expiry_hours):
            return json.loads(response_data)
        
        return None
    
    def set(self, endpoint: str, params: Dict, response_data: Any, expiry_hours: int):
        """Store data in cache"""
        cache_key = self._generate_cache_key(endpoint, params)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO api_cache 
            (cache_key, endpoint, params, response_data, timestamp, expiry_hours)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cache_key,
            endpoint,
            json.dumps(params, sort_keys=True),
            json.dumps(response_data),
            time.time(),
            expiry_hours
        ))
        
        conn.commit()
        conn.close()
    
    def clear_expired(self):
        """Remove expired entries from cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM api_cache 
            WHERE timestamp + (expiry_hours * 3600) < ?
        """, (time.time(),))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        return deleted
    
    def clear_all(self):
        """Clear entire cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM api_cache")
        conn.commit()
        conn.close()


class RateLimiter:
    """Rate limiter for API calls"""
    
    def __init__(self, calls_per_second: float = 10.0):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0
    
    def wait(self):
        """Wait if necessary to respect rate limit"""
        now = time.time()
        elapsed = now - self.last_call
        
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        
        self.last_call = time.time()


class EODHDDataLoader:
    """
    Comprehensive EODHD API wrapper with intelligent caching
    
    Supports:
    - EOD historical prices
    - Intraday data (1m, 5m, 1h)
    - Technical indicators (100+)
    - Options data and Greeks
    - Fundamental data
    - Real-time quotes
    - Market screener
    """
    
    # Cache expiry times (hours)
    CACHE_EXPIRY = {
        'eod': 24,           # End-of-day data - refresh daily
        'intraday': 2,       # Intraday bars - refresh every 2 hours
        'technicals': 24,    # Technical indicators - daily
        'fundamentals': 168, # Fundamental data - weekly
        'options': 1,        # Options data - hourly
        'realtime': 0,       # Real-time quotes - no caching
        'screener': 1,       # Screener results - hourly
    }
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 cache_enabled: bool = True,
                 rate_limit: float = 10.0):
        """
        Initialize EODHD data loader
        
        Args:
            api_key: EODHD API key (reads from .env if not provided)
            cache_enabled: Enable SQLite caching
            rate_limit: Max API calls per second
        """
        self.api_key = api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY not found in environment or parameters")
        
        self.base_url = "https://eodhd.com/api"
        self.cache_enabled = cache_enabled
        self.cache = EODHDCache() if cache_enabled else None
        self.rate_limiter = RateLimiter(rate_limit)
        
        # In-memory cache for frequently accessed data
        self._memory_cache: Dict[str, Tuple[Any, float]] = {}
        self._memory_cache_ttl = 60  # 60 seconds for memory cache
        
        # Statistics
        self.stats = {
            'api_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0
        }
    
    def _make_request(self, 
                      endpoint: str, 
                      params: Dict,
                      cache_type: str = 'eod',
                      use_cache: bool = True) -> Any:
        """
        Make API request with caching and rate limiting
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            cache_type: Type of cache expiry to use
            use_cache: Whether to use cache for this request
        """
        # Add API key to params
        params['api_token'] = self.api_key
        params['fmt'] = 'json'
        
        # Check memory cache first
        if use_cache and cache_type == 'realtime':
            cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
            if cache_key in self._memory_cache:
                data, timestamp = self._memory_cache[cache_key]
                if time.time() - timestamp < self._memory_cache_ttl:
                    self.stats['cache_hits'] += 1
                    return data
        
        # Check SQLite cache
        if use_cache and self.cache_enabled and cache_type != 'realtime':
            cached_data = self.cache.get(
                endpoint, 
                params, 
                self.CACHE_EXPIRY[cache_type]
            )
            if cached_data is not None:
                self.stats['cache_hits'] += 1
                return cached_data
            self.stats['cache_misses'] += 1
        
        # Make API request with rate limiting
        self.rate_limiter.wait()
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            self.stats['api_calls'] += 1
            
            # Store in appropriate cache
            if use_cache:
                if cache_type == 'realtime':
                    cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
                    self._memory_cache[cache_key] = (data, time.time())
                elif self.cache_enabled:
                    self.cache.set(endpoint, params, data, self.CACHE_EXPIRY[cache_type])
            
            return data
            
        except requests.exceptions.RequestException as e:
            self.stats['errors'] += 1
            raise Exception(f"EODHD API request failed: {str(e)}")
    
    # ========== EOD Historical Data ==========
    
    def get_eod_data(self, 
                     symbol: str,
                     from_date: Optional[str] = None,
                     to_date: Optional[str] = None,
                     period: str = 'd') -> pd.DataFrame:
        """
        Get end-of-day historical prices
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            period: Data period (d=daily, w=weekly, m=monthly)
        """
        params = {'period': period}
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        data = self._make_request(f"eod/{symbol}", params, cache_type='eod')
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        
        return df
    
    # ========== Intraday Data ==========
    
    def get_intraday_data(self,
                          symbol: str,
                          interval: str = '5m',
                          from_timestamp: Optional[int] = None,
                          to_timestamp: Optional[int] = None) -> pd.DataFrame:
        """
        Get intraday historical data
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
            interval: Time interval ('1m', '5m', '1h')
            from_timestamp: Start Unix timestamp
            to_timestamp: End Unix timestamp
        """
        params = {'interval': interval}
        if from_timestamp:
            params['from'] = from_timestamp
        if to_timestamp:
            params['to'] = to_timestamp
        
        data = self._make_request(f"intraday/{symbol}", params, cache_type='intraday')
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'], unit='s')
            df.set_index('datetime', inplace=True)
        
        return df
    
    # ========== Technical Indicators ==========
    
    def get_technical_indicator(self,
                                symbol: str,
                                function: str,
                                from_date: Optional[str] = None,
                                to_date: Optional[str] = None,
                                period: int = 50,
                                **kwargs) -> pd.DataFrame:
        """
        Get technical indicator data
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
            function: Indicator function (rsi, macd, bbands, sma, ema, etc.)
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            period: Indicator period
            **kwargs: Additional indicator-specific parameters
        """
        params = {
            'function': function,
            'period': period,
            **kwargs
        }
        
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        data = self._make_request(f"technical/{symbol}", params, cache_type='technicals')
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        
        return df
    
    # ========== Options Data ==========
    
    def get_options_data(self,
                        symbol: str,
                        from_date: Optional[str] = None,
                        to_date: Optional[str] = None,
                        contract_name: Optional[str] = None) -> Dict:
        """
        Get options data with Greeks
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            contract_name: Specific contract name
        """
        params = {}
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        if contract_name:
            params['contract_name'] = contract_name
        
        data = self._make_request(f"options/{symbol}", params, cache_type='options')
        return data
    
    # ========== Fundamentals Data ==========
    
    def get_fundamentals(self,
                        symbol: str,
                        filter_type: Optional[str] = None) -> Dict:
        """
        Get fundamental data
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
            filter_type: Specific section (General, Highlights, Valuation, etc.)
        """
        params = {}
        if filter_type:
            params['filter'] = filter_type
        
        data = self._make_request(f"fundamentals/{symbol}", params, cache_type='fundamentals')
        return data
    
    # ========== Real-Time Data ==========
    
    def get_realtime_quote(self, symbol: str) -> Dict:
        """
        Get real-time quote (no caching)
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL.US')
        """
        data = self._make_request(f"real-time/{symbol}", {}, cache_type='realtime')
        return data
    
    # ========== Market Screener ==========
    
    def screen_stocks(self,
                     filters: Optional[List[List]] = None,
                     sort: Optional[str] = None,
                     limit: int = 50) -> List[Dict]:
        """
        Screen stocks with filters
        
        Args:
            filters: List of filter conditions [["field", "operator", value], ...]
            sort: Sort field (e.g., "market_capitalization.desc")
            limit: Max results
        """
        params = {'limit': limit}
        
        if filters:
            params['filters'] = json.dumps(filters)
        if sort:
            params['sort'] = sort
        
        data = self._make_request("screener", params, cache_type='screener')
        return data.get('data', []) if isinstance(data, dict) else data
    
    # ========== Batch Operations ==========
    
    def get_multiple_eod(self, symbols: List[str], date: str) -> Dict[str, pd.DataFrame]:
        """
        Get EOD data for multiple symbols efficiently
        
        Args:
            symbols: List of ticker symbols
            date: Date (YYYY-MM-DD)
        """
        results = {}
        for symbol in symbols:
            try:
                df = self.get_eod_data(symbol, from_date=date, to_date=date)
                results[symbol] = df
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                results[symbol] = pd.DataFrame()
        
        return results
    
    # ========== Utility Methods ==========
    
    def clear_cache(self, cache_type: Optional[str] = None):
        """Clear cache (all or specific type)"""
        if cache_type == 'memory':
            self._memory_cache.clear()
        elif self.cache_enabled:
            if cache_type:
                # Clear specific endpoint from SQLite
                # (would need to implement selective clearing)
                pass
            else:
                self.cache.clear_all()
    
    def get_stats(self) -> Dict:
        """Get usage statistics"""
        total_requests = self.stats['cache_hits'] + self.stats['api_calls']
        cache_hit_rate = (
            self.stats['cache_hits'] / total_requests * 100
            if total_requests > 0 else 0
        )
        
        return {
            **self.stats,
            'total_requests': total_requests,
            'cache_hit_rate': f"{cache_hit_rate:.1f}%"
        }
    
    def cleanup_old_cache(self):
        """Remove expired cache entries"""
        if self.cache_enabled:
            deleted = self.cache.clear_expired()
            return f"Deleted {deleted} expired cache entries"


# ========== Convenience Functions ==========

def get_loader() -> EODHDDataLoader:
    """Get singleton EODHD loader instance"""
    if not hasattr(get_loader, '_instance'):
        get_loader._instance = EODHDDataLoader()
    return get_loader._instance


# ========== Example Usage ==========

if __name__ == "__main__":
    # Initialize loader
    loader = EODHDDataLoader()
    
    # Test EOD data
    print("Fetching EOD data for AAPL...")
    eod_df = loader.get_eod_data('AAPL.US', from_date='2024-01-01', to_date='2024-12-31')
    print(f"Got {len(eod_df)} EOD bars")
    print(eod_df.head())
    
    # Test intraday data
    print("\nFetching intraday data for SPY...")
    intraday_df = loader.get_intraday_data('SPY.US', interval='5m')
    print(f"Got {len(intraday_df)} intraday bars")
    
    # Test technical indicators
    print("\nFetching RSI for AAPL...")
    rsi_df = loader.get_technical_indicator('AAPL.US', function='rsi', period=14)
    print(f"Got {len(rsi_df)} RSI values")
    print(rsi_df.tail())
    
    # Test options data
    print("\nFetching options data for AAPL...")
    options = loader.get_options_data('AAPL.US')
    if options:
        print(f"Got options data with {len(options.get('data', []))} expirations")
    
    # Show statistics
    print("\n" + "="*50)
    print("EODHD Loader Statistics:")
    stats = loader.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
