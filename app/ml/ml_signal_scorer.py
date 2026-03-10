"""
ML Signal Scorer — War Machine

⚠️  STATUS: OFFLINE / NOT ACTIVE IN PRODUCTION
──────────────────────────────────────────────────────────────────────────────
This file is NOT imported by scanner.py, sniper.py, or any live scan path.

The ACTIVE ML path is:
    app/analytics/analytics_integration.py  ← AnalyticsIntegration class
    (imported by scanner.py when ANALYTICS_AVAILABLE=True)

This file is v1 of the ML scorer — superseded by ml_signal_scorer_v2.py
but neither version is currently wired into the live pipeline.

To activate: import score_signal() into sniper._run_signal_pipeline()
and wire the score as a confidence multiplier after Step 9 (MTF boost).

See app/ml/INTEGRATION.md for activation instructions.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Optional ML dependencies ──────────────────────────────────────────────────
try:
    import numpy as np
    import pandas as pd
    ML_DEPS_AVAILABLE = True
except ImportError:
    ML_DEPS_AVAILABLE = False
    logger.warning("[ML-SCORER-v1] numpy/pandas not available — scorer disabled")

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("[ML-SCORER-v1] scikit-learn not available — using rule-based fallback")


MODEL_PATH = os.path.join(os.getcwd(), 'models', 'ml_signal_scorer_v1.pkl')
FEATURE_VERSION = 'v1.0'


class MLSignalScorerV1:
    """
    V1 ML scorer — gradient boosting on 12 hand-crafted features.
    Superseded by MLSignalScorerV2 (ml_signal_scorer_v2.py).
    """

    def __init__(self):
        self.model   = None
        self.scaler  = None
        self.trained = False
        self._try_load()

    def _try_load(self):
        if not SKLEARN_AVAILABLE or not ML_DEPS_AVAILABLE:
            return
        if os.path.exists(MODEL_PATH):
            try:
                import pickle
                with open(MODEL_PATH, 'rb') as f:
                    bundle = pickle.load(f)
                self.model   = bundle.get('model')
                self.scaler  = bundle.get('scaler')
                self.trained = True
                logger.info(f"[ML-SCORER-v1] Loaded model from {MODEL_PATH}")
            except Exception as exc:
                logger.warning(f"[ML-SCORER-v1] Model load failed: {exc}")

    def _build_features(self, signal_data: Dict[str, Any]) -> Optional[list]:
        if not ML_DEPS_AVAILABLE:
            return None
        try:
            return [
                signal_data.get('rvol', 1.0),
                signal_data.get('score', 50) / 100.0,
                signal_data.get('confidence', 0.70),
                1.0 if signal_data.get('grade', 'B') in ('A+', 'A', 'A-') else 0.0,
                signal_data.get('ivr', 0.5),
                signal_data.get('gex_multiplier', 1.0),
                signal_data.get('mtf_boost', 0.0),
                signal_data.get('vwap_distance', 0.0),
                signal_data.get('or_range_pct', 0.01),
                1.0 if signal_data.get('direction') == 'bull' else 0.0,
                signal_data.get('hour', 10) / 16.0,
                signal_data.get('adx', 20.0) / 50.0,
            ]
        except Exception:
            return None

    def score_signal(self, signal_data: Dict[str, Any]) -> Tuple[float, str]:
        """
        Score a signal dict.  Returns (probability_win, reason_string).
        Falls back to rule-based scoring if model is not trained.
        """
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
            return prob, f"ML-v1 score={prob:.3f}"
        except Exception as exc:
            logger.warning(f"[ML-SCORER-v1] Inference error: {exc}")
            return self._rule_based_score(signal_data)

    def _rule_based_score(self, signal_data: Dict[str, Any]) -> Tuple[float, str]:
        confidence  = signal_data.get('confidence', 0.70)
        rvol        = signal_data.get('rvol', 1.0)
        grade       = signal_data.get('grade', 'B')
        grade_bonus = {'A+': 0.10, 'A': 0.07, 'A-': 0.04}.get(grade, 0.0)
        rvol_bonus  = min((rvol - 1.0) * 0.02, 0.08)
        score       = min(confidence + grade_bonus + rvol_bonus, 0.95)
        return score, f"rule-based score={score:.3f} (model not trained)"


# Module-level singleton
_scorer_v1: Optional[MLSignalScorerV1] = None


def get_scorer() -> MLSignalScorerV1:
    global _scorer_v1
    if _scorer_v1 is None:
        _scorer_v1 = MLSignalScorerV1()
    return _scorer_v1


def score_signal(signal_data: Dict[str, Any]) -> Tuple[float, str]:
    """Convenience wrapper — scores a signal and returns (prob, reason)."""
    return get_scorer().score_signal(signal_data)
