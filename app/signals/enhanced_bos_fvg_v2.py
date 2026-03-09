#!/usr/bin/env python3
"""
Enhanced BOS/FVG Detection v2 - LOOSENED FILTERS

Original v2 found ZERO signals (too strict).

Changes:
1. Allow neutral trends (don't require perfect alignment)
2. Reduce consolidation requirement (3 bars instead of 5)
3. Loosen VWAP distance (5% instead of 3%)
4. Lower volume requirement (2.0x instead of 2.5x)
5. Reduce breakout strength (1.0% instead of 1.5%)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time
from dataclasses import dataclass


@dataclass
class EnhancedSignalV2:
    """Enhanced signal with context data"""
    timestamp: datetime
    ticker: str
    signal_type: str
    direction: str
    entry_price: float
    breakout_strength: float
    volume_ratio: float
    trend_1min: str
    trend_5min: str
    consolidation_bars: int
    is_opening_range: bool
    price_vs_vwap: float
    vwap_slope: str
    near_hvn: bool
    near_lvn: bool
    grade: str
    confidence: float


class EnhancedDetectorV2:
    """
    Enhanced signal detector - LOOSENED VERSION
    """
    
    def __init__(self):
        self.params = {
            # LOOSENED from original
            'min_breakout_strength': 0.010,     # 1.0% (was 1.5%)
            'min_volume_ratio': 2.0,            # 2.0x (was 2.5x)
            'min_consolidation_bars': 3,        # 3 bars (was 5)
            
            # Trend - allow neutral
            'require_trend_alignment': False,    # DISABLED (was True)
            'allow_neutral_trend': True,        # NEW: Allow neutral trends
            
            # VWAP - loosened
            'vwap_max_distance': 0.05,          # 5% (was 3%)
            'require_vwap_direction': False,    # DISABLED (was True)
            
            # Opening range
            'opening_range_strength': 0.015,    # 1.5% (was 2.0%)
            'opening_range_end': time(10, 30),  # Extended to 10:30
        }
        
        print("[DETECTOR-V2] ✅ Initialized with LOOSENED filters")
        print(f"[DETECTOR-V2] Min breakout: {self.params['min_breakout_strength']:.1%}")
        print(f"[DETECTOR-V2] Min volume: {self.params['min_volume_ratio']:.1f}x")
        print(f"[DETECTOR-V2] Min consolidation: {self.params['min_consolidation_bars']} bars")
    
    def detect_signals(
        self,
        bars_1min: List[Dict],
        bars_5min: List[Dict],
        idx: int
    ) -> Optional[EnhancedSignalV2]:
        """
        Detect enhanced signals with context.
        """
        if idx < 50 or idx >= len(bars_1min) - 10:  # Reduced from 100
            return None
        
        current_bar = bars_1min[idx]
        timestamp = current_bar['datetime']
        
        # Skip pre-market (before 9:30) and after-hours (after 16:00)
        if timestamp.hour < 9 or (timestamp.hour == 9 and timestamp.minute < 30):
            return None
        
        if timestamp.hour >= 16:
            return None
        
        # Get trends
        trend_1min = self._calculate_trend(bars_1min, idx, lookback=20)
        trend_5min = self._calculate_trend_5min(bars_5min, timestamp)
        
        # Trend alignment - LOOSENED
        if self.params['require_trend_alignment']:
            # Allow neutral if other trend is strong
            if trend_1min == 'neutral' and trend_5min == 'neutral':
                return None
            # Reject only if trends oppose
            if (trend_1min == 'bull' and trend_5min == 'bear') or \
               (trend_1min == 'bear' and trend_5min == 'bull'):
                return None
        
        # Check consolidation
        consolidation_bars = self._check_consolidation(bars_1min, idx)
        if consolidation_bars < self.params['min_consolidation_bars']:
            return None
        
        # Calculate VWAP
        vwap_data = self._calculate_vwap_context(bars_1min, idx)
        
        # VWAP gate - LOOSENED
        if self.params['require_vwap_direction']:
            price_vs_vwap = vwap_data['price_vs_vwap']
            if abs(price_vs_vwap) > self.params['vwap_max_distance']:
                return None
        
        # Detect BOS
        bos_signal = self._detect_bos_v2(
            bars_1min, idx, trend_1min, consolidation_bars, timestamp
        )
        
        if bos_signal:
            signal = self._build_signal(
                bos_signal, timestamp, trend_1min, trend_5min,
                consolidation_bars, vwap_data
            )
            return signal
        
        # Detect FVG
        fvg_signal = self._detect_fvg_v2(
            bars_1min, idx, trend_1min, consolidation_bars, timestamp
        )
        
        if fvg_signal:
            signal = self._build_signal(
                fvg_signal, timestamp, trend_1min, trend_5min,
                consolidation_bars, vwap_data
            )
            return signal
        
        return None
    
    def _calculate_trend(self, bars: List[Dict], idx: int, lookback: int = 20) -> str:
        if idx < lookback + 10:
            return 'neutral'
        
        recent_bars = bars[idx-lookback:idx+1]
        closes = [b['close'] for b in recent_bars]
        
        ema = self._calculate_ema(closes, period=10)
        
        if len(ema) < 5:
            return 'neutral'
        
        recent_ema = ema[-5:]
        slope = (recent_ema[-1] - recent_ema[0]) / recent_ema[0]
        
        if slope > 0.003:  # 0.3% (was 0.5%)
            return 'bull'
        elif slope < -0.003:
            return 'bear'
        else:
            return 'neutral'
    
    def _calculate_trend_5min(self, bars_5min: List[Dict], current_time: datetime) -> str:
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
    
    def _check_consolidation(self, bars: List[Dict], idx: int) -> int:
        """
        Check consolidation - LOOSENED
        """
        if idx < 20:
            return 0
        
        lookback = bars[max(0, idx-30):idx]
        
        if len(lookback) < 10:
            return 0
        
        consolidation_count = 0
        
        for i in range(len(lookback)-1, 0, -1):
            bar = lookback[i]
            bar_range = (bar['high'] - bar['low']) / bar['close']
            
            # Looser range = consolidation
            if bar_range < 0.008:  # 0.8% (was 0.5%)
                consolidation_count += 1
            else:
                break
        
        return consolidation_count
    
    def _calculate_vwap_context(self, bars: List[Dict], idx: int) -> Dict:
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
    
    def _detect_bos_v2(
        self,
        bars: List[Dict],
        idx: int,
        trend: str,
        consolidation_bars: int,
        timestamp: datetime
    ) -> Optional[Dict]:
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
        
        recent_volumes = [b['volume'] for b in lookback[-10:]]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
        
        volume_ratio = current_bar['volume'] / avg_volume
        
        if volume_ratio < self.params['min_volume_ratio']:
            return None
        
        is_opening_range = (
            timestamp.hour == 9 or
            (timestamp.hour == 10 and timestamp.minute < 30)
        )
        
        min_strength = (
            self.params['opening_range_strength'] if is_opening_range
            else self.params['min_breakout_strength']
        )
        
        # Bullish BOS - allow if trend not bearish
        if trend != 'bear' and current_bar['close'] > swing_high:
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
        
        # Bearish BOS - allow if trend not bullish
        if trend != 'bull' and current_bar['close'] < swing_low:
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
    
    def _detect_fvg_v2(
        self,
        bars: List[Dict],
        idx: int,
        trend: str,
        consolidation_bars: int,
        timestamp: datetime
    ) -> Optional[Dict]:
        if idx < 5:
            return None
        
        bar_minus_2 = bars[idx - 2]
        current_bar = bars[idx]
        
        recent_volumes = [bars[i]['volume'] for i in range(max(0, idx-10), idx)]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
        
        volume_ratio = current_bar['volume'] / avg_volume
        
        if volume_ratio < self.params['min_volume_ratio']:
            return None
        
        is_opening_range = (
            timestamp.hour == 9 or
            (timestamp.hour == 10 and timestamp.minute < 30)
        )
        
        min_strength = (
            self.params['opening_range_strength'] if is_opening_range
            else self.params['min_breakout_strength']
        )
        
        # Bullish FVG - allow if trend not bearish
        if trend != 'bear' and bar_minus_2['high'] < current_bar['low']:
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
        
        # Bearish FVG - allow if trend not bullish
        if trend != 'bull' and bar_minus_2['low'] > current_bar['high']:
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
        consolidation_bars: int,
        vwap_data: Dict
    ) -> EnhancedSignalV2:
        is_opening_range = (
            timestamp.hour == 9 or
            (timestamp.hour == 10 and timestamp.minute < 30)
        )
        
        grade, confidence = self._calculate_grade(
            raw_signal,
            trend_1min,
            trend_5min,
            consolidation_bars,
            vwap_data,
            is_opening_range
        )
        
        return EnhancedSignalV2(
            timestamp=timestamp,
            ticker=raw_signal.get('ticker', 'UNKNOWN'),
            signal_type=raw_signal['type'],
            direction=raw_signal['direction'],
            entry_price=raw_signal['entry_price'],
            breakout_strength=raw_signal['strength'],
            volume_ratio=raw_signal['volume_ratio'],
            trend_1min=trend_1min,
            trend_5min=trend_5min,
            consolidation_bars=consolidation_bars,
            is_opening_range=is_opening_range,
            price_vs_vwap=vwap_data['price_vs_vwap'],
            vwap_slope=vwap_data['slope'],
            near_hvn=False,
            near_lvn=False,
            grade=grade,
            confidence=confidence
        )
    
    def _calculate_grade(
        self,
        raw_signal: Dict,
        trend_1min: str,
        trend_5min: str,
        consolidation_bars: int,
        vwap_data: Dict,
        is_opening_range: bool
    ) -> Tuple[str, float]:
        confidence = 0.5
        
        # Trend alignment bonus
        if trend_1min == trend_5min and trend_1min != 'neutral':
            confidence += 0.15
        elif trend_1min != 'neutral' or trend_5min != 'neutral':
            confidence += 0.05
        
        # Consolidation bonus
        if consolidation_bars >= 10:
            confidence += 0.15
        elif consolidation_bars >= 5:
            confidence += 0.10
        elif consolidation_bars >= 3:
            confidence += 0.05
        
        # Volume bonus
        if raw_signal['volume_ratio'] >= 3.0:
            confidence += 0.10
        elif raw_signal['volume_ratio'] >= 2.5:
            confidence += 0.05
        
        # VWAP alignment bonus
        if raw_signal['direction'] == 'CALL' and vwap_data['slope'] == 'rising':
            confidence += 0.05
        elif raw_signal['direction'] == 'PUT' and vwap_data['slope'] == 'falling':
            confidence += 0.05
        
        # Opening range bonus
        if is_opening_range and raw_signal['strength'] >= 0.015:
            confidence += 0.05
        
        confidence = min(confidence, 1.0)
        
        if confidence >= 0.80:
            grade = 'A+'
        elif confidence >= 0.70:
            grade = 'A'
        elif confidence >= 0.60:
            grade = 'B'
        else:
            grade = 'C'
        
        return grade, confidence


def get_enhanced_detector_v2() -> EnhancedDetectorV2:
    return EnhancedDetectorV2()
