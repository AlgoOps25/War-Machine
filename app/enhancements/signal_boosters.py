"""
Signal Boosters — Optional Enhancement Modules for Sniper.py
=============================================================

Consolidated from signal_generator.py — these are opt-in features that enhance
the core CFW6 BOS+FVG pipeline without creating a duplicate signal path.

Features:
- ML Confidence Booster: Predict confidence adjustments using historical data
- UOA Whale Detection: Identify unusual options activity and flow alignment
- OR Classifier: Opening range tight/wide classification with confidence adjustments

NOTE: MTFValidator stub has been removed from this file (Mar 10 2026).
      The real MTF trend validator now lives in app/signals/mtf_validator.py
      and is wired into sniper.py between Steps 8-9.

All features are disabled by default. Enable in sniper.py with:
    ML_BOOSTER_ENABLED = True
    UOA_WHALE_ENABLED = True
    OR_CLASSIFIER_ENABLED = True

Author: War Machine Team
Date: March 6, 2026
"""

from typing import Dict, Optional, List
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ═════════════════════════════════════════════════════════════════════════════════
# ML CONFIDENCE BOOSTER
# ═════════════════════════════════════════════════════════════════════════════════

class MLConfidenceBooster:
    """
    Predict confidence adjustments (±15%) based on 22 features:
    - Time features (hour, day of week, time since open)
    - Gap features (size, direction, absolute value)
    - Volume features (entry volume, surge ratio, OR volume)
    - Price vs levels (PDH, PDL, OR high)
    - VIX level
    - Signal type one-hot encoding

    Model is trained offline on historical signal outcomes.
    Returns adjustment in range [-0.15, +0.15] to be added to base confidence.
    """

    def __init__(self):
        self.is_trained = False
        self.model = None
        self.feature_means = None
        self.feature_stds = None
        try:
            self._load_model()
        except Exception as e:
            print(f"[ML-BOOST] Model not available: {e}")

    def _load_model(self):
        """Load trained model from disk (placeholder for now)."""
        pass

    def predict_confidence_adjustment(self, features: Dict[str, float]) -> float:
        if not self.is_trained or self.model is None:
            return 0.0
        return 0.0

    def extract_features(self, ticker: str, signal: Dict, latest_bar: Dict) -> Dict[str, float]:
        features = {}
        now_et = datetime.now(ET)
        features['hour_of_day']        = now_et.hour
        features['day_of_week']        = now_et.weekday()
        features['time_since_open_min'] = (now_et.hour - 9) * 60 + (now_et.minute - 30)
        gap_pct = signal.get('gap_pct', 0.0)
        features['gap_pct']       = gap_pct
        features['gap_abs']       = abs(gap_pct)
        features['gap_direction'] = 1 if gap_pct > 0 else 0
        volume = latest_bar.get('volume', signal.get('volume', 0))
        features['entry_volume']      = volume
        features['volume_surge_ratio'] = signal.get('volume_surge', 1.0)
        features['or_volume']         = signal.get('or_volume', 0)
        features['volume_log']        = np.log1p(volume)
        features['price_vs_pdh']      = signal.get('price_vs_pdh', 0.0)
        features['price_vs_or_high']  = signal.get('price_vs_or_high', 0.0)
        entry_price = signal.get('entry_price', 0)
        pdh = signal.get('pdh', 0)
        pdl = signal.get('pdl', 0)
        if pdh and pdl and entry_price:
            features['pdh_distance_pct'] = (entry_price - pdh) / pdh * 100
            features['pdl_distance_pct'] = (entry_price - pdl) / pdl * 100
            features['pd_range_pct']     = (pdh - pdl) / pdl * 100
        else:
            features['pdh_distance_pct'] = 0.0
            features['pdl_distance_pct'] = 0.0
            features['pd_range_pct']     = 0.0
        or_high = signal.get('or_high', 0)
        or_low  = signal.get('or_low',  0)
        if or_high and or_low and entry_price:
            features['or_breakout_size_pct'] = (entry_price - or_high) / or_high * 100
            features['or_range_pct']         = (or_high - or_low) / or_low * 100
        else:
            features['or_breakout_size_pct'] = 0.0
            features['or_range_pct']         = 0.0
        features['vix_level'] = signal.get('vix', 15.0)
        signal_type = signal.get('signal_type', 'CFW6_OR')
        for st in ['CFW6_OR', 'CFW6_INTRADAY', 'gap_breakout', 'volume_surge']:
            features[f'signal_{st}'] = 1 if st in signal_type else 0
        return features


# ═════════════════════════════════════════════════════════════════════════════════
# UOA WHALE DETECTION
# ═════════════════════════════════════════════════════════════════════════════════

class UOAWhaleDetector:
    """
    Detect unusual options activity and large whale trades.

    Checks:
    - Volume vs open interest ratio
    - Premium size (large premium = institutional interest)
    - Flow alignment with signal direction

    Returns confidence boost of 0-10% if whale activity detected and aligned.
    """

    def __init__(self):
        self.cache = {}
        self.cache_ttl = 300

    def check_whale_activity(self, ticker: str, direction: str) -> Dict:
        cache_key = f"{ticker}_{direction}"
        if cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_result
        result = {
            'is_unusual': False,
            'whale_score': 5.0,
            'flow_score': 5.0,
            'overall_score': 5.0,
            'confidence_boost': 0.0,
            'summary': 'UOA detection not yet implemented'
        }
        self.cache[cache_key] = (datetime.now(), result)
        return result

    def clear_cache(self):
        self.cache.clear()


# ═════════════════════════════════════════════════════════════════════════════════
# OPENING RANGE CLASSIFIER
# ═════════════════════════════════════════════════════════════════════════════════

class ORClassifier:
    """
    Classify opening range as TIGHT, NORMAL, or WIDE.

    Classification based on OR range vs ATR:
    - TIGHT: OR < 0.5x ATR  → High confidence breakouts
    - NORMAL: 0.5x ≤ OR ≤ 1.5x ATR → Standard confidence
    - WIDE: OR > 1.5x ATR   → Lower confidence (choppy, avoid)

    Confidence adjustments:
    - TIGHT:  +5%
    - NORMAL:  0%
    - WIDE:   -5% (filter if > 2.5x ATR)
    """

    def __init__(self):
        self.cache = {}
        self.cache_ttl = 300

    def classify_opening_range(self, ticker: str, or_high: float, or_low: float, atr: float) -> Dict:
        cache_key = f"{ticker}_or"
        if cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_result
        or_range     = or_high - or_low
        or_range_pct = (or_range / or_low) * 100 if or_low > 0 else 0
        or_range_atr = (or_range / atr)           if atr   > 0 else 0
        if or_range_atr < 0.5:
            classification, confidence_adjustment, min_confidence, should_filter = 'TIGHT',  0.05, 0.65, False
        elif or_range_atr <= 1.5:
            classification, confidence_adjustment, min_confidence, should_filter = 'NORMAL', 0.00, 0.70, False
        else:
            classification, confidence_adjustment, min_confidence, should_filter = 'WIDE', -0.05, 0.75, or_range_atr > 2.5
        result = {
            'classification': classification,
            'or_range': or_range,
            'or_range_pct': or_range_pct,
            'or_range_atr': or_range_atr,
            'confidence_adjustment': confidence_adjustment,
            'min_confidence': min_confidence,
            'should_filter': should_filter
        }
        self.cache[cache_key] = (datetime.now(), result)
        return result

    def adjust_signal_confidence(self, signal: Dict, or_classification: Dict) -> Dict:
        if or_classification['should_filter']:
            signal['or_filtered']      = True
            signal['or_filter_reason'] = f"OR too wide ({or_classification['or_range_atr']:.2f}x ATR)"
            return signal
        orig_conf      = signal.get('confidence', 0.70)
        adjusted_conf  = orig_conf + or_classification['confidence_adjustment']
        signal['confidence'] = max(0.40, min(0.95, adjusted_conf))
        signal['or_boost']   = or_classification['confidence_adjustment']
        signal['or']         = or_classification
        return signal

    def clear_cache(self):
        self.cache.clear()


# ═════════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCES (lazy)
# ═════════════════════════════════════════════════════════════════════════════════

_ml_booster   = None
_uoa_detector = None
_or_classifier = None


def get_ml_booster() -> MLConfidenceBooster:
    global _ml_booster
    if _ml_booster is None:
        _ml_booster = MLConfidenceBooster()
    return _ml_booster


def get_uoa_detector() -> UOAWhaleDetector:
    global _uoa_detector
    if _uoa_detector is None:
        _uoa_detector = UOAWhaleDetector()
    return _uoa_detector


def get_or_classifier() -> ORClassifier:
    global _or_classifier
    if _or_classifier is None:
        _or_classifier = ORClassifier()
    return _or_classifier


def clear_all_caches():
    """Clear all booster caches (called at EOD reset)."""
    if _uoa_detector:  _uoa_detector.clear_cache()
    if _or_classifier: _or_classifier.clear_cache()
    print("[BOOSTERS] All caches cleared")
