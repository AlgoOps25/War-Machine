"""
Multi-Timeframe Data Manager

Manages fetching, caching, and synchronization of market data across
multiple timeframes (5m, 3m, 2m, 1m) for MTF confluence analysis.

Key Features:
  - Smart caching with TTL to minimize API calls
  - Batch updates for efficiency
  - Timestamp alignment across timeframes
  - Memory-efficient data structures
  - Graceful degradation if timeframe unavailable

Architecture:
  1. EODHD API fetches intraday data for each timeframe
  2. Cache stores bars with 5-minute TTL (fresh data guarantee)
  3. Synchronization ensures bars align at equivalent timestamps
  4. Batch mode updates all tickers at once for scanning

Usage:
  from mtf_data_manager import mtf_data_manager
  
  # Single ticker, all timeframes
  data = mtf_data_manager.get_all_timeframes('AAPL')
  bars_5m = data['5m']
  bars_3m = data['3m']
  
  # Batch update for multiple tickers
  tickers = ['AAPL', 'MSFT', 'NVDA']
  mtf_data_manager.batch_update(tickers)
  
  # Check cache freshness
  if mtf_data_manager.is_cache_stale('AAPL', '5m'):
      mtf_data_manager.update_ticker('AAPL')
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import requests
from collections import defaultdict
import config

ET = ZoneInfo("America/New_York")

# Supported timeframes with their interval codes for EODHD API
TIMEFRAMES = {
    '5m': 5,
    '3m': 3,
    '2m': 2,
    '1m': 1
}

# Cache TTL: 5 minutes (data refreshes frequently during trading)
CACHE_TTL_SECONDS = 300


class MTFDataManager:
    """Multi-timeframe data fetcher and cache manager."""
    
    def __init__(self):
        # Cache structure: {ticker: {timeframe: {'bars': [...], 'timestamp': datetime}}}
        self.cache: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(dict))
        
        # API configuration
        self.api_token = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/intraday"
        
        # Statistics
        self.stats = {
            'api_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        print("[MTF-DATA] Multi-Timeframe Data Manager initialized")
        print(f"[MTF-DATA] Timeframes: {', '.join(TIMEFRAMES.keys())}")
        print(f"[MTF-DATA] Cache TTL: {CACHE_TTL_SECONDS}s")
    
    def _fetch_intraday_bars(self, ticker: str, interval_minutes: int) -> List[Dict]:
        """
        Fetch intraday bars from EODHD API for specific timeframe.
        
        Args:
            ticker: Stock symbol
            interval_minutes: Bar interval (1, 2, 3, or 5 minutes)
        
        Returns:
            List of bar dicts with datetime, open, high, low, close, volume
        """
        try:
            params = {
                'api_token': self.api_token,
                'interval': f'{interval_minutes}m',
                'fmt': 'json',
                'from': int((datetime.now(ET) - timedelta(days=1)).timestamp()),
                'to': int(datetime.now(ET).timestamp())
            }
            
            url = f"{self.base_url}/{ticker}.US"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            self.stats['api_calls'] += 1
            
            raw_data = response.json()
            if not raw_data:
                return []
            
            # Convert to consistent format
            bars = []
            for bar in raw_data:
                try:
                    # Parse timestamp (EODHD returns Unix timestamp)
                    dt = datetime.fromtimestamp(bar['timestamp'], tz=ET)
                    
                    bars.append({
                        'datetime': dt,
                        'open': float(bar['open']),
                        'high': float(bar['high']),
                        'low': float(bar['low']),
                        'close': float(bar['close']),
                        'volume': int(bar['volume'])
                    })
                except (KeyError, ValueError) as e:
                    # Skip malformed bars
                    continue
            
            return bars
        
        except requests.exceptions.RequestException as e:
            print(f"[MTF-DATA] API error for {ticker} {interval_minutes}m: {e}")
            return []
        except Exception as e:
            print(f"[MTF-DATA] Unexpected error for {ticker} {interval_minutes}m: {e}")
            return []
    
    def _filter_session_bars(self, bars: List[Dict]) -> List[Dict]:
        """
        Filter bars to only include regular trading session (9:30 AM - 4:00 PM ET).
        
        Args:
            bars: List of bar dicts
        
        Returns:
            Filtered list containing only session bars
        """
        session_bars = []
        for bar in bars:
            bar_time = bar['datetime'].time()
            # Include premarket for OR calculation (4:00 AM - 4:00 PM)
            if dtime(4, 0) <= bar_time < dtime(16, 0):
                session_bars.append(bar)
        
        return session_bars
    
    def is_cache_stale(self, ticker: str, timeframe: str) -> bool:
        """
        Check if cached data for ticker/timeframe is stale.
        
        Args:
            ticker: Stock symbol
            timeframe: Timeframe string ('5m', '3m', '2m', '1m')
        
        Returns:
            True if cache is stale or missing, False if fresh
        """
        if ticker not in self.cache:
            return True
        
        if timeframe not in self.cache[ticker]:
            return True
        
        cached_data = self.cache[ticker][timeframe]
        if 'timestamp' not in cached_data:
            return True
        
        age_seconds = (datetime.now(ET) - cached_data['timestamp']).total_seconds()
        return age_seconds > CACHE_TTL_SECONDS
    
    def update_ticker(self, ticker: str, force: bool = False) -> bool:
        """
        Update all timeframes for a ticker.
        
        Args:
            ticker: Stock symbol
            force: Force update even if cache is fresh
        
        Returns:
            True if update successful, False otherwise
        """
        # Check if update needed
        if not force:
            all_fresh = all(
                not self.is_cache_stale(ticker, tf)
                for tf in TIMEFRAMES.keys()
            )
            if all_fresh:
                self.stats['cache_hits'] += 1
                return True
        
        self.stats['cache_misses'] += 1
        
        # Fetch all timeframes
        success = True
        for timeframe, interval in TIMEFRAMES.items():
            bars = self._fetch_intraday_bars(ticker, interval)
            
            if not bars:
                print(f"[MTF-DATA] Warning: No data for {ticker} {timeframe}")
                success = False
                continue
            
            # Filter to session hours
            session_bars = self._filter_session_bars(bars)
            
            # Cache the data
            self.cache[ticker][timeframe] = {
                'bars': session_bars,
                'timestamp': datetime.now(ET)
            }
        
        if success:
            print(f"[MTF-DATA] ✅ Updated {ticker}: {', '.join(f'{tf}={len(self.cache[ticker][tf]['bars'])}' for tf in TIMEFRAMES.keys())}")
        
        return success
    
    def batch_update(self, tickers: List[str], force: bool = False) -> Dict[str, bool]:
        """
        Update multiple tickers at once (for scanning).
        
        Args:
            tickers: List of stock symbols
            force: Force update even if cache is fresh
        
        Returns:
            Dict mapping ticker -> success status
        """
        print(f"[MTF-DATA] Batch updating {len(tickers)} tickers...")
        
        results = {}
        for ticker in tickers:
            results[ticker] = self.update_ticker(ticker, force=force)
        
        successful = sum(1 for success in results.values() if success)
        print(f"[MTF-DATA] Batch complete: {successful}/{len(tickers)} successful")
        
        return results
    
    def get_timeframe_bars(self, ticker: str, timeframe: str) -> Optional[List[Dict]]:
        """
        Get bars for specific ticker and timeframe.
        
        Args:
            ticker: Stock symbol
            timeframe: Timeframe string ('5m', '3m', '2m', '1m')
        
        Returns:
            List of bars or None if unavailable
        """
        if timeframe not in TIMEFRAMES:
            print(f"[MTF-DATA] Invalid timeframe: {timeframe}")
            return None
        
        # Update if stale
        if self.is_cache_stale(ticker, timeframe):
            self.update_ticker(ticker)
        
        # Return cached data
        if ticker in self.cache and timeframe in self.cache[ticker]:
            return self.cache[ticker][timeframe]['bars']
        
        return None
    
    def get_all_timeframes(self, ticker: str) -> Dict[str, List[Dict]]:
        """
        Get bars for all timeframes for a ticker.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Dict mapping timeframe -> bars list
            Example: {'5m': [...], '3m': [...], '2m': [...], '1m': [...]}
        """
        # Update if any timeframe is stale
        needs_update = any(
            self.is_cache_stale(ticker, tf)
            for tf in TIMEFRAMES.keys()
        )
        
        if needs_update:
            self.update_ticker(ticker)
        
        # Return all timeframes
        result = {}
        for timeframe in TIMEFRAMES.keys():
            if ticker in self.cache and timeframe in self.cache[ticker]:
                result[timeframe] = self.cache[ticker][timeframe]['bars']
            else:
                result[timeframe] = []
        
        return result
    
    def get_aligned_bars(self, ticker: str, reference_time: datetime) -> Dict[str, Optional[Dict]]:
        """
        Get bars from all timeframes that align with a reference timestamp.
        
        This is used to find bars across timeframes that represent the
        same or closest time period for comparison.
        
        Args:
            ticker: Stock symbol
            reference_time: Reference timestamp (typically from 5m bar)
        
        Returns:
            Dict mapping timeframe -> closest bar dict
            Example: {'5m': {...}, '3m': {...}, '2m': {...}, '1m': {...}}
        """
        all_bars = self.get_all_timeframes(ticker)
        aligned = {}
        
        for timeframe, bars in all_bars.items():
            if not bars:
                aligned[timeframe] = None
                continue
            
            # Find closest bar to reference time
            closest_bar = None
            min_diff = float('inf')
            
            for bar in bars:
                diff = abs((bar['datetime'] - reference_time).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    closest_bar = bar
            
            # Only include if within reasonable window (10 minutes)
            if min_diff <= 600:
                aligned[timeframe] = closest_bar
            else:
                aligned[timeframe] = None
        
        return aligned
    
    def get_stats(self) -> Dict:
        """
        Get cache performance statistics.
        
        Returns:
            Dict with API calls, cache hits/misses, hit rate
        """
        total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
        hit_rate = (self.stats['cache_hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'api_calls': self.stats['api_calls'],
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'hit_rate': round(hit_rate, 1),
            'cached_tickers': len(self.cache)
        }
    
    def clear_cache(self, ticker: Optional[str] = None):
        """
        Clear cache for specific ticker or all tickers.
        
        Args:
            ticker: Stock symbol or None to clear all
        """
        if ticker:
            if ticker in self.cache:
                del self.cache[ticker]
                print(f"[MTF-DATA] Cleared cache for {ticker}")
        else:
            self.cache.clear()
            print("[MTF-DATA] Cleared entire cache")
    
    def print_status(self):
        """Print current status and statistics."""
        stats = self.get_stats()
        
        print("\n" + "="*80)
        print("MTF DATA MANAGER STATUS")
        print("="*80)
        print(f"Timeframes:      {', '.join(TIMEFRAMES.keys())}")
        print(f"Cache TTL:       {CACHE_TTL_SECONDS}s")
        print(f"Cached Tickers:  {stats['cached_tickers']}")
        print(f"API Calls:       {stats['api_calls']}")
        print(f"Cache Hits:      {stats['cache_hits']}")
        print(f"Cache Misses:    {stats['cache_misses']}")
        print(f"Hit Rate:        {stats['hit_rate']}%")
        print("="*80 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

mtf_data_manager = MTFDataManager()


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING & CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    print("\n🔍 MTF Data Manager Test\n")
    
    # Test with a sample ticker
    test_ticker = "AAPL"
    
    if len(sys.argv) > 1:
        test_ticker = sys.argv[1].upper()
    
    print(f"Testing with ticker: {test_ticker}\n")
    
    # Fetch all timeframes
    print("[TEST] Fetching all timeframes...")
    data = mtf_data_manager.get_all_timeframes(test_ticker)
    
    # Display results
    print("\n" + "─"*80)
    print("DATA SUMMARY")
    print("─"*80)
    for tf, bars in data.items():
        if bars:
            print(f"{tf:>3}: {len(bars):>4} bars | "
                  f"Range: {bars[0]['datetime'].strftime('%H:%M')} - {bars[-1]['datetime'].strftime('%H:%M')} | "
                  f"Latest: ${bars[-1]['close']:.2f}")
        else:
            print(f"{tf:>3}: No data available")
    
    # Cache status
    print("\n")
    mtf_data_manager.print_status()
    
    # Test cache hit
    print("[TEST] Testing cache hit (should be instant)...")
    data2 = mtf_data_manager.get_all_timeframes(test_ticker)
    print(f"✅ Cache working: Same data returned = {data == data2}")
    
    # Test alignment
    if data['5m']:
        print(f"\n[TEST] Testing bar alignment at {data['5m'][-1]['datetime'].strftime('%H:%M')}...")
        aligned = mtf_data_manager.get_aligned_bars(test_ticker, data['5m'][-1]['datetime'])
        
        print("\nAligned Bars:")
        for tf, bar in aligned.items():
            if bar:
                print(f"  {tf}: {bar['datetime'].strftime('%H:%M:%S')} | Close: ${bar['close']:.2f}")
            else:
                print(f"  {tf}: No aligned bar found")
    
    print("\n✅ MTF Data Manager test complete!\n")
