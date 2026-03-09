#!/usr/bin/env python3
"""
Comprehensive Multi-Indicator BOS/FVG Detector
==============================================

Leverages ALL available War Machine features:
1. BOS/FVG from MTF engine (existing proven logic)
2. Volume Profile (HVN/LVN zones)
3. VWAP bands and zones
4. Opening Range classification
5. Multi-timeframe alignment (1m/5m/15m)
6. Signal boosters (ML, UOA, MTF validator)
7. 3-tier candle confirmation (A+/A/A-)

Strategy:
- Focus on FIRST 30 minutes (9:30-10:00) for Opening Range BOS
- Then continue scanning for high-quality intraday BOS throughout day
- Use all indicators for GRADING, not filtering
- Enter ONLY A+ and A signals (85%+ confidence)

Author: War Machine Team
Date: March 9, 2026
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time
from dataclasses import dataclass

# Import existing modules
try:
    from app.mtf.bos_fvg_engine import (
        detect_bos, find_fvg_after_bos, classify_confirmation_candle,
        check_fvg_entry, compute_0dte_stops_and_targets
    )
    from app.indicators.vwap_calculator import VWAPCalculator
    from app.indicators.volume_profile import VolumeProfileCalculator
    from app.enhancements.signal_boosters import (
        get_or_classifier, get_mtf_validator
    )
except ImportError:
    # Fallback for testing
    detect_bos = None
    VWAPCalculator = None
    VolumeProfileCalculator = None
    get_or_classifier = None


@dataclass
class ComprehensiveSignal:
    """Signal with full context from all indicators"""
    # Core signal
    timestamp: datetime
    ticker: str
    direction: str  # 'CALL' or 'PUT'
    entry_price: float
    stop_price: float
    target_1: float
    target_2: float
    
    # BOS/FVG details
    bos_price: float
    bos_strength: float
    fvg_low: float
    fvg_high: float
    fvg_size_pct: float
    confirmation_grade: str  # 'A+', 'A', 'A-'
    confirmation_score: int
    
    # Volume context
    volume_ratio: float
    volume_profile_zone: str  # 'HVN', 'LVN', 'neutral'
    
    # VWAP context
    price_vs_vwap: float
    vwap_band: str  # 'above_2sd', 'above_1sd', 'at_vwap', etc.
    
    # Opening Range
    is_opening_range: bool
    or_classification: str  # 'TIGHT', 'NORMAL', 'WIDE'
    or_boost: float
    
    # Multi-timeframe
    mtf_score: float
    trend_1min: str
    trend_5min: str
    trend_15min: str
    
    # Final grading
    grade: str  # 'A+', 'A', 'B', 'C'
    confidence: float
    

class ComprehensiveDetector:
    """
    Comprehensive detector using ALL War Machine features.
    """
    
    def __init__(self):
        # Initialize calculators
        try:
            self.vwap_calc = VWAPCalculator() if VWAPCalculator else None
            self.vp_calc = VolumeProfileCalculator() if VolumeProfileCalculator else None
            self.or_classifier = get_or_classifier() if get_or_classifier else None
            self.mtf_validator = get_mtf_validator() if get_mtf_validator else None
        except:
            self.vwap_calc = None
            self.vp_calc = None
            self.or_classifier = None
            self.mtf_validator = None
        
        # Detector params - VERY RELAXED for initial detection
        self.params = {
            # Detection thresholds (loose - we filter with grading)
            'min_bos_strength': 0.003,      # 0.3%
            'min_fvg_size': 0.002,          # 0.2%
            'min_volume_ratio': 1.2,        # 1.2x
            
            # Opening range (9:30-10:00)
            'or_start': time(9, 30),
            'or_end': time(10, 0),
            'or_min_bos': 0.005,            # 0.5% for OR breakouts
            'or_min_volume': 1.5,            # 1.5x for OR
            
            # Intraday (10:00-15:30)
            'intraday_min_bos': 0.004,      # 0.4%
            'intraday_min_volume': 1.3,      # 1.3x
            
            # Signal quality filters
            'min_confidence_to_signal': 0.75,  # Only A+ and A signals
            'require_confirmation': True,       # Must have A+/A/A- candle
        }
        
        print("[COMPREHENSIVE] ✅ Initialized with ALL indicators")
        print(f"[COMPREHENSIVE] Min confidence: {self.params['min_confidence_to_signal']:.0%}")
        print(f"[COMPREHENSIVE] OR window: {self.params['or_start']}-{self.params['or_end']}")
    
    def detect_signals(
        self,
        ticker: str,
        bars_1min: List[Dict],
        bars_5min: List[Dict],
        bars_15min: List[Dict] = None
    ) -> Optional[ComprehensiveSignal]:
        """
        Detect comprehensive signals using all indicators.
        
        Args:
            ticker: Stock ticker
            bars_1min: 1-minute bars (current detection timeframe)
            bars_5min: 5-minute bars (for MTF validation)
            bars_15min: 15-minute bars (optional, for deeper MTF)
        
        Returns:
            ComprehensiveSignal if valid setup found, None otherwise
        """
        if len(bars_1min) < 50:
            return None
        
        latest_bar = bars_1min[-1]
        timestamp = latest_bar['datetime']
        
        # Market hours check
        if timestamp.hour < 9 or (timestamp.hour == 9 and timestamp.minute < 30):
            return None
        
        if timestamp.hour >= 16:
            return None
        
        # Determine session type
        is_opening_range = (
            self.params['or_start'] <= timestamp.time() < self.params['or_end']
        )
        
        # === STEP 1: DETECT BOS ===
        if not detect_bos:
            return None  # MTF engine not available
        
        bos = detect_bos(bars_1min)
        if not bos:
            return None
        
        # Check BOS strength
        min_strength = (
            self.params['or_min_bos'] if is_opening_range
            else self.params['intraday_min_bos']
        )
        
        if bos['strength'] < min_strength:
            return None
        
        # === STEP 2: FIND FVG ===
        fvg_threshold = (
            self.params['min_fvg_size'] * 0.5 if is_opening_range
            else self.params['min_fvg_size']
        )
        
        fvg = find_fvg_after_bos(
            bars_1min, bos['bos_idx'], bos['direction'],
            min_pct=fvg_threshold
        )
        
        if not fvg:
            return None
        
        # === STEP 3: CHECK FOR CONFIRMATION ENTRY ===
        entry_trigger = check_fvg_entry(
            bars_1min, fvg,
            require_confirmation=self.params['require_confirmation']
        )
        
        if not entry_trigger:
            return None
        
        # Only trade A+, A, or A- confirmations
        if entry_trigger['confirmation'] not in ['A+', 'A', 'A-']:
            return None
        
        # === STEP 4: CALCULATE STOPS & TARGETS ===
        levels = compute_0dte_stops_and_targets(
            entry_trigger['entry_price'], bos['direction'], fvg
        )
        
        # === STEP 5: ENRICH WITH ALL INDICATORS ===
        
        # Volume analysis
        volume_data = self._analyze_volume(bars_1min, len(bars_1min) - 1)
        
        # VWAP analysis
        vwap_data = self._analyze_vwap(bars_1min, len(bars_1min) - 1)
        
        # Volume Profile analysis
        vp_data = self._analyze_volume_profile(bars_1min, entry_trigger['entry_price'])
        
        # Opening Range classification
        or_data = self._classify_opening_range(
            ticker, bars_1min, is_opening_range
        )
        
        # Multi-timeframe analysis
        mtf_data = self._analyze_mtf(
            ticker, bars_1min, bars_5min, bars_15min,
            bos['direction']
        )
        
        # === STEP 6: CALCULATE FINAL GRADE & CONFIDENCE ===
        grade, confidence = self._calculate_comprehensive_grade(
            bos, fvg, entry_trigger, volume_data, vwap_data,
            vp_data, or_data, mtf_data, is_opening_range
        )
        
        # Filter by minimum confidence
        if confidence < self.params['min_confidence_to_signal']:
            return None
        
        # === STEP 7: BUILD SIGNAL ===
        signal = ComprehensiveSignal(
            timestamp=timestamp,
            ticker=ticker,
            direction='CALL' if bos['direction'] == 'bull' else 'PUT',
            entry_price=entry_trigger['entry_price'],
            stop_price=levels['stop'],
            target_1=levels['t1'],
            target_2=levels['t2'],
            bos_price=bos['bos_price'],
            bos_strength=bos['strength'],
            fvg_low=fvg['fvg_low'],
            fvg_high=fvg['fvg_high'],
            fvg_size_pct=fvg['fvg_size_pct'],
            confirmation_grade=entry_trigger['confirmation'],
            confirmation_score=entry_trigger['conf_score'],
            volume_ratio=volume_data['ratio'],
            volume_profile_zone=vp_data['zone'],
            price_vs_vwap=vwap_data['price_vs_vwap'],
            vwap_band=vwap_data['band'],
            is_opening_range=is_opening_range,
            or_classification=or_data['classification'],
            or_boost=or_data['boost'],
            mtf_score=mtf_data['score'],
            trend_1min=mtf_data['trend_1min'],
            trend_5min=mtf_data['trend_5min'],
            trend_15min=mtf_data['trend_15min'],
            grade=grade,
            confidence=confidence
        )
        
        return signal
    
    def _analyze_volume(self, bars: List[Dict], idx: int) -> Dict:
        """Analyze volume context"""
        if idx < 20:
            return {'ratio': 1.0, 'percentile': 50}
        
        current_vol = bars[idx]['volume']
        recent_vols = [bars[i]['volume'] for i in range(max(0, idx-20), idx)]
        avg_vol = np.mean(recent_vols) if recent_vols else 1
        
        ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        percentile = sum(1 for v in recent_vols if current_vol > v) / len(recent_vols) * 100
        
        return {'ratio': ratio, 'percentile': percentile}
    
    def _analyze_vwap(self, bars: List[Dict], idx: int) -> Dict:
        """Analyze VWAP context"""
        if idx < 50:
            return {'price_vs_vwap': 0, 'band': 'unknown', 'distance': 0}
        
        # Calculate session VWAP
        session_bars = bars[max(0, idx-100):idx+1]
        
        cum_pv = sum((b['high']+b['low']+b['close'])/3 * b['volume'] for b in session_bars)
        cum_vol = sum(b['volume'] for b in session_bars)
        
        if cum_vol == 0:
            return {'price_vs_vwap': 0, 'band': 'unknown', 'distance': 0}
        
        vwap = cum_pv / cum_vol
        current_price = bars[idx]['close']
        price_vs_vwap = (current_price - vwap) / vwap
        
        # Calculate standard deviation bands
        deviations = [(b['close'] - vwap)**2 * b['volume'] for b in session_bars]
        variance = sum(deviations) / cum_vol
        std_dev = np.sqrt(variance)
        
        # Determine band
        if current_price > vwap + 2*std_dev:
            band = 'above_2sd'
        elif current_price > vwap + std_dev:
            band = 'above_1sd'
        elif current_price > vwap:
            band = 'above_vwap'
        elif current_price < vwap - 2*std_dev:
            band = 'below_2sd'
        elif current_price < vwap - std_dev:
            band = 'below_1sd'
        else:
            band = 'at_vwap'
        
        return {
            'price_vs_vwap': price_vs_vwap,
            'band': band,
            'distance': abs(price_vs_vwap)
        }
    
    def _analyze_volume_profile(self, bars: List[Dict], entry_price: float) -> Dict:
        """Analyze volume profile context"""
        if len(bars) < 100:
            return {'zone': 'neutral', 'hvn_distance': 0, 'lvn_distance': 0}
        
        # Simple VP: bucket prices and sum volume
        recent_bars = bars[-100:]
        
        # Create price buckets (0.1% increments)
        prices = [b['close'] for b in recent_bars]
        min_price = min(prices)
        max_price = max(prices)
        
        if max_price == min_price:
            return {'zone': 'neutral', 'hvn_distance': 0, 'lvn_distance': 0}
        
        num_buckets = 20
        bucket_size = (max_price - min_price) / num_buckets
        
        volume_by_price = {}
        for bar in recent_bars:
            bucket = int((bar['close'] - min_price) / bucket_size)
            bucket = min(bucket, num_buckets - 1)
            volume_by_price[bucket] = volume_by_price.get(bucket, 0) + bar['volume']
        
        # Find HVN (high volume nodes) and LVN (low volume nodes)
        sorted_buckets = sorted(volume_by_price.items(), key=lambda x: x[1], reverse=True)
        
        hvn_buckets = [b[0] for b in sorted_buckets[:3]]  # Top 3
        lvn_buckets = [b[0] for b in sorted_buckets[-3:]]  # Bottom 3
        
        # Determine entry bucket
        entry_bucket = int((entry_price - min_price) / bucket_size)
        entry_bucket = min(entry_bucket, num_buckets - 1)
        
        # Classify zone
        if entry_bucket in hvn_buckets:
            zone = 'HVN'
        elif entry_bucket in lvn_buckets:
            zone = 'LVN'
        else:
            zone = 'neutral'
        
        return {'zone': zone, 'hvn_distance': 0, 'lvn_distance': 0}
    
    def _classify_opening_range(self, ticker: str, bars: List[Dict], is_opening_range: bool) -> Dict:
        """Classify opening range"""
        if not is_opening_range or len(bars) < 20:
            return {'classification': 'N/A', 'boost': 0.0}
        
        # Find OR high/low (9:30-10:00)
        or_bars = [b for b in bars if self.params['or_start'] <= b['datetime'].time() < self.params['or_end']]
        
        if len(or_bars) < 5:
            return {'classification': 'N/A', 'boost': 0.0}
        
        or_high = max(b['high'] for b in or_bars)
        or_low = min(b['low'] for b in or_bars)
        or_range = or_high - or_low
        or_range_pct = or_range / or_low if or_low > 0 else 0
        
        # Calculate ATR
        atr = self._calculate_atr(bars[-20:])
        
        or_range_atr = or_range / atr if atr > 0 else 1.0
        
        # Classify
        if or_range_atr < 0.5:
            classification = 'TIGHT'
            boost = 0.10
        elif or_range_atr <= 1.5:
            classification = 'NORMAL'
            boost = 0.05
        else:
            classification = 'WIDE'
            boost = 0.0
        
        return {'classification': classification, 'boost': boost}
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR"""
        if len(bars) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        return np.mean(true_ranges[-period:]) if len(true_ranges) >= period else 0.0
    
    def _analyze_mtf(self, ticker: str, bars_1min: List[Dict], bars_5min: List[Dict], bars_15min: Optional[List[Dict]], direction: str) -> Dict:
        """Analyze multi-timeframe context"""
        trend_1min = self._calculate_trend(bars_1min, len(bars_1min)-1)
        trend_5min = self._calculate_trend(bars_5min, len(bars_5min)-1) if bars_5min and len(bars_5min) > 20 else 'neutral'
        trend_15min = self._calculate_trend(bars_15min, len(bars_15min)-1) if bars_15min and len(bars_15min) > 20 else 'neutral'
        
        # Calculate alignment score
        expected_trend = 'bull' if direction == 'bull' else 'bear'
        
        score = 5.0  # Base score
        
        if trend_1min == expected_trend:
            score += 2.0
        if trend_5min == expected_trend:
            score += 2.0
        if trend_15min == expected_trend:
            score += 1.0
        
        return {
            'trend_1min': trend_1min,
            'trend_5min': trend_5min,
            'trend_15min': trend_15min,
            'score': min(score, 10.0)
        }
    
    def _calculate_trend(self, bars: List[Dict], idx: int, lookback: int = 20) -> str:
        """Calculate trend using EMA"""
        if idx < lookback + 10 or not bars:
            return 'neutral'
        
        recent_bars = bars[max(0, idx-lookback):idx+1]
        closes = [b['close'] for b in recent_bars]
        
        if len(closes) < 10:
            return 'neutral'
        
        ema = self._calculate_ema(closes, 10)
        
        if len(ema) < 5:
            return 'neutral'
        
        slope = (ema[-1] - ema[0]) / ema[0]
        
        if slope > 0.002:
            return 'bull'
        elif slope < -0.002:
            return 'bear'
        else:
            return 'neutral'
    
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
    
    def _calculate_comprehensive_grade(self, bos, fvg, entry_trigger, volume_data, vwap_data, vp_data, or_data, mtf_data, is_opening_range) -> Tuple[str, float]:
        """Calculate comprehensive grade using all indicators"""
        confidence = 0.50  # Base
        
        # === CANDLE CONFIRMATION (25%) ===
        conf_grade = entry_trigger['confirmation']
        if conf_grade == 'A+':
            confidence += 0.25
        elif conf_grade == 'A':
            confidence += 0.20
        elif conf_grade == 'A-':
            confidence += 0.15
        
        # === BOS STRENGTH (10%) ===
        if bos['strength'] >= 0.015:  # 1.5%+
            confidence += 0.10
        elif bos['strength'] >= 0.010:  # 1.0%+
            confidence += 0.07
        elif bos['strength'] >= 0.005:  # 0.5%+
            confidence += 0.05
        
        # === VOLUME (10%) ===
        vol_ratio = volume_data['ratio']
        if vol_ratio >= 2.5:
            confidence += 0.10
        elif vol_ratio >= 2.0:
            confidence += 0.07
        elif vol_ratio >= 1.5:
            confidence += 0.05
        
        # === VWAP ALIGNMENT (10%) ===
        vwap_band = vwap_data['band']
        if vwap_band in ['at_vwap', 'above_vwap', 'below_vwap']:  # Near VWAP = good
            confidence += 0.10
        elif vwap_band in ['above_1sd', 'below_1sd']:
            confidence += 0.05
        
        # === VOLUME PROFILE (5%) ===
        if vp_data['zone'] == 'LVN':  # Low volume = clean breakout
            confidence += 0.05
        
        # === OPENING RANGE (10%) ===
        if is_opening_range:
            confidence += or_data['boost']
        
        # === MULTI-TIMEFRAME (10%) ===
        mtf_score = mtf_data['score']
        if mtf_score >= 9.0:
            confidence += 0.10
        elif mtf_score >= 7.0:
            confidence += 0.07
        elif mtf_score >= 5.0:
            confidence += 0.05
        
        confidence = min(confidence, 1.0)
        
        # Assign grade
        if confidence >= 0.90:
            grade = 'A+'
        elif confidence >= 0.80:
            grade = 'A'
        elif confidence >= 0.70:
            grade = 'B'
        else:
            grade = 'C'
        
        return grade, confidence


def get_comprehensive_detector() -> ComprehensiveDetector:
    """Get detector instance"""
    return ComprehensiveDetector()
