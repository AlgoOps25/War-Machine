"""
Signal Replay - Historical Signal Generator

Replays your actual signal generation logic on historical bars.
Works with your existing signal_generator.py and breakout_detector.py.

Usage:
  # Define your strategy function
  def my_strategy(bars, params):
      # Use your actual signal logic here
      from app.signals.breakout_detector import BreakoutDetector
      
      detector = BreakoutDetector(
          lookback_bars=params.get('lookback_bars', 12),
          volume_multiplier=params.get('volume_threshold', 2.0),
          min_candle_body_pct=params.get('min_candle_body_pct', 0.4)
      )
      
      signal = detector.detect_breakout(bars)
      return signal
  
  # Run backtest
  engine = BacktestEngine()
  results = engine.run(
      ticker='AAPL',
      bars=historical_bars,
      strategy=my_strategy,
      strategy_params={'lookback_bars': 12, 'volume_threshold': 2.0}
  )
"""
from typing import Dict, List, Optional, Callable
from datetime import datetime


def create_strategy_from_breakout_detector(lookback_bars: int = 12,
                                           volume_multiplier: float = 2.0,
                                           atr_stop_multiplier: float = 1.5,
                                           min_candle_body_pct: float = 0.4) -> Callable:
    """
    Create a strategy function from BreakoutDetector.
    
    Returns:
        Strategy function compatible with BacktestEngine
    """
    def strategy(bars: List[Dict], params: Dict) -> Optional[Dict]:
        """Strategy function using BreakoutDetector."""
        try:
            from app.signals.breakout_detector import BreakoutDetector
            
            detector = BreakoutDetector(
                lookback_bars=params.get('lookback_bars', lookback_bars),
                volume_multiplier=params.get('volume_threshold', volume_multiplier),
                atr_stop_multiplier=params.get('atr_stop_multiplier', atr_stop_multiplier),
                min_candle_body_pct=params.get('min_candle_body_pct', min_candle_body_pct)
            )
            
            signal = detector.detect_breakout(bars, ticker="BACKTEST")
            return signal
            
        except Exception as e:
            # Silent fail for backtesting
            return None
    
    return strategy


def create_strategy_from_signal_generator(min_confidence: int = 60,
                                          volume_threshold: float = 2.0,
                                          lookback_bars: int = 12) -> Callable:
    """
    Create a strategy function from SignalGenerator.
    
    Returns:
        Strategy function compatible with BacktestEngine
    """
    def strategy(bars: List[Dict], params: Dict) -> Optional[Dict]:
        """Strategy function using SignalGenerator."""
        try:
            from app.signals.signal_generator import SignalGenerator
            
            generator = SignalGenerator(
                min_confidence=params.get('min_confidence', min_confidence),
                lookback_bars=params.get('lookback_bars', lookback_bars)
            )
            
            # Convert bars to format expected by signal_generator
            ticker = "BACKTEST"
            latest_bar = bars[-1]
            
            # Generate signal (this would call your actual signal logic)
            signal = generator.generate_signal(ticker, bars)
            
            return signal
            
        except Exception as e:
            return None
    
    return strategy


def create_custom_strategy(signal_logic: Callable) -> Callable:
    """
    Wrapper for custom signal logic.
    
    Args:
        signal_logic: Function with signature: signal_logic(bars, params) -> Optional[Dict]
    
    Returns:
        Strategy function compatible with BacktestEngine
    """
    def strategy(bars: List[Dict], params: Dict) -> Optional[Dict]:
        """Wrapper for custom strategy."""
        try:
            return signal_logic(bars, params)
        except Exception as e:
            print(f"[BACKTEST] Strategy error: {e}")
            return None
    
    return strategy


# Example strategy for testing
def example_simple_breakout_strategy(bars: List[Dict], params: Dict) -> Optional[Dict]:
    """
    Simple breakout strategy for testing backtesting engine.
    
    Args:
        bars: OHLCV bars
        params: Dict with 'lookback_bars', 'volume_threshold'
    
    Returns:
        Signal dict or None
    """
    if len(bars) < 20:
        return None
    
    lookback = params.get('lookback_bars', 12)
    volume_threshold = params.get('volume_threshold', 2.0)
    
    latest = bars[-1]
    recent = bars[-lookback:]
    
    # Calculate resistance (highest high)
    resistance = max(b['high'] for b in recent[:-1])
    
    # Calculate average volume
    avg_volume = sum(b['volume'] for b in recent[:-1]) / len(recent[:-1])
    
    # Check for breakout
    if latest['close'] > resistance and latest['volume'] > avg_volume * volume_threshold:
        # Simple signal
        entry = latest['close']
        stop = entry * 0.98  # 2% stop
        target = entry * 1.04  # 4% target
        
        return {
            'signal': 'BUY',
            'entry': entry,
            'stop': stop,
            'target': target,
            'confidence': 70,
            'reason': f'Breakout above ${resistance:.2f} with {latest["volume"] / avg_volume:.1f}x volume'
        }
    
    return None


if __name__ == "__main__":
    print("Signal Replay - Example Usage")
    print("="*80)
    print("\nUse create_strategy_from_breakout_detector() to wrap your actual signal logic.")
    print("Then pass to BacktestEngine.run() for historical testing.")
