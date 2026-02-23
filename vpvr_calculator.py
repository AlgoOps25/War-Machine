"""
Volume Profile Visible Range (VPVR) Calculator

Calculates volume distribution across price levels from intraday bar data.
No external API needed - built from existing 1m/5m bars.

Key Metrics:
  - POC (Point of Control): Price level with highest volume
  - Value Area: Price range containing 70% of total volume
  - HVN (High Volume Nodes): Areas with significant volume concentration
  - LVN (Low Volume Nodes): Areas with minimal volume (breakout zones)

Usage:
  1. Intraday Profile: Use today's bars to identify key support/resistance
  2. Session Profile: Pre-market or regular hours only
  3. Multi-day Profile: Look for major support/resistance zones
"""
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, time as dtime
import data_manager


class VPVRCalculator:
    """Calculate Volume Profile from bar data."""
    
    def __init__(self, price_buckets: int = 50):
        """
        Initialize VPVR calculator.
        
        Args:
            price_buckets: Number of price levels to divide range into (default 50)
        """
        self.price_buckets = price_buckets
    
    def calculate_profile(
        self,
        bars: List[Dict],
        value_area_pct: float = 0.70
    ) -> Optional[Dict]:
        """
        Calculate volume profile from bar data.
        
        Args:
            bars: List of OHLCV bar dicts
            value_area_pct: Percentage of volume for value area (default 70%)
        
        Returns:
            {
                'poc_price': float,              # Point of Control price
                'poc_volume': int,               # Volume at POC
                'value_area_high': float,        # Upper value area boundary
                'value_area_low': float,         # Lower value area boundary
                'total_volume': int,             # Total session volume
                'price_levels': List[Dict],      # [{price, volume, pct_of_total}]
                'hvn_levels': List[float],       # High Volume Nodes
                'lvn_levels': List[float]        # Low Volume Nodes
            }
        """
        if not bars:
            return None
        
        # Find price range
        all_prices = []
        for bar in bars:
            all_prices.extend([bar['high'], bar['low']])
        
        min_price = min(all_prices)
        max_price = max(all_prices)
        price_range = max_price - min_price
        
        if price_range == 0:
            return None
        
        bucket_size = price_range / self.price_buckets
        
        # Initialize volume buckets
        volume_by_bucket = defaultdict(int)
        
        # Distribute volume across price levels
        for bar in bars:
            bar_range = bar['high'] - bar['low']
            
            if bar_range == 0:
                # Single price level - all volume goes there
                bucket = int((bar['close'] - min_price) / bucket_size)
                bucket = min(bucket, self.price_buckets - 1)
                volume_by_bucket[bucket] += bar['volume']
            else:
                # Distribute volume proportionally across touched levels
                # Simple approach: split evenly across low/mid/high
                for price in [bar['low'], bar['close'], bar['high']]:
                    bucket = int((price - min_price) / bucket_size)
                    bucket = min(bucket, self.price_buckets - 1)
                    volume_by_bucket[bucket] += bar['volume'] / 3
        
        # Calculate total volume
        total_volume = sum(volume_by_bucket.values())
        
        if total_volume == 0:
            return None
        
        # Find POC (Point of Control)
        poc_bucket = max(volume_by_bucket, key=volume_by_bucket.get)
        poc_price = min_price + (poc_bucket * bucket_size) + (bucket_size / 2)
        poc_volume = volume_by_bucket[poc_bucket]
        
        # Calculate Value Area (70% of volume around POC)
        value_area_volume_target = total_volume * value_area_pct
        value_area_buckets = {poc_bucket}
        value_area_volume = poc_volume
        
        # Expand outward from POC until we reach target volume
        lower_bucket = poc_bucket - 1
        upper_bucket = poc_bucket + 1
        
        while value_area_volume < value_area_volume_target:
            lower_vol = volume_by_bucket.get(lower_bucket, 0) if lower_bucket >= 0 else 0
            upper_vol = volume_by_bucket.get(upper_bucket, 0) if upper_bucket < self.price_buckets else 0
            
            if lower_vol == 0 and upper_vol == 0:
                break
            
            # Add the side with more volume
            if lower_vol >= upper_vol and lower_bucket >= 0:
                value_area_buckets.add(lower_bucket)
                value_area_volume += lower_vol
                lower_bucket -= 1
            elif upper_vol > 0 and upper_bucket < self.price_buckets:
                value_area_buckets.add(upper_bucket)
                value_area_volume += upper_vol
                upper_bucket += 1
            else:
                break
        
        # Calculate value area boundaries
        if value_area_buckets:
            min_va_bucket = min(value_area_buckets)
            max_va_bucket = max(value_area_buckets)
            value_area_low = min_price + (min_va_bucket * bucket_size)
            value_area_high = min_price + ((max_va_bucket + 1) * bucket_size)
        else:
            value_area_low = poc_price
            value_area_high = poc_price
        
        # Build price levels list
        price_levels = []
        for bucket in sorted(volume_by_bucket.keys()):
            bucket_price = min_price + (bucket * bucket_size) + (bucket_size / 2)
            bucket_volume = int(volume_by_bucket[bucket])
            pct_of_total = (bucket_volume / total_volume) * 100
            
            price_levels.append({
                'price': round(bucket_price, 2),
                'volume': bucket_volume,
                'pct_of_total': round(pct_of_total, 2)
            })
        
        # Identify HVN (High Volume Nodes) - top 20% by volume
        avg_volume_per_level = total_volume / len(volume_by_bucket)
        hvn_threshold = avg_volume_per_level * 1.5
        
        hvn_levels = [
            level['price']
            for level in price_levels
            if level['volume'] >= hvn_threshold
        ]
        
        # Identify LVN (Low Volume Nodes) - bottom 20% by volume
        lvn_threshold = avg_volume_per_level * 0.5
        
        lvn_levels = [
            level['price']
            for level in price_levels
            if level['volume'] <= lvn_threshold and level['volume'] > 0
        ]
        
        return {
            'poc_price': round(poc_price, 2),
            'poc_volume': int(poc_volume),
            'value_area_high': round(value_area_high, 2),
            'value_area_low': round(value_area_low, 2),
            'total_volume': int(total_volume),
            'price_levels': price_levels,
            'hvn_levels': hvn_levels,
            'lvn_levels': lvn_levels
        }
    
    def calculate_session_profile(
        self,
        ticker: str,
        session_type: str = "regular"
    ) -> Optional[Dict]:
        """
        Calculate volume profile for a specific session.
        
        Args:
            ticker: Stock symbol
            session_type: 'regular' (9:30-16:00), 'premarket' (4:00-9:30), or 'all'
        
        Returns:
            Volume profile dict
        """
        # Get today's bars
        bars = data_manager.data_manager.get_today_session_bars(ticker)
        
        if not bars:
            return None
        
        # Filter by session type
        if session_type == "regular":
            bars = [
                bar for bar in bars
                if dtime(9, 30) <= bar['datetime'].time() < dtime(16, 0)
            ]
        elif session_type == "premarket":
            bars = [
                bar for bar in bars
                if dtime(4, 0) <= bar['datetime'].time() < dtime(9, 30)
            ]
        # 'all' uses all bars
        
        if not bars:
            return None
        
        return self.calculate_profile(bars)
    
    def get_nearest_hvn(self, current_price: float, hvn_levels: List[float]) -> Optional[float]:
        """
        Find nearest High Volume Node to current price.
        
        Args:
            current_price: Current stock price
            hvn_levels: List of HVN price levels
        
        Returns:
            Nearest HVN price level
        """
        if not hvn_levels:
            return None
        
        return min(hvn_levels, key=lambda x: abs(x - current_price))
    
    def get_nearest_lvn(self, current_price: float, lvn_levels: List[float]) -> Optional[float]:
        """
        Find nearest Low Volume Node to current price.
        
        Args:
            current_price: Current stock price
            lvn_levels: List of LVN price levels
        
        Returns:
            Nearest LVN price level
        """
        if not lvn_levels:
            return None
        
        return min(lvn_levels, key=lambda x: abs(x - current_price))
    
    def is_price_near_poc(self, current_price: float, poc_price: float, tolerance_pct: float = 0.5) -> bool:
        """
        Check if current price is near POC.
        
        Args:
            current_price: Current stock price
            poc_price: POC price level
            tolerance_pct: Tolerance as percentage (default 0.5%)
        
        Returns:
            True if within tolerance of POC
        """
        tolerance = poc_price * (tolerance_pct / 100)
        return abs(current_price - poc_price) <= tolerance
    
    def is_price_in_value_area(self, current_price: float, va_low: float, va_high: float) -> bool:
        """
        Check if price is within value area.
        
        Args:
            current_price: Current stock price
            va_low: Value area low
            va_high: Value area high
        
        Returns:
            True if within value area
        """
        return va_low <= current_price <= va_high


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL INTEGRATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_vpvr_signal_context(
    ticker: str,
    current_price: float,
    direction: str = "BUY"
) -> Optional[Dict]:
    """
    Get VPVR context for signal validation.
    
    Args:
        ticker: Stock symbol
        current_price: Current price for signal
        direction: Signal direction ('BUY' or 'SELL')
    
    Returns:
        {
            'near_poc': bool,
            'in_value_area': bool,
            'nearest_hvn': float,
            'nearest_lvn': float,
            'distance_to_poc_pct': float,
            'recommendation': str  # 'STRONG', 'MODERATE', 'WEAK'
        }
    """
    calculator = VPVRCalculator()
    profile = calculator.calculate_session_profile(ticker, session_type="all")
    
    if not profile:
        return None
    
    poc_price = profile['poc_price']
    va_low = profile['value_area_low']
    va_high = profile['value_area_high']
    hvn_levels = profile['hvn_levels']
    lvn_levels = profile['lvn_levels']
    
    # Check POC proximity
    near_poc = calculator.is_price_near_poc(current_price, poc_price)
    
    # Check value area
    in_value_area = calculator.is_price_in_value_area(current_price, va_low, va_high)
    
    # Find nearest nodes
    nearest_hvn = calculator.get_nearest_hvn(current_price, hvn_levels)
    nearest_lvn = calculator.get_nearest_lvn(current_price, lvn_levels)
    
    # Calculate distance to POC
    distance_to_poc_pct = abs(current_price - poc_price) / poc_price * 100
    
    # Generate recommendation
    if direction == "BUY":
        if near_poc or (in_value_area and current_price <= poc_price):
            recommendation = "STRONG"  # Buying near support
        elif in_value_area:
            recommendation = "MODERATE"  # Buying within value area
        else:
            recommendation = "WEAK"  # Buying outside value area
    else:  # SELL
        if near_poc or (in_value_area and current_price >= poc_price):
            recommendation = "STRONG"  # Selling near resistance
        elif in_value_area:
            recommendation = "MODERATE"  # Selling within value area
        else:
            recommendation = "WEAK"  # Selling outside value area
    
    return {
        'near_poc': near_poc,
        'in_value_area': in_value_area,
        'nearest_hvn': nearest_hvn,
        'nearest_lvn': nearest_lvn,
        'distance_to_poc_pct': round(distance_to_poc_pct, 2),
        'recommendation': recommendation,
        'poc_price': poc_price,
        'value_area_low': va_low,
        'value_area_high': va_high
    }


def print_vpvr_summary(profile: Dict):
    """Print formatted VPVR summary."""
    if not profile:
        print("⚠️  No volume profile data available")
        return
    
    print("\n" + "="*80)
    print("VOLUME PROFILE VISIBLE RANGE (VPVR)")
    print("="*80)
    
    print(f"\n🎯 POC (Point of Control): ${profile['poc_price']:.2f}")
    print(f"   Volume at POC: {profile['poc_volume']:,}")
    
    print(f"\n📊 Value Area (70% volume):")
    print(f"   High: ${profile['value_area_high']:.2f}")
    print(f"   Low:  ${profile['value_area_low']:.2f}")
    print(f"   Width: ${profile['value_area_high'] - profile['value_area_low']:.2f}")
    
    print(f"\n🟢 High Volume Nodes (HVN): {len(profile['hvn_levels'])} levels")
    if profile['hvn_levels']:
        print(f"   {', '.join(f'${p:.2f}' for p in profile['hvn_levels'][:5])}")
    
    print(f"\n🔴 Low Volume Nodes (LVN): {len(profile['lvn_levels'])} levels")
    if profile['lvn_levels']:
        print(f"   {', '.join(f'${p:.2f}' for p in profile['lvn_levels'][:5])}")
    
    print(f"\n📊 Total Volume: {profile['total_volume']:,}")
    print("="*80 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test VPVR calculator
    test_ticker = "AAPL"
    
    print(f"Testing VPVR calculator for {test_ticker}...\n")
    
    calculator = VPVRCalculator(price_buckets=50)
    
    # Calculate regular session profile
    profile = calculator.calculate_session_profile(test_ticker, session_type="regular")
    
    if profile:
        print_vpvr_summary(profile)
        
        # Test signal context
        current_price = profile['poc_price'] * 1.02  # 2% above POC
        context = get_vpvr_signal_context(test_ticker, current_price, direction="BUY")
        
        if context:
            print("\n" + "="*80)
            print("SIGNAL CONTEXT")
            print("="*80)
            print(f"Current Price: ${current_price:.2f}")
            print(f"Near POC: {'✅' if context['near_poc'] else '❌'}")
            print(f"In Value Area: {'✅' if context['in_value_area'] else '❌'}")
            print(f"Distance to POC: {context['distance_to_poc_pct']:.2f}%")
            print(f"Recommendation: {context['recommendation']}")
            print("="*80)
    else:
        print(f"⚠️  No bars available for {test_ticker}")
