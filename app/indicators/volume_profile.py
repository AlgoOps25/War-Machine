"""
Volume Profile Calculator - Institutional Support/Resistance

Calculates:
  - POC (Point of Control): Price level with highest volume
  - VAH (Value Area High): Upper boundary of 70% volume zone
  - VAL (Value Area Low): Lower boundary of 70% volume zone
  - High-Volume Nodes: Price levels with volume > 1.5x average

Use Cases:
  1. POC breakout = high-probability institutional breakout
  2. VAH/VAL act as dynamic support/resistance
  3. High-volume nodes = magnets for price action
  4. Low-volume zones = weak breakouts (likely to fail)

Integration:
  - Boost breakout confidence when breaking POC
  - Filter breakouts into low-volume zones
  - Identify reversal zones at VAH/VAL

Phase: Task 8 (Volume Profile + VWAP Integration)
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import statistics

ET = ZoneInfo("America/New_York")


class VolumeProfile:
    """Calculate volume profile metrics from intraday bars."""
    
    def __init__(self, 
                 num_price_levels: int = 50,
                 value_area_pct: float = 0.70,
                 high_volume_threshold: float = 1.5,
                 cache_ttl_seconds: int = 300):
        """
        Args:
            num_price_levels: Number of price bins for volume distribution (50 = good balance)
            value_area_pct: Percentage of volume for value area (0.70 = 70% standard)
            high_volume_threshold: Multiplier for high-volume node detection (1.5x avg)
            cache_ttl_seconds: Cache results for N seconds (300s = 5min for intraday)
        """
        self.num_price_levels = num_price_levels
        self.value_area_pct = value_area_pct
        self.high_volume_threshold = high_volume_threshold
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # Session cache: {ticker -> (profile_data, timestamp)}
        self._cache: Dict[str, Tuple[Dict, datetime]] = {}
        
        print(f"[VP] Volume Profile initialized | "
              f"Levels: {num_price_levels} | "
              f"Value Area: {value_area_pct*100:.0f}% | "
              f"Cache: {cache_ttl_seconds}s")
    
    def _calculate_price_levels(self, bars: List[Dict]) -> List[float]:
        """
        Create evenly-spaced price levels between session high/low.
        
        Args:
            bars: List of OHLCV bars
        
        Returns:
            List of price levels (bin edges)
        """
        if not bars:
            return []
        
        # Get session range
        highs = [bar['high'] for bar in bars]
        lows = [bar['low'] for bar in bars]
        
        session_high = max(highs)
        session_low = min(lows)
        
        # Create price levels (bin edges)
        price_range = session_high - session_low
        if price_range == 0:
            return [session_low]
        
        level_size = price_range / self.num_price_levels
        
        price_levels = []
        for i in range(self.num_price_levels + 1):
            price_levels.append(session_low + (i * level_size))
        
        return price_levels
    
    def _distribute_volume(self, bars: List[Dict], price_levels: List[float]) -> Dict[float, float]:
        """
        Distribute volume across price levels based on bar OHLC.
        
        For each bar, volume is distributed proportionally across price levels
        that fall within the bar's high-low range.
        
        Args:
            bars: List of OHLCV bars
            price_levels: List of price bin edges
        
        Returns:
            Dict mapping price_level -> total_volume
        """
        # Initialize volume distribution
        volume_at_price: Dict[float, float] = {level: 0.0 for level in price_levels}
        
        for bar in bars:
            bar_high = bar['high']
            bar_low = bar['low']
            bar_volume = bar['volume']
            
            # Find price levels within this bar's range
            levels_in_range = [
                level for level in price_levels 
                if bar_low <= level <= bar_high
            ]
            
            if not levels_in_range:
                # Edge case: find closest level
                closest_level = min(price_levels, key=lambda x: abs(x - bar['close']))
                levels_in_range = [closest_level]
            
            # Distribute volume evenly across levels in range
            volume_per_level = bar_volume / len(levels_in_range)
            
            for level in levels_in_range:
                volume_at_price[level] += volume_per_level
        
        return volume_at_price
    
    def _find_poc(self, volume_at_price: Dict[float, float]) -> float:
        """
        Find Point of Control (POC) - price level with highest volume.
        
        Args:
            volume_at_price: Dict mapping price -> volume
        
        Returns:
            POC price level
        """
        if not volume_at_price:
            return 0.0
        
        poc_price = max(volume_at_price.items(), key=lambda x: x[1])[0]
        return poc_price
    
    def _find_value_area(self, volume_at_price: Dict[float, float], 
                        poc: float) -> Tuple[float, float]:
        """
        Find Value Area High (VAH) and Value Area Low (VAL).
        
        Value Area = zone containing 70% of total volume, centered around POC.
        
        Algorithm:
          1. Start at POC
          2. Expand up/down alternately to capture most volume
          3. Stop when 70% of total volume is captured
        
        Args:
            volume_at_price: Dict mapping price -> volume
            poc: Point of Control price
        
        Returns:
            (VAL, VAH) tuple
        """
        if not volume_at_price:
            return 0.0, 0.0
        
        total_volume = sum(volume_at_price.values())
        target_volume = total_volume * self.value_area_pct
        
        # Sort price levels
        sorted_levels = sorted(volume_at_price.keys())
        
        # Find POC index
        poc_idx = sorted_levels.index(poc)
        
        # Initialize value area
        va_volume = volume_at_price[poc]
        va_low_idx = poc_idx
        va_high_idx = poc_idx
        
        # Expand value area until 70% volume captured
        while va_volume < target_volume:
            # Check if we can expand
            can_expand_up = va_high_idx < len(sorted_levels) - 1
            can_expand_down = va_low_idx > 0
            
            if not can_expand_up and not can_expand_down:
                break
            
            # Determine which direction to expand
            volume_above = volume_at_price[sorted_levels[va_high_idx + 1]] if can_expand_up else 0
            volume_below = volume_at_price[sorted_levels[va_low_idx - 1]] if can_expand_down else 0
            
            # Expand toward higher volume
            if volume_above >= volume_below and can_expand_up:
                va_high_idx += 1
                va_volume += volume_at_price[sorted_levels[va_high_idx]]
            elif can_expand_down:
                va_low_idx -= 1
                va_volume += volume_at_price[sorted_levels[va_low_idx]]
            elif can_expand_up:
                va_high_idx += 1
                va_volume += volume_at_price[sorted_levels[va_high_idx]]
            else:
                break
        
        val = sorted_levels[va_low_idx]
        vah = sorted_levels[va_high_idx]
        
        return val, vah
    
    def _find_high_volume_nodes(self, volume_at_price: Dict[float, float]) -> List[Dict]:
        """
        Identify high-volume nodes (HVN) - price levels with volume > threshold.
        
        HVNs act as magnets - price tends to gravitate toward these levels.
        
        Args:
            volume_at_price: Dict mapping price -> volume
        
        Returns:
            List of dicts: [{'price': float, 'volume': float, 'volume_ratio': float}, ...]
        """
        if not volume_at_price:
            return []
        
        avg_volume = statistics.mean(volume_at_price.values())
        threshold = avg_volume * self.high_volume_threshold
        
        hvns = []
        for price, volume in volume_at_price.items():
            if volume >= threshold:
                hvns.append({
                    'price': round(price, 2),
                    'volume': volume,
                    'volume_ratio': round(volume / avg_volume, 2)
                })
        
        # Sort by volume (descending)
        hvns.sort(key=lambda x: x['volume'], reverse=True)
        
        return hvns
    
    def _find_low_volume_nodes(self, volume_at_price: Dict[float, float]) -> List[Dict]:
        """
        Identify low-volume nodes (LVN) - price levels with volume < 50% average.
        
        LVNs are weak zones - breakouts into LVNs often fail (no support).
        
        Args:
            volume_at_price: Dict mapping price -> volume
        
        Returns:
            List of dicts: [{'price': float, 'volume': float, 'volume_ratio': float}, ...]
        """
        if not volume_at_price:
            return []
        
        avg_volume = statistics.mean(volume_at_price.values())
        threshold = avg_volume * 0.5  # 50% of average
        
        lvns = []
        for price, volume in volume_at_price.items():
            if volume <= threshold:
                lvns.append({
                    'price': round(price, 2),
                    'volume': volume,
                    'volume_ratio': round(volume / avg_volume, 2)
                })
        
        # Sort by volume (ascending)
        lvns.sort(key=lambda x: x['volume'])
        
        return lvns
    
    def calculate_profile(self, bars: List[Dict], ticker: str = "unknown", 
                         use_cache: bool = True) -> Optional[Dict]:
        """
        Calculate complete volume profile for intraday session.
        
        Args:
            bars: List of OHLCV bars (intraday session)
            ticker: Stock ticker (for caching)
            use_cache: Use cached results if available
        
        Returns:
            Dict with profile data:
            {
                'poc': float,              # Point of Control
                'vah': float,              # Value Area High
                'val': float,              # Value Area Low
                'high_volume_nodes': List[Dict],  # HVNs
                'low_volume_nodes': List[Dict],   # LVNs
                'total_volume': float,
                'avg_volume_per_level': float,
                'timestamp': datetime
            }
        """
        # Check cache
        if use_cache and ticker in self._cache:
            cached_profile, cached_time = self._cache[ticker]
            age_seconds = (datetime.now(ET) - cached_time).total_seconds()
            
            if age_seconds < self.cache_ttl_seconds:
                return cached_profile
        
        if not bars or len(bars) < 3:
            return None
        
        # Calculate price levels
        price_levels = self._calculate_price_levels(bars)
        
        if len(price_levels) < 2:
            return None
        
        # Distribute volume across price levels
        volume_at_price = self._distribute_volume(bars, price_levels)
        
        # Calculate POC
        poc = self._find_poc(volume_at_price)
        
        # Calculate Value Area
        val, vah = self._find_value_area(volume_at_price, poc)
        
        # Find high-volume nodes
        hvns = self._find_high_volume_nodes(volume_at_price)
        
        # Find low-volume nodes
        lvns = self._find_low_volume_nodes(volume_at_price)
        
        # Calculate summary stats
        total_volume = sum(bar['volume'] for bar in bars)
        avg_volume_per_level = statistics.mean(volume_at_price.values())
        
        profile = {
            'poc': round(poc, 2),
            'vah': round(vah, 2),
            'val': round(val, 2),
            'high_volume_nodes': hvns[:10],  # Top 10 HVNs
            'low_volume_nodes': lvns[:10],   # Bottom 10 LVNs
            'total_volume': total_volume,
            'avg_volume_per_level': avg_volume_per_level,
            'session_high': max(bar['high'] for bar in bars),
            'session_low': min(bar['low'] for bar in bars),
            'timestamp': datetime.now(ET)
        }
        
        # Cache result
        self._cache[ticker] = (profile, datetime.now(ET))
        
        return profile
    
    def check_price_at_level(self, price: float, target_level: float, 
                             tolerance_pct: float = 0.005) -> bool:
        """
        Check if price is at a specific level (POC, VAH, VAL, HVN).
        
        Args:
            price: Current price
            target_level: Target level to check
            tolerance_pct: Tolerance as percentage (0.005 = 0.5%)
        
        Returns:
            True if price is within tolerance of target level
        """
        tolerance = target_level * tolerance_pct
        return abs(price - target_level) <= tolerance
    
    def get_nearest_hvn(self, price: float, profile: Dict, 
                       direction: str = 'above') -> Optional[Dict]:
        """
        Find nearest high-volume node above/below current price.
        
        Args:
            price: Current price
            profile: Volume profile dict
            direction: 'above' or 'below'
        
        Returns:
            HVN dict or None
        """
        hvns = profile.get('high_volume_nodes', [])
        
        if direction == 'above':
            candidates = [hvn for hvn in hvns if hvn['price'] > price]
            if candidates:
                return min(candidates, key=lambda x: x['price'])
        else:  # below
            candidates = [hvn for hvn in hvns if hvn['price'] < price]
            if candidates:
                return max(candidates, key=lambda x: x['price'])
        
        return None
    
    def is_in_low_volume_zone(self, price: float, profile: Dict, 
                              tolerance_pct: float = 0.01) -> bool:
        """
        Check if price is in a low-volume zone (weak breakout area).
        
        Args:
            price: Current price
            profile: Volume profile dict
            tolerance_pct: Tolerance (0.01 = 1%)
        
        Returns:
            True if price is near a low-volume node
        """
        lvns = profile.get('low_volume_nodes', [])
        
        for lvn in lvns:
            if self.check_price_at_level(price, lvn['price'], tolerance_pct):
                return True
        
        return False
    
    def clear_cache(self, ticker: Optional[str] = None) -> None:
        """
        Clear volume profile cache.
        
        Args:
            ticker: Clear specific ticker, or all if None
        """
        if ticker:
            if ticker in self._cache:
                del self._cache[ticker]
        else:
            self._cache.clear()


# ========================================
# GLOBAL INSTANCE
# ========================================
volume_profile = VolumeProfile(
    num_price_levels=50,
    value_area_pct=0.70,
    high_volume_threshold=1.5,
    cache_ttl_seconds=300
)


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def get_volume_profile(ticker: str, bars: List[Dict], use_cache: bool = True) -> Optional[Dict]:
    """Get volume profile for ticker."""
    return volume_profile.calculate_profile(bars, ticker, use_cache)


def check_poc_breakout(price: float, profile: Dict, direction: str = 'bull') -> bool:
    """
    Check if price is breaking POC (high-probability breakout).
    
    Args:
        price: Current price
        profile: Volume profile dict
        direction: 'bull' or 'bear'
    
    Returns:
        True if breaking POC in the specified direction
    """
    poc = profile.get('poc', 0)
    if poc == 0:
        return False
    
    if direction == 'bull':
        # Price must be above POC
        return price > poc
    else:  # bear
        # Price must be below POC
        return price < poc


def check_value_area_breakout(price: float, profile: Dict, direction: str = 'bull') -> bool:
    """
    Check if price is breaking Value Area (institutional zone).
    
    Args:
        price: Current price
        profile: Volume profile dict
        direction: 'bull' or 'bear'
    
    Returns:
        True if breaking Value Area in the specified direction
    """
    vah = profile.get('vah', 0)
    val = profile.get('val', 0)
    
    if vah == 0 or val == 0:
        return False
    
    if direction == 'bull':
        # Price must be above VAH
        return price > vah
    else:  # bear
        # Price must be below VAL
        return price < val


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    from datetime import datetime
    
    # Sample intraday bars
    sample_bars = [
        {'datetime': datetime.now(), 'open': 100, 'high': 101, 'low': 99.5, 'close': 100.5, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 100.5, 'high': 102, 'low': 100, 'close': 101, 'volume': 1500000},
        {'datetime': datetime.now(), 'open': 101, 'high': 103, 'low': 100.5, 'close': 102, 'volume': 2000000},
        {'datetime': datetime.now(), 'open': 102, 'high': 103.5, 'low': 101.5, 'close': 102.5, 'volume': 1800000},
        {'datetime': datetime.now(), 'open': 102.5, 'high': 104, 'low': 102, 'close': 103, 'volume': 2200000},
        {'datetime': datetime.now(), 'open': 103, 'high': 104.5, 'low': 102.5, 'close': 103.5, 'volume': 1900000},
        {'datetime': datetime.now(), 'open': 103.5, 'high': 105, 'low': 103, 'close': 104, 'volume': 2500000},
        {'datetime': datetime.now(), 'open': 104, 'high': 105.5, 'low': 103.5, 'close': 104.5, 'volume': 2100000},
        {'datetime': datetime.now(), 'open': 104.5, 'high': 106, 'low': 104, 'close': 105, 'volume': 2300000},
        {'datetime': datetime.now(), 'open': 105, 'high': 106.5, 'low': 104.5, 'close': 105.5, 'volume': 2000000},
    ]
    
    print("\n" + "="*70)
    print("VOLUME PROFILE CALCULATION")
    print("="*70)
    
    profile = get_volume_profile("TEST", sample_bars, use_cache=False)
    
    if profile:
        print(f"\nPOC (Point of Control): ${profile['poc']:.2f}")
        print(f"VAH (Value Area High):  ${profile['vah']:.2f}")
        print(f"VAL (Value Area Low):   ${profile['val']:.2f}")
        print(f"\nSession Range: ${profile['session_low']:.2f} - ${profile['session_high']:.2f}")
        print(f"Total Volume: {profile['total_volume']:,}")
        
        print(f"\nHigh-Volume Nodes (HVNs) - Top 5:")
        for i, hvn in enumerate(profile['high_volume_nodes'][:5], 1):
            print(f"  {i}. ${hvn['price']:.2f} | {hvn['volume_ratio']:.1f}x avg volume")
        
        print(f"\nLow-Volume Nodes (LVNs) - Bottom 3:")
        for i, lvn in enumerate(profile['low_volume_nodes'][:3], 1):
            print(f"  {i}. ${lvn['price']:.2f} | {lvn['volume_ratio']:.1f}x avg volume (WEAK ZONE)")
        
        # Test breakout detection
        current_price = 105.5
        print(f"\nCurrent Price: ${current_price:.2f}")
        print(f"POC Breakout (Bull): {check_poc_breakout(current_price, profile, 'bull')}")
        print(f"Value Area Breakout (Bull): {check_value_area_breakout(current_price, profile, 'bull')}")
        print(f"In Low-Volume Zone: {volume_profile.is_in_low_volume_zone(current_price, profile)}")
    
    print("="*70 + "\n")
