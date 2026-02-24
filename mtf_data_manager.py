"""
Multi-Timeframe Data Manager

Fetches and caches market data across multiple timeframes (5m, 3m, 2m, 1m)
for simultaneous FVG detection and MTF convergence analysis.

Key Features:
  - Smart caching to minimize API calls
  - Timestamp synchronization across timeframes
  - Session-based cache management
  - Compatible with existing data_manager.py
  - Graceful degradation if timeframes unavailable

Usage:
  from mtf_data_manager import mtf_data_manager
  
  # Get single timeframe
  bars_5m = mtf_data_manager.get_bars('SPY', '5m')
  
  # Get all timeframes at once
  all_bars = mtf_data_manager.get_all_timeframes('SPY')
  # Returns: {'5m': [...], '3m': [...], '2m': [...], '1m': [...]}
  
  # Clear cache at EOD
  mtf_data_manager.clear_cache()
"""

from typing import Dict, List, Optional
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import requests
from collections import defaultdict

import config
from data_manager import data_manager  # Leverage existing data_manager for 5m

ET = ZoneInfo("America/New_York")


class MTFDataManager:
    """Multi-timeframe data fetching and caching."""
    
    def __init__(self):
        # Cache structure: {ticker: {timeframe: bars}}
        self.cache: Dict[str, Dict[str, List[dict]]] = defaultdict(dict)
        
        # Supported timeframes (in order of priority)
        self.timeframes = ['5m', '3m', '2m', '1m']
        
        # Session tracking for cache invalidation
        self.current_session_date = datetime.now(ET).date()
        
        # API endpoint (using existing EODHD from config)
        self.api_token = getattr(config, 'EODHD_API_TOKEN', '')
        self.base_url = 'https://eodhd.com/api/intraday'
        
        print("[MTF] Multi-Timeframe Data Manager initialized")
        print(f"[MTF] Supported timeframes: {', '.join(self.timeframes)}")
    
    def _check_session_rollover(self) -> bool:
        """
        Check if we've rolled over to a new trading session.
        Returns True if cache should be cleared.
        """
        today = datetime.now(ET).date()
        if today != self.current_session_date:
            print(f"[MTF] Session rollover detected: {self.current_session_date} → {today}")
            self.current_session_date = today
            return True
        return False
    
    def get_bars(self, ticker: str, timeframe: str, force_refresh: bool = False) -> List[dict]:
        """
        Get bars for a specific ticker and timeframe.
        
        Args:
            ticker: Stock symbol
            timeframe: '5m', '3m', '2m', or '1m'
            force_refresh: Bypass cache and fetch fresh data
        
        Returns:
            List of bar dicts with keys: datetime, open, high, low, close, volume
        """
        # Session rollover check
        if self._check_session_rollover():
            self.clear_cache()
        
        # Validate timeframe
        if timeframe not in self.timeframes:
            print(f"[MTF] Unsupported timeframe: {timeframe}")
            return []
        
        # Check cache first
        if not force_refresh and ticker in self.cache and timeframe in self.cache[ticker]:
            bars = self.cache[ticker][timeframe]
            if bars:  # Non-empty cache
                return bars
        
        # Special handling for 5m: use existing data_manager
        if timeframe == '5m':
            bars = self._get_5m_bars(ticker)
        else:
            # Fetch from API for other timeframes
            bars = self._fetch_from_api(ticker, timeframe)
        
        # Cache result
        if bars:
            self.cache[ticker][timeframe] = bars
        
        return bars
    
    def _get_5m_bars(self, ticker: str) -> List[dict]:
        """
        Get 5m bars using existing data_manager (already optimized).
        
        Args:
            ticker: Stock symbol
        
        Returns:
            List of 5m bars
        """
        try:
            # Leverage existing data_manager for 5m data
            data_manager.update_ticker(ticker)
            bars = data_manager.get_today_session_bars(ticker)
            
            if bars:
                print(f"[MTF] {ticker} 5m: {len(bars)} bars (from data_manager)")
            return bars
        
        except Exception as e:
            print(f"[MTF] Error fetching 5m bars for {ticker}: {e}")
            return []
    
    def _fetch_from_api(self, ticker: str, timeframe: str) -> List[dict]:
        """
        Fetch intraday bars from EODHD API for non-5m timeframes.
        
        Args:
            ticker: Stock symbol
            timeframe: '3m', '2m', or '1m'
        
        Returns:
            List of bars
        """
        try:
            # Convert timeframe format for API
            interval_map = {
                '3m': '3m',
                '2m': '2m',
                '1m': '1m'
            }
            
            interval = interval_map.get(timeframe)
            if not interval:
                return []
            
            # Build API URL
            url = f"{self.base_url}/{ticker}.US"
            params = {
                'api_token': self.api_token,
                'interval': interval,
                'fmt': 'json'
            }
            
            # Fetch data
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            raw_bars = response.json()
            if not raw_bars:
                print(f"[MTF] No data returned for {ticker} {timeframe}")
                return []
            
            # Parse and filter to today's session
            bars = self._parse_and_filter_bars(raw_bars, ticker, timeframe)
            
            if bars:
                print(f"[MTF] {ticker} {timeframe}: {len(bars)} bars (from API)")
            
            return bars
        
        except requests.exceptions.RequestException as e:
            print(f"[MTF] API request failed for {ticker} {timeframe}: {e}")
            return []
        except Exception as e:
            print(f"[MTF] Error fetching {ticker} {timeframe}: {e}")
            return []
    
    def _parse_and_filter_bars(self, raw_bars: List[dict], ticker: str, timeframe: str) -> List[dict]:
        """
        Parse API response and filter to today's session (9:30 AM - 4:00 PM ET).
        
        Args:
            raw_bars: Raw API response
            ticker: Stock symbol
            timeframe: Timeframe string
        
        Returns:
            Filtered and parsed bars
        """
        try:
            today = datetime.now(ET).date()
            session_start = time(9, 30)
            session_end = time(16, 0)
            
            parsed_bars = []
            
            for bar in raw_bars:
                # Parse timestamp
                timestamp = bar.get('datetime') or bar.get('timestamp')
                if not timestamp:
                    continue
                
                # Convert to datetime (handle both Unix timestamp and ISO format)
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp, tz=ET)
                else:
                    dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                    dt = dt.astimezone(ET)
                
                # Filter to today's session
                if dt.date() != today:
                    continue
                if not (session_start <= dt.time() < session_end):
                    continue
                
                # Build bar dict (normalize field names)
                parsed_bar = {
                    'datetime': dt,
                    'open': float(bar.get('open', 0)),
                    'high': float(bar.get('high', 0)),
                    'low': float(bar.get('low', 0)),
                    'close': float(bar.get('close', 0)),
                    'volume': int(bar.get('volume', 0))
                }
                
                parsed_bars.append(parsed_bar)
            
            # Sort by datetime
            parsed_bars.sort(key=lambda x: x['datetime'])
            
            return parsed_bars
        
        except Exception as e:
            print(f"[MTF] Error parsing bars for {ticker} {timeframe}: {e}")
            return []
    
    def get_all_timeframes(self, ticker: str, required_timeframes: Optional[List[str]] = None) -> Dict[str, List[dict]]:
        """
        Get bars for all timeframes simultaneously.
        
        Args:
            ticker: Stock symbol
            required_timeframes: Optional list of required timeframes (default: all supported)
        
        Returns:
            Dict mapping timeframe -> bars
            Example: {'5m': [...], '3m': [...], '2m': [...], '1m': [...]}
        """
        timeframes_to_fetch = required_timeframes or self.timeframes
        
        result = {}
        for tf in timeframes_to_fetch:
            bars = self.get_bars(ticker, tf)
            if bars:
                result[tf] = bars
        
        # Log summary
        available_tfs = ', '.join(result.keys())
        missing_tfs = ', '.join(set(timeframes_to_fetch) - set(result.keys()))
        
        print(f"[MTF] {ticker} timeframes available: {available_tfs}")
        if missing_tfs:
            print(f"[MTF] {ticker} timeframes missing: {missing_tfs}")
        
        return result
    
    def get_latest_price(self, ticker: str) -> Optional[float]:
        """
        Get latest price across all available timeframes (prefer 1m for recency).
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Latest close price or None
        """
        # Try timeframes in order of recency (1m -> 2m -> 3m -> 5m)
        for tf in ['1m', '2m', '3m', '5m']:
            bars = self.get_bars(ticker, tf)
            if bars:
                return bars[-1]['close']
        
        return None
    
    def clear_cache(self, ticker: Optional[str] = None, timeframe: Optional[str] = None):
        """
        Clear cached data.
        
        Args:
            ticker: Optional ticker to clear (if None, clear all tickers)
            timeframe: Optional timeframe to clear (if None, clear all timeframes)
        """
        if ticker and timeframe:
            # Clear specific ticker + timeframe
            if ticker in self.cache and timeframe in self.cache[ticker]:
                del self.cache[ticker][timeframe]
                print(f"[MTF] Cleared cache: {ticker} {timeframe}")
        elif ticker:
            # Clear all timeframes for ticker
            if ticker in self.cache:
                del self.cache[ticker]
                print(f"[MTF] Cleared cache: {ticker} (all timeframes)")
        else:
            # Clear entire cache
            self.cache.clear()
            print("[MTF] Cleared entire cache")
    
    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dict with cache size and hit info
        """
        total_tickers = len(self.cache)
        total_entries = sum(len(tfs) for tfs in self.cache.values())
        
        timeframe_counts = defaultdict(int)
        for ticker_cache in self.cache.values():
            for tf in ticker_cache.keys():
                timeframe_counts[tf] += 1
        
        return {
            'total_tickers': total_tickers,
            'total_entries': total_entries,
            'by_timeframe': dict(timeframe_counts),
            'session_date': str(self.current_session_date)
        }
    
    def print_cache_stats(self):
        """Print formatted cache statistics."""
        stats = self.get_cache_stats()
        print("\n" + "="*60)
        print("MTF DATA MANAGER - CACHE STATISTICS")
        print("="*60)
        print(f"Session Date:    {stats['session_date']}")
        print(f"Cached Tickers:  {stats['total_tickers']}")
        print(f"Total Entries:   {stats['total_entries']}")
        print("\nBy Timeframe:")
        for tf, count in sorted(stats['by_timeframe'].items()):
            print(f"  {tf:>3}: {count:>2} tickers")
        print("="*60 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

mtf_data_manager = MTFDataManager()


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING / CLI USAGE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mtf_data_manager.py <ticker> [timeframe]")
        print("Example: python mtf_data_manager.py SPY")
        print("Example: python mtf_data_manager.py SPY 3m")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
    if len(sys.argv) == 3:
        # Single timeframe test
        timeframe = sys.argv[2]
        print(f"\nFetching {ticker} {timeframe} bars...\n")
        bars = mtf_data_manager.get_bars(ticker, timeframe)
        
        if bars:
            print(f"\nReceived {len(bars)} bars:")
            print(f"First bar: {bars[0]['datetime']} | Close: ${bars[0]['close']:.2f}")
            print(f"Last bar:  {bars[-1]['datetime']} | Close: ${bars[-1]['close']:.2f}")
        else:
            print("No bars received")
    else:
        # All timeframes test
        print(f"\nFetching {ticker} across all timeframes...\n")
        all_bars = mtf_data_manager.get_all_timeframes(ticker)
        
        print("\n" + "="*60)
        print("RESULTS")
        print("="*60)
        for tf, bars in all_bars.items():
            if bars:
                print(f"{tf:>3}: {len(bars):>3} bars | "
                      f"Latest: ${bars[-1]['close']:>7.2f} @ {bars[-1]['datetime'].strftime('%I:%M %p')}")
        print("="*60)
        
        # Show cache stats
        mtf_data_manager.print_cache_stats()
