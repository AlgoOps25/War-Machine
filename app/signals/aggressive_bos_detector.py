#!/usr/bin/env python3
"""
Aggressive BOS/FVG Detector - Catches More Signals
===================================================

Simplified BOS detection:
- Uses recent high/low (last 5-20 bars) instead of complex swing logic
- Detects when price breaks above recent high or below recent low
- Finds FVG (3-candle gap) immediately
- Requires strong candle confirmation

This will catch MANY more signals than the strict MTF engine.
Use multi-indicator scoring to filter quality.

Author: War Machine Team
Date: March 9, 2026
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time


class AggressiveBOSDetector:
    """
    Aggressive BOS/FVG detector with relaxed thresholds.
    """
    
    def __init__(self):
        self.params = {
            # BOS Detection
            'bos_lookback_min': 5,      # Minimum bars to look back
            'bos_lookback_max': 20,     # Maximum bars to look back
            'min_bos_strength': 0.001,  # 0.1% minimum break
            
            # FVG Detection
            'min_fvg_size': 0.0005,     # 0.05% minimum gap
            'fvg_search_bars': 30,      # How far to search for FVG
            
            # Confirmation
            'require_strong_candle': True,  # Require green/red candle
        }
    
    def detect_breakout(self, bars: List[Dict]) -> Optional[Dict]:
        """
        Detect breakout above recent high or below recent low.
        
        Much simpler than complex swing point logic:
        1. Find highest high and lowest low in last 5-20 bars
        2. Check if current bar breaks above/below with strength
        3. Validate with candle direction
        """
        if len(bars) < 25:
            return None
        
        current_bar = bars[-1]
        
        # Look at recent bars (excluding current)
        lookback_min = self.params['bos_lookback_min']
        lookback_max = self.params['bos_lookback_max']
        
        recent_bars = bars[-(lookback_max+1):-1]  # Exclude current bar
        
        # Find recent high and low
        recent_high = max(b['high'] for b in recent_bars)
        recent_low = min(b['low'] for b in recent_bars)
        
        # Check for BULL breakout (close above recent high)
        if current_bar['close'] > recent_high:
            strength = (current_bar['close'] - recent_high) / recent_high
            
            if strength >= self.params['min_bos_strength']:
                # Validate: should be a green candle
                is_green = current_bar['close'] > current_bar['open']
                
                if not self.params['require_strong_candle'] or is_green:
                    return {
                        'direction': 'bull',
                        'breakout_level': recent_high,
                        'break_price': current_bar['close'],
                        'strength': strength,
                        'bar_idx': len(bars) - 1,
                        'bar': current_bar
                    }
        
        # Check for BEAR breakout (close below recent low)
        if current_bar['close'] < recent_low:
            strength = (recent_low - current_bar['close']) / recent_low
            
            if strength >= self.params['min_bos_strength']:
                # Validate: should be a red candle
                is_red = current_bar['close'] < current_bar['open']
                
                if not self.params['require_strong_candle'] or is_red:
                    return {
                        'direction': 'bear',
                        'breakout_level': recent_low,
                        'break_price': current_bar['close'],
                        'strength': strength,
                        'bar_idx': len(bars) - 1,
                        'bar': current_bar
                    }
        
        return None
    
    def find_fvg(self, bars: List[Dict], breakout_idx: int, direction: str) -> Optional[Dict]:
        """
        Find Fair Value Gap (3-candle pattern with gap).
        
        FVG pattern:
        - Bull: candle[0].high < candle[2].low (gap between them)
        - Bear: candle[0].low > candle[2].high (gap between them)
        
        Search backwards from breakout bar.
        """
        # Search area: from breakout backwards up to search limit
        search_start = max(0, breakout_idx - self.params['fvg_search_bars'])
        search_bars = bars[search_start:breakout_idx+1]
        
        if len(search_bars) < 3:
            return None
        
        # Scan backwards for FVG (most recent first)
        for i in range(len(search_bars) - 1, 1, -1):
            c0 = search_bars[i - 2]
            c1 = search_bars[i - 1]  # Middle candle (not directly used)
            c2 = search_bars[i]
            
            if direction == 'bull':
                # Bull FVG: gap between c0.high and c2.low
                gap = c2['low'] - c0['high']
                
                if gap > 0:
                    gap_pct = gap / c0['high']
                    
                    if gap_pct >= self.params['min_fvg_size']:
                        return {
                            'fvg_high': c2['low'],
                            'fvg_low': c0['high'],
                            'fvg_mid': (c2['low'] + c0['high']) / 2,
                            'fvg_size': gap,
                            'fvg_size_pct': gap_pct * 100,
                            'bar_idx': search_start + i,
                            'direction': 'bull'
                        }
            
            elif direction == 'bear':
                # Bear FVG: gap between c2.high and c0.low
                gap = c0['low'] - c2['high']
                
                if gap > 0:
                    gap_pct = gap / c0['low']
                    
                    if gap_pct >= self.params['min_fvg_size']:
                        return {
                            'fvg_high': c0['low'],
                            'fvg_low': c2['high'],
                            'fvg_mid': (c0['low'] + c2['high']) / 2,
                            'fvg_size': gap,
                            'fvg_size_pct': gap_pct * 100,
                            'bar_idx': search_start + i,
                            'direction': 'bear'
                        }
        
        return None
    
    def check_confirmation(self, bars: List[Dict], fvg: Dict) -> Optional[Dict]:
        """
        Check if price has pulled back into FVG and confirmed.
        
        Simpler logic:
        1. Check if any recent bar touched FVG
        2. Check if current bar is moving back in breakout direction
        3. Grade the confirmation candle
        """
        if len(bars) < 2:
            return None
        
        direction = fvg['direction']
        fvg_low = fvg['fvg_low']
        fvg_high = fvg['fvg_high']
        
        # Check last few bars for FVG touch
        lookback = min(10, len(bars) - 1)
        recent_bars = bars[-lookback:]
        
        # Find bars that touched FVG
        touched_fvg = False
        confirmation_bar = None
        
        for i in range(len(recent_bars) - 1, -1, -1):
            bar = recent_bars[i]
            
            if direction == 'bull':
                # Price pulled back into FVG (low touched zone)
                if bar['low'] <= fvg_high and bar['high'] >= fvg_low:
                    touched_fvg = True
                    confirmation_bar = bar
                    break
            
            elif direction == 'bear':
                # Price pulled back into FVG (high touched zone)
                if bar['high'] >= fvg_low and bar['low'] <= fvg_high:
                    touched_fvg = True
                    confirmation_bar = bar
                    break
        
        if not touched_fvg or not confirmation_bar:
            return None
        
        # Grade the confirmation
        grade = self._grade_candle(confirmation_bar, direction)
        
        if grade['score'] == 0:
            return None  # No valid confirmation
        
        # Entry on current bar
        current_bar = bars[-1]
        
        return {
            'entry_price': current_bar['open'],
            'entry_bar': current_bar,
            'confirmation_bar': confirmation_bar,
            'grade': grade['grade'],
            'score': grade['score'],
            'candle_type': grade['type']
        }
    
    def _grade_candle(self, bar: Dict, direction: str) -> Dict:
        """
        Grade confirmation candle quality.
        
        Grades:
        - A+: Strong directional candle (green for bull, red for bear)
        - A: Directional with some wick
        - A-: Has rejection wick
        - None: No confirmation
        """
        o = bar['open']
        h = bar['high']
        l = bar['low']
        c = bar['close']
        
        body = abs(c - o)
        total_range = h - l
        
        if total_range == 0:
            return {'grade': None, 'score': 0, 'type': 'Doji'}
        
        body_pct = body / total_range
        
        if direction == 'bull':
            is_green = c > o
            lower_wick = (min(o, c) - l) / total_range
            
            if is_green:
                if body_pct > 0.70:  # Strong body
                    return {'grade': 'A+', 'score': 100, 'type': 'Strong bull'}
                elif body_pct > 0.50:
                    return {'grade': 'A', 'score': 85, 'type': 'Bull with wick'}
                elif lower_wick > 0.40:
                    return {'grade': 'A-', 'score': 70, 'type': 'Bull rejection'}
            else:
                # Red candle but has lower wick rejection
                if lower_wick > 0.50:
                    return {'grade': 'A-', 'score': 70, 'type': 'Bear rejection (bull setup)'}
        
        elif direction == 'bear':
            is_red = c < o
            upper_wick = (h - max(o, c)) / total_range
            
            if is_red:
                if body_pct > 0.70:
                    return {'grade': 'A+', 'score': 100, 'type': 'Strong bear'}
                elif body_pct > 0.50:
                    return {'grade': 'A', 'score': 85, 'type': 'Bear with wick'}
                elif upper_wick > 0.40:
                    return {'grade': 'A-', 'score': 70, 'type': 'Bear rejection'}
            else:
                # Green candle but has upper wick rejection
                if upper_wick > 0.50:
                    return {'grade': 'A-', 'score': 70, 'type': 'Bull rejection (bear setup)'}
        
        return {'grade': None, 'score': 0, 'type': 'No confirmation'}
    
    def calculate_stops_targets(self, entry_price: float, direction: str, fvg: Dict) -> Dict:
        """
        Calculate stops and targets based on FVG.
        """
        fvg_size = fvg['fvg_high'] - fvg['fvg_low']
        buffer = fvg_size * 0.20
        
        if direction == 'bull':
            stop = fvg['fvg_low'] - buffer
            risk = entry_price - stop
            t1 = entry_price + risk * 1.5
            t2 = entry_price + risk * 2.5
        else:
            stop = fvg['fvg_high'] + buffer
            risk = stop - entry_price
            t1 = entry_price - risk * 1.5
            t2 = entry_price - risk * 2.5
        
        return {
            'stop': round(stop, 2),
            't1': round(t1, 2),
            't2': round(t2, 2),
            'risk': round(risk, 2)
        }
    
    def scan(self, ticker: str, bars: List[Dict]) -> Optional[Dict]:
        """
        Full scan for BOS+FVG signal.
        
        Returns:
            Signal dict if valid setup found, None otherwise
        """
        if len(bars) < 30:
            return None
        
        # Step 1: Detect breakout
        breakout = self.detect_breakout(bars)
        if not breakout:
            return None
        
        # Step 2: Find FVG
        fvg = self.find_fvg(bars, breakout['bar_idx'], breakout['direction'])
        if not fvg:
            return None
        
        # Step 3: Check for confirmation
        confirmation = self.check_confirmation(bars, fvg)
        if not confirmation:
            return None
        
        # Step 4: Calculate stops/targets
        levels = self.calculate_stops_targets(
            confirmation['entry_price'],
            breakout['direction'],
            fvg
        )
        
        return {
            'ticker': ticker,
            'timestamp': bars[-1]['datetime'],
            'direction': breakout['direction'],
            'entry_price': confirmation['entry_price'],
            'stop_price': levels['stop'],
            'target_1': levels['t1'],
            'target_2': levels['t2'],
            'bos_price': breakout['breakout_level'],
            'bos_strength': breakout['strength'],
            'fvg_low': fvg['fvg_low'],
            'fvg_high': fvg['fvg_high'],
            'fvg_size_pct': fvg['fvg_size_pct'],
            'confirmation_grade': confirmation['grade'],
            'confirmation_score': confirmation['score'],
            'candle_type': confirmation['candle_type']
        }


def get_aggressive_detector() -> AggressiveBOSDetector:
    """Get detector instance"""
    return AggressiveBOSDetector()
