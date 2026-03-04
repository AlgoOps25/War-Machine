"""
VWAP Calculator - Institutional Support/Resistance

Calculates:
  - VWAP (Volume Weighted Average Price): Institutional benchmark
  - Standard Deviation Bands (1σ, 2σ, 3σ): Support/resistance zones
  - Distance from VWAP: Overbought/oversold signal

Use Cases:
  1. VWAP as dynamic support/resistance (institutions trade around VWAP)
  2. VWAP breakout = strong directional move
  3. Price at 2σ = mean reversion opportunity
  4. Price at 3σ = extreme overextension (reversal likely)

Integration:
  - Boost breakout confidence when breaking VWAP
  - Identify mean reversion setups at 2σ/3σ bands
  - Filter weak breakouts that fail at VWAP

Phase: Task 8 (Volume Profile + VWAP Integration)
"""
from typing import Dict, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import statistics
import math

ET = ZoneInfo("America/New_York")


class VWAPCalculator:
    """Calculate VWAP and standard deviation bands."""
    
    def __init__(self, num_std_devs: List[float] = [1.0, 2.0, 3.0]):
        """
        Args:
            num_std_devs: List of standard deviations for bands (default: 1σ, 2σ, 3σ)
        """
        self.num_std_devs = num_std_devs
        
        # Session cache: {ticker -> vwap_data}
        self._session_cache: Dict[str, Dict] = {}
        
        print(f"[VWAP] Calculator initialized | Bands: {', '.join([f'{x}σ' for x in num_std_devs])}")
    
    def calculate_vwap(self, bars: List[Dict]) -> Optional[Dict]:
        """
        Calculate VWAP and standard deviation bands from intraday bars.
        
        VWAP Formula:
          VWAP = Σ(Typical Price × Volume) / Σ(Volume)
          Typical Price = (High + Low + Close) / 3
        
        Args:
            bars: List of OHLCV bars (session data from 9:30 AM)
        
        Returns:
            Dict with VWAP data:
            {
                'vwap': float,
                'upper_1sd': float,
                'lower_1sd': float,
                'upper_2sd': float,
                'lower_2sd': float,
                'upper_3sd': float,
                'lower_3sd': float,
                'current_price': float,
                'distance_from_vwap_pct': float,
                'std_dev': float,
                'num_bars': int,
                'timestamp': datetime
            }
        """
        if not bars or len(bars) < 2:
            return None
        
        # Calculate VWAP
        cumulative_tpv = 0.0  # Typical Price × Volume
        cumulative_volume = 0.0
        typical_prices = []
        volumes = []
        
        for bar in bars:
            typical_price = (bar['high'] + bar['low'] + bar['close']) / 3
            volume = bar['volume']
            
            cumulative_tpv += typical_price * volume
            cumulative_volume += volume
            
            typical_prices.append(typical_price)
            volumes.append(volume)
        
        if cumulative_volume == 0:
            return None
        
        vwap = cumulative_tpv / cumulative_volume
        
        # Calculate standard deviation (volume-weighted)
        squared_diffs = []
        for i, typical_price in enumerate(typical_prices):
            diff = typical_price - vwap
            squared_diff = diff ** 2
            squared_diffs.append(squared_diff * volumes[i])
        
        variance = sum(squared_diffs) / cumulative_volume
        std_dev = math.sqrt(variance)
        
        # Calculate bands
        bands = {
            'vwap': round(vwap, 2),
            'std_dev': round(std_dev, 2)
        }
        
        for num_sd in self.num_std_devs:
            bands[f'upper_{int(num_sd)}sd'] = round(vwap + (std_dev * num_sd), 2)
            bands[f'lower_{int(num_sd)}sd'] = round(vwap - (std_dev * num_sd), 2)
        
        # Current price analysis
        current_price = bars[-1]['close']
        distance_pct = ((current_price - vwap) / vwap) * 100
        
        bands['current_price'] = round(current_price, 2)
        bands['distance_from_vwap_pct'] = round(distance_pct, 2)
        bands['num_bars'] = len(bars)
        bands['timestamp'] = datetime.now(ET)
        
        return bands
    
    def get_vwap_cached(self, ticker: str, bars: List[Dict], 
                       force_recalc: bool = False) -> Optional[Dict]:
        """
        Get VWAP with session-based caching.
        
        Cache persists for the session (9:30 AM - 4:00 PM).
        Recalculated when new bars are added.
        
        Args:
            ticker: Stock ticker
            bars: List of OHLCV bars
            force_recalc: Force recalculation (bypass cache)
        
        Returns:
            VWAP data dict
        """
        # Check cache
        if not force_recalc and ticker in self._session_cache:
            cached_data = self._session_cache[ticker]
            cached_bars = cached_data.get('num_bars', 0)
            
            # Use cache if bar count matches (no new bars)
            if cached_bars == len(bars):
                return cached_data
        
        # Calculate VWAP
        vwap_data = self.calculate_vwap(bars)
        
        if vwap_data:
            # Store in cache
            self._session_cache[ticker] = vwap_data
        
        return vwap_data
    
    def check_vwap_breakout(self, price: float, vwap_data: Dict, 
                           direction: str = 'bull') -> bool:
        """
        Check if price is breaking VWAP (high-probability directional move).
        
        Args:
            price: Current price
            vwap_data: VWAP data dict
            direction: 'bull' or 'bear'
        
        Returns:
            True if breaking VWAP in the specified direction
        """
        vwap = vwap_data.get('vwap', 0)
        if vwap == 0:
            return False
        
        if direction == 'bull':
            return price > vwap
        else:  # bear
            return price < vwap
    
    def check_band_touch(self, price: float, vwap_data: Dict, 
                        band_level: int = 2) -> Optional[str]:
        """
        Check if price is touching a specific standard deviation band.
        
        Args:
            price: Current price
            vwap_data: VWAP data dict
            band_level: Band level (1, 2, or 3)
        
        Returns:
            'upper' if touching upper band, 'lower' if touching lower band, None otherwise
        """
        upper_key = f'upper_{band_level}sd'
        lower_key = f'lower_{band_level}sd'
        
        upper_band = vwap_data.get(upper_key, 0)
        lower_band = vwap_data.get(lower_key, 0)
        
        if upper_band == 0 or lower_band == 0:
            return None
        
        # Tolerance: 0.2% of band value
        upper_tolerance = upper_band * 0.002
        lower_tolerance = lower_band * 0.002
        
        if abs(price - upper_band) <= upper_tolerance:
            return 'upper'
        elif abs(price - lower_band) <= lower_tolerance:
            return 'lower'
        
        return None
    
    def get_mean_reversion_signal(self, vwap_data: Dict) -> Optional[Dict]:
        """
        Identify mean reversion opportunity (price at 2σ or 3σ bands).
        
        Args:
            vwap_data: VWAP data dict
        
        Returns:
            Dict with mean reversion signal or None:
            {
                'signal': 'BUY' or 'SELL',
                'reason': str,
                'confidence': int,
                'entry': float,
                'target': float (VWAP),
                'stop': float,
                'band_level': int
            }
        """
        current_price = vwap_data.get('current_price', 0)
        vwap = vwap_data.get('vwap', 0)
        distance_pct = vwap_data.get('distance_from_vwap_pct', 0)
        
        if vwap == 0 or current_price == 0:
            return None
        
        # Check 3σ band (extreme overextension)
        band_3sd = self.check_band_touch(current_price, vwap_data, band_level=3)
        if band_3sd:
            if band_3sd == 'upper':
                # Price at upper 3σ → mean reversion SHORT
                return {
                    'signal': 'SELL',
                    'reason': f'Mean reversion from +3σ band ({distance_pct:+.1f}% from VWAP)',
                    'confidence': 80,
                    'entry': current_price,
                    'target': vwap,
                    'stop': vwap_data['upper_3sd'] * 1.005,  # 0.5% above 3σ
                    'band_level': 3
                }
            else:  # lower
                # Price at lower 3σ → mean reversion LONG
                return {
                    'signal': 'BUY',
                    'reason': f'Mean reversion from -3σ band ({distance_pct:+.1f}% from VWAP)',
                    'confidence': 80,
                    'entry': current_price,
                    'target': vwap,
                    'stop': vwap_data['lower_3sd'] * 0.995,  # 0.5% below 3σ
                    'band_level': 3
                }
        
        # Check 2σ band (moderate overextension)
        band_2sd = self.check_band_touch(current_price, vwap_data, band_level=2)
        if band_2sd:
            if band_2sd == 'upper':
                # Price at upper 2σ → mean reversion SHORT
                return {
                    'signal': 'SELL',
                    'reason': f'Mean reversion from +2σ band ({distance_pct:+.1f}% from VWAP)',
                    'confidence': 65,
                    'entry': current_price,
                    'target': vwap,
                    'stop': vwap_data['upper_2sd'] * 1.005,
                    'band_level': 2
                }
            else:  # lower
                # Price at lower 2σ → mean reversion LONG
                return {
                    'signal': 'BUY',
                    'reason': f'Mean reversion from -2σ band ({distance_pct:+.1f}% from VWAP)',
                    'confidence': 65,
                    'entry': current_price,
                    'target': vwap,
                    'stop': vwap_data['lower_2sd'] * 0.995,
                    'band_level': 2
                }
        
        return None
    
    def get_position_relative_to_vwap(self, vwap_data: Dict) -> str:
        """
        Get price position relative to VWAP and bands.
        
        Args:
            vwap_data: VWAP data dict
        
        Returns:
            Position string: 'far_above', 'above', 'at_vwap', 'below', 'far_below'
        """
        distance_pct = abs(vwap_data.get('distance_from_vwap_pct', 0))
        
        if distance_pct > 2.0:  # >2% from VWAP
            if vwap_data['distance_from_vwap_pct'] > 0:
                return 'far_above'
            else:
                return 'far_below'
        elif distance_pct > 0.5:  # 0.5-2% from VWAP
            if vwap_data['distance_from_vwap_pct'] > 0:
                return 'above'
            else:
                return 'below'
        else:  # Within 0.5% of VWAP
            return 'at_vwap'
    
    def clear_cache(self, ticker: Optional[str] = None) -> None:
        """
        Clear VWAP session cache.
        
        Args:
            ticker: Clear specific ticker, or all if None
        """
        if ticker:
            if ticker in self._session_cache:
                del self._session_cache[ticker]
        else:
            self._session_cache.clear()


# ========================================
# GLOBAL INSTANCE
# ========================================
vwap_calculator = VWAPCalculator(num_std_devs=[1.0, 2.0, 3.0])


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def get_vwap(ticker: str, bars: List[Dict], use_cache: bool = True) -> Optional[Dict]:
    """Get VWAP data for ticker."""
    return vwap_calculator.get_vwap_cached(ticker, bars, force_recalc=not use_cache)


def check_vwap_breakout(price: float, vwap_data: Dict, direction: str = 'bull') -> bool:
    """Check if price is breaking VWAP."""
    return vwap_calculator.check_vwap_breakout(price, vwap_data, direction)


def get_mean_reversion_signal(vwap_data: Dict) -> Optional[Dict]:
    """Get mean reversion signal if price is at 2σ/3σ bands."""
    return vwap_calculator.get_mean_reversion_signal(vwap_data)


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    from datetime import datetime
    
    # Sample intraday bars (9:30 AM - 10:30 AM)
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
    print("VWAP CALCULATION")
    print("="*70)
    
    vwap_data = get_vwap("TEST", sample_bars, use_cache=False)
    
    if vwap_data:
        print(f"\nVWAP: ${vwap_data['vwap']:.2f}")
        print(f"Current Price: ${vwap_data['current_price']:.2f}")
        print(f"Distance from VWAP: {vwap_data['distance_from_vwap_pct']:+.2f}%")
        
        print(f"\nStandard Deviation Bands:")
        print(f"  +3σ: ${vwap_data['upper_3sd']:.2f}")
        print(f"  +2σ: ${vwap_data['upper_2sd']:.2f}")
        print(f"  +1σ: ${vwap_data['upper_1sd']:.2f}")
        print(f"  VWAP: ${vwap_data['vwap']:.2f}")
        print(f"  -1σ: ${vwap_data['lower_1sd']:.2f}")
        print(f"  -2σ: ${vwap_data['lower_2sd']:.2f}")
        print(f"  -3σ: ${vwap_data['lower_3sd']:.2f}")
        
        # Test breakout detection
        current_price = vwap_data['current_price']
        print(f"\nVWAP Breakout (Bull): {check_vwap_breakout(current_price, vwap_data, 'bull')}")
        
        # Test mean reversion
        mr_signal = get_mean_reversion_signal(vwap_data)
        if mr_signal:
            print(f"\nMean Reversion Signal:")
            print(f"  Signal: {mr_signal['signal']}")
            print(f"  Confidence: {mr_signal['confidence']}%")
            print(f"  Reason: {mr_signal['reason']}")
            print(f"  Entry: ${mr_signal['entry']:.2f}")
            print(f"  Target: ${mr_signal['target']:.2f}")
            print(f"  Stop: ${mr_signal['stop']:.2f}")
        else:
            print(f"\nNo mean reversion signal (price not at 2σ/3σ bands)")
        
        # Position relative to VWAP
        position = vwap_calculator.get_position_relative_to_vwap(vwap_data)
        print(f"\nPosition Relative to VWAP: {position.replace('_', ' ').upper()}")
    
    print("="*70 + "\n")
