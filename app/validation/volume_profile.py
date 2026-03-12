"""
Volume Profile Analyzer
Identifies high-volume nodes (HVN) and low-volume nodes (LVN) to validate breakouts
"""
from typing import Dict, List, Optional, Tuple
import numpy as np

class VolumeProfileAnalyzer:
    """Analyze volume distribution across price levels."""
    
    def __init__(self, num_bins: int = 20):
        self.num_bins = num_bins
    
    def analyze_session_profile(self, bars: List[Dict]) -> Dict:
        """
        Build volume profile for session bars.
        
        Returns:
            {
                'poc': float,  # Point of Control (highest volume price)
                'vah': float,  # Value Area High (70% volume top)
                'val': float,  # Value Area Low (70% volume bottom)
                'hvn_levels': List[float],  # High Volume Nodes
                'lvn_levels': List[float],  # Low Volume Nodes
                'profile': List[Tuple[float, float]]  # [(price, volume)]
            }
        """
        if not bars or len(bars) < 10:
            return self._empty_profile()
        
        # Extract price range and volumes
        prices = []
        volumes = []
        for bar in bars:
            # Sample 3 points per bar: high, low, close
            prices.extend([bar['high'], bar['low'], bar['close']])
            vol_per_point = bar['volume'] / 3
            volumes.extend([vol_per_point, vol_per_point, vol_per_point])
        
        prices = np.array(prices)
        volumes = np.array(volumes)
        
        # Create price bins
        price_min, price_max = prices.min(), prices.max()
        bins = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        # Aggregate volume in each bin
        bin_volumes = np.zeros(self.num_bins)
        for price, volume in zip(prices, volumes):
            bin_idx = np.searchsorted(bins[:-1], price, side='right') - 1
            bin_idx = max(0, min(bin_idx, self.num_bins - 1))
            bin_volumes[bin_idx] += volume
        
        # Find POC (Point of Control)
        poc_idx = np.argmax(bin_volumes)
        poc = bin_centers[poc_idx]
        
        # Find Value Area (70% of volume)
        total_volume = bin_volumes.sum()
        target_volume = total_volume * 0.70
        
        # Start from POC and expand outward
        va_indices = {poc_idx}
        current_volume = bin_volumes[poc_idx]
        
        left_idx = poc_idx - 1
        right_idx = poc_idx + 1
        
        while current_volume < target_volume:
            left_vol = bin_volumes[left_idx] if left_idx >= 0 else 0
            right_vol = bin_volumes[right_idx] if right_idx < self.num_bins else 0
            
            if left_vol == 0 and right_vol == 0:
                break
            
            if left_vol >= right_vol and left_idx >= 0:
                va_indices.add(left_idx)
                current_volume += left_vol
                left_idx -= 1
            elif right_idx < self.num_bins:
                va_indices.add(right_idx)
                current_volume += right_vol
                right_idx += 1
            else:
                break
        
        va_prices = [bin_centers[i] for i in sorted(va_indices)]
        vah = max(va_prices) if va_prices else poc
        val = min(va_prices) if va_prices else poc
        
        # Identify HVN and LVN
        volume_threshold_high = np.percentile(bin_volumes, 80)
        volume_threshold_low = np.percentile(bin_volumes, 20)
        
        hvn_levels = [bin_centers[i] for i, vol in enumerate(bin_volumes) 
                      if vol >= volume_threshold_high]
        lvn_levels = [bin_centers[i] for i, vol in enumerate(bin_volumes) 
                      if vol <= volume_threshold_low and vol > 0]
        
        # Build profile
        profile = [(bin_centers[i], bin_volumes[i]) for i in range(self.num_bins)]
        
        return {
            'poc': poc,
            'vah': vah,
            'val': val,
            'hvn_levels': hvn_levels,
            'lvn_levels': lvn_levels,
            'profile': profile,
            'total_volume': total_volume
        }
    
    def _empty_profile(self) -> Dict:
        return {
            'poc': 0,
            'vah': 0,
            'val': 0,
            'hvn_levels': [],
            'lvn_levels': [],
            'profile': [],
            'total_volume': 0
        }
    
    def validate_breakout(self, profile: Dict, breakout_price: float, 
                          direction: str) -> Tuple[bool, str]:
        """
        Validate if breakout occurs at a favorable volume level.
        
        Args:
            profile: Volume profile from analyze_session_profile()
            breakout_price: Price where breakout occurred
            direction: 'bull' or 'bear'
        
        Returns:
            (is_valid, reason)
        """
        if not profile or profile['total_volume'] == 0:
            return True, "No volume profile data"
        
        poc = profile['poc']
        vah = profile['vah']
        val = profile['val']
        hvn_levels = profile['hvn_levels']
        lvn_levels = profile['lvn_levels']
        
        # Check if breakout is near LVN (low resistance)
        for lvn in lvn_levels:
            if abs(breakout_price - lvn) / breakout_price < 0.01:  # Within 1%
                return True, f"Breakout near LVN (${lvn:.2f}) - Low resistance"
        
        # Check if breakout is away from HVN (high resistance)
        for hvn in hvn_levels:
            if abs(breakout_price - hvn) / breakout_price < 0.01:  # Within 1%
                return False, f"Breakout near HVN (${hvn:.2f}) - High resistance"
        
        # Check Value Area context
        if direction == 'bull':
            if breakout_price > vah:
                return True, f"Bullish breakout above VAH (${vah:.2f})"
            elif breakout_price < val:
                return False, f"Bullish breakout below VAL (${val:.2f}) - Weak"
        else:  # bear
            if breakout_price < val:
                return True, f"Bearish breakout below VAL (${val:.2f})"
            elif breakout_price > vah:
                return False, f"Bearish breakout above VAH (${vah:.2f}) - Weak"
        
        return True, "Neutral volume profile context"

    def validate_entry(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        bars: List[Dict]
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Convenience wrapper called by sniper.py Step 6.6.
        Builds the volume profile then validates the entry price.

        Returns:
            (is_valid, reason, vp_data)
            vp_data keys: poc, distance_from_poc_pct, volume_rank
        """
        profile = self.analyze_session_profile(bars)

        if not profile or profile.get('total_volume', 0) == 0:
            return True, "Volume profile unavailable (insufficient bars)", None

        is_valid, reason = self.validate_breakout(profile, entry_price, direction)

        poc = profile.get('poc', 0)
        distance_pct = abs(entry_price - poc) / poc if poc > 0 else 0.0

        # Volume rank: what percentile of bins is the entry price near?
        # Use the bin closest to entry_price and express as a fraction of max bin vol.
        volume_rank = "N/A"
        try:
            profile_bins = profile.get('profile', [])
            if profile_bins:
                closest = min(profile_bins, key=lambda x: abs(x[0] - entry_price))
                max_vol = max(v for _, v in profile_bins) or 1
                volume_rank = f"{closest[1] / max_vol:.0%}"
        except Exception:
            pass

        vp_data = {
            'poc': round(poc, 2),
            'vah': round(profile.get('vah', 0), 2),
            'val': round(profile.get('val', 0), 2),
            'distance_from_poc_pct': round(distance_pct, 4),
            'volume_rank': volume_rank,
        }

        return is_valid, reason, vp_data


# Global instance
_volume_analyzer = None

def get_volume_analyzer() -> VolumeProfileAnalyzer:
    global _volume_analyzer
    if _volume_analyzer is None:
        _volume_analyzer = VolumeProfileAnalyzer()
    return _volume_analyzer
