"""
Multi-Timeframe FVG Detection Engine

Simultaneously scans for CFW6 BOS+FVG patterns across multiple timeframes
and calculates convergence scores based on zone alignment.

Key Concepts:
  - FVG Alignment: Multiple timeframes show FVG in same price zone
  - Convergence Score: Weighted measure of MTF agreement (0.0 - 1.0)
  - Timeframe Weights: 5m (40%) > 3m (30%) > 2m (20%) > 1m (10%)

Usage:
  from mtf_fvg_engine import mtf_fvg_engine
  from mtf_data_manager import mtf_data_manager
  
  # Get all timeframes
  bars_dict = mtf_data_manager.get_all_timeframes('SPY')
  
  # Detect MTF signal
  result = mtf_fvg_engine.detect_mtf_signal('SPY', bars_dict)
  
  if result:
      print(f"MTF Signal: {result['direction']} with {result['convergence_score']:.2f} convergence")
      print(f"Timeframes: {result['timeframes_aligned']}")
      print(f"Zone: ${result['zone_low']:.2f} - ${result['zone_high']:.2f}")
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, time
import statistics

import config
from bos_fvg_engine import scan_bos_fvg
from trade_calculator import get_adaptive_fvg_threshold


class MTFFVGEngine:
    """Multi-timeframe FVG detection and convergence analysis."""
    
    def __init__(self):
        # Timeframe priority weights (must sum to 1.0)
        self.timeframe_weights = {
            '5m': 0.40,  # Primary timeframe
            '3m': 0.30,  # High confidence
            '2m': 0.20,  # Medium confidence
            '1m': 0.10   # Low confidence (noisy)
        }
        
        # Convergence requirements
        self.min_convergence_score = 0.60  # Require 60% weighted agreement
        self.min_timeframes_required = 2    # At least 2 TFs must show FVG
        self.min_zone_overlap_pct = 0.30    # Zones must overlap by 30%+
        
        # 5m must always be present for signal
        self.require_5m = True
        
        print("[MTF-FVG] Engine initialized")
        print(f"[MTF-FVG] Min convergence: {self.min_convergence_score:.1%}")
        print(f"[MTF-FVG] Min timeframes: {self.min_timeframes_required}")
        print(f"[MTF-FVG] Min overlap: {self.min_zone_overlap_pct:.1%}")
    
    def detect_mtf_signal(self, ticker: str, bars_dict: Dict[str, List[dict]]) -> Optional[Dict]:
        """
        Detect CFW6 signal with multi-timeframe convergence.
        
        Args:
            ticker: Stock symbol
            bars_dict: Dict mapping timeframe -> bars
                      Example: {'5m': [...], '3m': [...], ...}
        
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
                'bos_idx': int,  # From primary timeframe (5m)
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
        for tf in self.timeframe_weights.keys():
            if tf not in bars_dict:
                continue
            
            bars = bars_dict[tf]
            if len(bars) < 30:  # Minimum bars required
                continue
            
            # Run CFW6 BOS+FVG detection
            signal = self._detect_fvg_single_tf(ticker, bars, tf)
            if signal:
                signals_by_tf[tf] = signal
        
        # Check if we have enough timeframes
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
        primary_tf = '5m' if '5m' in signals_by_tf else list(signals_by_tf.keys())[0]
        primary_signal = signals_by_tf[primary_tf]
        
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
            'primary_timeframe': primary_tf
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
            timeframe: Timeframe string ('5m', '3m', etc.)
        
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
        Analyze FVG convergence across multiple timeframes.
        
        Args:
            ticker: Stock symbol
            signals_by_tf: Dict mapping timeframe -> signal details
        
        Returns:
            Dict with convergence analysis or None if no convergence
        """
        # Group signals by direction
        bull_signals = {tf: sig for tf, sig in signals_by_tf.items() if sig['direction'] == 'bull'}
        bear_signals = {tf: sig for tf, sig in signals_by_tf.items() if sig['direction'] == 'bear'}
        
        # Determine dominant direction (by weighted score)
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
        
        # Check if we have minimum timeframes in aligned direction
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
        convergence_score *= (0.8 + (overlap_score * 0.2))  # Up to +20% bonus for perfect overlap
        
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
        Calculate overlapping FVG zone across multiple timeframes.
        
        Args:
            signals: Dict mapping timeframe -> signal details
        
        Returns:
            (zone_low, zone_high, overlap_score)
            
            zone_low/high: Overlapping zone boundaries
            overlap_score: Quality of overlap (0.0 - 1.0)
        """
        # Get all FVG zones
        zones = [(sig['fvg_low'], sig['fvg_high']) for sig in signals.values()]
        
        if not zones:
            return 0.0, 0.0, 0.0
        
        # Calculate intersection zone (max of lows, min of highs)
        zone_low = max(low for low, _ in zones)
        zone_high = min(high for _, high in zones)
        
        # If zones don't overlap at all
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
            Confidence boost value (0.00 - 0.15)
        """
        # Linear scale: 60% convergence = 0.00, 100% convergence = 0.15
        if convergence_score < self.min_convergence_score:
            return 0.0
        
        normalized = (convergence_score - self.min_convergence_score) / (1.0 - self.min_convergence_score)
        boost = normalized * 0.15  # Max +15% confidence boost
        
        return round(boost, 3)
    
    def update_config(self, **kwargs):
        """
        Update engine configuration.
        
        Args:
            min_convergence_score: float (0.0 - 1.0)
            min_timeframes_required: int (1-4)
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
    
    # Get all timeframes
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
        print(f"Primary TF:       {result['primary_timeframe']}")
        
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
        print("Reasons: Insufficient convergence, timeframes, or zone overlap")
        print(f"{'='*80}\n")
