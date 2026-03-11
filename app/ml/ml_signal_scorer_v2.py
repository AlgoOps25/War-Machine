"""
ML Signal Scorer V2 — War Machine

⚠️  STATUS: OFFLINE / NOT ACTIVE IN PRODUCTION
──────────────────────────────────────────────────────────────────────────────
This file is NOT imported by scanner.py, sniper.py, or any live scan path.

The ACTIVE ML path is:
    app/analytics/analytics_integration.py  ← AnalyticsIntegration class
    (imported by scanner.py when ANALYTICS_AVAILABLE=True)

This is the PREFERRED scorer (v2) over ml_signal_scorer.py (v1).
It uses a richer feature set (20 features vs 12) and an XGBoost-style
gradient booster when available.

To activate v2 in production:
  1. Import score_signal_v2() in sniper._run_signal_pipeline()
  2. Wire the returned probability as a confidence multiplier after
     Step 9 (MTF boost) — e.g. confidence *= (0.8 + 0.4 * prob_win)
  3. Train the model offline: python -m app.ml.train_from_analytics
  4. Confirm model saved to models/ml_signal_scorer_v2.pkl

See app/ml/INTEGRATION.md for full activation instructions.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pandas as pd
    ML_DEPS_AVAILABLE = True
except ImportError:
    ML_DEPS_AVAILABLE = False
    logger.warning("[ML-SCORER-v2] numpy/pandas not available — scorer disabled")

try:
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("[ML-SCORER-v2] scikit-learn not available — using rule-based fallback")


MODEL_PATH = os.path.join(os.getcwd(), 'models', 'ml_model_historical.pkl')
FEATURE_VERSION = 'v2.0'
FEATURE_COUNT   = 20


class MLSignalScorerV2:
    """
    V2 ML scorer — 20-feature gradient booster.
    Preferred over V1 for production activation.
    """

    def __init__(self):
        self.model   = None
        self.scaler  = None
        self.trained = False
        self._feature_names: list = []
        self._try_load()

    def _try_load(self):
        if not SKLEARN_AVAILABLE or not ML_DEPS_AVAILABLE:
            return
        if os.path.exists(MODEL_PATH):
            try:
                import pickle
                with open(MODEL_PATH, 'rb') as f:
                    bundle = pickle.load(f)
                self.model         = bundle.get('model')
                self.scaler        = bundle.get('scaler')
                self._feature_names = bundle.get('feature_names', [])
                self.trained       = True
                logger.info(f"[ML-SCORER-v2] Loaded model from {MODEL_PATH}")
            except Exception as exc:
                logger.warning(f"[ML-SCORER-v2] Model load failed: {exc}")

    def _build_features(self, signal_data: Dict[str, Any]) -> Optional[list]:
        if not ML_DEPS_AVAILABLE:
            return None
        grade_map = {'A+': 9,'A': 8,'A-': 7,'B+': 6,'B': 5,'B-': 4,'C+': 3,'C': 2,'C-': 1}
        try:
            return [
                # Core signal quality
                signal_data.get('confidence', 0.70),
                grade_map.get(signal_data.get('grade', 'B'), 5) / 9.0,
                signal_data.get('rvol', 1.0),
                signal_data.get('score', 50) / 100.0,
                # Options intelligence
                signal_data.get('ivr', 0.5),
                signal_data.get('gex_multiplier', 1.0),
                signal_data.get('uoa_multiplier', 1.0),
                signal_data.get('ivr_multiplier', 1.0),
                # Multi-timeframe
                signal_data.get('mtf_boost', 0.0),
                float(signal_data.get('mtf_convergence', False)),
                signal_data.get('mtf_convergence_count', 0) / 4.0,
                # Technical context
                signal_data.get('vwap_distance', 0.0),
                signal_data.get('or_range_pct', 0.01),
                signal_data.get('adx', 20.0) / 50.0,
                signal_data.get('atr_pct', 0.01),
                # Signal type / timing
                1.0 if signal_data.get('signal_type') == 'CFW6_OR' else 0.0,
                1.0 if signal_data.get('direction') == 'bull' else 0.0,
                signal_data.get('hour', 10) / 16.0,
                # Risk context
                signal_data.get('rr_ratio', 2.0) / 5.0,
                float(signal_data.get('explosive_mover', False)),
            ]
        except Exception:
            return None

    def score_signal(self, signal_data: Dict[str, Any]) -> Tuple[float, str]:
        if not self.trained or not SKLEARN_AVAILABLE:
            return self._rule_based_score(signal_data)

        features = self._build_features(signal_data)
        if features is None:
            return self._rule_based_score(signal_data)

        try:
            import numpy as np
            X = np.array(features).reshape(1, -1)
            if self.scaler:
                X = self.scaler.transform(X)
            prob = float(self.model.predict_proba(X)[0][1])
            return prob, f"ML-v2 score={prob:.3f} ({FEATURE_COUNT} features)"
        except Exception as exc:
            logger.warning(f"[ML-SCORER-v2] Inference error: {exc}")
            return self._rule_based_score(signal_data)

    def _rule_based_score(self, signal_data: Dict[str, Any]) -> Tuple[float, str]:
        grade_map   = {'A+': 9,'A': 8,'A-': 7,'B+': 6,'B': 5,'B-': 4,'C+': 3,'C': 2,'C-': 1}
        confidence  = signal_data.get('confidence', 0.70)
        grade_score = grade_map.get(signal_data.get('grade', 'B'), 5) / 9.0
        rvol        = signal_data.get('rvol', 1.0)
        mtf_boost   = signal_data.get('mtf_boost', 0.0)
        rvol_bonus  = min((rvol - 1.0) * 0.015, 0.08)
        base        = (confidence * 0.5) + (grade_score * 0.3) + (rvol_bonus * 0.2)
        score       = min(base + mtf_boost * 0.5, 0.95)
        return score, f"rule-based-v2 score={score:.3f} (model not trained)"


_scorer_v2: Optional[MLSignalScorerV2] = None


def get_scorer_v2() -> MLSignalScorerV2:
    global _scorer_v2
    if _scorer_v2 is None:
        _scorer_v2 = MLSignalScorerV2()
    return _scorer_v2


def score_signal_v2(signal_data: Dict[str, Any]) -> Tuple[float, str]:
    """Convenience wrapper — scores a signal and returns (prob, reason)."""
    return get_scorer_v2().score_signal(signal_data)
