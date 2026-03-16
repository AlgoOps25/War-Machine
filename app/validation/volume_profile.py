"""
app/validation/volume_profile.py  —  Entry-gate Volume Profile Validator

Purpose
-------
Per-signal entry validation called by sniper.py Step 6.6 via validate_entry().
Takes a list of live OHLCV bars, builds a coarse 20-bin profile, then checks
whether the entry price is near an HVN (high resistance) or LVN (low resistance).

Relationship to app/indicators/volume_profile.py
-------------------------------------------------
app/indicators/volume_profile.py (class VolumeProfile, 50-bin)
  └─ Broad market analysis engine with time-aware caching (5-min TTL).
     Used by indicator pipelines, breakout strength checks, and HTF scans.

app/validation/volume_profile.py  ←  THIS FILE  (class VolumeProfileAnalyzer, 20-bin)
  └─ Lightweight per-signal gate.  Receives already-fetched bars so it avoids
     any additional API calls.  Exposes validate_entry() for sniper.py.

The two files share the same POC/VAH/VAL algorithm but are intentionally kept
separate: different bin granularity, different caching strategy, different caller
contract.  Do NOT merge them.

TODO (nice-to-have): have this class delegate the core math to VolumeProfile
once the bar-list constructor is added there, removing the duplication.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np

# ---------------------------------------------------------------------------
# Simple in-process TTL cache for validate_entry results
# ---------------------------------------------------------------------------
_CACHE_TTL = timedelta(minutes=5)
_entry_cache: Dict[str, tuple] = {}   # ticker -> (result_tuple, expiry)


def _cache_key(ticker: str, direction: str, entry_price: float) -> str:
    return f"{ticker}:{direction}:{entry_price:.2f}"


class VolumeProfileAnalyzer:
    """Lightweight volume profile validator for per-signal entry gating."""

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

        prices = []
        volumes = []
        for bar in bars:
            prices.extend([bar['high'], bar['low'], bar['close']])
            vol_per_point = bar['volume'] / 3
            volumes.extend([vol_per_point, vol_per_point, vol_per_point])

        prices = np.array(prices)
        volumes = np.array(volumes)

        price_min, price_max = prices.min(), prices.max()
        bins = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2

        bin_volumes = np.zeros(self.num_bins)
        for price, volume in zip(prices, volumes):
            bin_idx = np.searchsorted(bins[:-1], price, side='right') - 1
            bin_idx = max(0, min(bin_idx, self.num_bins - 1))
            bin_volumes[bin_idx] += volume

        poc_idx = np.argmax(bin_volumes)
        poc = bin_centers[poc_idx]

        total_volume = bin_volumes.sum()
        target_volume = total_volume * 0.70

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

        volume_threshold_high = np.percentile(bin_volumes, 80)
        volume_threshold_low  = np.percentile(bin_volumes, 20)

        hvn_levels = [bin_centers[i] for i, vol in enumerate(bin_volumes)
                      if vol >= volume_threshold_high]
        lvn_levels = [bin_centers[i] for i, vol in enumerate(bin_volumes)
                      if vol <= volume_threshold_low and vol > 0]

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
            'poc': 0, 'vah': 0, 'val': 0,
            'hvn_levels': [], 'lvn_levels': [],
            'profile': [], 'total_volume': 0
        }

    def validate_breakout(self, profile: Dict, breakout_price: float,
                          direction: str) -> Tuple[bool, str]:
        """
        Validate if breakout occurs at a favorable volume level.
        """
        if not profile or profile['total_volume'] == 0:
            return True, "No volume profile data"

        poc = profile['poc']
        vah = profile['vah']
        val = profile['val']
        hvn_levels = profile['hvn_levels']
        lvn_levels = profile['lvn_levels']

        for lvn in lvn_levels:
            if abs(breakout_price - lvn) / breakout_price < 0.01:
                return True, f"Breakout near LVN (${lvn:.2f}) - Low resistance"

        for hvn in hvn_levels:
            if abs(breakout_price - hvn) / breakout_price < 0.01:
                return False, f"Breakout near HVN (${hvn:.2f}) - High resistance"

        if direction == 'bull':
            if breakout_price > vah:
                return True, f"Bullish breakout above VAH (${vah:.2f})"
            elif breakout_price < val:
                return False, f"Bullish breakout below VAL (${val:.2f}) - Weak"
        else:
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
        Results are cached for 5 minutes per (ticker, direction, entry_price).

        Returns:
            (is_valid, reason, vp_data)
            vp_data keys: poc, vah, val, distance_from_poc_pct, volume_rank
        """
        key = _cache_key(ticker, direction, entry_price)
        now = datetime.utcnow()
        if key in _entry_cache:
            result, expiry = _entry_cache[key]
            if now < expiry:
                return result

        profile = self.analyze_session_profile(bars)

        if not profile or profile.get('total_volume', 0) == 0:
            result = (True, "Volume profile unavailable (insufficient bars)", None)
            _entry_cache[key] = (result, now + _CACHE_TTL)
            return result

        is_valid, reason = self.validate_breakout(profile, entry_price, direction)

        poc = profile.get('poc', 0)
        distance_pct = abs(entry_price - poc) / poc if poc > 0 else 0.0

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
            'poc':                  round(poc, 2),
            'vah':                  round(profile.get('vah', 0), 2),
            'val':                  round(profile.get('val', 0), 2),
            'distance_from_poc_pct': round(distance_pct, 4),
            'volume_rank':          volume_rank,
        }

        result = (is_valid, reason, vp_data)
        _entry_cache[key] = (result, now + _CACHE_TTL)
        return result


# Global instance
_volume_analyzer = None


def get_volume_analyzer() -> VolumeProfileAnalyzer:
    global _volume_analyzer
    if _volume_analyzer is None:
        _volume_analyzer = VolumeProfileAnalyzer()
    return _volume_analyzer
