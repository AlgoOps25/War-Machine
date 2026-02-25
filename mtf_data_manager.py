"""
Multi-Timeframe Data Manager - Simplified Version

Fetches 5m and 1m bars, then derives 3m internally for MTF convergence.
Works with all EODHD plans that support standard 1m/5m intervals.

Key Features:
  - 5m bars from data_manager (primary timeframe)
  - 1m bars from EODHD API
  - 3m bars aggregated from 1m (higher accuracy than API 3m)
  - Smart caching to minimize API calls
  - Session-based cache management

Timeframe Strategy:
  - 5m: Primary (70% weight) - from existing data_manager
  - 3m: Secondary (30% weight) - aggregated from 1m bars
  - MTF convergence requires both timeframes to align

Usage:
  from mtf_data_manager import mtf_data_manager
  
  # Get both timeframes
  bars_dict = mtf_data_manager.get_all_timeframes('SPY')
  # Returns: {'5m': [...], '3m': [...]}
  
  # Clear cache at EOD
  mtf_data_manager.clear_cache()
"""

from typing import Dict, List, Optional
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import requests
from collections import defaultdict

import config
from data_manager import data_manager

ET = ZoneInfo("America/New_York")


class MTFDataManager:
    """Simplified multi-timeframe data fetching (5m + 1m-derived-3m)."""
    
    def __init__(self):
        # Cache structure: {ticker: {timeframe: bars}}
        self.cache: Dict[str, Dict[str, List[dict]]] = defaultdict(dict)
        
        # Supported timeframes (simplified)
        self.timeframes = ['5m', '3m']  # 3m derived from 1m
        
        # Session tracking for cache invalidation
        self.current_session_date = datetime.now(ET).date()
        
        # API configuration
        self.api_token = getattr(config, 'EODHD_API_KEY', '')
        if not self.api_token:
            print("[MTF] WARNING: EODHD_API_KEY not found in config - 1m data unavailable")
        self.base_url = 'https://eodhd.com/api/intraday'
        
        print("[MTF] Multi-Timeframe Data Manager initialized (Simplified Mode)")
        print(f"[MTF] Strategy: 5m (primary) + 3m (derived from 1m)")
        print(f"[MTF] Weights: 5m (70%) + 3m (30%)")
    
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
            timeframe: '5m' or '3m'
            force_refresh: Bypass cache and fetch fresh data
        
        Returns:
            List of bar dicts with keys: datetime, open, high, low, close, volume
        """
        # Session rollover check
        if self._check_session_rollover():
            self.clear_cache()
        
        # Validate timeframe
        if timeframe not in self.timeframes:
            print(f"[MTF] Unsupported timeframe: {timeframe} (use '5m' or '3m')")
            return []
        
        # Check cache first
        if not force_refresh and ticker in self.cache and timeframe in self.cache[ticker]:
            bars = self.cache[ticker][timeframe]
            if bars:
                return bars
        
        # Fetch based on timeframe
        if timeframe == '5m':
            bars = self._get_5m_bars(ticker)
        elif timeframe == '3m':
            bars = self._get_3m_bars(ticker)
        else:
            bars = []
        
        # Cache result
        if bars:
            self.cache[ticker][timeframe] = bars
        
        return bars
    
    def _get_5m_bars(self, ticker: str) -> List[dict]:
        """
        Get 5m bars using existing data_manager.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            List of 5m bars
        """
        try:
            # Get from data_manager (already optimized)
            bars = data_manager.get_today_5m_bars(ticker)
            
            if not bars:
                # Fallback: try to materialize from 1m bars
                bars_1m = data_manager.get_today_session_bars(ticker)
                if bars_1m:
                    bars = self._aggregate_to_5m(bars_1m)
            
            if bars:
                print(f"[MTF] {ticker} 5m: {len(bars)} bars (from data_manager)")
            return bars
        
        except Exception as e:
            print(f"[MTF] Error fetching 5m bars for {ticker}: {e}")
            return []
    
    def _get_3m_bars(self, ticker: str) -> List[dict]:
        """
        Get 3m bars by aggregating 1m bars.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            List of 3m bars
        """
        try:
            # First try to get 1m from data_manager
            bars_1m = data_manager.get_today_session_bars(ticker)
            
            # If not in DB, try API
            if not bars_1m and self.api_token:
                bars_1m = self._fetch_1m_from_api(ticker)
            
            if not bars_1m:
                return []
            
            # Aggregate 1m → 3m
            bars_3m = self._aggregate_to_3m(bars_1m)
            
            if bars_3m:
                print(f"[MTF] {ticker} 3m: {len(bars_3m)} bars (aggregated from 1m)")
            
            return bars_3m
        
        except Exception as e:
            print(f"[MTF] Error creating 3m bars for {ticker}: {e}")
            return []
    
    def _fetch_1m_from_api(self, ticker: str) -> List[dict]:
        """
        Fetch 1m bars from EODHD API for today's session.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            List of 1m bars
        """
        if not self.api_token:
            return []
        
        try:
            # Build API URL
            url = f"{self.base_url}/{ticker}.US"
            params = {
                'api_token': self.api_token,
                'interval': '1m',
                'fmt': 'json'
            }
            
            # Fetch data
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            raw_bars = response.json()
            if not raw_bars:
                return []
            
            # Parse and filter to today's session
            bars = self._parse_and_filter_bars(raw_bars, ticker)
            
            return bars
        
        except requests.exceptions.RequestException as e:
            print(f"[MTF] API request failed for {ticker} 1m: {e}")
            return []
        except Exception as e:
            print(f"[MTF] Error fetching {ticker} 1m: {e}")
            return []
    
    def _parse_and_filter_bars(self, raw_bars: List[dict], ticker: str) -> List[dict]:
        """
        Parse API response and filter to today's session (9:30 AM - 4:00 PM ET).
        
        Args:
            raw_bars: Raw API response
            ticker: Stock symbol
        
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
                
                # Convert to datetime
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp, tz=ET)
                else:
                    dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                    dt = dt.astimezone(ET)
                
                # Remove timezone for consistency with data_manager
                dt = dt.replace(tzinfo=None)
                
                # Filter to today's session
                if dt.date() != today:
                    continue
                if not (session_start <= dt.time() < session_end):
                    continue
                
                # Build bar dict
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
            print(f"[MTF] Error parsing bars for {ticker}: {e}")
            return []
    
    def _aggregate_to_3m(self, bars_1m: List[dict]) -> List[dict]:
        """
        Aggregate 1m bars into 3m bars.
        
        Args:
            bars_1m: List of 1m bars
        
        Returns:
            List of 3m bars
        """
        if not bars_1m:
            return []
        
        buckets: Dict[datetime, List[dict]] = defaultdict(list)
        
        for bar in bars_1m:
            dt = bar['datetime']
            # Round down to nearest 3-minute interval
            minute_floor = (dt.minute // 3) * 3
            bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)
            buckets[bucket_dt].append(bar)
        
        bars_3m = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            bars_3m.append({
                'datetime': bucket_dt,
                'open': bucket[0]['open'],
                'high': max(b['high'] for b in bucket),
                'low': min(b['low'] for b in bucket),
                'close': bucket[-1]['close'],
                'volume': sum(b['volume'] for b in bucket)
            })
        
        return bars_3m
    
    def _aggregate_to_5m(self, bars_1m: List[dict]) -> List[dict]:
        """
        Aggregate 1m bars into 5m bars (fallback for data_manager).
        
        Args:
            bars_1m: List of 1m bars
        
        Returns:
            List of 5m bars
        """
        if not bars_1m:
            return []
        
        buckets: Dict[datetime, List[dict]] = defaultdict(list)
        
        for bar in bars_1m:
            dt = bar['datetime']
            # Round down to nearest 5-minute interval
            minute_floor = (dt.minute // 5) * 5
            bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)
            buckets[bucket_dt].append(bar)
        
        bars_5m = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            bars_5m.append({
                'datetime': bucket_dt,
                'open': bucket[0]['open'],
                'high': max(b['high'] for b in bucket),
                'low': min(b['low'] for b in bucket),
                'close': bucket[-1]['close'],
                'volume': sum(b['volume'] for b in bucket)
            })
        
        return bars_5m
    
    def get_all_timeframes(self, ticker: str) -> Dict[str, List[dict]]:
        """
        Get bars for both 5m and 3m timeframes.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Dict mapping timeframe -> bars
            Example: {'5m': [...], '3m': [...]}
        """
        result = {}
        
        for tf in self.timeframes:
            bars = self.get_bars(ticker, tf)
            if bars:
                result[tf] = bars
        
        # Log summary
        if result:
            available_tfs = ', '.join(result.keys())
            print(f"[MTF] {ticker} timeframes available: {available_tfs}")
        else:
            print(f"[MTF] {ticker} no timeframes available")
        
        return result
    
    def clear_cache(self, ticker: Optional[str] = None, timeframe: Optional[str] = None):
        """
        Clear cached data.
        
        Args:
            ticker: Optional ticker to clear (if None, clear all tickers)
            timeframe: Optional timeframe to clear (if None, clear all timeframes)
        """
        if ticker and timeframe:
            if ticker in self.cache and timeframe in self.cache[ticker]:
                del self.cache[ticker][timeframe]
                print(f"[MTF] Cleared cache: {ticker} {timeframe}")
        elif ticker:
            if ticker in self.cache:
                del self.cache[ticker]
                print(f"[MTF] Cleared cache: {ticker} (all timeframes)")
        else:
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


# ════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ════════════════════════════════════════════════════════════════════════════

mtf_data_manager = MTFDataManager()


# ════════════════════════════════════════════════════════════════════════════
# TESTING / CLI USAGE
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mtf_data_manager.py <ticker>")
        print("Example: python mtf_data_manager.py SPY")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
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
