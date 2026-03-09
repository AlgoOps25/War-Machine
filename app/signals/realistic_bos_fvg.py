#!/usr/bin/env python3
"""
Realistic BOS/FVG Detector - Achievable Thresholds

Based on debug analysis showing original thresholds found only 1 signal in 30 days.

New realistic thresholds:
- Volume: 1.3x (was 2.0x) - catches normal volume spikes
- Breakout: 0.5% (was 1.0%) - catches normal intraday moves
- Market hours: 9:30-16:00 (no pre-market/after-hours for now)
- Trend: Awareness without strict requirements
- Signal grading: A+/A/B/C based on quality factors

Expected: 20-50 signals per 30 days across 3 tickers
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass


@dataclass
class RealisticSignal:
    """Realistic signal with context"""
    timestamp: datetime
    ticker: str
    signal_type: str  # 'BOS' or 'FVG'
    direction: str    # 'CALL' or 'PUT'
    entry_price: float
    
    # Quality metrics
    breakout_strength: float
    volume_ratio: float
    
    # Context
    trend_1min: str
    trend_5min: str
    price_vs_vwap: float
    vwap_slope: str
    
    # Grading
    grade: str        # 'A+', 'A', 'B', 'C'
    confidence: float # 0.0 to 1.0


class RealisticDetector:
    """
    Realistic detector with achievable thresholds.
    """
    
    def __init__(self):
        self.params = {
            # REALISTIC thresholds
            'min_breakout_strength': 0.005,     # 0.5% (was 1.0%)
            'min_volume_ratio': 1.3,            # 1.3x (was 2.0x)
            
            # Opening range gets higher thresholds
            'opening_range_strength': 0.008,    # 0.8%
            'opening_range_volume': 1.5,         # 1.5x
            
            # Market structure awareness (not strict filtering)
            'trend_boost_threshold': 0.003,     # 0.3% slope = strong trend
            'vwap_distance_warning': 0.02,      # Warn if >2% from VWAP
        }
        
        print("[REALISTIC-DETECTOR] ✅ Initialized")
        print(f"[REALISTIC-DETECTOR] Min breakout: {self.params['min_breakout_strength']:.1%}")
        print(f"[REALISTIC-DETECTOR] Min volume: {self.params['min_volume_ratio']:.1f}x")
    
    def detect_signals(
        self,
        bars_1min: List[Dict],
        bars_5min: List[Dict],
        idx: int
    ) -> Optional[RealisticSignal]:
        """
        Detect realistic signals.
        """
        if idx < 50 or idx >= len(bars_1min) - 10:
            return None
        
        current_bar = bars_1min[idx]
        timestamp = current_bar['datetime']
        
        # Market hours: 9:30-16:00 ONLY
        if timestamp.hour < 9 or (timestamp.hour == 9 and timestamp.minute < 30):
            return None
        
        if timestamp.hour >= 16:
            return None
        
        # Get context (for grading, not filtering)
        trend_1min = self._calculate_trend(bars_1min, idx, lookback=20)
        trend_5min = self._calculate_trend_5min(bars_5min, timestamp)
        vwap_data = self._calculate_vwap_context(bars_1min, idx)
        
        # Check if opening range (first hour: 9:30-10:30)
        is_opening_range = (
            timestamp.hour == 9 or
            (timestamp.hour == 10 and timestamp.minute < 30)
        )
        
        # Detect BOS
        bos_signal = self._detect_bos(
            bars_1min, idx, trend_1min, timestamp, is_opening_range
        )
        
        if bos_signal:
            signal = self._build_signal(
                bos_signal, timestamp, trend_1min, trend_5min, vwap_data
            )
            return signal
        
        # Detect FVG
        fvg_signal = self._detect_fvg(
            bars_1min, idx, trend_1min, timestamp, is_opening_range
        )
        
        if fvg_signal:
            signal = self._build_signal(
                fvg_signal, timestamp, trend_1min, trend_5min, vwap_data
            )
            return signal
        
        return None
    
    def _calculate_trend(self, bars: List[Dict], idx: int, lookback: int = 20) -> str:
        """Calculate trend using EMA slope"""
        if idx < lookback + 10:
            return 'neutral'
        
        recent_bars = bars[idx-lookback:idx+1]
        closes = [b['close'] for b in recent_bars]
        
        ema = self._calculate_ema(closes, period=10)
        
        if len(ema) < 5:
            return 'neutral'
        
        recent_ema = ema[-5:]
        slope = (recent_ema[-1] - recent_ema[0]) / recent_ema[0]
        
        # Relaxed thresholds
        if slope > 0.002:  # 0.2%
            return 'bull'
        elif slope < -0.002:
            return 'bear'
        else:
            return 'neutral'
    
    def _calculate_trend_5min(self, bars_5min: List[Dict], current_time: datetime) -> str:
        """Calculate 5min trend"""
        if not bars_5min or len(bars_5min) < 20:
            return 'neutral'
        
        idx = -1
        for i in range(len(bars_5min)-1, max(0, len(bars_5min)-50), -1):
            if bars_5min[i]['datetime'] <= current_time:
                idx = i
                break
        
        if idx < 20:
            return 'neutral'
        
        return self._calculate_trend(bars_5min, idx, lookback=12)
    
    def _calculate_ema(self, values: List[float], period: int) -> List[float]:
        """Calculate EMA"""
        if len(values) < period:
            return []
        
        ema = []
        multiplier = 2.0 / (period + 1)
        
        sma = sum(values[:period]) / period
        ema.append(sma)
        
        for i in range(period, len(values)):
            ema_val = (values[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_val)
        
        return ema
    
    def _calculate_vwap_context(self, bars: List[Dict], idx: int) -> Dict:
        """Calculate VWAP context"""
        if idx < 50:
            return {'vwap': 0, 'price_vs_vwap': 0, 'slope': 'flat'}
        
        session_bars = bars[max(0, idx-100):idx+1]
        
        cum_pv = 0
        cum_vol = 0
        
        for bar in session_bars:
            typical_price = (bar['high'] + bar['low'] + bar['close']) / 3
            cum_pv += typical_price * bar['volume']
            cum_vol += bar['volume']
        
        if cum_vol == 0:
            return {'vwap': 0, 'price_vs_vwap': 0, 'slope': 'flat'}
        
        vwap = cum_pv / cum_vol
        current_price = bars[idx]['close']
        price_vs_vwap = (current_price - vwap) / vwap
        
        # Calculate slope
        slope = 'flat'
        if len(session_bars) >= 10:
            recent_vwaps = []
            for i in range(len(session_bars)-10, len(session_bars)):
                sub_bars = session_bars[:i+1]
                pv = sum(((b['high']+b['low']+b['close'])/3) * b['volume'] for b in sub_bars)
                vol = sum(b['volume'] for b in sub_bars)
                if vol > 0:
                    recent_vwaps.append(pv / vol)
            
            if len(recent_vwaps) >= 2:
                slope_val = (recent_vwaps[-1] - recent_vwaps[0]) / recent_vwaps[0]
                if slope_val > 0.001:
                    slope = 'rising'
                elif slope_val < -0.001:
                    slope = 'falling'
        
        return {
            'vwap': vwap,
            'price_vs_vwap': price_vs_vwap,
            'slope': slope
        }
    
    def _detect_bos(
        self,
        bars: List[Dict],
        idx: int,
        trend: str,
        timestamp: datetime,
        is_opening_range: bool
    ) -> Optional[Dict]:
        """Detect BOS with realistic thresholds"""
        if idx < 20:
            return None
        
        current_bar = bars[idx]
        lookback = bars[max(0, idx-20):idx]
        
        if len(lookback) < 10:
            return None
        
        highs = [b['high'] for b in lookback]
        lows = [b['low'] for b in lookback]
        swing_high = max(highs)
        swing_low = min(lows)
        
        # Volume check - REALISTIC threshold
        recent_volumes = [b['volume'] for b in lookback[-10:]]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
        
        volume_ratio = current_bar['volume'] / avg_volume
        
        # Different thresholds for opening range
        min_volume = (
            self.params['opening_range_volume'] if is_opening_range
            else self.params['min_volume_ratio']
        )
        
        if volume_ratio < min_volume:
            return None
        
        min_strength = (
            self.params['opening_range_strength'] if is_opening_range
            else self.params['min_breakout_strength']
        )
        
        # Bullish BOS
        if current_bar['close'] > swing_high:
            strength = (current_bar['close'] - swing_high) / swing_high
            
            if strength >= min_strength:
                return {
                    'type': 'BOS',
                    'direction': 'CALL',
                    'strength': strength,
                    'entry_price': current_bar['close'],
                    'volume_ratio': volume_ratio,
                    'ticker': 'UNKNOWN'
                }
        
        # Bearish BOS
        if current_bar['close'] < swing_low:
            strength = (swing_low - current_bar['close']) / swing_low
            
            if strength >= min_strength:
                return {
                    'type': 'BOS',
                    'direction': 'PUT',
                    'strength': strength,
                    'entry_price': current_bar['close'],
                    'volume_ratio': volume_ratio,
                    'ticker': 'UNKNOWN'
                }
        
        return None
    
    def _detect_fvg(
        self,
        bars: List[Dict],
        idx: int,
        trend: str,
        timestamp: datetime,
        is_opening_range: bool
    ) -> Optional[Dict]:
        """Detect FVG with realistic thresholds"""
        if idx < 5:
            return None
        
        bar_minus_2 = bars[idx - 2]
        current_bar = bars[idx]
        
        # Volume check
        recent_volumes = [bars[i]['volume'] for i in range(max(0, idx-10), idx)]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
        
        volume_ratio = current_bar['volume'] / avg_volume
        
        min_volume = (
            self.params['opening_range_volume'] if is_opening_range
            else self.params['min_volume_ratio']
        )
        
        if volume_ratio < min_volume:
            return None
        
        min_strength = (
            self.params['opening_range_strength'] if is_opening_range
            else self.params['min_breakout_strength']
        )
        
        # Bullish FVG
        if bar_minus_2['high'] < current_bar['low']:
            gap_size = (current_bar['low'] - bar_minus_2['high']) / bar_minus_2['high']
            
            if gap_size >= min_strength:
                return {
                    'type': 'FVG',
                    'direction': 'CALL',
                    'strength': gap_size,
                    'entry_price': current_bar['close'],
                    'volume_ratio': volume_ratio,
                    'ticker': 'UNKNOWN'
                }
        
        # Bearish FVG
        if bar_minus_2['low'] > current_bar['high']:
            gap_size = (bar_minus_2['low'] - current_bar['high']) / bar_minus_2['low']
            
            if gap_size >= min_strength:
                return {
                    'type': 'FVG',
                    'direction': 'PUT',
                    'strength': gap_size,
                    'entry_price': current_bar['close'],
                    'volume_ratio': volume_ratio,
                    'ticker': 'UNKNOWN'
                }
        
        return None
    
    def _build_signal(
        self,
        raw_signal: Dict,
        timestamp: datetime,
        trend_1min: str,
        trend_5min: str,
        vwap_data: Dict
    ) -> RealisticSignal:
        """Build signal with grading"""
        grade, confidence = self._calculate_grade(
            raw_signal, trend_1min, trend_5min, vwap_data
        )
        
        return RealisticSignal(
            timestamp=timestamp,
            ticker=raw_signal.get('ticker', 'UNKNOWN'),
            signal_type=raw_signal['type'],
            direction=raw_signal['direction'],
            entry_price=raw_signal['entry_price'],
            breakout_strength=raw_signal['strength'],
            volume_ratio=raw_signal['volume_ratio'],
            trend_1min=trend_1min,
            trend_5min=trend_5min,
            price_vs_vwap=vwap_data['price_vs_vwap'],
            vwap_slope=vwap_data['slope'],
            grade=grade,
            confidence=confidence
        )
    
    def _calculate_grade(
        self,
        raw_signal: Dict,
        trend_1min: str,
        trend_5min: str,
        vwap_data: Dict
    ) -> Tuple[str, float]:
        """Calculate signal grade and confidence"""
        confidence = 0.50  # Base
        
        # Trend alignment bonus
        if trend_1min == trend_5min:
            if trend_1min == raw_signal['direction'].lower().replace('call', 'bull').replace('put', 'bear'):
                confidence += 0.15  # Perfect alignment
            elif trend_1min != 'neutral':
                confidence += 0.05  # Same trend
        
        # Strong volume bonus
        if raw_signal['volume_ratio'] >= 2.5:
            confidence += 0.15
        elif raw_signal['volume_ratio'] >= 2.0:
            confidence += 0.10
        elif raw_signal['volume_ratio'] >= 1.5:
            confidence += 0.05
        
        # Strong breakout bonus
        if raw_signal['strength'] >= 0.015:  # 1.5%+
            confidence += 0.10
        elif raw_signal['strength'] >= 0.010:  # 1.0%+
            confidence += 0.05
        
        # VWAP alignment bonus
        direction = raw_signal['direction']
        vwap_slope = vwap_data['slope']
        
        if (direction == 'CALL' and vwap_slope == 'rising') or \
           (direction == 'PUT' and vwap_slope == 'falling'):
            confidence += 0.10
        
        # VWAP distance penalty (far from VWAP = lower confidence)
        if abs(vwap_data['price_vs_vwap']) > self.params['vwap_distance_warning']:
            confidence -= 0.05
        
        confidence = max(0.0, min(confidence, 1.0))
        
        # Assign grade
        if confidence >= 0.85:
            grade = 'A+'
        elif confidence >= 0.75:
            grade = 'A'
        elif confidence >= 0.65:
            grade = 'B'
        else:
            grade = 'C'
        
        return grade, confidence


def get_realistic_detector() -> RealisticDetector:
    """Get singleton detector instance"""
    return RealisticDetector()
