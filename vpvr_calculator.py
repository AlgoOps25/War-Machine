"""
Volume Profile Value Area Ratio (VPVR) Calculator

Provides volume profile analysis for better entry/exit precision:
  - Point of Control (POC): Price level with highest traded volume
  - High Volume Nodes (HVN): Price clusters with heavy activity
  - Low Volume Nodes (LVN): Price zones with thin trading (potential breakout areas)
  - Value Area High/Low (VAH/VAL): 70% volume distribution boundaries

Integration: Called by signal_validator.py and sniper.py for entry refinement.

Edge Case Handling (Issue #4 fixes):
  - Minimum 10 bars required (graceful fallback below threshold)
  - Zero/low volume bars filtered appropriately
  - Flat price action detection (< $0.01 range)
  - Division by zero protection
"""
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


class VPVRCalculator:
    """
    Calculate volume profile metrics from intraday bars.
    
    Use cases:
      - Entry refinement: Enter near POC or HVN for institutional support
      - Avoid LVNs: Thin zones where price can whipsaw quickly
      - Target setting: Place targets at VAH/VAL boundaries
      - Stop placement: Use LVNs as stop-loss zones (price likely to slice through)
    """
    
    # ⭐ Issue #4 Fix: Edge case thresholds
    MIN_BARS_REQUIRED = 10
    MIN_PRICE_RANGE = 0.01
    MIN_TOTAL_VOLUME = 1000
    
    def __init__(self, num_bins: int = 30):
        """
        Initialize VPVR calculator.
        
        Args:
            num_bins: Number of price bins to divide range into (default 30)
                     Higher = more granular, Lower = smoother profile
        """
        self.num_bins = num_bins
        self._cache = {}  # Cache results to avoid recalculation
        self._cache_ttl = 60  # Cache TTL in seconds
        
        print(f"[VPVR] Initialized with {num_bins} bins | Min bars: {self.MIN_BARS_REQUIRED}")
    
    def calculate_vpvr(self, bars: List[Dict], lookback_bars: int = 78) -> Dict:
        """
        Calculate volume profile from recent bars.
        
        Args:
            bars: List of bar dicts with datetime, open, high, low, close, volume
            lookback_bars: Number of bars to analyze (default 78 = ~1.3 hours of 1m bars)
        
        Returns:
            Dict with:
              - poc: Point of Control price
              - poc_volume: Volume at POC
              - vah: Value Area High (top of 70% volume)
              - val: Value Area Low (bottom of 70% volume)
              - hvn_zones: List of (price_low, price_high) tuples for High Volume Nodes
              - lvn_zones: List of (price_low, price_high) tuples for Low Volume Nodes
              - profile: Full volume profile bins [(price, volume), ...]
              - error: Optional error message if edge case detected
        """
        # ⭐ Issue #4 Fix: Enhanced validation
        if not bars:
            return self._empty_result(error="No bars provided")
        
        if len(bars) < self.MIN_BARS_REQUIRED:
            return self._empty_result(
                error=f"Insufficient bars: {len(bars)} < {self.MIN_BARS_REQUIRED} required"
            )
        
        # Use only last N bars
        recent_bars = bars[-lookback_bars:] if len(bars) > lookback_bars else bars
        
        # ⭐ Issue #4 Fix: Filter bars with missing or invalid data
        valid_bars = [
            b for b in recent_bars
            if all(k in b for k in ['low', 'high', 'volume'])
            and b['high'] >= b['low']
            and b['volume'] >= 0
        ]
        
        if len(valid_bars) < self.MIN_BARS_REQUIRED:
            return self._empty_result(
                error=f"Insufficient valid bars: {len(valid_bars)} < {self.MIN_BARS_REQUIRED}"
            )
        
        # Find price range
        try:
            price_low = min(b["low"] for b in valid_bars)
            price_high = max(b["high"] for b in valid_bars)
        except (ValueError, KeyError) as e:
            return self._empty_result(error=f"Price range calculation error: {e}")
        
        price_range = price_high - price_low
        
        # ⭐ Issue #4 Fix: Handle flat price action
        if price_range < self.MIN_PRICE_RANGE:
            print(f"[VPVR] ⚠️  Flat price action detected (range: ${price_range:.4f})")
            # Return simplified result with POC at midpoint
            mid_price = (price_low + price_high) / 2
            total_volume = sum(b.get('volume', 0) for b in valid_bars)
            
            return {
                'poc': round(mid_price, 2),
                'poc_volume': round(total_volume, 0),
                'vah': round(price_high, 2),
                'val': round(price_low, 2),
                'hvn_zones': [(round(price_low, 2), round(price_high, 2))],  # Entire range is HVN
                'lvn_zones': [],
                'profile': [(round(mid_price, 2), total_volume)],
                'total_volume': round(total_volume, 0),
                'price_range': round(price_range, 2),
                'warning': 'Flat price action - limited profile accuracy'
            }
        
        # Create price bins
        bin_size = price_range / self.num_bins
        bins = [0.0] * self.num_bins  # Volume per bin
        bin_prices = [
            price_low + (i + 0.5) * bin_size
            for i in range(self.num_bins)
        ]
        
        # ⭐ Issue #4 Fix: Track bars with zero volume
        zero_volume_count = 0
        
        # Distribute volume across bins based on bar range
        for bar in valid_bars:
            bar_low = bar["low"]
            bar_high = bar["high"]
            bar_volume = bar.get("volume", 0)
            
            # ⭐ Issue #4 Fix: Handle zero volume bars
            if bar_volume <= 0:
                zero_volume_count += 1
                continue
            
            # Find bins that this bar spans
            start_bin = int((bar_low - price_low) / bin_size)
            end_bin = int((bar_high - price_low) / bin_size)
            
            # Clamp to valid range
            start_bin = max(0, min(start_bin, self.num_bins - 1))
            end_bin = max(0, min(end_bin, self.num_bins - 1))
            
            # Distribute volume evenly across bins the bar touched
            bins_touched = end_bin - start_bin + 1
            volume_per_bin = bar_volume / bins_touched
            
            for i in range(start_bin, end_bin + 1):
                bins[i] += volume_per_bin
        
        # ⭐ Issue #4 Fix: Validate total volume
        total_volume = sum(bins)
        
        if total_volume < self.MIN_TOTAL_VOLUME:
            print(f"[VPVR] ⚠️  Low total volume: {total_volume:,.0f}")
            return self._empty_result(
                error=f"Insufficient volume: {total_volume:,.0f} < {self.MIN_TOTAL_VOLUME:,.0f}"
            )
        
        if zero_volume_count > len(valid_bars) * 0.3:
            print(f"[VPVR] ⚠️  High zero-volume bar ratio: {zero_volume_count}/{len(valid_bars)}")
        
        # Find POC (Point of Control) - bin with highest volume
        try:
            poc_bin_idx = np.argmax(bins)
            poc_price = bin_prices[poc_bin_idx]
            poc_volume = bins[poc_bin_idx]
        except (ValueError, IndexError) as e:
            return self._empty_result(error=f"POC calculation error: {e}")
        
        # Calculate Value Area (70% of volume)
        target_volume = total_volume * 0.70
        
        # Start from POC and expand outward until we capture 70% volume
        try:
            vah_idx, val_idx = self._find_value_area(
                bins, poc_bin_idx, target_volume
            )
            vah = bin_prices[vah_idx]
            val = bin_prices[val_idx]
        except Exception as e:
            print(f"[VPVR] ⚠️  Value area calculation error: {e}")
            # Fallback to full range
            vah = price_high
            val = price_low
        
        # Identify HVN and LVN zones
        try:
            hvn_zones, lvn_zones = self._identify_nodes(
                bins, bin_prices, bin_size, total_volume
            )
        except Exception as e:
            print(f"[VPVR] ⚠️  Node identification error: {e}")
            hvn_zones = []
            lvn_zones = []
        
        # Build full profile for optional detailed analysis
        profile = list(zip(bin_prices, bins))
        
        result = {
            "poc": round(poc_price, 2),
            "poc_volume": round(poc_volume, 0),
            "vah": round(vah, 2),
            "val": round(val, 2),
            "hvn_zones": hvn_zones,
            "lvn_zones": lvn_zones,
            "profile": profile,
            "total_volume": round(total_volume, 0),
            "price_range": round(price_range, 2)
        }
        
        # Add warnings if edge cases detected
        if zero_volume_count > 0:
            result['zero_volume_bars'] = zero_volume_count
        
        return result
    
    def _find_value_area(self, bins: List[float], poc_idx: int, 
                        target_volume: float) -> Tuple[int, int]:
        """
        Find Value Area High and Low indices by expanding from POC.
        
        Args:
            bins: Volume distribution across bins
            poc_idx: Index of POC bin
            target_volume: Target volume (70% of total)
        
        Returns:
            (vah_idx, val_idx) tuple
        """
        if not bins or poc_idx >= len(bins) or poc_idx < 0:
            raise ValueError(f"Invalid POC index: {poc_idx}")
        
        accumulated_volume = bins[poc_idx]
        vah_idx = poc_idx
        val_idx = poc_idx
        
        # ⭐ Issue #4 Fix: Safety counter to prevent infinite loops
        max_iterations = len(bins) * 2
        iterations = 0
        
        # Expand outward from POC until we capture target volume
        while accumulated_volume < target_volume and iterations < max_iterations:
            iterations += 1
            
            # Check which direction has more volume
            volume_above = bins[vah_idx + 1] if vah_idx + 1 < len(bins) else 0
            volume_below = bins[val_idx - 1] if val_idx - 1 >= 0 else 0
            
            # ⭐ Issue #4 Fix: Handle case where both directions are exhausted
            if volume_above == 0 and volume_below == 0:
                break
            
            if volume_above > volume_below and vah_idx + 1 < len(bins):
                vah_idx += 1
                accumulated_volume += bins[vah_idx]
            elif val_idx - 1 >= 0:
                val_idx -= 1
                accumulated_volume += bins[val_idx]
            else:
                break  # Can't expand further
        
        return vah_idx, val_idx
    
    def _identify_nodes(self, bins: List[float], bin_prices: List[float],
                       bin_size: float, total_volume: float) -> Tuple[List, List]:
        """
        Identify High Volume Nodes (HVN) and Low Volume Nodes (LVN).
        
        Args:
            bins: Volume distribution
            bin_prices: Price at each bin center
            bin_size: Width of each bin
            total_volume: Total volume across all bins
        
        Returns:
            (hvn_zones, lvn_zones) tuple of lists
        """
        # ⭐ Issue #4 Fix: Enhanced validation
        if not bins or total_volume == 0 or len(bins) != len(bin_prices):
            return [], []
        
        avg_volume = total_volume / len(bins)
        
        # ⭐ Issue #4 Fix: Avoid thresholds on very low average volume
        if avg_volume < 10:
            print(f"[VPVR] ⚠️  Very low average volume per bin: {avg_volume:.1f}")
            return [], []
        
        # HVN: Bins with volume > 150% of average
        hvn_threshold = avg_volume * 1.5
        # LVN: Bins with volume < 50% of average
        lvn_threshold = avg_volume * 0.5
        
        hvn_zones = []
        lvn_zones = []
        
        # Group consecutive bins into zones
        i = 0
        while i < len(bins):
            if bins[i] >= hvn_threshold:
                # Start of HVN zone
                zone_start = i
                while i < len(bins) and bins[i] >= hvn_threshold:
                    i += 1
                zone_end = i - 1
                
                price_low = bin_prices[zone_start] - bin_size / 2
                price_high = bin_prices[zone_end] + bin_size / 2
                hvn_zones.append((round(price_low, 2), round(price_high, 2)))
            
            elif bins[i] <= lvn_threshold:
                # Start of LVN zone
                zone_start = i
                while i < len(bins) and bins[i] <= lvn_threshold:
                    i += 1
                zone_end = i - 1
                
                price_low = bin_prices[zone_start] - bin_size / 2
                price_high = bin_prices[zone_end] + bin_size / 2
                lvn_zones.append((round(price_low, 2), round(price_high, 2)))
            else:
                i += 1
        
        return hvn_zones, lvn_zones
    
    def _empty_result(self, error: str = None) -> Dict:
        """
        Return empty result when insufficient data.
        
        Args:
            error: Optional error message describing why result is empty
        """
        result = {
            "poc": None,
            "poc_volume": 0,
            "vah": None,
            "val": None,
            "hvn_zones": [],
            "lvn_zones": [],
            "profile": [],
            "total_volume": 0,
            "price_range": 0
        }
        
        if error:
            result['error'] = error
            print(f"[VPVR] {error}")
        
        return result
    
    def get_entry_score(self, price: float, vpvr: Dict) -> Tuple[float, str]:
        """
        Score an entry price based on VPVR analysis.
        
        Args:
            price: Proposed entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            (score, reason) tuple
              score: 0.0 - 1.0 (higher is better)
              reason: Human-readable explanation
        """
        # ⭐ Issue #4 Fix: Better edge case handling
        if not vpvr:
            return 0.5, "No VPVR data"
        
        if 'error' in vpvr:
            return 0.5, f"VPVR error: {vpvr['error']}"
        
        if vpvr["poc"] is None:
            return 0.5, "No POC calculated"
        
        # ⭐ Issue #4 Fix: Handle warnings
        if 'warning' in vpvr:
            print(f"[VPVR] Entry score calculated with warning: {vpvr['warning']}")
        
        poc = vpvr["poc"]
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr["hvn_zones"]
        lvn_zones = vpvr["lvn_zones"]
        
        # ⭐ Issue #4 Fix: Division by zero protection
        if poc == 0:
            return 0.5, "Invalid POC (zero price)"
        
        # Best: Entry at or near POC (institutional support)
        poc_distance_pct = abs(price - poc) / poc * 100
        if poc_distance_pct < 0.3:  # Within 0.3% of POC
            return 1.0, f"At POC (${poc:.2f}) - strongest support"
        
        # Good: Entry within HVN zone (high volume area)
        for hvn_low, hvn_high in hvn_zones:
            if hvn_low <= price <= hvn_high:
                return 0.85, f"In HVN zone (${hvn_low:.2f}-${hvn_high:.2f})"
        
        # Good: Entry within Value Area (70% volume)
        if vah and val and val <= price <= vah:
            return 0.75, f"In Value Area (${val:.2f}-${vah:.2f})"
        
        # Risky: Entry in LVN zone (thin volume, whipsaw risk)
        for lvn_low, lvn_high in lvn_zones:
            if lvn_low <= price <= lvn_high:
                return 0.3, f"⚠️  In LVN zone (${lvn_low:.2f}-${lvn_high:.2f}) - thin volume"
        
        # Neutral: Outside value area but not in LVN
        if vah and price > vah:
            return 0.55, f"Above Value Area (VAH: ${vah:.2f})"
        elif val and price < val:
            return 0.55, f"Below Value Area (VAL: ${val:.2f})"
        else:
            return 0.6, "Near value area"
    
    def get_stop_recommendation(self, direction: str, entry: float, 
                               vpvr: Dict) -> Optional[float]:
        """
        Recommend stop-loss placement based on volume profile.
        
        Args:
            direction: "bull" or "bear"
            entry: Entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Recommended stop price or None
        """
        if not vpvr or not vpvr.get("lvn_zones") or 'error' in vpvr:
            return None
        
        lvn_zones = vpvr["lvn_zones"]
        
        if direction == "bull":
            # For longs, find LVN below entry (price likely to slice through)
            candidates = [
                lvn_low for lvn_low, lvn_high in lvn_zones
                if lvn_high < entry
            ]
            if candidates:
                # Return bottom of closest LVN below entry
                return max(candidates)
        
        else:  # bear
            # For shorts, find LVN above entry
            candidates = [
                lvn_high for lvn_low, lvn_high in lvn_zones
                if lvn_low > entry
            ]
            if candidates:
                # Return top of closest LVN above entry
                return min(candidates)
        
        return None
    
    def get_target_recommendation(self, direction: str, entry: float,
                                 vpvr: Dict) -> Optional[float]:
        """
        Recommend profit target based on volume profile.
        
        Args:
            direction: "bull" or "bear"
            entry: Entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Recommended target price or None
        """
        if not vpvr or vpvr.get("vah") is None or 'error' in vpvr:
            return None
        
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr.get("hvn_zones", [])
        
        if direction == "bull":
            # For longs, target VAH or next HVN above entry
            if vah > entry:
                return vah
            
            # Find next HVN above VAH
            candidates = [
                hvn_low for hvn_low, hvn_high in hvn_zones
                if hvn_low > vah
            ]
            if candidates:
                return min(candidates)
        
        else:  # bear
            # For shorts, target VAL or next HVN below entry
            if val and val < entry:
                return val
            
            # Find next HVN below VAL
            candidates = [
                hvn_high for hvn_low, hvn_high in hvn_zones
                if hvn_high < val
            ]
            if candidates:
                return max(candidates)
        
        return None
    
    def format_vpvr_summary(self, vpvr: Dict) -> str:
        """
        Format VPVR data for console display.
        
        Args:
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Formatted string
        """
        if not vpvr:
            return "[VPVR] No volume profile data available"
        
        if 'error' in vpvr:
            return f"[VPVR] Error: {vpvr['error']}"
        
        if vpvr.get("poc") is None:
            return "[VPVR] No volume profile data available"
        
        lines = [
            f"[VPVR] POC: ${vpvr['poc']:.2f} (vol: {vpvr['poc_volume']:,.0f})",
            f"[VPVR] Value Area: ${vpvr['val']:.2f} - ${vpvr['vah']:.2f}"
        ]
        
        if 'warning' in vpvr:
            lines.append(f"[VPVR] ⚠️  Warning: {vpvr['warning']}")
        
        if vpvr.get("hvn_zones"):
            hvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["hvn_zones"]
            )
            lines.append(f"[VPVR] HVN Zones: {hvn_str}")
        
        if vpvr.get("lvn_zones"):
            lvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["lvn_zones"]
            )
            lines.append(f"[VPVR] LVN Zones: {lvn_str} (⚠️  thin volume)")
        
        if 'zero_volume_bars' in vpvr and vpvr['zero_volume_bars'] > 0:
            lines.append(f"[VPVR] Zero-volume bars: {vpvr['zero_volume_bars']}")
        
        return "\n".join(lines)


# ── Global singleton ──────────────────────────────────────────────────────────────────
vpvr_calculator = VPVRCalculator(num_bins=30)
