"""
Signal Boosters — Optional Enhancement Modules for Sniper.py
=============================================================

Consolidated from signal_generator.py — these are opt-in features that enhance
the core CFW6 BOS+FVG pipeline without creating a duplicate signal path.

Features:
- ML Confidence Booster: Predict confidence adjustments using historical data
- UOA Whale Detection: Identify unusual options activity and flow alignment
- MTF Validator: Multi-timeframe convergence validation (1m/5m/15m/30m)
- OR Classifier: Opening range tight/wide classification with confidence adjustments

All features are disabled by default. Enable in sniper.py with:
    ML_BOOSTER_ENABLED = True
    UOA_WHALE_ENABLED = True
    MTF_VALIDATOR_ENABLED = True
    OR_CLASSIFIER_ENABLED = True

Author: War Machine Team
Date: March 6, 2026
"""

from typing import Dict, Optional, List
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ════════════════════════════════════════════════════════════════════════════════
# ML CONFIDENCE BOOSTER
# ════════════════════════════════════════════════════════════════════════════════

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
        
        # Try to load trained model
        try:
            self._load_model()
        except Exception as e:
            print(f"[ML-BOOST] Model not available: {e}")
    
    def _load_model(self):
        """Load trained model from disk (placeholder for now)."""
        # TODO: Implement model loading from saved pickle/joblib file
        # For now, model remains None and predict will return 0.0
        pass
    
    def predict_confidence_adjustment(self, features: Dict[str, float]) -> float:
        """
        Predict confidence adjustment given feature dict.
        
        Args:
            features: Dict with 22 feature keys (see extract_features in sniper.py)
        
        Returns:
            Float in range [-0.15, +0.15] representing confidence adjustment
        """
        if not self.is_trained or self.model is None:
            return 0.0  # No adjustment if model not trained
        
        # TODO: Implement model prediction
        # For now, return 0.0 as placeholder
        return 0.0
    
    def extract_features(self, ticker: str, signal: Dict, latest_bar: Dict) -> Dict[str, float]:
        """
        Extract ML features from signal data for confidence prediction.
        
        Args:
            ticker: Stock ticker
            signal: Signal dict with entry/stop/targets
            latest_bar: Latest price bar
        
        Returns:
            Dict of feature_name -> value (22 features)
        """
        features = {}
        now_et = datetime.now(ET)
        
        # Time features
        features['hour_of_day'] = now_et.hour
        features['day_of_week'] = now_et.weekday()
        features['time_since_open_min'] = (now_et.hour - 9) * 60 + (now_et.minute - 30)
        
        # Gap features
        gap_pct = signal.get('gap_pct', 0.0)
        features['gap_pct'] = gap_pct
        features['gap_abs'] = abs(gap_pct)
        features['gap_direction'] = 1 if gap_pct > 0 else 0
        
        # Volume features
        volume = latest_bar.get('volume', signal.get('volume', 0))
        features['entry_volume'] = volume
        features['volume_surge_ratio'] = signal.get('volume_surge', 1.0)
        features['or_volume'] = signal.get('or_volume', 0)
        features['volume_log'] = np.log1p(volume)
        
        # Price vs key levels
        features['price_vs_pdh'] = signal.get('price_vs_pdh', 0.0)
        features['price_vs_or_high'] = signal.get('price_vs_or_high', 0.0)
        
        # PDH/PDL distance
        entry_price = signal.get('entry_price', 0)
        pdh = signal.get('pdh', 0)
        pdl = signal.get('pdl', 0)
        
        if pdh and pdl and entry_price:
            features['pdh_distance_pct'] = (entry_price - pdh) / pdh * 100
            features['pdl_distance_pct'] = (entry_price - pdl) / pdl * 100
            features['pd_range_pct'] = (pdh - pdl) / pdl * 100
        else:
            features['pdh_distance_pct'] = 0.0
            features['pdl_distance_pct'] = 0.0
            features['pd_range_pct'] = 0.0
        
        # OR breakout
        or_high = signal.get('or_high', 0)
        or_low = signal.get('or_low', 0)
        
        if or_high and or_low and entry_price:
            features['or_breakout_size_pct'] = (entry_price - or_high) / or_high * 100
            features['or_range_pct'] = (or_high - or_low) / or_low * 100
        else:
            features['or_breakout_size_pct'] = 0.0
            features['or_range_pct'] = 0.0
        
        # VIX
        features['vix_level'] = signal.get('vix', 15.0)
        
        # Signal type one-hot
        signal_type = signal.get('signal_type', 'CFW6_OR')
        for sig_type in ['CFW6_OR', 'CFW6_INTRADAY', 'gap_breakout', 'volume_surge']:
            features[f'signal_{sig_type}'] = 1 if sig_type in signal_type else 0
        
        return features


# ════════════════════════════════════════════════════════════════════════════════
# UOA WHALE DETECTION
# ════════════════════════════════════════════════════════════════════════════════

class UOAWhaleDetector:
    """
    Detect unusual options activity and large whale trades.
    
    Checks:
    - Volume vs open interest ratio (whale activity if volume >> OI)
    - Premium size (large premium trades indicate institutional interest)
    - Flow alignment (calls/puts aligning with signal direction)
    
    Returns confidence boost of 0-10% if whale activity detected and aligned.
    """
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    def check_whale_activity(self, ticker: str, direction: str) -> Dict:
        """
        Check for unusual options activity aligned with signal direction.
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT'
        
        Returns:
            Dict with whale detection results:
            {
                'is_unusual': bool,
                'whale_score': float (0-10),
                'flow_score': float (0-10),
                'overall_score': float (0-10),
                'confidence_boost': float (0.00-0.10),
                'summary': str
            }
        """
        # Check cache
        cache_key = f"{ticker}_{direction}"
        if cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_result
        
        # TODO: Implement actual UOA API integration
        # For now, return neutral result
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
        """Clear UOA cache (called at EOD reset)."""
        self.cache.clear()


# ════════════════════════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME VALIDATOR
# ════════════════════════════════════════════════════════════════════════════════

class MTFValidator:
    """
    Multi-timeframe convergence validator.
    
    Checks signal alignment across 1m, 5m, 15m, 30m timeframes:
    - Trend direction (EMA/SMA alignment)
    - Momentum (RSI alignment)
    - Volume confirmation
    
    Returns:
    - Overall alignment score (0-10)
    - Confidence boost (0-15%) if strong convergence
    - Divergence warnings if timeframes conflict
    
    NOTE: This is different from MTF FVG Priority in sniper.py.
    This validates trend/momentum convergence, not FVG timing.
    """
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 60  # 1 minute
    
    def validate_signal(self, ticker: str, direction: str, entry_price: float) -> Dict:
        """
        Validate signal across multiple timeframes.
        
        Args:
            ticker: Stock ticker
            direction: 'BUY' or 'SELL'
            entry_price: Entry price
        
        Returns:
            Dict with MTF validation results:
            {
                'passes': bool,
                'overall_score': float (0-10),
                'tf_scores': {'30m': float, '15m': float, '5m': float, '1m': float},
                'confidence_boost': float (0.00-0.15),
                'divergences': List[str],
                'summary': str
            }
        """
        # Check cache
        cache_key = f"{ticker}_{direction}"
        if cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_result
        
        # TODO: Implement actual MTF analysis
        # For now, return neutral result
        result = {
            'passes': True,
            'overall_score': 6.0,
            'tf_scores': {'30m': 6, '15m': 6, '5m': 6, '1m': 6},
            'confidence_boost': 0.0,
            'divergences': [],
            'summary': 'MTF validation not yet implemented'
        }
        
        self.cache[cache_key] = (datetime.now(), result)
        return result
    
    def clear_cache(self):
        """Clear MTF cache (called at EOD reset)."""
        self.cache.clear()


# ════════════════════════════════════════════════════════════════════════════════
# OPENING RANGE CLASSIFIER
# ════════════════════════════════════════════════════════════════════════════════

class ORClassifier:
    """
    Classify opening range as TIGHT, NORMAL, or WIDE.
    
    Classification based on OR range vs ATR:
    - TIGHT: OR < 0.5x ATR → High confidence breakouts (clean setup)
    - NORMAL: 0.5x ≤ OR ≤ 1.5x ATR → Standard confidence
    - WIDE: OR > 1.5x ATR → Lower confidence (choppy, avoid)
    
    Applies confidence adjustments:
    - TIGHT: +5% confidence boost
    - NORMAL: No adjustment
    - WIDE: May filter signal entirely if very wide
    """
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes (OR doesn't change)
    
    def classify_opening_range(self, ticker: str, or_high: float, or_low: float, atr: float) -> Dict:
        """
        Classify opening range quality.
        
        Args:
            ticker: Stock ticker
            or_high: Opening range high
            or_low: Opening range low
            atr: 14-period ATR
        
        Returns:
            Dict with OR classification:
            {
                'classification': 'TIGHT' | 'NORMAL' | 'WIDE',
                'or_range': float,
                'or_range_pct': float,
                'or_range_atr': float (OR / ATR ratio),
                'confidence_adjustment': float (0.00-0.05),
                'min_confidence': float (threshold for this OR type),
                'should_filter': bool (if OR too wide)
            }
        """
        # Check cache
        cache_key = f"{ticker}_or"
        if cache_key in self.cache:
            cached_time, cached_result = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_result
        
        or_range = or_high - or_low
        or_range_pct = (or_range / or_low) * 100 if or_low > 0 else 0
        or_range_atr = (or_range / atr) if atr > 0 else 0
        
        # Classify
        if or_range_atr < 0.5:
            classification = 'TIGHT'
            confidence_adjustment = 0.05
            min_confidence = 0.65
            should_filter = False
        elif or_range_atr <= 1.5:
            classification = 'NORMAL'
            confidence_adjustment = 0.0
            min_confidence = 0.70
            should_filter = False
        else:
            classification = 'WIDE'
            confidence_adjustment = -0.05
            min_confidence = 0.75
            should_filter = or_range_atr > 2.5  # Filter if extremely wide
        
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
        """
        Apply OR-based confidence adjustment to signal.
        
        Args:
            signal: Signal dict with base confidence
            or_classification: Result from classify_opening_range()
        
        Returns:
            Updated signal dict with adjusted confidence and OR metadata
        """
        if or_classification['should_filter']:
            signal['or_filtered'] = True
            signal['or_filter_reason'] = f"OR too wide ({or_classification['or_range_atr']:.2f}x ATR)"
            return signal
        
        # Apply confidence boost/penalty
        original_conf = signal.get('confidence', 0.70)
        adjusted_conf = original_conf + or_classification['confidence_adjustment']
        
        signal['confidence'] = max(0.40, min(0.95, adjusted_conf))
        signal['or_boost'] = or_classification['confidence_adjustment']
        signal['or'] = or_classification
        
        return signal
    
    def clear_cache(self):
        """Clear OR cache (called at EOD reset)."""
        self.cache.clear()


# ════════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCES (lazy initialization)
# ════════════════════════════════════════════════════════════════════════════════

_ml_booster = None
_uoa_detector = None
_mtf_validator = None
_or_classifier = None


def get_ml_booster() -> MLConfidenceBooster:
    """Get or create ML booster instance."""
    global _ml_booster
    if _ml_booster is None:
        _ml_booster = MLConfidenceBooster()
    return _ml_booster


def get_uoa_detector() -> UOAWhaleDetector:
    """Get or create UOA detector instance."""
    global _uoa_detector
    if _uoa_detector is None:
        _uoa_detector = UOAWhaleDetector()
    return _uoa_detector


def get_mtf_validator() -> MTFValidator:
    """Get or create MTF validator instance."""
    global _mtf_validator
    if _mtf_validator is None:
        _mtf_validator = MTFValidator()
    return _mtf_validator


def get_or_classifier() -> ORClassifier:
    """Get or create OR classifier instance."""
    global _or_classifier
    if _or_classifier is None:
        _or_classifier = ORClassifier()
    return _or_classifier


def clear_all_caches():
    """Clear all booster caches (called at EOD reset)."""
    if _uoa_detector:
        _uoa_detector.clear_cache()
    if _mtf_validator:
        _mtf_validator.clear_cache()
    if _or_classifier:
        _or_classifier.clear_cache()
    print("[BOOSTERS] All caches cleared")
