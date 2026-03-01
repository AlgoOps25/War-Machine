"""
Day 5: Dynamic Target Discovery
Adaptive profit targets using 90-day cached historical data

Priority chain:
1. Volume resistance zones (institutional S/R)
2. VWAP bands (mean reversion)
3. Swing highs/lows (psychological levels)
4. Fixed R-multiples (1.5R/2.5R fallback)
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import statistics


class TargetDiscovery:
    """
    Discovers adaptive profit targets using cached historical data
    
    Uses 90-day lookback to find statistically significant price levels
    where institutional buying/selling historically occurred.
    """
    
    def __init__(self, candle_cache):
        """
        Initialize target discovery engine
        
        Args:
            candle_cache: Instance of CandleCache from Day 4
        """
        self.cache = candle_cache
        
        # Configuration
        self.lookback_days = 90
        self.volume_threshold = 2.0  # 2x average volume
        self.rejection_count = 2      # Min touches to confirm S/R
        self.r_min = 0.5              # Min R-multiple to search
        self.r_max = 3.0              # Max R-multiple to search
        
        # VWAP configuration
        self.vwap_time_start = "09:30"
        self.vwap_time_end = "16:00"
        
        print(f"[TARGET-DISCOVERY] Initialized | Lookback: {self.lookback_days}d | "
              f"Volume threshold: {self.volume_threshold}x | "
              f"R-range: {self.r_min}-{self.r_max}R")
    
    def get_adaptive_targets(
        self, 
        ticker: str, 
        direction: str, 
        entry: float, 
        stop: float, 
        confidence: float = 0.75
    ) -> Dict:
        """
        Main API: Get adaptive T1/T2 targets for a signal
        
        Args:
            ticker: Stock symbol
            direction: 'bull' or 'bear'
            entry: Entry price
            stop: Stop loss price
            confidence: Signal confidence (0-1)
            
        Returns:
            {
                't1': float,
                't2': float,
                'confidence': float,  # 0-1, how strong the levels are
                'method': str,        # detection method used
                'levels': list,       # all candidate levels found
                'debug': dict         # diagnostic info
            }
        """
        risk = abs(entry - stop)
        search_min = entry + (risk * self.r_min if direction == 'bull' else -risk * self.r_max)
        search_max = entry + (risk * self.r_max if direction == 'bull' else -risk * self.r_min)
        
        # Get cached bars (90 days, RTH only)
        try:
            bars = self._get_cached_bars(ticker)
            if not bars or len(bars) < 100:
                print(f"[TARGET-DISCOVERY] {ticker}: insufficient data ({len(bars) if bars else 0} bars) - using fallback")
                return self._fallback_rmultiples(entry, stop, direction)
        except Exception as e:
            print(f"[TARGET-DISCOVERY] {ticker}: cache error ({e}) - using fallback")
            return self._fallback_rmultiples(entry, stop, direction)
        
        # Try detection methods in priority order
        
        # 1. Volume resistance zones (primary)
        result = self._find_volume_resistance(bars, direction, entry, stop, search_min, search_max)
        if result:
            result['confidence'] = min(0.9, confidence * 1.2)  # Boost confidence for strong levels
            return result
        
        # 2. VWAP bands (fallback #1)
        result = self._calculate_vwap_bands(bars, direction, entry, stop, search_min, search_max)
        if result:
            result['confidence'] = confidence
            return result
        
        # 3. Swing levels (fallback #2)
        result = self._find_swing_levels(bars, direction, entry, stop, search_min, search_max)
        if result:
            result['confidence'] = max(0.5, confidence * 0.9)  # Slight confidence penalty
            return result
        
        # 4. Fixed R-multiples (last resort)
        result = self._fallback_rmultiples(entry, stop, direction)
        result['confidence'] = max(0.4, confidence * 0.8)  # Lower confidence for fixed targets
        return result
    
    def _get_cached_bars(self, ticker: str) -> List[Dict]:
        """
        Fetch 90 days of RTH bars from cache
        
        Returns bars sorted ascending by datetime
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=self.lookback_days)
        
        # Query cache (this should be fast - Day 4 optimization)
        bars = self.cache.get_bars(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date
        )
        
        if not bars:
            return []
        
        # Filter to RTH only (09:30-16:00 ET)
        rth_bars = []
        for bar in bars:
            dt = bar.get('datetime')
            if dt:
                # Parse time (handle both string and datetime)
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                    except:
                        continue
                
                bar_time = dt.strftime('%H:%M')
                if self.vwap_time_start <= bar_time <= self.vwap_time_end:
                    rth_bars.append(bar)
        
        return sorted(rth_bars, key=lambda x: x['datetime'])
    
    def _find_volume_resistance(
        self, 
        bars: List[Dict], 
        direction: str, 
        entry: float, 
        stop: float,
        search_min: float,
        search_max: float
    ) -> Optional[Dict]:
        """
        Find resistance/support zones with high volume and multiple touches
        
        Returns targets if 2+ levels found, else None
        """
        risk = abs(entry - stop)
        
        # Calculate average volume for threshold
        volumes = [b['volume'] for b in bars if b.get('volume')]
        if not volumes:
            return None
        avg_volume = statistics.mean(volumes)
        volume_threshold = avg_volume * self.volume_threshold
        
        # Build price level candidates
        levels = {}
        tolerance = risk * 0.02  # 2% of risk distance for "same level" grouping
        
        for bar in bars:
            price = bar['high'] if direction == 'bull' else bar['low']
            volume = bar.get('volume', 0)
            
            # Skip if outside search range or low volume
            if not (search_min <= price <= search_max):
                continue
            if volume < volume_threshold:
                continue
            
            # Group nearby prices (tolerance clustering)
            found_level = False
            for level_price in list(levels.keys()):
                if abs(price - level_price) <= tolerance:
                    levels[level_price]['touches'] += 1
                    levels[level_price]['total_volume'] += volume
                    found_level = True
                    break
            
            if not found_level:
                levels[price] = {
                    'touches': 1,
                    'total_volume': volume,
                    'price': price
                }
        
        # Filter: require rejection_count touches minimum
        significant_levels = [
            v for v in levels.values() 
            if v['touches'] >= self.rejection_count
        ]
        
        if len(significant_levels) < 2:
            return None
        
        # Sort by price (ascending for bull, descending for bear)
        significant_levels.sort(
            key=lambda x: x['price'],
            reverse=(direction == 'bear')
        )
        
        # Pick T1 (nearest) and T2 (next)
        t1_level = significant_levels[0]
        t2_level = significant_levels[1] if len(significant_levels) > 1 else significant_levels[0]
        
        t1 = t1_level['price']
        t2 = t2_level['price']
        
        # Ensure T2 > T1 for bulls, T2 < T1 for bears
        if direction == 'bull' and t2 <= t1:
            t2 = t1 + risk * 1.0  # Extend T2 by 1R
        elif direction == 'bear' and t2 >= t1:
            t2 = t1 - risk * 1.0
        
        return {
            't1': t1,
            't2': t2,
            'method': 'volume_resistance',
            'levels': [l['price'] for l in significant_levels[:5]],  # Top 5 levels
            'debug': {
                'levels_found': len(significant_levels),
                't1_touches': t1_level['touches'],
                't2_touches': t2_level['touches'],
                't1_volume': t1_level['total_volume'],
                't2_volume': t2_level['total_volume'],
                't1_r_multiple': abs(t1 - entry) / risk,
                't2_r_multiple': abs(t2 - entry) / risk,
            }
        }
    
    def _calculate_vwap_bands(
        self, 
        bars: List[Dict], 
        direction: str, 
        entry: float, 
        stop: float,
        search_min: float,
        search_max: float
    ) -> Optional[Dict]:
        """
        Calculate VWAP bands for mean reversion targets
        
        Uses full RTH (09:30-16:00) last 90 days
        """
        risk = abs(entry - stop)
        
        # Calculate VWAP
        total_pv = 0
        total_v = 0
        prices = []
        
        for bar in bars:
            price = (bar['high'] + bar['low'] + bar['close']) / 3  # Typical price
            volume = bar.get('volume', 0)
            if volume > 0:
                total_pv += price * volume
                total_v += volume
                prices.append(price)
        
        if total_v == 0 or not prices:
            return None
        
        vwap = total_pv / total_v
        
        # Calculate volume-weighted standard deviation
        try:
            # Simple std dev as approximation (full volume-weighting is complex)
            std_dev = statistics.stdev(prices)
        except:
            return None
        
        # Generate bands
        if direction == 'bull':
            t1 = vwap + (1.5 * std_dev)
            t2 = vwap + (2.5 * std_dev)
        else:
            t1 = vwap - (1.5 * std_dev)
            t2 = vwap - (2.5 * std_dev)
        
        # Validate within search range
        if not (search_min <= t1 <= search_max):
            return None
        
        return {
            't1': t1,
            't2': t2,
            'method': 'vwap_bands',
            'levels': [vwap, t1, t2],
            'debug': {
                'vwap': vwap,
                'std_dev': std_dev,
                't1_r_multiple': abs(t1 - entry) / risk,
                't2_r_multiple': abs(t2 - entry) / risk,
            }
        }
    
    def _find_swing_levels(
        self, 
        bars: List[Dict], 
        direction: str, 
        entry: float, 
        stop: float,
        search_min: float,
        search_max: float
    ) -> Optional[Dict]:
        """
        Find swing highs/lows from highest volume bars
        
        Psychological levels where big moves occurred
        """
        risk = abs(entry - stop)
        
        # Sort bars by volume (descending)
        sorted_bars = sorted(bars, key=lambda x: x.get('volume', 0), reverse=True)
        
        # Take top 20% highest volume bars
        top_bars = sorted_bars[:max(10, len(sorted_bars) // 5)]
        
        # Extract swing levels
        swing_levels = []
        for bar in top_bars:
            level = bar['high'] if direction == 'bull' else bar['low']
            if search_min <= level <= search_max:
                swing_levels.append(level)
        
        if len(swing_levels) < 2:
            return None
        
        # Sort and pick T1/T2
        swing_levels.sort(reverse=(direction == 'bear'))
        t1 = swing_levels[0]
        t2 = swing_levels[1]
        
        return {
            't1': t1,
            't2': t2,
            'method': 'swing_levels',
            'levels': swing_levels[:5],
            'debug': {
                'levels_found': len(swing_levels),
                't1_r_multiple': abs(t1 - entry) / risk,
                't2_r_multiple': abs(t2 - entry) / risk,
            }
        }
    
    def _fallback_rmultiples(
        self, 
        entry: float, 
        stop: float, 
        direction: str
    ) -> Dict:
        """
        Fixed R-multiple targets (current system)
        
        Used when no statistical levels found
        """
        risk = abs(entry - stop)
        
        if direction == 'bull':
            t1 = entry + (risk * 1.5)
            t2 = entry + (risk * 2.5)
        else:
            t1 = entry - (risk * 1.5)
            t2 = entry - (risk * 2.5)
        
        return {
            't1': t1,
            't2': t2,
            'method': 'fixed_rmultiples',
            'levels': [t1, t2],
            'debug': {
                't1_r_multiple': 1.5,
                't2_r_multiple': 2.5,
            }
        }


# Global singleton instance (initialized on first import)
target_discovery = None


def get_target_discovery(candle_cache):
    """
    Get or create global TargetDiscovery instance
    
    Args:
        candle_cache: CandleCache instance from Day 4
        
    Returns:
        TargetDiscovery singleton
    """
    global target_discovery
    if target_discovery is None:
        target_discovery = TargetDiscovery(candle_cache)
    return target_discovery
