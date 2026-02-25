"""
Volume Profile Value Area Ratio (VPVR) Calculator

Provides volume profile analysis for better entry/exit precision:
  - Point of Control (POC): Price level with highest traded volume
  - High Volume Nodes (HVN): Price clusters with heavy activity
  - Low Volume Nodes (LVN): Price zones with thin trading (potential breakout areas)
  - Value Area High/Low (VAH/VAL): 70% volume distribution boundaries

Integration: Called by signal_validator.py and sniper.py for entry refinement.
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
        """
        if not bars or len(bars) < 10:
            return self._empty_result()
        
        # Use only last N bars
        recent_bars = bars[-lookback_bars:] if len(bars) > lookback_bars else bars
        
        # Find price range
        price_low = min(b["low"] for b in recent_bars)
        price_high = max(b["high"] for b in recent_bars)
        price_range = price_high - price_low
        
        if price_range < 0.01:  # Avoid division by zero
            return self._empty_result()
        
        # Create price bins
        bin_size = price_range / self.num_bins
        bins = [0.0] * self.num_bins  # Volume per bin
        bin_prices = [
            price_low + (i + 0.5) * bin_size
            for i in range(self.num_bins)
        ]
        
        # Distribute volume across bins based on bar range
        for bar in recent_bars:
            bar_low = bar["low"]
            bar_high = bar["high"]
            bar_volume = bar["volume"]
            
            if bar_volume <= 0:
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
        
        # Find POC (Point of Control) - bin with highest volume
        poc_bin_idx = np.argmax(bins)
        poc_price = bin_prices[poc_bin_idx]
        poc_volume = bins[poc_bin_idx]
        
        # Calculate Value Area (70% of volume)
        total_volume = sum(bins)
        target_volume = total_volume * 0.70
        
        # Start from POC and expand outward until we capture 70% volume
        vah_idx, val_idx = self._find_value_area(
            bins, poc_bin_idx, target_volume
        )
        
        vah = bin_prices[vah_idx]
        val = bin_prices[val_idx]
        
        # Identify HVN and LVN zones
        hvn_zones, lvn_zones = self._identify_nodes(
            bins, bin_prices, bin_size, total_volume
        )
        
        # Build full profile for optional detailed analysis
        profile = list(zip(bin_prices, bins))
        
        return {
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
        accumulated_volume = bins[poc_idx]
        vah_idx = poc_idx
        val_idx = poc_idx
        
        # Expand outward from POC until we capture target volume
        while accumulated_volume < target_volume:
            # Check which direction has more volume
            volume_above = bins[vah_idx + 1] if vah_idx + 1 < len(bins) else 0
            volume_below = bins[val_idx - 1] if val_idx - 1 >= 0 else 0
            
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
        if total_volume == 0:
            return [], []
        
        avg_volume = total_volume / len(bins)
        
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
    
    def _empty_result(self) -> Dict:
        """Return empty result when insufficient data."""
        return {
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
        if not vpvr or vpvr["poc"] is None:
            return 0.5, "No VPVR data"
        
        poc = vpvr["poc"]
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr["hvn_zones"]
        lvn_zones = vpvr["lvn_zones"]
        
        # Best: Entry at or near POC (institutional support)
        poc_distance_pct = abs(price - poc) / poc * 100
        if poc_distance_pct < 0.3:  # Within 0.3% of POC
            return 1.0, f"At POC (${poc:.2f}) - strongest support"
        
        # Good: Entry within HVN zone (high volume area)
        for hvn_low, hvn_high in hvn_zones:
            if hvn_low <= price <= hvn_high:
                return 0.85, f"In HVN zone (${hvn_low:.2f}-${hvn_high:.2f})"
        
        # Good: Entry within Value Area (70% volume)
        if val <= price <= vah:
            return 0.75, f"In Value Area (${val:.2f}-${vah:.2f})"
        
        # Risky: Entry in LVN zone (thin volume, whipsaw risk)
        for lvn_low, lvn_high in lvn_zones:
            if lvn_low <= price <= lvn_high:
                return 0.3, f"⚠️ In LVN zone (${lvn_low:.2f}-${lvn_high:.2f}) - thin volume"
        
        # Neutral: Outside value area but not in LVN
        if price > vah:
            return 0.55, f"Above Value Area (VAH: ${vah:.2f})"
        else:
            return 0.55, f"Below Value Area (VAL: ${val:.2f})"
    
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
        if not vpvr or not vpvr["lvn_zones"]:
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
        if not vpvr or vpvr["vah"] is None:
            return None
        
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr["hvn_zones"]
        
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
            if val < entry:
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
        if not vpvr or vpvr["poc"] is None:
            return "[VPVR] No volume profile data available"
        
        lines = [
            f"[VPVR] POC: ${vpvr['poc']:.2f} (vol: {vpvr['poc_volume']:,.0f})",
            f"[VPVR] Value Area: ${vpvr['val']:.2f} - ${vpvr['vah']:.2f}"
        ]
        
        if vpvr["hvn_zones"]:
            hvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["hvn_zones"]
            )
            lines.append(f"[VPVR] HVN Zones: {hvn_str}")
        
        if vpvr["lvn_zones"]:
            lvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["lvn_zones"]
            )
            lines.append(f"[VPVR] LVN Zones: {lvn_str} (⚠️ thin volume)")
        
        return "\n".join(lines)


# ── Global singleton ──────────────────────────────────────────────────────────────────
vpvr_calculator = VPVRCalculator(num_bins=30)
