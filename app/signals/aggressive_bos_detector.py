#!/usr/bin/env python3
"""
Aggressive BOS/FVG Detector - Catches More Signals
===================================================

Simplified BOS detection:
- Uses recent high/low (last 5-20 bars) instead of complex swing logic
- Detects when price breaks above recent high or below recent low
- Finds FVG (3-candle gap) immediately
- Requires strong candle confirmation

FIXED: Proper FVG retest confirmation logic
- Track FVG state across bars
- Wait for pullback INTO FVG zone
- Confirm with strong directional candle
- Enter on next bar

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
            'fvg_retest_lookback': 20,      # How far back to look for FVG retest
        }
        
        # Track active FVG zones
        self.active_fvg = None
        self.fvg_found_at = None
    
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
    
    def check_fvg_retest_and_confirm(self, bars: List[Dict], fvg: Dict, fvg_bar_idx: int) -> Optional[Dict]:
        """
        FIXED: Proper FVG retest and confirmation logic.
        
        Logic:
        1. FVG must have been created at least 2 bars ago
        2. Look for a bar that pulled back INTO the FVG zone
        3. That bar must have CLOSED (we're looking at historical bars)
        4. Grade that closed bar
        5. If confirmed (A+/A/A-), trigger entry on NEXT bar
        6. We need at least 2 bars after FVG (retest bar + entry bar)
        
        Returns:
            Confirmation dict with entry details, or None
        """
        current_bar_idx = len(bars) - 1
        
        # Need at least 2 bars after FVG was created
        if current_bar_idx < fvg_bar_idx + 2:
            return None
        
        direction = fvg['direction']
        fvg_low = fvg['fvg_low']
        fvg_high = fvg['fvg_high']
        
        # Look at bars AFTER FVG was created
        bars_after_fvg = bars[fvg_bar_idx+1:]
        
        if len(bars_after_fvg) < 2:
            return None
        
        # Check if the PREVIOUS bar (bars_after_fvg[-2]) retested FVG
        # And we're now on the ENTRY bar (bars_after_fvg[-1])
        
        retest_bar = bars_after_fvg[-2]
        entry_bar = bars_after_fvg[-1]
        
        # Check if retest bar touched FVG
        touched_fvg = False
        
        if direction == 'bull':
            # Bull: price pulled back into FVG from above
            if retest_bar['low'] <= fvg_high and retest_bar['high'] >= fvg_low:
                touched_fvg = True
        
        elif direction == 'bear':
            # Bear: price pulled back into FVG from below
            if retest_bar['high'] >= fvg_low and retest_bar['low'] <= fvg_high:
                touched_fvg = True
        
        if not touched_fvg:
            return None
        
        # Grade the retest bar
        grade = self._grade_candle(retest_bar, direction)
        
        if grade['score'] == 0:
            return None  # No valid confirmation
        
        # Entry on current bar (the bar AFTER retest)
        return {
            'entry_price': entry_bar['open'],
            'entry_bar': entry_bar,
            'confirmation_bar': retest_bar,
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
        Full scan for BOS+FVG signal with PROPER confirmation wait logic.
        
        Returns:
            Signal dict if valid setup found, None otherwise
        """
        if len(bars) < 30:
            return None
        
        # Step 1: Check if we have an active FVG waiting for retest
        if self.active_fvg is not None:
            # Check for confirmation on active FVG
            confirmation = self.check_fvg_retest_and_confirm(
                bars, self.active_fvg, self.fvg_found_at
            )
            
            if confirmation:
                # Got confirmation! Build signal and reset
                levels = self.calculate_stops_targets(
                    confirmation['entry_price'],
                    self.active_fvg['direction'],
                    self.active_fvg
                )
                
                signal = {
                    'ticker': ticker,
                    'timestamp': bars[-1]['datetime'],
                    'direction': self.active_fvg['direction'],
                    'entry_price': confirmation['entry_price'],
                    'stop_price': levels['stop'],
                    'target_1': levels['t1'],
                    'target_2': levels['t2'],
                    'bos_price': self.active_fvg.get('bos_price', 0),
                    'bos_strength': self.active_fvg.get('bos_strength', 0),
                    'fvg_low': self.active_fvg['fvg_low'],
                    'fvg_high': self.active_fvg['fvg_high'],
                    'fvg_size_pct': self.active_fvg['fvg_size_pct'],
                    'confirmation_grade': confirmation['grade'],
                    'confirmation_score': confirmation['score'],
                    'candle_type': confirmation['candle_type']
                }
                
                # Reset active FVG
                self.active_fvg = None
                self.fvg_found_at = None
                
                return signal
            
            # Still waiting for confirmation, continue
            # Check if FVG is too old (more than 50 bars ago)
            if len(bars) - self.fvg_found_at > 50:
                self.active_fvg = None
                self.fvg_found_at = None
        
        # Step 2: Look for new breakout + FVG
        breakout = self.detect_breakout(bars)
        if not breakout:
            return None
        
        # Step 3: Find FVG
        fvg = self.find_fvg(bars, breakout['bar_idx'], breakout['direction'])
        if not fvg:
            return None
        
        # Step 4: Store FVG and wait for retest
        fvg['bos_price'] = breakout['breakout_level']
        fvg['bos_strength'] = breakout['strength']
        
        self.active_fvg = fvg
        self.fvg_found_at = len(bars) - 1
        
        # Don't return signal yet - wait for confirmation on next scan
        return None


def get_aggressive_detector() -> AggressiveBOSDetector:
    """Get detector instance"""
    return AggressiveBOSDetector()
