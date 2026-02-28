"""
Multi-Timeframe FVG Detection Engine - Simplified Version

Detects CFW6 BOS+FVG patterns across 5m (primary) and 3m (secondary) timeframes
and calculates convergence scores based on zone alignment.

Simplified Strategy:
  - 5m: Primary timeframe (70% weight) - from existing data_manager
  - 3m: Secondary timeframe (30% weight) - aggregated from 1m
  - Requires both timeframes to show FVG in aligned zones
  - Convergence score based on zone overlap quality

Usage:
  from mtf_fvg_engine import mtf_fvg_engine
  from mtf_data_manager import mtf_data_manager
  
  # Get both timeframes
  bars_dict = mtf_data_manager.get_all_timeframes('SPY')
  
  # Detect MTF signal
  result = mtf_fvg_engine.detect_mtf_signal('SPY', bars_dict)
  
  if result:
      print(f"MTF Signal: {result['direction']} with {result['convergence_score']:.2f} convergence")
      print(f"Zone: ${result['zone_low']:.2f} - ${result['zone_high']:.2f}")
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, time
import statistics

import config
from bos_fvg_engine import scan_bos_fvg
from trade_calculator import get_adaptive_fvg_threshold


class MTFFVGEngine:
    """Simplified multi-timeframe FVG detection (5m + 3m convergence)."""
    
    def __init__(self):
        # Timeframe priority weights (must sum to 1.0)
        self.timeframe_weights = {
            '5m': 0.70,  # Primary timeframe
            '3m': 0.30   # Secondary timeframe (derived from 1m)
        }
        
        # Convergence requirements (adjusted for 2-TF strategy)
        self.min_convergence_score = 0.50  # Lower threshold (only 2 TFs)
        self.min_timeframes_required = 2   # Both timeframes must show FVG
        self.min_zone_overlap_pct = 0.25   # Zones must overlap by 25%+
        
        # Always require 5m (primary)
        self.require_5m = True
        
        print("[MTF-FVG] Engine initialized (Simplified Mode)")
        print(f"[MTF-FVG] Strategy: 5m (primary) + 3m (secondary)")
        print(f"[MTF-FVG] Min convergence: {self.min_convergence_score:.1%}")
        print(f"[MTF-FVG] Min overlap: {self.min_zone_overlap_pct:.1%}")
    
    def detect_mtf_signal(self, ticker: str, bars_dict: Dict[str, List[dict]]) -> Optional[Dict]:
        """
        Detect CFW6 signal with 5m + 3m convergence.
        
        Args:
            ticker: Stock symbol
            bars_dict: Dict mapping timeframe -> bars
                      Example: {'5m': [...], '3m': [...]}
        
        Returns:
            Dict with MTF signal details or None if no convergence
            {
                'ticker': str,
                'direction': 'bull' | 'bear',
                'zone_low': float,
                'zone_high': float,
                'convergence_score': float (0.0 - 1.0),
                'timeframes_aligned': List[str],
                'signals_by_tf': Dict[str, Dict],
                'bos_idx': int,
                'bos_price': float
            }
        """
        # Validate input
        if not bars_dict:
            return None
        
        # Require 5m timeframe
        if self.require_5m and '5m' not in bars_dict:
            print(f"[MTF-FVG] {ticker} - 5m timeframe required but not available")
            return None
        
        # Detect FVG on each available timeframe
        signals_by_tf = {}
        for tf in ['5m', '3m']:
            if tf not in bars_dict:
                continue
            
            bars = bars_dict[tf]
            if len(bars) < 30:  # Minimum bars required
                continue
            
            # Run CFW6 BOS+FVG detection
            signal = self._detect_fvg_single_tf(ticker, bars, tf)
            if signal:
                signals_by_tf[tf] = signal
        
        # Check if we have both timeframes
        if len(signals_by_tf) < self.min_timeframes_required:
            return None
        
        # Analyze convergence
        convergence = self._analyze_convergence(ticker, signals_by_tf)
        if not convergence:
            return None
        
        # Check convergence score threshold
        if convergence['score'] < self.min_convergence_score:
            print(f"[MTF-FVG] {ticker} - Convergence {convergence['score']:.2f} below threshold {self.min_convergence_score:.2f}")
            return None
        
        # Build MTF signal result
        primary_signal = signals_by_tf['5m']
        
        result = {
            'ticker': ticker,
            'direction': convergence['direction'],
            'zone_low': convergence['zone_low'],
            'zone_high': convergence['zone_high'],
            'convergence_score': round(convergence['score'], 3),
            'timeframes_aligned': convergence['timeframes'],
            'signals_by_tf': signals_by_tf,
            'bos_idx': primary_signal['bos_idx'],
            'bos_price': primary_signal['bos_price'],
            'primary_timeframe': '5m'
        }
        
        print(f"[MTF-FVG] ✅ {ticker} MTF {convergence['direction'].upper()} signal")
        print(f"[MTF-FVG]    Convergence: {convergence['score']:.1%} | TFs: {', '.join(convergence['timeframes'])}")
        print(f"[MTF-FVG]    Zone: ${convergence['zone_low']:.2f} - ${convergence['zone_high']:.2f}")
        
        return result
    
    def _detect_fvg_single_tf(self, ticker: str, bars: List[dict], timeframe: str) -> Optional[Dict]:
        """
        Detect BOS+FVG pattern on a single timeframe.
        
        Args:
            ticker: Stock symbol
            bars: List of bars for this timeframe
            timeframe: Timeframe string ('5m' or '3m')
        
        Returns:
            Dict with signal details or None
        """
        try:
            # Get adaptive FVG threshold
            fvg_threshold, _ = get_adaptive_fvg_threshold(bars, ticker)
            
            # Run BOS+FVG detection
            signal = scan_bos_fvg(ticker, bars, fvg_min_pct=fvg_threshold)
            
            if signal:
                return {
                    'direction': signal['direction'],
                    'fvg_low': signal['fvg_low'],
                    'fvg_high': signal['fvg_high'],
                    'bos_idx': signal['bos_idx'],
                    'bos_price': signal['bos_price'],
                    'timeframe': timeframe
                }
            
            return None
        
        except Exception as e:
            print(f"[MTF-FVG] Error detecting FVG on {ticker} {timeframe}: {e}")
            return None
    
    def _analyze_convergence(self, ticker: str, signals_by_tf: Dict[str, Dict]) -> Optional[Dict]:
        """
        Analyze FVG convergence across 5m and 3m timeframes.
        
        Args:
            ticker: Stock symbol
            signals_by_tf: Dict mapping timeframe -> signal details
        
        Returns:
            Dict with convergence analysis or None if no convergence
        """
        # Group signals by direction
        bull_signals = {tf: sig for tf, sig in signals_by_tf.items() if sig['direction'] == 'bull'}
        bear_signals = {tf: sig for tf, sig in signals_by_tf.items() if sig['direction'] == 'bear'}
        
        # Determine dominant direction
        bull_weight = sum(self.timeframe_weights.get(tf, 0) for tf in bull_signals.keys())
        bear_weight = sum(self.timeframe_weights.get(tf, 0) for tf in bear_signals.keys())
        
        if bull_weight > bear_weight:
            direction = 'bull'
            aligned_signals = bull_signals
        elif bear_weight > bull_weight:
            direction = 'bear'
            aligned_signals = bear_signals
        else:
            # Tie - no clear direction
            return None
        
        # Check if we have both timeframes in aligned direction
        if len(aligned_signals) < self.min_timeframes_required:
            return None
        
        # Calculate zone overlap
        zone_low, zone_high, overlap_score = self._calculate_zone_overlap(aligned_signals)
        
        if overlap_score < self.min_zone_overlap_pct:
            print(f"[MTF-FVG] {ticker} - Zone overlap {overlap_score:.1%} below threshold {self.min_zone_overlap_pct:.1%}")
            return None
        
        # Calculate weighted convergence score
        convergence_score = sum(
            self.timeframe_weights.get(tf, 0) 
            for tf in aligned_signals.keys()
        )
        
        # Bonus for zone overlap quality
        convergence_score *= (0.7 + (overlap_score * 0.3))  # Up to +30% bonus for perfect overlap
        
        return {
            'direction': direction,
            'zone_low': zone_low,
            'zone_high': zone_high,
            'score': convergence_score,
            'overlap_score': overlap_score,
            'timeframes': list(aligned_signals.keys())
        }
    
    def _calculate_zone_overlap(self, signals: Dict[str, Dict]) -> Tuple[float, float, float]:
        """
        Calculate overlapping FVG zone across timeframes.
        
        Args:
            signals: Dict mapping timeframe -> signal details
        
        Returns:
            (zone_low, zone_high, overlap_score)
        """
        # Get all FVG zones
        zones = [(sig['fvg_low'], sig['fvg_high']) for sig in signals.values()]
        
        if not zones:
            return 0.0, 0.0, 0.0
        
        # Calculate intersection zone (max of lows, min of highs)
        zone_low = max(low for low, _ in zones)
        zone_high = min(high for _, high in zones)
        
        # If zones don't overlap
        if zone_low >= zone_high:
            # Fallback: use average zone
            all_lows = [low for low, _ in zones]
            all_highs = [high for _, high in zones]
            zone_low = statistics.mean(all_lows)
            zone_high = statistics.mean(all_highs)
            overlap_score = 0.0
        else:
            # Calculate overlap quality
            overlap_size = zone_high - zone_low
            avg_zone_size = statistics.mean((high - low) for low, high in zones)
            overlap_score = min(1.0, overlap_size / avg_zone_size) if avg_zone_size > 0 else 0.0
        
        return zone_low, zone_high, overlap_score
    
    def get_mtf_boost_value(self, convergence_score: float) -> float:
        """
        Calculate confidence boost based on MTF convergence score.
        
        Args:
            convergence_score: Convergence score from detect_mtf_signal()
        
        Returns:
            Confidence boost value (0.00 - 0.10)
        """
        # Linear scale: 50% convergence = 0.00, 100% convergence = 0.10
        if convergence_score < self.min_convergence_score:
            return 0.0
        
        normalized = (convergence_score - self.min_convergence_score) / (1.0 - self.min_convergence_score)
        boost = normalized * 0.10  # Max +10% confidence boost
        
        return round(boost, 3)
    
    def update_config(self, **kwargs):
        """
        Update engine configuration.
        
        Args:
            min_convergence_score: float (0.0 - 1.0)
            min_timeframes_required: int (1-2)
            min_zone_overlap_pct: float (0.0 - 1.0)
            require_5m: bool
        """
        if 'min_convergence_score' in kwargs:
            self.min_convergence_score = kwargs['min_convergence_score']
        if 'min_timeframes_required' in kwargs:
            self.min_timeframes_required = kwargs['min_timeframes_required']
        if 'min_zone_overlap_pct' in kwargs:
            self.min_zone_overlap_pct = kwargs['min_zone_overlap_pct']
        if 'require_5m' in kwargs:
            self.require_5m = kwargs['require_5m']
        
        print("[MTF-FVG] Configuration updated")


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

mtf_fvg_engine = MTFFVGEngine()


# ══════════════════════════════════════════════════════════════════════════════
# TESTING / CLI USAGE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mtf_fvg_engine.py <ticker>")
        print("Example: python mtf_fvg_engine.py SPY")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
    # Import data manager
    from mtf_data_manager import mtf_data_manager
    
    print(f"\n{'='*80}")
    print(f"MTF FVG DETECTION TEST: {ticker}")
    print(f"{'='*80}\n")
    
    # Get both timeframes
    print(f"Fetching {ticker} data across all timeframes...\n")
    bars_dict = mtf_data_manager.get_all_timeframes(ticker)
    
    if not bars_dict:
        print(f"No data available for {ticker}")
        sys.exit(1)
    
    # Detect MTF signal
    print(f"\nRunning MTF FVG detection...\n")
    result = mtf_fvg_engine.detect_mtf_signal(ticker, bars_dict)
    
    if result:
        print(f"\n{'='*80}")
        print("MTF SIGNAL DETECTED")
        print(f"{'='*80}")
        print(f"Direction:        {result['direction'].upper()}")
        print(f"Convergence:      {result['convergence_score']:.1%}")
        print(f"Timeframes:       {', '.join(result['timeframes_aligned'])}")
        print(f"Zone:             ${result['zone_low']:.2f} - ${result['zone_high']:.2f}")
        print(f"BOS Price:        ${result['bos_price']:.2f}")
        
        # Show per-timeframe details
        print(f"\n{'-'*80}")
        print("PER-TIMEFRAME DETAILS")
        print(f"{'-'*80}")
        for tf, sig in result['signals_by_tf'].items():
            print(f"{tf:>3}: {sig['direction']:>4} | Zone: ${sig['fvg_low']:.2f} - ${sig['fvg_high']:.2f}")
        
        # Calculate confidence boost
        boost = mtf_fvg_engine.get_mtf_boost_value(result['convergence_score'])
        print(f"\nMTF Confidence Boost: +{boost:.2%}")
        print(f"{'='*80}\n")
    else:
        print(f"\n{'='*80}")
        print("NO MTF SIGNAL")
        print(f"{'='*80}")
        print("Reasons: Insufficient convergence or zone overlap")
        print(f"{'='*80}\n")
