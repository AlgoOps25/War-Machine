#!/usr/bin/env python3
"""
Advanced Technical Indicators Module

Additional indicators that can be tested separately from core BOS/FVG logic:

1. MOVING AVERAGES:
   - SMA (Simple Moving Average)
   - EMA (Exponential Moving Average)
   - VWAP (Volume Weighted Average Price)

2. MOMENTUM INDICATORS:
   - RSI (Relative Strength Index)
   - MACD (Moving Average Convergence Divergence)
   - Stochastic Oscillator

3. VOLATILITY INDICATORS:
   - Bollinger Bands
   - Keltner Channels
   - Standard Deviation

4. VOLUME INDICATORS:
   - OBV (On Balance Volume)
   - Volume Rate of Change
   - Accumulation/Distribution

5. PATTERN RECOGNITION:
   - Engulfing candles
   - Doji detection
   - Inside/Outside bars

Usage:
    from advanced_indicators import AdvancedIndicators
    
    indicators = AdvancedIndicators()
    rsi = indicators.calculate_rsi(bars, period=14)
    macd = indicators.calculate_macd(bars)
    bb_upper, bb_lower = indicators.calculate_bollinger_bands(bars)
"""
import numpy as np
from typing import List, Dict, Tuple, Optional


class AdvancedIndicators:
    """Calculate advanced technical indicators from OHLCV data."""
    
    # ==================== MOVING AVERAGES ====================
    
    def calculate_sma(self, bars: List[Dict], period: int = 20) -> Optional[float]:
        """Calculate Simple Moving Average."""
        if len(bars) < period:
            return None
        
        closes = [b['close'] for b in bars[-period:]]
        return np.mean(closes)
    
    def calculate_ema(self, bars: List[Dict], period: int = 20) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        if len(bars) < period:
            return None
        
        closes = [b['close'] for b in bars[-period:]]
        multiplier = 2 / (period + 1)
        
        # Start with SMA
        ema = np.mean(closes[:period])
        
        # Apply EMA formula
        for close in closes[period:]:
            ema = (close * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_vwap(self, bars: List[Dict]) -> Optional[float]:
        """Calculate Volume Weighted Average Price for current day."""
        if not bars:
            return None
        
        # Filter to current day only
        current_day = bars[-1]['datetime'].date()
        day_bars = [b for b in bars if b['datetime'].date() == current_day]
        
        if not day_bars:
            return None
        
        total_volume = sum(b['volume'] for b in day_bars)
        if total_volume == 0:
            return None
        
        # VWAP = Sum(Price * Volume) / Sum(Volume)
        typical_prices = [(b['high'] + b['low'] + b['close']) / 3 for b in day_bars]
        vwap = sum(p * b['volume'] for p, b in zip(typical_prices, day_bars)) / total_volume
        
        return vwap
    
    # ==================== MOMENTUM INDICATORS ====================
    
    def calculate_rsi(self, bars: List[Dict], period: int = 14) -> Optional[float]:
        """Calculate Relative Strength Index."""
        if len(bars) < period + 1:
            return None
        
        # Calculate price changes
        closes = [b['close'] for b in bars[-(period+1):]]
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        # Separate gains and losses
        gains = [c if c > 0 else 0 for c in changes]
        losses = [abs(c) if c < 0 else 0 for c in changes]
        
        # Average gains and losses
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_macd(self, bars: List[Dict], 
                      fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Tuple[float, float, float]]:
        """Calculate MACD (Moving Average Convergence Divergence).
        
        Returns:
            Tuple of (macd_line, signal_line, histogram) or None
        """
        if len(bars) < slow + signal:
            return None
        
        # Calculate EMAs
        closes = [b['close'] for b in bars]
        
        # Fast EMA
        fast_ema = self._ema_array(closes, fast)
        # Slow EMA
        slow_ema = self._ema_array(closes, slow)
        
        # MACD line
        macd_line = fast_ema[-1] - slow_ema[-1]
        
        # Signal line (EMA of MACD)
        macd_values = [fast_ema[i] - slow_ema[i] for i in range(len(fast_ema))]
        signal_line = self._ema_array(macd_values, signal)[-1]
        
        # Histogram
        histogram = macd_line - signal_line
        
        return (macd_line, signal_line, histogram)
    
    def _ema_array(self, values: List[float], period: int) -> List[float]:
        """Calculate EMA array (helper function)."""
        if len(values) < period:
            return []
        
        multiplier = 2 / (period + 1)
        ema_values = []
        
        # Start with SMA
        ema = np.mean(values[:period])
        ema_values.append(ema)
        
        # Apply EMA formula
        for value in values[period:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
            ema_values.append(ema)
        
        return ema_values
    
    def calculate_stochastic(self, bars: List[Dict], period: int = 14) -> Optional[Tuple[float, float]]:
        """Calculate Stochastic Oscillator (%K and %D).
        
        Returns:
            Tuple of (k_value, d_value) or None
        """
        if len(bars) < period + 3:
            return None
        
        recent_bars = bars[-period:]
        current = bars[-1]
        
        # Find highest high and lowest low
        highest_high = max(b['high'] for b in recent_bars)
        lowest_low = min(b['low'] for b in recent_bars)
        
        if highest_high == lowest_low:
            return (50.0, 50.0)
        
        # %K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100
        k_value = ((current['close'] - lowest_low) / (highest_high - lowest_low)) * 100
        
        # %D = 3-period SMA of %K (simplified)
        d_value = k_value  # Would need multiple bars for true %D
        
        return (k_value, d_value)
    
    # ==================== VOLATILITY INDICATORS ====================
    
    def calculate_bollinger_bands(self, bars: List[Dict], 
                                  period: int = 20, std_dev: float = 2.0) -> Optional[Tuple[float, float, float]]:
        """Calculate Bollinger Bands.
        
        Returns:
            Tuple of (upper_band, middle_band, lower_band) or None
        """
        if len(bars) < period:
            return None
        
        closes = [b['close'] for b in bars[-period:]]
        
        # Middle band = SMA
        middle = np.mean(closes)
        
        # Standard deviation
        std = np.std(closes)
        
        # Upper and lower bands
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return (upper, middle, lower)
    
    def calculate_keltner_channels(self, bars: List[Dict], 
                                   period: int = 20, atr_mult: float = 2.0) -> Optional[Tuple[float, float, float]]:
        """Calculate Keltner Channels.
        
        Returns:
            Tuple of (upper_channel, middle_channel, lower_channel) or None
        """
        if len(bars) < period + 1:
            return None
        
        # Middle line = EMA of close
        middle = self.calculate_ema(bars, period)
        if middle is None:
            return None
        
        # ATR calculation
        atr = self._calculate_atr(bars, period)
        if atr == 0:
            return None
        
        # Upper and lower channels
        upper = middle + (atr * atr_mult)
        lower = middle - (atr * atr_mult)
        
        return (upper, middle, lower)
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR (helper function)."""
        if len(bars) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        return np.mean(tr_values[-period:]) if tr_values else 0
    
    def calculate_standard_deviation(self, bars: List[Dict], period: int = 20) -> Optional[float]:
        """Calculate standard deviation of closing prices."""
        if len(bars) < period:
            return None
        
        closes = [b['close'] for b in bars[-period:]]
        return np.std(closes)
    
    # ==================== VOLUME INDICATORS ====================
    
    def calculate_obv(self, bars: List[Dict]) -> Optional[float]:
        """Calculate On Balance Volume."""
        if len(bars) < 2:
            return None
        
        obv = 0
        for i in range(1, len(bars)):
            if bars[i]['close'] > bars[i-1]['close']:
                obv += bars[i]['volume']
            elif bars[i]['close'] < bars[i-1]['close']:
                obv -= bars[i]['volume']
        
        return obv
    
    def calculate_volume_roc(self, bars: List[Dict], period: int = 10) -> Optional[float]:
        """Calculate Volume Rate of Change."""
        if len(bars) < period:
            return None
        
        current_volume = bars[-1]['volume']
        past_volume = bars[-period]['volume']
        
        if past_volume == 0:
            return 0
        
        return ((current_volume - past_volume) / past_volume) * 100
    
    def calculate_accumulation_distribution(self, bars: List[Dict]) -> Optional[float]:
        """Calculate Accumulation/Distribution Line."""
        if not bars:
            return None
        
        ad_line = 0
        for bar in bars:
            # Money Flow Multiplier
            if bar['high'] == bar['low']:
                mfm = 0
            else:
                mfm = ((bar['close'] - bar['low']) - (bar['high'] - bar['close'])) / (bar['high'] - bar['low'])
            
            # Money Flow Volume
            mfv = mfm * bar['volume']
            ad_line += mfv
        
        return ad_line
    
    # ==================== PATTERN RECOGNITION ====================
    
    def detect_engulfing(self, bars: List[Dict]) -> Optional[str]:
        """Detect bullish or bearish engulfing pattern.
        
        Returns:
            'bullish', 'bearish', or None
        """
        if len(bars) < 2:
            return None
        
        prev = bars[-2]
        current = bars[-1]
        
        prev_body = abs(prev['close'] - prev['open'])
        current_body = abs(current['close'] - current['open'])
        
        # Bullish engulfing
        if (prev['close'] < prev['open'] and  # Previous was bearish
            current['close'] > current['open'] and  # Current is bullish
            current['open'] < prev['close'] and  # Opens below previous close
            current['close'] > prev['open'] and  # Closes above previous open
            current_body > prev_body * 1.1):  # Current body 10% larger
            return 'bullish'
        
        # Bearish engulfing
        if (prev['close'] > prev['open'] and  # Previous was bullish
            current['close'] < current['open'] and  # Current is bearish
            current['open'] > prev['close'] and  # Opens above previous close
            current['close'] < prev['open'] and  # Closes below previous open
            current_body > prev_body * 1.1):  # Current body 10% larger
            return 'bearish'
        
        return None
    
    def detect_doji(self, bars: List[Dict], threshold: float = 0.001) -> bool:
        """Detect Doji candle (open ≈ close).
        
        Args:
            bars: List of bars
            threshold: Max body size as % of high-low range
        
        Returns:
            True if Doji detected
        """
        if not bars:
            return False
        
        current = bars[-1]
        body = abs(current['close'] - current['open'])
        range_size = current['high'] - current['low']
        
        if range_size == 0:
            return False
        
        body_pct = body / range_size
        return body_pct <= threshold
    
    def detect_inside_outside_bar(self, bars: List[Dict]) -> Optional[str]:
        """Detect inside or outside bar pattern.
        
        Returns:
            'inside', 'outside', or None
        """
        if len(bars) < 2:
            return None
        
        prev = bars[-2]
        current = bars[-1]
        
        # Inside bar: Current high/low within previous high/low
        if (current['high'] <= prev['high'] and 
            current['low'] >= prev['low']):
            return 'inside'
        
        # Outside bar: Current high/low engulfs previous high/low
        if (current['high'] > prev['high'] and 
            current['low'] < prev['low']):
            return 'outside'
        
        return None
    
    # ==================== COMBINED SIGNALS ====================
    
    def generate_indicator_signals(self, bars: List[Dict]) -> Dict[str, any]:
        """Generate all indicator signals for current bar.
        
        Returns:
            Dictionary with all indicator values and signals
        """
        signals = {}
        
        # Moving averages
        signals['sma_20'] = self.calculate_sma(bars, 20)
        signals['ema_20'] = self.calculate_ema(bars, 20)
        signals['vwap'] = self.calculate_vwap(bars)
        
        # Momentum
        signals['rsi'] = self.calculate_rsi(bars)
        macd = self.calculate_macd(bars)
        if macd:
            signals['macd_line'] = macd[0]
            signals['macd_signal'] = macd[1]
            signals['macd_histogram'] = macd[2]
        
        stoch = self.calculate_stochastic(bars)
        if stoch:
            signals['stoch_k'] = stoch[0]
            signals['stoch_d'] = stoch[1]
        
        # Volatility
        bb = self.calculate_bollinger_bands(bars)
        if bb:
            signals['bb_upper'] = bb[0]
            signals['bb_middle'] = bb[1]
            signals['bb_lower'] = bb[2]
            
            # Check if price is at bands
            current_close = bars[-1]['close']
            if current_close >= bb[0] * 0.99:
                signals['bb_position'] = 'upper'
            elif current_close <= bb[2] * 1.01:
                signals['bb_position'] = 'lower'
            else:
                signals['bb_position'] = 'middle'
        
        # Volume
        signals['obv'] = self.calculate_obv(bars)
        signals['volume_roc'] = self.calculate_volume_roc(bars)
        signals['ad_line'] = self.calculate_accumulation_distribution(bars)
        
        # Patterns
        signals['engulfing'] = self.detect_engulfing(bars)
        signals['doji'] = self.detect_doji(bars)
        signals['inside_outside'] = self.detect_inside_outside_bar(bars)
        
        # Generate combined signals
        signals['trend_signal'] = self._determine_trend_signal(signals, bars)
        signals['momentum_signal'] = self._determine_momentum_signal(signals)
        signals['volatility_signal'] = self._determine_volatility_signal(signals, bars)
        
        return signals
    
    def _determine_trend_signal(self, signals: Dict, bars: List[Dict]) -> str:
        """Determine overall trend signal."""
        if not bars or 'ema_20' not in signals or signals['ema_20'] is None:
            return 'neutral'
        
        current_close = bars[-1]['close']
        ema = signals['ema_20']
        
        if current_close > ema * 1.01:
            return 'bullish'
        elif current_close < ema * 0.99:
            return 'bearish'
        return 'neutral'
    
    def _determine_momentum_signal(self, signals: Dict) -> str:
        """Determine momentum signal."""
        if 'rsi' not in signals or signals['rsi'] is None:
            return 'neutral'
        
        rsi = signals['rsi']
        
        if rsi > 70:
            return 'overbought'
        elif rsi < 30:
            return 'oversold'
        elif rsi > 50:
            return 'bullish'
        else:
            return 'bearish'
    
    def _determine_volatility_signal(self, signals: Dict, bars: List[Dict]) -> str:
        """Determine volatility signal."""
        if 'bb_position' not in signals:
            return 'neutral'
        
        bb_pos = signals['bb_position']
        
        if bb_pos == 'upper':
            return 'high_top'
        elif bb_pos == 'lower':
            return 'high_bottom'
        return 'normal'


# Global instance
advanced_indicators = AdvancedIndicators()
