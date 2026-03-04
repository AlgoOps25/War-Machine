"""
Multi-Timeframe (MTF) Validator - Task 5

Responsibilities:
  - Validate signals across multiple timeframes (1m, 5m, 15m, 30m)
  - Check for bullish/bearish alignment across TFs
  - Analyze volume profile consistency
  - Detect divergences that invalidate signals
  - Boost confidence when all TFs align

Impact: Reduce false breakouts, cleaner entries, higher win rate
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from app.data.data_manager import data_manager

ET = ZoneInfo("America/New_York")


class MTFValidator:
    """
    Multi-Timeframe validator for signal confirmation.
    
    Checks signal across 4 timeframes:
      - 1m: Entry precision
      - 5m: Primary signal timeframe
      - 15m: Trend confirmation
      - 30m: Macro trend alignment
    
    Scoring System:
      - Each TF gets 0-10 score based on:
        * Price action (higher highs/lower lows)
        * Volume confirmation
        * Momentum (RSI, slope)
      - Overall score: Weighted average (30m=35%, 15m=30%, 5m=25%, 1m=10%)
      - Confidence boost: +0-15% based on alignment
    """
    
    def __init__(self):
        """Initialize MTF validator."""
        self.timeframes = ['1m', '5m', '15m', '30m']
        self.weights = {
            '30m': 0.35,  # Macro trend most important
            '15m': 0.30,  # Intermediate trend
            '5m': 0.25,   # Signal timeframe
            '1m': 0.10    # Entry precision
        }
        
        # Thresholds
        self.min_bars = {
            '1m': 20,
            '5m': 12,
            '15m': 8,
            '30m': 6
        }
        
        self.min_overall_score = 6.0  # Minimum for passing validation
        self.strong_alignment_threshold = 8.0  # All TFs strongly aligned
        
        print("[MTF] Multi-Timeframe Validator initialized")
        print(f"[MTF] Timeframes: {', '.join(self.timeframes)}")
        print(f"[MTF] Weights: {self.weights}")
    
    def validate_signal(self, ticker: str, direction: str, entry_price: float) -> Dict:
        """
        Validate signal across multiple timeframes.
        
        Args:
            ticker: Stock ticker
            direction: 'BUY' or 'SELL'
            entry_price: Signal entry price
        
        Returns:
            Dict with MTF validation results
        """
        # Get bars for all timeframes
        bars_1m = data_manager.get_today_session_bars(ticker)
        bars_5m = data_manager.get_today_5m_bars(ticker)
        bars_15m = self._aggregate_to_15m(bars_1m) if bars_1m else []
        bars_30m = self._aggregate_to_30m(bars_1m) if bars_1m else []
        
        # Score each timeframe
        score_1m = self._score_timeframe(bars_1m, direction, entry_price, '1m')
        score_5m = self._score_timeframe(bars_5m, direction, entry_price, '5m')
        score_15m = self._score_timeframe(bars_15m, direction, entry_price, '15m')
        score_30m = self._score_timeframe(bars_30m, direction, entry_price, '30m')
        
        # Calculate weighted overall score
        overall_score = (
            score_30m * self.weights['30m'] +
            score_15m * self.weights['15m'] +
            score_5m * self.weights['5m'] +
            score_1m * self.weights['1m']
        )
        
        # Determine if signal passes
        passes = overall_score >= self.min_overall_score
        
        # Calculate confidence boost
        if overall_score >= self.strong_alignment_threshold:
            confidence_boost = 0.15  # +15% for strong alignment
        elif overall_score >= 7.0:
            confidence_boost = 0.10  # +10% for good alignment
        elif overall_score >= 6.0:
            confidence_boost = 0.05  # +5% for adequate alignment
        else:
            confidence_boost = 0.0  # No boost for weak alignment
        
        # Check for divergences (red flags)
        divergences = self._detect_divergences(
            scores={'1m': score_1m, '5m': score_5m, '15m': score_15m, '30m': score_30m},
            direction=direction
        )
        
        # Apply divergence penalty
        if divergences:
            confidence_boost = max(0, confidence_boost - 0.05)  # -5% penalty
        
        result = {
            'ticker': ticker,
            'direction': direction,
            'passes': passes,
            'overall_score': round(overall_score, 1),
            'tf_scores': {
                '1m': round(score_1m, 1),
                '5m': round(score_5m, 1),
                '15m': round(score_15m, 1),
                '30m': round(score_30m, 1)
            },
            'confidence_boost': confidence_boost,
            'divergences': divergences,
            'summary': self._generate_summary(overall_score, divergences),
            'timestamp': datetime.now(ET).isoformat()
        }
        
        # Log validation result
        emoji = "✅" if passes else "❌"
        print(f"[MTF] {ticker} {emoji} | Score: {overall_score:.1f}/10 | \")
        print(f"      30m:{score_30m:.1f} 15m:{score_15m:.1f} 5m:{score_5m:.1f} 1m:{score_1m:.1f}")
        
        if divergences:
            print(f"[MTF]   ⚠️  Divergences: {', '.join(divergences)}")
        
        if confidence_boost > 0:
            print(f"[MTF]   📈 Confidence Boost: +{confidence_boost*100:.0f}%")
        
        return result
    
    def _score_timeframe(self, bars: List[Dict], direction: str, entry_price: float, tf: str) -> float:
        """
        Score a single timeframe for signal confirmation.
        
        Args:
            bars: OHLCV bars for this timeframe
            direction: 'BUY' or 'SELL'
            entry_price: Signal entry price
            tf: Timeframe label ('1m', '5m', etc.)
        
        Returns:
            Score 0-10 (10 = perfect alignment)
        """
        if not bars or len(bars) < self.min_bars.get(tf, 5):
            return 0.0
        
        score = 0.0
        
        # 1. Price Action Score (0-4 points)
        price_score = self._score_price_action(bars, direction, entry_price)
        score += price_score
        
        # 2. Volume Profile Score (0-3 points)
        volume_score = self._score_volume_profile(bars, direction)
        score += volume_score
        
        # 3. Momentum Score (0-3 points)
        momentum_score = self._score_momentum(bars, direction)
        score += momentum_score
        
        return min(10.0, score)  # Cap at 10
    
    def _score_price_action(self, bars: List[Dict], direction: str, entry_price: float) -> float:
        """
        Score price action alignment (0-4 points).
        
        For BUY signals:
          - Higher highs and higher lows = bullish
          - Price above recent moving average = bullish
          - Breakout above resistance = bullish
        
        For SELL signals:
          - Lower highs and lower lows = bearish
          - Price below recent moving average = bearish
          - Breakdown below support = bearish
        """
        if len(bars) < 5:
            return 0.0
        
        score = 0.0
        recent_bars = bars[-10:]  # Last 10 bars
        
        # Check for higher highs/lower lows
        highs = [b['high'] for b in recent_bars]
        lows = [b['low'] for b in recent_bars]
        
        if direction == 'BUY':
            # Higher highs
            if highs[-1] > highs[-3] > highs[-5]:
                score += 1.5
            # Higher lows
            if lows[-1] > lows[-3] > lows[-5]:
                score += 1.5
            # Price above MA(10)
            ma10 = np.mean([b['close'] for b in recent_bars])
            if bars[-1]['close'] > ma10:
                score += 1.0
        else:  # SELL
            # Lower highs
            if highs[-1] < highs[-3] < highs[-5]:
                score += 1.5
            # Lower lows
            if lows[-1] < lows[-3] < lows[-5]:
                score += 1.5
            # Price below MA(10)
            ma10 = np.mean([b['close'] for b in recent_bars])
            if bars[-1]['close'] < ma10:
                score += 1.0
        
        return min(4.0, score)
    
    def _score_volume_profile(self, bars: List[Dict], direction: str) -> float:
        """
        Score volume profile alignment (0-3 points).
        
        Strong signals have:
          - Increasing volume on moves in signal direction
          - Decreasing volume on pullbacks
          - Recent volume > average volume
        """
        if len(bars) < 5:
            return 0.0
        
        score = 0.0
        recent_bars = bars[-10:]
        
        # Average volume
        volumes = [b['volume'] for b in recent_bars]
        avg_volume = np.mean(volumes)
        current_volume = bars[-1]['volume']
        
        # Volume confirmation
        if current_volume > avg_volume * 1.5:
            score += 2.0  # Strong volume confirmation
        elif current_volume > avg_volume:
            score += 1.0  # Moderate volume confirmation
        
        # Volume trend
        recent_volumes = volumes[-3:]
        if np.mean(recent_volumes[-2:]) > np.mean(recent_volumes[:2]):
            score += 1.0  # Increasing volume trend
        
        return min(3.0, score)
    
    def _score_momentum(self, bars: List[Dict], direction: str) -> float:
        """
        Score momentum alignment (0-3 points).
        
        Uses:
          - Simple RSI (overbought/oversold)
          - Price slope (uptrend/downtrend)
          - Recent candle strength
        """
        if len(bars) < 14:
            return 0.0
        
        score = 0.0
        
        # Calculate simple RSI(14)
        closes = [b['close'] for b in bars[-14:]]
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = np.mean(gains) if gains else 0
        avg_loss = np.mean(losses) if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # RSI confirmation
        if direction == 'BUY':
            if 40 <= rsi <= 70:  # Good momentum, not overbought
                score += 1.5
            elif rsi > 50:
                score += 1.0
        else:  # SELL
            if 30 <= rsi <= 60:  # Good momentum, not oversold
                score += 1.5
            elif rsi < 50:
                score += 1.0
        
        # Price slope (last 5 bars)
        recent_closes = closes[-5:]
        slope = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0]
        
        if direction == 'BUY' and slope > 0:
            score += 1.0
        elif direction == 'SELL' and slope < 0:
            score += 1.0
        
        # Recent candle strength
        last_bar = bars[-1]
        body = abs(last_bar['close'] - last_bar['open'])
        range_val = last_bar['high'] - last_bar['low']
        
        if range_val > 0:
            body_ratio = body / range_val
            if body_ratio > 0.7:  # Strong directional candle
                score += 0.5
        
        return min(3.0, score)
    
    def _detect_divergences(self, scores: Dict[str, float], direction: str) -> List[str]:
        """
        Detect timeframe divergences (red flags).
        
        Divergence occurs when:
          - Higher TF disagrees with signal (e.g., 30m bearish on BUY signal)
          - Large score gap between TFs (>4 points)
        
        Args:
            scores: Dict of timeframe -> score
            direction: Signal direction
        
        Returns:
            List of divergence descriptions
        """
        divergences = []
        
        # Check if 30m contradicts signal
        if scores['30m'] < 4.0:
            divergences.append("30m weak trend")
        
        # Check if 15m contradicts signal
        if scores['15m'] < 4.0:
            divergences.append("15m weak trend")
        
        # Check for large gaps between TFs
        if abs(scores['30m'] - scores['5m']) > 4.0:
            divergences.append("30m/5m misalignment")
        
        if abs(scores['15m'] - scores['5m']) > 4.0:
            divergences.append("15m/5m misalignment")
        
        return divergences
    
    def _generate_summary(self, overall_score: float, divergences: List[str]) -> str:
        """
        Generate human-readable summary.
        
        Args:
            overall_score: Overall MTF score
            divergences: List of divergences detected
        
        Returns:
            Summary string
        """
        if divergences:
            return f"⚠️ MTF Score: {overall_score:.1f}/10 | Divergences: {', '.join(divergences)}"
        elif overall_score >= 8.0:
            return f"✅ Strong MTF alignment ({overall_score:.1f}/10) - All TFs confirm"
        elif overall_score >= 6.0:
            return f"✅ Good MTF alignment ({overall_score:.1f}/10) - Signal confirmed"
        else:
            return f"❌ Weak MTF alignment ({overall_score:.1f}/10) - Signal rejected"
    
    def _aggregate_to_15m(self, bars_1m: List[Dict]) -> List[Dict]:
        """
        Aggregate 1-minute bars to 15-minute bars.
        
        Args:
            bars_1m: List of 1-minute OHLCV bars
        
        Returns:
            List of 15-minute bars
        """
        if not bars_1m or len(bars_1m) < 15:
            return []
        
        bars_15m = []
        
        for i in range(0, len(bars_1m), 15):
            chunk = bars_1m[i:i+15]
            if len(chunk) < 15:
                continue
            
            bar_15m = {
                'timestamp': chunk[0]['timestamp'],
                'open': chunk[0]['open'],
                'high': max(b['high'] for b in chunk),
                'low': min(b['low'] for b in chunk),
                'close': chunk[-1]['close'],
                'volume': sum(b['volume'] for b in chunk)
            }
            bars_15m.append(bar_15m)
        
        return bars_15m
    
    def _aggregate_to_30m(self, bars_1m: List[Dict]) -> List[Dict]:
        """
        Aggregate 1-minute bars to 30-minute bars.
        
        Args:
            bars_1m: List of 1-minute OHLCV bars
        
        Returns:
            List of 30-minute bars
        """
        if not bars_1m or len(bars_1m) < 30:
            return []
        
        bars_30m = []
        
        for i in range(0, len(bars_1m), 30):
            chunk = bars_1m[i:i+30]
            if len(chunk) < 30:
                continue
            
            bar_30m = {
                'timestamp': chunk[0]['timestamp'],
                'open': chunk[0]['open'],
                'high': max(b['high'] for b in chunk),
                'low': min(b['low'] for b in chunk),
                'close': chunk[-1]['close'],
                'volume': sum(b['volume'] for b in chunk)
            }
            bars_30m.append(bar_30m)
        
        return bars_30m


# ========================================
# GLOBAL INSTANCE
# ========================================
mtf_validator = MTFValidator()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def validate_signal_mtf(ticker: str, direction: str, entry_price: float) -> Dict:
    """Validate signal across multiple timeframes."""
    return mtf_validator.validate_signal(ticker, direction, entry_price)


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Validate signal
    test_ticker = "AAPL"
    test_direction = "BUY"
    test_entry = 175.50
    
    print(f"Validating {test_direction} signal for {test_ticker} @ ${test_entry}...\n")
    
    result = validate_signal_mtf(test_ticker, test_direction, test_entry)
    
    print(f"\nResult:")
    print(f"  Passes: {result['passes']}")
    print(f"  Overall Score: {result['overall_score']}/10")
    print(f"  TF Scores: {result['tf_scores']}")
    print(f"  Confidence Boost: +{result['confidence_boost']*100:.0f}%")
    print(f"  Divergences: {result['divergences'] if result['divergences'] else 'None'}")
    print(f"  Summary: {result['summary']}")
