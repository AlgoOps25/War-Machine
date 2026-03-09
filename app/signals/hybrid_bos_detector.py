#!/usr/bin/env python3
"""
Hybrid BOS/FVG Detector - Best of Both Worlds
=============================================

Combines:
1. AGGRESSIVE BOS detection (recent high/low - catches more setups)
2. PROVEN MTF FVG logic (3-candle gap pattern - battle-tested)
3. NITRO TRADES confirmation (A+/A/A- grading - proven quality filter)

This is the BEST detector for live trading.

Author: War Machine Team  
Date: March 9, 2026
"""

import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, time


class HybridBOSDetector:
    """
    Hybrid detector with aggressive BOS + proven MTF FVG.
    """
    
    def __init__(self):
        self.params = {
            # AGGRESSIVE BOS (relaxed thresholds)
            'bos_lookback_min': 5,
            'bos_lookback_max': 20,
            'min_bos_strength': 0.001,  # 0.1%
            
            # PROVEN MTF FVG
            'min_fvg_size': 0.001,  # 0.1% (same as MTF default)
            'fvg_search_bars': 30,
            
            # NITRO TRADES CONFIRMATION
            'require_confirmation': True,
        }
        
        # State tracking
        self.active_fvg = None
        self.fvg_found_at = None
    
    def detect_breakout(self, bars: List[Dict]) -> Optional[Dict]:
        """
        AGGRESSIVE: Detect breakout above/below recent high/low.
        
        More sensitive than swing point logic - catches early moves.
        """
        if len(bars) < 25:
            return None
        
        current_bar = bars[-1]
        lookback_min = self.params['bos_lookback_min']
        lookback_max = self.params['bos_lookback_max']
        
        recent_bars = bars[-(lookback_max+1):-1]
        recent_high = max(b['high'] for b in recent_bars)
        recent_low = min(b['low'] for b in recent_bars)
        
        # BULL breakout
        if current_bar['close'] > recent_high:
            strength = (current_bar['close'] - recent_high) / recent_high
            
            if strength >= self.params['min_bos_strength']:
                is_green = current_bar['close'] > current_bar['open']
                
                if not self.params['require_confirmation'] or is_green:
                    return {
                        'direction': 'bull',
                        'bos_price': recent_high,
                        'break_price': current_bar['close'],
                        'strength': strength,
                        'bar_idx': len(bars) - 1,
                        'bar': current_bar
                    }
        
        # BEAR breakout
        if current_bar['close'] < recent_low:
            strength = (recent_low - current_bar['close']) / recent_low
            
            if strength >= self.params['min_bos_strength']:
                is_red = current_bar['close'] < current_bar['open']
                
                if not self.params['require_confirmation'] or is_red:
                    return {
                        'direction': 'bear',
                        'bos_price': recent_low,
                        'break_price': current_bar['close'],
                        'strength': strength,
                        'bar_idx': len(bars) - 1,
                        'bar': current_bar
                    }
        
        return None
    
    def find_fvg_mtf_logic(self, bars: List[Dict], bos_idx: int, direction: str) -> Optional[Dict]:
        """
        PROVEN MTF LOGIC: Find FVG using battle-tested 3-candle pattern.
        
        This is the EXACT logic from your working MTF engine.
        """
        search_start = max(0, bos_idx - 5)
        search_bars = bars[search_start:]
        
        if len(search_bars) < 3:
            return None
        
        min_pct = self.params['min_fvg_size']
        
        for i in range(2, len(search_bars)):
            c0 = search_bars[i - 2]
            c1 = search_bars[i - 1]
            c2 = search_bars[i]
            
            if direction == 'bull':
                gap = c2['low'] - c0['high']
                
                if gap > 0 and (gap / c0['high']) >= min_pct:
                    return {
                        'fvg_high': c2['low'],
                        'fvg_low': c0['high'],
                        'fvg_mid': (c2['low'] + c0['high']) / 2,
                        'fvg_size': gap,
                        'fvg_size_pct': round(gap / c0['high'] * 100, 3),
                        'fvg_bar_idx': search_start + i,
                        'direction': 'bull'
                    }
            
            elif direction == 'bear':
                gap = c0['low'] - c2['high']
                
                if gap > 0 and (gap / c0['low']) >= min_pct:
                    return {
                        'fvg_high': c0['low'],
                        'fvg_low': c2['high'],
                        'fvg_mid': (c0['low'] + c2['high']) / 2,
                        'fvg_size': gap,
                        'fvg_size_pct': round(gap / c0['low'] * 100, 3),
                        'fvg_bar_idx': search_start + i,
                        'direction': 'bear'
                    }
        
        return None
    
    def classify_confirmation_nitro(self, bar: Dict, fvg: Dict) -> Dict:
        """
        NITRO TRADES LOGIC: 3-tier candle grading (A+/A/A-).
        
        This is the EXACT logic from your proven MTF engine.
        """
        direction = fvg['direction']
        o = bar['open']
        h = bar['high']
        l = bar['low']
        c = bar['close']
        
        body = abs(c - o)
        total_range = h - l
        
        if total_range == 0:
            return {'grade': None, 'score': 0, 'candle_type': 'Doji (no range)'}
        
        if direction == 'bull':
            lower_wick = o - l if c >= o else c - l
            upper_wick = h - c if c >= o else h - o
            is_green = c > o
            is_red = c < o
            
            # A+: Strong green candle with minimal lower wick
            if is_green and (lower_wick / total_range) < 0.20:
                return {
                    'grade': 'A+',
                    'score': 100,
                    'candle_type': 'Strong bull push (no wick)'
                }
            
            # A: Opens red initially, flips to green (strong lower wick)
            if is_green and (lower_wick / total_range) >= 0.30:
                return {
                    'grade': 'A',
                    'score': 85,
                    'candle_type': 'Bull flip (red→green with wick)'
                }
            
            # A-: Red candle but large lower wick rejection
            if is_red and (lower_wick / total_range) >= 0.50:
                return {
                    'grade': 'A-',
                    'score': 70,
                    'candle_type': 'Bull rejection wick (stayed red)'
                }
        
        elif direction == 'bear':
            upper_wick = h - o if c <= o else h - c
            lower_wick = c - l if c <= o else o - l
            is_red = c < o
            is_green = c > o
            
            # A+: Strong red candle with minimal upper wick
            if is_red and (upper_wick / total_range) < 0.20:
                return {
                    'grade': 'A+',
                    'score': 100,
                    'candle_type': 'Strong bear push (no wick)'
                }
            
            # A: Opens green initially, flips to red (strong upper wick)
            if is_red and (upper_wick / total_range) >= 0.30:
                return {
                    'grade': 'A',
                    'score': 85,
                    'candle_type': 'Bear flip (green→red with wick)'
                }
            
            # A-: Green candle but large upper wick rejection
            if is_green and (upper_wick / total_range) >= 0.50:
                return {
                    'grade': 'A-',
                    'score': 70,
                    'candle_type': 'Bear rejection wick (stayed green)'
                }
        
        return {
            'grade': None,
            'score': 0,
            'candle_type': 'No confirmation'
        }
    
    def check_fvg_entry_mtf(self, bars: List[Dict], fvg: Dict) -> Optional[Dict]:
        """
        PROVEN MTF LOGIC: Check for FVG retest + confirmation.
        
        Checks PREVIOUS bar for retest, enters on CURRENT bar.
        This is the EXACT logic from your working MTF engine.
        """
        if len(bars) < 2:
            return None
        
        prev_bar = bars[-2]
        current_bar = bars[-1]
        
        direction = fvg['direction']
        fvg_low = fvg['fvg_low']
        fvg_high = fvg['fvg_high']
        
        # Check if PREVIOUS bar retested FVG
        price_in_fvg = False
        
        if direction == 'bull':
            if prev_bar['low'] <= fvg_high and prev_bar['close'] >= fvg_low:
                price_in_fvg = True
        
        elif direction == 'bear':
            if prev_bar['high'] >= fvg_low and prev_bar['close'] <= fvg_high:
                price_in_fvg = True
        
        if not price_in_fvg:
            return None
        
        # Grade the confirmation candle
        confirmation = self.classify_confirmation_nitro(prev_bar, fvg)
        
        if self.params['require_confirmation'] and confirmation['grade'] is None:
            return None
        
        # Entry on CURRENT bar open
        return {
            'entry_price': current_bar['open'],
            'entry_bar': current_bar,
            'confirmation_bar': prev_bar,
            'grade': confirmation['grade'],
            'score': confirmation['score'],
            'candle_type': confirmation['candle_type']
        }
    
    def calculate_stops_targets(self, entry_price: float, direction: str, fvg: Dict) -> Dict:
        """
        0DTE stops and targets (same as MTF).
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
        HYBRID SCAN: Aggressive BOS + Proven MTF FVG + Nitro confirmation.
        
        This combines the best of all worlds.
        """
        if len(bars) < 30:
            return None
        
        # Check if we have active FVG waiting for retest
        if self.active_fvg is not None:
            confirmation = self.check_fvg_entry_mtf(bars, self.active_fvg)
            
            if confirmation:
                # Got confirmation! Build signal
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
                
                # Reset
                self.active_fvg = None
                self.fvg_found_at = None
                
                return signal
            
            # FVG too old? Reset
            if len(bars) - self.fvg_found_at > 50:
                self.active_fvg = None
                self.fvg_found_at = None
        
        # Look for new BOS + FVG
        breakout = self.detect_breakout(bars)
        if not breakout:
            return None
        
        fvg = self.find_fvg_mtf_logic(bars, breakout['bar_idx'], breakout['direction'])
        if not fvg:
            return None
        
        # Store FVG and wait
        fvg['bos_price'] = breakout['bos_price']
        fvg['bos_strength'] = breakout['strength']
        
        self.active_fvg = fvg
        self.fvg_found_at = len(bars) - 1
        
        return None


def get_hybrid_detector() -> HybridBOSDetector:
    """Get hybrid detector instance"""
    return HybridBOSDetector()
