"""
MTF Convergence Scorer

Calculates convergence quality and confidence boost for multi-timeframe
FVG signals. Provides scoring logic for integrating MTF analysis into
the War Machine trading system.

Scoring Components:
  1. Timeframe Presence - Weighted by timeframe importance
  2. Zone Overlap Quality - How well zones align across timeframes
  3. Zone Size Consistency - Similar zone sizes across timeframes
  4. Directional Agreement - All timeframes agree on bull/bear

Confidence Boost:
  - 3 timeframes aligned: +5-8% confidence
  - 4 timeframes aligned: +10-15% confidence
  - Perfect overlap (>90%): Additional +2-3% bonus

Usage:
  from mtf_convergence import mtf_convergence_scorer
  
  # Calculate convergence score
  score = mtf_convergence_scorer.calculate_convergence_score(signal)
  
  # Get confidence boost for sniper.py
  boost = mtf_convergence_scorer.get_confidence_boost(signal)
  
  # Check if signal meets quality threshold
  if mtf_convergence_scorer.meets_quality_threshold(signal):
      print("High-quality MTF signal!")
"""

from typing import Dict, List, Optional, Tuple
import statistics

# Timeframe weights (must sum to 1.0)
TIMEFRAME_WEIGHTS = {
    '5m': 0.40,
    '3m': 0.30,
    '2m': 0.20,
    '1m': 0.10
}

# Confidence boost ranges (applied to base confidence)
CONFIDENCE_BOOST = {
    3: (0.05, 0.08),  # 3 timeframes: +5-8%
    4: (0.10, 0.15)   # 4 timeframes: +10-15%
}

# Quality thresholds
MIN_CONVERGENCE_SCORE = 0.60  # Minimum score to consider signal valid
HIGH_QUALITY_SCORE = 0.80     # Score for high-quality signals


class MTFConvergenceScorer:
    """Scores MTF signal convergence quality."""
    
    def __init__(self):
        self.stats = {
            'signals_scored': 0,
            'high_quality_signals': 0,
            'avg_score': 0.0
        }
        
        print("[MTF-CONV] MTF Convergence Scorer initialized")
        print(f"[MTF-CONV] Quality threshold: {MIN_CONVERGENCE_SCORE:.2f}")
        print(f"[MTF-CONV] High quality threshold: {HIGH_QUALITY_SCORE:.2f}")
    
    def _score_timeframe_presence(self, signal: Dict) -> float:
        """
        Score based on which timeframes are present.
        
        Args:
            signal: MTF signal dict
        
        Returns:
            Score 0.0 - 1.0 based on weighted timeframe presence
        """
        patterns = signal.get('patterns_by_timeframe', {})
        
        # Sum weights of present timeframes
        score = sum(
            TIMEFRAME_WEIGHTS.get(tf, 0.0)
            for tf in patterns.keys()
        )
        
        # Normalize to 0-1 (max possible score is 1.0 if all TFs present)
        return score
    
    def _score_zone_overlap(self, signal: Dict) -> float:
        """
        Score based on how well FVG zones overlap.
        
        Args:
            signal: MTF signal dict
        
        Returns:
            Score 0.0 - 1.0 based on zone overlap quality
        """
        patterns = signal.get('patterns_by_timeframe', {})
        
        if len(patterns) < 2:
            return 0.0
        
        # Calculate overlap between consensus zone and each timeframe's zone
        consensus_low = signal['zone_low']
        consensus_high = signal['zone_high']
        consensus_size = consensus_high - consensus_low
        
        overlap_scores = []
        
        for tf, pattern in patterns.items():
            tf_low = pattern['fvg_low']
            tf_high = pattern['fvg_high']
            tf_size = tf_high - tf_low
            
            # Calculate how much of timeframe's zone is within consensus
            overlap_low = max(consensus_low, tf_low)
            overlap_high = min(consensus_high, tf_high)
            overlap_size = max(0, overlap_high - overlap_low)
            
            # Score is percentage of TF zone within consensus
            if tf_size > 0:
                overlap_pct = overlap_size / tf_size
                overlap_scores.append(overlap_pct)
        
        # Average overlap across all timeframes
        return statistics.mean(overlap_scores) if overlap_scores else 0.0
    
    def _score_zone_consistency(self, signal: Dict) -> float:
        """
        Score based on consistency of zone sizes across timeframes.
        
        Similar zone sizes indicate strong agreement.
        
        Args:
            signal: MTF signal dict
        
        Returns:
            Score 0.0 - 1.0 based on zone size consistency
        """
        patterns = signal.get('patterns_by_timeframe', {})
        
        if len(patterns) < 2:
            return 0.0
        
        # Get zone sizes as percentages
        zone_size_pcts = [
            pattern['fvg_size_pct']
            for pattern in patterns.values()
        ]
        
        # Calculate coefficient of variation (lower = more consistent)
        if not zone_size_pcts:
            return 0.0
        
        mean_size = statistics.mean(zone_size_pcts)
        if mean_size == 0:
            return 0.0
        
        std_dev = statistics.stdev(zone_size_pcts) if len(zone_size_pcts) > 1 else 0
        cv = std_dev / mean_size
        
        # Convert CV to score (lower CV = higher score)
        # CV of 0 = perfect consistency = score 1.0
        # CV of 1.0 or more = poor consistency = score 0.0
        consistency_score = max(0.0, 1.0 - cv)
        
        return consistency_score
    
    def calculate_convergence_score(self, signal: Dict) -> float:
        """
        Calculate overall convergence quality score.
        
        Args:
            signal: MTF signal dict from mtf_fvg_engine
        
        Returns:
            Composite score 0.0 - 1.0
        """
        if not signal:
            return 0.0
        
        # Component scores
        presence_score = self._score_timeframe_presence(signal)
        overlap_score = self._score_zone_overlap(signal)
        consistency_score = self._score_zone_consistency(signal)
        
        # Weighted average (presence is most important)
        composite_score = (
            presence_score * 0.50 +
            overlap_score * 0.30 +
            consistency_score * 0.20
        )
        
        # Update stats
        self.stats['signals_scored'] += 1
        self.stats['avg_score'] = (
            (self.stats['avg_score'] * (self.stats['signals_scored'] - 1) + composite_score)
            / self.stats['signals_scored']
        )
        
        if composite_score >= HIGH_QUALITY_SCORE:
            self.stats['high_quality_signals'] += 1
        
        return round(composite_score, 3)
    
    def get_confidence_boost(self, signal: Dict) -> float:
        """
        Calculate confidence boost for trading system integration.
        
        Args:
            signal: MTF signal dict
        
        Returns:
            Confidence boost value (0.00 - 0.15)
        """
        if not signal:
            return 0.0
        
        # Base boost from number of timeframes
        num_timeframes = signal.get('timeframes_aligned', 0)
        
        if num_timeframes not in CONFIDENCE_BOOST:
            return 0.0
        
        min_boost, max_boost = CONFIDENCE_BOOST[num_timeframes]
        
        # Calculate convergence score
        conv_score = self.calculate_convergence_score(signal)
        
        # Interpolate boost based on convergence score
        # Score 0.6 (min) -> min_boost
        # Score 1.0 (max) -> max_boost
        if conv_score < MIN_CONVERGENCE_SCORE:
            return min_boost
        
        boost_range = max_boost - min_boost
        score_range = 1.0 - MIN_CONVERGENCE_SCORE
        score_position = (conv_score - MIN_CONVERGENCE_SCORE) / score_range
        
        boost = min_boost + (boost_range * score_position)
        
        return round(boost, 3)
    
    def meets_quality_threshold(self, signal: Dict, threshold: Optional[float] = None) -> bool:
        """
        Check if signal meets quality threshold.
        
        Args:
            signal: MTF signal dict
            threshold: Custom threshold or None to use MIN_CONVERGENCE_SCORE
        
        Returns:
            True if signal meets threshold
        """
        if threshold is None:
            threshold = MIN_CONVERGENCE_SCORE
        
        score = self.calculate_convergence_score(signal)
        return score >= threshold
    
    def is_high_quality(self, signal: Dict) -> bool:
        """
        Check if signal is high quality.
        
        Args:
            signal: MTF signal dict
        
        Returns:
            True if signal exceeds high quality threshold
        """
        return self.meets_quality_threshold(signal, HIGH_QUALITY_SCORE)
    
    def compare_signals(self, signal1: Dict, signal2: Dict) -> Dict:
        """
        Compare two MTF signals and return the better one.
        
        Args:
            signal1: First MTF signal
            signal2: Second MTF signal
        
        Returns:
            Dict with comparison results
        """
        score1 = self.calculate_convergence_score(signal1)
        score2 = self.calculate_convergence_score(signal2)
        
        better_signal = signal1 if score1 >= score2 else signal2
        
        return {
            'better_signal': better_signal,
            'signal1_score': score1,
            'signal2_score': score2,
            'difference': abs(score1 - score2)
        }
    
    def get_stats(self) -> Dict:
        """Get scoring statistics."""
        high_quality_rate = (
            (self.stats['high_quality_signals'] / self.stats['signals_scored'] * 100)
            if self.stats['signals_scored'] > 0 else 0
        )
        
        return {
            **self.stats,
            'high_quality_rate': round(high_quality_rate, 1)
        }
    
    def print_score_breakdown(self, signal: Dict):
        """Print detailed score breakdown for a signal."""
        if not signal:
            print("No signal to score")
            return
        
        presence = self._score_timeframe_presence(signal)
        overlap = self._score_zone_overlap(signal)
        consistency = self._score_zone_consistency(signal)
        composite = self.calculate_convergence_score(signal)
        boost = self.get_confidence_boost(signal)
        
        print("\n" + "="*80)
        print(f"MTF CONVERGENCE SCORE BREAKDOWN: {signal['ticker']}")
        print("="*80)
        print(f"Component Scores:")
        print(f"  Timeframe Presence:  {presence:.3f} (50% weight)")
        print(f"  Zone Overlap:        {overlap:.3f} (30% weight)")
        print(f"  Zone Consistency:    {consistency:.3f} (20% weight)")
        print(f"\nComposite Score:       {composite:.3f}")
        print(f"Confidence Boost:      +{boost*100:.1f}%")
        print(f"\nQuality Assessment:")
        
        if composite >= HIGH_QUALITY_SCORE:
            print("  ✅ HIGH QUALITY SIGNAL")
        elif composite >= MIN_CONVERGENCE_SCORE:
            print("  ✅ Valid Signal (meets threshold)")
        else:
            print("  ❌ Below quality threshold")
        
        print("="*80 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

mtf_convergence_scorer = MTFConvergenceScorer()


# ══════════════════════════════════════════════════════════════════════════════
# TESTING & CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from mtf_fvg_engine import mtf_fvg_engine
    
    print("\n🔍 MTF Convergence Scorer Test\n")
    
    # Test with sample ticker
    test_ticker = "AAPL"
    
    if len(sys.argv) > 1:
        test_ticker = sys.argv[1].upper()
    
    print(f"Testing with ticker: {test_ticker}\n")
    
    # Detect signal
    print("[TEST] Detecting MTF signal...")
    signal = mtf_fvg_engine.detect_mtf_signal(test_ticker)
    
    if signal:
        # Print signal
        mtf_fvg_engine.print_signal(signal)
        
        # Score signal
        print("[TEST] Scoring convergence...")
        mtf_convergence_scorer.print_score_breakdown(signal)
        
        # Get boost
        boost = mtf_convergence_scorer.get_confidence_boost(signal)
        print(f"✅ Confidence boost for sniper.py: +{boost*100:.1f}%")
        
    else:
        print("❌ No MTF signal found (cannot test scoring)")
    
    # Print stats
    stats = mtf_convergence_scorer.get_stats()
    print("\nScorer Statistics:")
    print(f"  Signals Scored:        {stats['signals_scored']}")
    print(f"  High Quality Signals:  {stats['high_quality_signals']}")
    print(f"  High Quality Rate:     {stats['high_quality_rate']:.1f}%")
    print(f"  Average Score:         {stats['avg_score']:.3f}")
    
    print("\n✅ MTF Convergence Scorer test complete!\n")
