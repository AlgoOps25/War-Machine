"""
Breakout Entry Detector - High-Probability Entry Signals

Strategy:
  - 5-minute breakout above resistance (highest high of last N bars)
  - Volume confirmation: current volume > 2x average volume
  - ATR-based dynamic stops and targets
  - Filters out low-quality breakouts (low volume, choppy price action)

Entry Types:
  1. BULL BREAKOUT: Price breaks above resistance + volume spike
  2. BEAR BREAKDOWN: Price breaks below support + volume spike
  3. RETEST ENTRY: Price retests breakout level with volume confirmation

Risk Management:
  - Stop: ATR-based dynamic stop (typically 1.5-2x ATR)
  - Target: Risk-reward based (minimum 1.5:1, optimal 2:1)
  - Max risk per trade: 1-2% of account
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import statistics


class BreakoutDetector:
    """Detect high-probability breakout entries with volume confirmation."""
    
    def __init__(self, 
                 lookback_bars: int = 12,
                 volume_multiplier: float = 2.0,
                 atr_period: int = 14,
                 atr_stop_multiplier: float = 1.5,
                 risk_reward_ratio: float = 2.0):
        """
        Args:
            lookback_bars: Number of bars to determine support/resistance
            volume_multiplier: Volume must be Nx average for confirmation
            atr_period: Period for ATR calculation
            atr_stop_multiplier: Stop distance = ATR * multiplier
            risk_reward_ratio: Target distance = Stop distance * ratio
        """
        self.lookback_bars = lookback_bars
        self.volume_multiplier = volume_multiplier
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_reward_ratio = risk_reward_ratio
    
    def calculate_atr(self, bars: List[Dict]) -> float:
        """Calculate Average True Range for dynamic stops."""
        if len(bars) < 2:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            # True Range = max(high-low, high-prev_close, prev_close-low)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        # Return average of last N true ranges
        atr_bars = true_ranges[-self.atr_period:] if len(true_ranges) >= self.atr_period else true_ranges
        return statistics.mean(atr_bars) if atr_bars else 0.0
    
    def calculate_support_resistance(self, bars: List[Dict]) -> Tuple[float, float]:
        """Calculate support and resistance levels from recent bars."""
        if not bars:
            return 0.0, 0.0
        
        lookback = bars[-self.lookback_bars:] if len(bars) >= self.lookback_bars else bars
        
        resistance = max(bar['high'] for bar in lookback)
        support = min(bar['low'] for bar in lookback)
        
        return support, resistance
    
    def calculate_average_volume(self, bars: List[Dict]) -> float:
        """Calculate average volume over lookback period."""
        if not bars:
            return 0.0
        
        lookback = bars[-self.lookback_bars:] if len(bars) >= self.lookback_bars else bars
        volumes = [bar['volume'] for bar in lookback]
        
        return statistics.mean(volumes) if volumes else 0.0
    
    def detect_breakout(self, bars: List[Dict]) -> Optional[Dict]:
        """
        Detect breakout entry signal.
        
        Args:
            bars: List of OHLCV bars (must have at least lookback_bars)
        
        Returns:
            Signal dict if breakout detected, None otherwise
            {
                'signal': 'BUY' or 'SELL',
                'entry': float,
                'stop': float,
                'target': float,
                'risk': float,
                'reward': float,
                'risk_reward': float,
                'atr': float,
                'volume_ratio': float,
                'confidence': int (0-100),
                'reason': str,
                'timestamp': datetime
            }
        """
        if len(bars) < self.lookback_bars:
            return None
        
        latest = bars[-1]
        support, resistance = self.calculate_support_resistance(bars[:-1])  # Exclude current bar
        avg_volume = self.calculate_average_volume(bars[:-1])
        atr = self.calculate_atr(bars)
        
        if avg_volume == 0 or atr == 0:
            return None
        
        current_volume = latest['volume']
        volume_ratio = current_volume / avg_volume
        
        # ========================================
        # BULL BREAKOUT: Close above resistance
        # ========================================
        if latest['close'] > resistance and volume_ratio >= self.volume_multiplier:
            entry = latest['close']
            stop = entry - (atr * self.atr_stop_multiplier)
            risk = entry - stop
            reward = risk * self.risk_reward_ratio
            target = entry + reward
            
            # Quality filters
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=(entry - resistance) / resistance,
                atr_pct=atr / entry,
                signal_type='BULL'
            )
            
            if confidence < 50:
                return None
            
            return {
                'signal': 'BUY',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),
                'risk': round(risk, 2),
                'reward': round(reward, 2),
                'risk_reward': round(reward / risk, 2),
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'confidence': confidence,
                'reason': f'Breakout above ${resistance:.2f} with {volume_ratio:.1f}x volume',
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        # =========================================
        # BEAR BREAKDOWN: Close below support
        # =========================================
        elif latest['close'] < support and volume_ratio >= self.volume_multiplier:
            entry = latest['close']
            stop = entry + (atr * self.atr_stop_multiplier)
            risk = stop - entry
            reward = risk * self.risk_reward_ratio
            target = entry - reward
            
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=(support - entry) / support,
                atr_pct=atr / entry,
                signal_type='BEAR'
            )
            
            if confidence < 50:
                return None
            
            return {
                'signal': 'SELL',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),
                'risk': round(risk, 2),
                'reward': round(reward, 2),
                'risk_reward': round(reward / risk, 2),
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'confidence': confidence,
                'reason': f'Breakdown below ${support:.2f} with {volume_ratio:.1f}x volume',
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        return None
    
    def detect_retest_entry(self, bars: List[Dict], breakout_level: float, breakout_type: str) -> Optional[Dict]:
        """
        Detect retest of a previous breakout level (higher probability entry).
        
        Args:
            bars: List of OHLCV bars
            breakout_level: Previous breakout/breakdown level
            breakout_type: 'BULL' or 'BEAR'
        
        Returns:
            Signal dict if retest entry detected, None otherwise
        """
        if len(bars) < 3:
            return None
        
        latest = bars[-1]
        atr = self.calculate_atr(bars)
        avg_volume = self.calculate_average_volume(bars[:-1])
        
        if atr == 0 or avg_volume == 0:
            return None
        
        volume_ratio = latest['volume'] / avg_volume
        
        # Define retest zone (within 1 ATR of breakout level)
        retest_tolerance = atr * 0.5
        
        # BULL RETEST: Price comes back to test breakout level from above
        if breakout_type == 'BULL':
            in_retest_zone = abs(latest['low'] - breakout_level) <= retest_tolerance
            bouncing_up = latest['close'] > latest['open']  # Bullish candle
            
            if in_retest_zone and bouncing_up and volume_ratio >= 1.5:
                entry = latest['close']
                stop = breakout_level - (atr * self.atr_stop_multiplier)
                risk = entry - stop
                reward = risk * self.risk_reward_ratio
                target = entry + reward
                
                confidence = self._calculate_confidence(
                    volume_ratio=volume_ratio,
                    breakout_strength=0.02,  # Retest has lower breakout strength
                    atr_pct=atr / entry,
                    signal_type='BULL'
                ) + 10  # Bonus for retest (higher probability)
                
                return {
                    'signal': 'BUY',
                    'entry': round(entry, 2),
                    'stop': round(stop, 2),
                    'target': round(target, 2),
                    'risk': round(risk, 2),
                    'reward': round(reward, 2),
                    'risk_reward': round(reward / risk, 2),
                    'atr': round(atr, 2),
                    'volume_ratio': round(volume_ratio, 2),
                    'confidence': min(confidence, 95),
                    'reason': f'Retest of ${breakout_level:.2f} breakout with {volume_ratio:.1f}x volume',
                    'timestamp': latest.get('datetime', datetime.now())
                }
        
        # BEAR RETEST: Price comes back to test breakdown level from below
        elif breakout_type == 'BEAR':
            in_retest_zone = abs(latest['high'] - breakout_level) <= retest_tolerance
            rejecting_down = latest['close'] < latest['open']  # Bearish candle
            
            if in_retest_zone and rejecting_down and volume_ratio >= 1.5:
                entry = latest['close']
                stop = breakout_level + (atr * self.atr_stop_multiplier)
                risk = stop - entry
                reward = risk * self.risk_reward_ratio
                target = entry - reward
                
                confidence = self._calculate_confidence(
                    volume_ratio=volume_ratio,
                    breakout_strength=0.02,
                    atr_pct=atr / entry,
                    signal_type='BEAR'
                ) + 10
                
                return {
                    'signal': 'SELL',
                    'entry': round(entry, 2),
                    'stop': round(stop, 2),
                    'target': round(target, 2),
                    'risk': round(risk, 2),
                    'reward': round(reward, 2),
                    'risk_reward': round(reward / risk, 2),
                    'atr': round(atr, 2),
                    'volume_ratio': round(volume_ratio, 2),
                    'confidence': min(confidence, 95),
                    'reason': f'Retest of ${breakout_level:.2f} breakdown with {volume_ratio:.1f}x volume',
                    'timestamp': latest.get('datetime', datetime.now())
                }
        
        return None
    
    def _calculate_confidence(self, volume_ratio: float, breakout_strength: float, 
                            atr_pct: float, signal_type: str) -> int:
        """
        Calculate confidence score (0-100) for breakout signal.
        
        Factors:
          - Volume ratio: Higher volume = higher confidence
          - Breakout strength: Stronger break = higher confidence
          - ATR percentage: Lower volatility = higher confidence (cleaner move)
        """
        confidence = 50  # Base confidence
        
        # Volume factor (0-30 points)
        if volume_ratio >= 3.0:
            confidence += 30
        elif volume_ratio >= 2.5:
            confidence += 20
        elif volume_ratio >= 2.0:
            confidence += 10
        
        # Breakout strength (0-20 points)
        if breakout_strength >= 0.03:  # 3%+ breakout
            confidence += 20
        elif breakout_strength >= 0.02:  # 2%+ breakout
            confidence += 15
        elif breakout_strength >= 0.01:  # 1%+ breakout
            confidence += 10
        
        # ATR percentage - lower is better for clean moves (0-10 points)
        if atr_pct < 0.02:  # Less than 2% ATR
            confidence += 10
        elif atr_pct < 0.03:
            confidence += 5
        
        return min(confidence, 100)
    
    def calculate_position_size(self, account_balance: float, risk_percent: float, 
                              entry: float, stop: float) -> int:
        """
        Calculate position size based on account risk.
        
        Args:
            account_balance: Total account value
            risk_percent: Risk per trade (e.g., 1.0 = 1%)
            entry: Entry price
            stop: Stop loss price
        
        Returns:
            Number of shares to trade
        """
        risk_amount = account_balance * (risk_percent / 100)
        risk_per_share = abs(entry - stop)
        
        if risk_per_share == 0:
            return 0
        
        shares = int(risk_amount / risk_per_share)
        return max(shares, 0)


def format_signal_message(ticker: str, signal: Dict) -> str:
    """
    Format breakout signal for Discord/console output.
    
    Args:
        ticker: Stock ticker
        signal: Signal dict from detect_breakout()
    
    Returns:
        Formatted message string
    """
    emoji = "📈" if signal['signal'] == 'BUY' else "📉"
    
    msg = (
        f"{emoji} **{signal['signal']} {ticker}** @ ${signal['entry']}\n"
        f"Stop: ${signal['stop']} | Target: ${signal['target']}\n"
        f"Risk: ${signal['risk']} | Reward: ${signal['reward']} | R:R {signal['risk_reward']}:1\n"
        f"Volume: {signal['volume_ratio']}x avg | ATR: ${signal['atr']}\n"
        f"Confidence: {signal['confidence']}% - {signal['reason']}"
    )
    
    return msg


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Test with sample bars
    detector = BreakoutDetector(
        lookback_bars=12,
        volume_multiplier=2.0,
        atr_stop_multiplier=1.5,
        risk_reward_ratio=2.0
    )
    
    # Sample bars (OHLCV)
    sample_bars = [
        {'datetime': datetime.now(), 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 100.5, 'high': 102, 'low': 100, 'close': 101, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 101, 'high': 103, 'low': 100.5, 'close': 102, 'volume': 1200000},
        {'datetime': datetime.now(), 'open': 102, 'high': 104, 'low': 101.5, 'close': 103, 'volume': 1300000},
        {'datetime': datetime.now(), 'open': 103, 'high': 104.5, 'low': 102, 'close': 103.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 103.5, 'high': 105, 'low': 103, 'close': 104, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 104, 'high': 105.5, 'low': 103.5, 'close': 104.5, 'volume': 1050000},
        {'datetime': datetime.now(), 'open': 104.5, 'high': 106, 'low': 104, 'close': 105, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 105, 'high': 106.5, 'low': 104.5, 'close': 105.5, 'volume': 1150000},
        {'datetime': datetime.now(), 'open': 105.5, 'high': 107, 'low': 105, 'close': 106, 'volume': 1200000},
        {'datetime': datetime.now(), 'open': 106, 'high': 107.5, 'low': 105.5, 'close': 106.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 106.5, 'high': 108, 'low': 106, 'close': 107, 'volume': 1000000},
        # BREAKOUT BAR: Price breaks above 108 with 2.5x volume
        {'datetime': datetime.now(), 'open': 107, 'high': 110, 'low': 106.5, 'close': 109, 'volume': 2500000},
    ]
    
    signal = detector.detect_breakout(sample_bars)
    
    if signal:
        print("\n" + "="*60)
        print("BREAKOUT DETECTED!")
        print("="*60)
        print(format_signal_message("TEST", signal))
        print("="*60)
        
        # Calculate position size for $10,000 account risking 1%
        shares = detector.calculate_position_size(
            account_balance=10000,
            risk_percent=1.0,
            entry=signal['entry'],
            stop=signal['stop']
        )
        print(f"\nPosition Size: {shares} shares")
        print(f"Total Risk: ${shares * signal['risk']:.2f}")
        print(f"Potential Profit: ${shares * signal['reward']:.2f}")
    else:
        print("No breakout signal detected")
