"""
Multi-Timeframe FVG Detection Engine

Detects Fair Value Gap (FVG) patterns simultaneously across multiple
timeframes (5m, 3m, 2m, 1m) and identifies convergence zones.

Convergence Logic:
  - Strict Mode: Requires FVG on at least 3 of 4 timeframes
  - All FVG zones must overlap by at least 50%
  - Primary timeframe (5m) must always be present
  - Higher timeframes weighted more heavily

Pattern Detection:
  1. BOS (Break of Structure) - Price breaks previous high/low
  2. FVG (Fair Value Gap) - Gap between candle 0 high and candle 2 low
  3. Zone Alignment - Multiple timeframes show same FVG zone

Output:
  - Direction (bull/bear)
  - Consensus FVG zone (overlapping region)
  - Timeframes aligned count
  - Per-timeframe pattern metadata
  - Convergence confidence score

Usage:
  from mtf_fvg_engine import mtf_fvg_engine
  
  # Detect MTF signal
  signal = mtf_fvg_engine.detect_mtf_signal('AAPL')
  
  if signal:
      print(f"Direction: {signal['direction']}")
      print(f"Zone: ${signal['zone_low']:.2f} - ${signal['zone_high']:.2f}")
      print(f"Timeframes: {signal['timeframes_aligned']} / {signal['timeframes_checked']}")
      print(f"Confidence: {signal['convergence_score']:.2f}")
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, time as dtime
import config
from mtf_data_manager import mtf_data_manager, TIMEFRAMES

# Convergence requirements (Strict mode)
MIN_TIMEFRAMES_REQUIRED = 3  # Must have FVG on at least 3 timeframes
MIN_ZONE_OVERLAP_PCT = 0.50  # Zones must overlap by 50%+

# Timeframe weights for scoring (higher = more important)
TIMEFRAME_WEIGHTS = {
    '5m': 0.40,
    '3m': 0.30,
    '2m': 0.20,
    '1m': 0.10
}


class MTFFVGEngine:
    """Multi-timeframe FVG pattern detection engine."""
    
    def __init__(self):
        self.stats = {
            'signals_detected': 0,
            'convergence_passed': 0,
            'convergence_failed': 0
        }
        
        print("[MTF-FVG] Multi-Timeframe FVG Engine initialized")
        print(f"[MTF-FVG] Convergence: {MIN_TIMEFRAMES_REQUIRED}+ timeframes required")
        print(f"[MTF-FVG] Zone overlap: {MIN_ZONE_OVERLAP_PCT*100:.0f}% minimum")
    
    def _detect_bos(self, bars: List[Dict], direction: str) -> Optional[int]:
        """
        Detect Break of Structure (BOS) - price breaks previous swing high/low.
        
        Args:
            bars: List of bar dicts
            direction: 'bull' or 'bear'
        
        Returns:
            Index of BOS bar or None if not found
        """
        if len(bars) < 10:
            return None
        
        # Use OR breakout logic similar to sniper.py
        if direction == 'bull':
            # Find recent swing high
            swing_high = max(bar['high'] for bar in bars[-20:-5])
            
            # Look for break above swing high
            for i in range(len(bars) - 5, len(bars)):
                if bars[i]['close'] > swing_high * 1.002:  # 0.2% break threshold
                    return i
        else:  # bear
            # Find recent swing low
            swing_low = min(bar['low'] for bar in bars[-20:-5])
            
            # Look for break below swing low
            for i in range(len(bars) - 5, len(bars)):
                if bars[i]['close'] < swing_low * 0.998:
                    return i
        
        return None
    
    def _detect_fvg(self, bars: List[Dict], bos_idx: int, direction: str) -> Optional[Tuple[float, float]]:
        """
        Detect Fair Value Gap after BOS.
        
        Args:
            bars: List of bar dicts
            bos_idx: Index of BOS bar
            direction: 'bull' or 'bear'
        
        Returns:
            (fvg_low, fvg_high) tuple or None if not found
        """
        # Look for FVG in 3-5 bars after BOS
        for i in range(bos_idx + 3, min(bos_idx + 8, len(bars))):
            if i < 2:
                continue
            
            c0 = bars[i - 2]
            c2 = bars[i]
            
            if direction == 'bull':
                gap = c2['low'] - c0['high']
                if gap > 0:
                    gap_pct = gap / c0['high']
                    # Use adaptive threshold from config
                    min_gap = getattr(config, 'FVG_MIN_SIZE_PCT', 0.002)
                    
                    if gap_pct >= min_gap:
                        return (c0['high'], c2['low'])
            
            else:  # bear
                gap = c0['low'] - c2['high']
                if gap > 0:
                    gap_pct = gap / c0['low']
                    min_gap = getattr(config, 'FVG_MIN_SIZE_PCT', 0.002)
                    
                    if gap_pct >= min_gap:
                        return (c2['high'], c0['low'])
        
        return None
    
    def _detect_pattern_single_timeframe(self, bars: List[Dict], direction: str) -> Optional[Dict]:
        """
        Detect BOS + FVG pattern on a single timeframe.
        
        Args:
            bars: List of bar dicts for specific timeframe
            direction: 'bull' or 'bear'
        
        Returns:
            Dict with pattern data or None if not found
        """
        if not bars or len(bars) < 15:
            return None
        
        # Detect BOS
        bos_idx = self._detect_bos(bars, direction)
        if bos_idx is None:
            return None
        
        # Detect FVG after BOS
        fvg_zone = self._detect_fvg(bars, bos_idx, direction)
        if fvg_zone is None:
            return None
        
        fvg_low, fvg_high = fvg_zone
        
        return {
            'direction': direction,
            'bos_idx': bos_idx,
            'bos_price': bars[bos_idx]['close'],
            'fvg_low': fvg_low,
            'fvg_high': fvg_high,
            'fvg_size': fvg_high - fvg_low,
            'fvg_size_pct': ((fvg_high - fvg_low) / fvg_low) * 100
        }
    
    def _calculate_zone_overlap(self, zone1: Tuple[float, float], zone2: Tuple[float, float]) -> float:
        """
        Calculate percentage overlap between two FVG zones.
        
        Args:
            zone1: (low, high) tuple
            zone2: (low, high) tuple
        
        Returns:
            Overlap percentage (0.0 - 1.0)
        """
        low1, high1 = zone1
        low2, high2 = zone2
        
        # Find overlapping region
        overlap_low = max(low1, low2)
        overlap_high = min(high1, high2)
        
        # No overlap
        if overlap_low >= overlap_high:
            return 0.0
        
        # Calculate overlap as percentage of smaller zone
        overlap_size = overlap_high - overlap_low
        zone1_size = high1 - low1
        zone2_size = high2 - low2
        smaller_zone_size = min(zone1_size, zone2_size)
        
        if smaller_zone_size == 0:
            return 0.0
        
        return overlap_size / smaller_zone_size
    
    def _find_consensus_zone(self, patterns: Dict[str, Dict]) -> Optional[Tuple[float, float]]:
        """
        Find consensus FVG zone from multiple timeframe patterns.
        
        Uses the overlapping region across all detected FVG zones.
        
        Args:
            patterns: Dict mapping timeframe -> pattern dict
        
        Returns:
            (consensus_low, consensus_high) or None if no valid overlap
        """
        if not patterns:
            return None
        
        # Start with first pattern's zone
        zones = [(p['fvg_low'], p['fvg_high']) for p in patterns.values()]
        
        # Find maximum of all lows (bottom of consensus zone)
        consensus_low = max(zone[0] for zone in zones)
        
        # Find minimum of all highs (top of consensus zone)
        consensus_high = min(zone[1] for zone in zones)
        
        # Valid consensus zone must have positive height
        if consensus_low >= consensus_high:
            return None
        
        return (consensus_low, consensus_high)
    
    def detect_mtf_signal(self, ticker: str) -> Optional[Dict]:
        """
        Detect MTF FVG signal with strict convergence requirements.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Dict with signal data or None if no convergent signal found
        """
        # Fetch all timeframes
        all_data = mtf_data_manager.get_all_timeframes(ticker)
        
        # Try both directions
        for direction in ['bull', 'bear']:
            patterns = {}
            
            # Detect pattern on each timeframe
            for timeframe, bars in all_data.items():
                if not bars or len(bars) < 15:
                    continue
                
                pattern = self._detect_pattern_single_timeframe(bars, direction)
                if pattern:
                    patterns[timeframe] = pattern
            
            # Check convergence requirements
            if len(patterns) < MIN_TIMEFRAMES_REQUIRED:
                continue
            
            # Verify 5m (primary) is present
            if '5m' not in patterns:
                continue
            
            # Check zone overlap between all patterns
            timeframes_list = list(patterns.keys())
            all_overlap = True
            
            for i in range(len(timeframes_list)):
                for j in range(i + 1, len(timeframes_list)):
                    tf1 = timeframes_list[i]
                    tf2 = timeframes_list[j]
                    
                    zone1 = (patterns[tf1]['fvg_low'], patterns[tf1]['fvg_high'])
                    zone2 = (patterns[tf2]['fvg_low'], patterns[tf2]['fvg_high'])
                    
                    overlap = self._calculate_zone_overlap(zone1, zone2)
                    
                    if overlap < MIN_ZONE_OVERLAP_PCT:
                        all_overlap = False
                        break
                
                if not all_overlap:
                    break
            
            if not all_overlap:
                self.stats['convergence_failed'] += 1
                continue
            
            # Find consensus zone
            consensus_zone = self._find_consensus_zone(patterns)
            if not consensus_zone:
                continue
            
            # Calculate convergence score (weighted by timeframe)
            convergence_score = sum(
                TIMEFRAME_WEIGHTS.get(tf, 0.0)
                for tf in patterns.keys()
            )
            
            self.stats['signals_detected'] += 1
            self.stats['convergence_passed'] += 1
            
            # Build signal data
            signal = {
                'ticker': ticker,
                'direction': direction,
                'zone_low': consensus_zone[0],
                'zone_high': consensus_zone[1],
                'zone_size': consensus_zone[1] - consensus_zone[0],
                'timeframes_aligned': len(patterns),
                'timeframes_checked': len(TIMEFRAMES),
                'convergence_score': round(convergence_score, 3),
                'primary_timeframe': '5m',
                'patterns_by_timeframe': patterns,
                'detection_time': datetime.now()
            }
            
            return signal
        
        return None
    
    def scan_multiple_tickers(self, tickers: List[str]) -> List[Dict]:
        """
        Scan multiple tickers for MTF FVG signals.
        
        Args:
            tickers: List of stock symbols
        
        Returns:
            List of signal dicts
        """
        # Batch update all tickers first
        mtf_data_manager.batch_update(tickers)
        
        signals = []
        for ticker in tickers:
            signal = self.detect_mtf_signal(ticker)
            if signal:
                signals.append(signal)
        
        return signals
    
    def get_stats(self) -> Dict:
        """Get detection statistics."""
        total = self.stats['convergence_passed'] + self.stats['convergence_failed']
        pass_rate = (self.stats['convergence_passed'] / total * 100) if total > 0 else 0
        
        return {
            **self.stats,
            'convergence_pass_rate': round(pass_rate, 1)
        }
    
    def print_signal(self, signal: Dict):
        """Pretty print a signal."""
        if not signal:
            print("No signal")
            return
        
        arrow = "🟢" if signal['direction'] == 'bull' else "🔴"
        
        print("\n" + "="*80)
        print(f"MTF SIGNAL DETECTED: {signal['ticker']} {arrow} {signal['direction'].upper()}")
        print("="*80)
        print(f"Consensus Zone:      ${signal['zone_low']:.2f} - ${signal['zone_high']:.2f}")
        print(f"Zone Size:           ${signal['zone_size']:.2f} ({(signal['zone_size']/signal['zone_low']*100):.2f}%)")
        print(f"Timeframes Aligned:  {signal['timeframes_aligned']} / {signal['timeframes_checked']}")
        print(f"Convergence Score:   {signal['convergence_score']:.3f}")
        print(f"\nTimeframe Breakdown:")
        
        for tf in ['5m', '3m', '2m', '1m']:
            if tf in signal['patterns_by_timeframe']:
                pattern = signal['patterns_by_timeframe'][tf]
                print(f"  {tf}: ${pattern['fvg_low']:.2f} - ${pattern['fvg_high']:.2f} "
                      f"(size: {pattern['fvg_size_pct']:.2f}%)")
            else:
                print(f"  {tf}: No pattern detected")
        
        print("="*80 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

mtf_fvg_engine = MTFFVGEngine()


# ══════════════════════════════════════════════════════════════════════════════
# TESTING & CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    print("\n🔍 MTF FVG Engine Test\n")
    
    # Test with sample ticker
    test_ticker = "AAPL"
    
    if len(sys.argv) > 1:
        test_ticker = sys.argv[1].upper()
    
    print(f"Testing with ticker: {test_ticker}\n")
    
    # Detect signal
    print("[TEST] Detecting MTF signal...")
    signal = mtf_fvg_engine.detect_mtf_signal(test_ticker)
    
    if signal:
        mtf_fvg_engine.print_signal(signal)
        print("✅ MTF signal detected!")
    else:
        print("❌ No MTF signal found (strict convergence not met)")
    
    # Print stats
    stats = mtf_fvg_engine.get_stats()
    print("\nEngine Statistics:")
    print(f"  Signals Detected:      {stats['signals_detected']}")
    print(f"  Convergence Passed:    {stats['convergence_passed']}")
    print(f"  Convergence Failed:    {stats['convergence_failed']}")
    print(f"  Pass Rate:             {stats['convergence_pass_rate']:.1f}%")
    
    print("\n✅ MTF FVG Engine test complete!\n")
