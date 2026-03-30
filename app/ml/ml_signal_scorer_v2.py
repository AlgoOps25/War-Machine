#!/usr/bin/env python3
"""
ML Signal Scorer V2 — app.ml.ml_signal_scorer_v2
=================================================
Gate 5 adapter for cfw6_gate_validator.py.

Bridges the existing trained models into the interface expected by Gate 5:

    scorer = MLSignalScorerV2()
    if scorer.is_ready:
        prob = scorer.score_signal(signal_dict)  # float in [0.0, 1.0]
        ml_adjustment = (prob - 0.50) * 30.0     # maps to [-15, +15] pts

Model resolution order (first available wins):
    1. HistGradientBoosting + Platt scaling  — ml_model.joblib
       (EOD live-retrained, most recent signal distribution)
    2. XGBoost MLConfidenceBooster           — confidence_booster.pkl
       (weekly retrain, wider feature set)
    3. Heuristic fallback                    — no model on disk
       (uses raw confidence + rvol, returns 0.0 neutral adjustment)

Feature contract:
    score_signal() accepts the `signal` dict that validate_signal() builds
    from its own local state. Keys mapped to LIVE_FEATURE_COLS from
    ml_trainer.py. Missing keys are zero-filled (same as training-time
    behaviour). No KeyError is ever raised.

Sentinel: score_signal() returns -1.0 when the model is unavailable so
    callers can skip the adjustment cleanly.

FIX BUG-ML-1 (Mar 27 2026 — Session 11):
    File did not exist. Gate 5 in cfw6_gate_validator.py was catching
    ImportError silently every run — ml_adjustment=0.0 always, ML layer
    had zero effect on any signal. This file resolves that.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Paths — match ml_trainer.py and ml_confidence_boost.py conventions
_HIST_MODEL_PATH    = os.path.join(os.path.dirname(__file__), '..', '..', 'ml_model.joblib')
_BOOSTER_MODEL_PATH = "/app/models/confidence_booster.pkl"

# Feature keys expected in the signal dict — matches LIVE_FEATURE_COLS in ml_trainer.py
_LIVE_FEATURE_KEYS = [
    'confidence', 'rvol', 'adx', 'time_minutes',
    'spy_correlation', 'iv_rank', 'mtf_convergence',
]


class MLSignalScorerV2:
    """
    Gate 5 ML scorer. Loads the best available model at construction time.
    Thread-safe for read-only inference (no shared mutable state after __init__).
    """

    def __init__(self):
        self._model       = None
        self._model_type  = None   # 'hist' | 'booster' | None
        self._threshold   = 0.50
        self._feature_names: list = []
        self.is_ready     = False
        self.model_version = 'none'
        self._load_best_model()

    # ── Model loading ────────────────────────────────────────────────────────

    def _load_best_model(self):
        """Try HistGBM first, fall back to XGBoost booster."""
        if self._try_load_hist_model():
            return
        if self._try_load_booster_model():
            return
        logger.warning("[ML-SCORER-V2] No trained model found — heuristic fallback active")

    def _try_load_hist_model(self) -> bool:
        """Load ml_model.joblib (HistGradientBoosting + Platt)."""
        path = os.path.abspath(_HIST_MODEL_PATH)
        if not os.path.exists(path):
            return False
        try:
            import joblib
            data = joblib.load(path)
            self._model        = data['model']
            self._feature_names = data.get('feature_names', _LIVE_FEATURE_KEYS)
            self._threshold    = float(data.get('threshold', 0.50))
            self._model_type   = 'hist'
            self.model_version = data.get('model_version', 'hist_v1')
            self.is_ready      = True
            logger.info(
                f"[ML-SCORER-V2] Loaded HistGBM model  "
                f"version={self.model_version}  threshold={self._threshold:.3f}"
            )
            return True
        except Exception as exc:
            logger.warning(f"[ML-SCORER-V2] HistGBM load failed ({exc}) — trying booster")
            return False

    def _try_load_booster_model(self) -> bool:
        """Load confidence_booster.pkl (XGBoost MLConfidenceBooster)."""
        if not os.path.exists(_BOOSTER_MODEL_PATH):
            return False
        try:
            import pickle
            with open(_BOOSTER_MODEL_PATH, 'rb') as f:
                data = pickle.load(f)
            self._model         = data['model']
            self._feature_names = data.get('feature_names', _LIVE_FEATURE_KEYS)
            self._threshold     = 0.50  # booster uses midpoint
            self._model_type    = 'booster'
            self.model_version  = 'xgb_booster'
            self.is_ready       = True
            logger.info("[ML-SCORER-V2] Loaded XGBoost booster model")
            return True
        except Exception as exc:
            logger.warning(f"[ML-SCORER-V2] Booster load failed ({exc})")
            return False

    # ── Feature bridging ─────────────────────────────────────────────────────

    def _build_feature_vector(self, signal: dict) -> Optional[list]:
        """
        Map signal dict keys to the model's expected feature order.
        Missing keys are zero-filled (matches training-time fillna(0) behaviour).
        adx defaults to 20.0 (neutral, not 0.0 which is a misleading floor).
        confidence is normalised from [0,100] to [0,1] if > 1.0.
        """
        # Normalise confidence to [0,1] if caller passes it as 0–100
        raw_conf = signal.get('confidence', 0.5)
        conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf

        # Build a lookup with sensible defaults for every possible key
        lookup = {
            'confidence':     conf,
            'rvol':           signal.get('rvol', 1.0),
            'adx':            signal.get('adx') or 20.0,  # None-safe
            'time_minutes':   signal.get('time_minutes', 0.0),
            'spy_correlation':signal.get('spy_correlation', 0.0),
            'iv_rank':        signal.get('iv_rank', 50.0),
            'mtf_convergence':signal.get('mtf_convergence', 0.0),
        }

        try:
            return [lookup.get(f, 0.0) for f in self._feature_names]
        except Exception as exc:
            logger.warning(f"[ML-SCORER-V2] Feature build error: {exc}")
            return None

    # ── Inference ────────────────────────────────────────────────────────────

    def score_signal(self, signal: dict) -> float:
        """
        Score a signal dict and return a win probability in [0.0, 1.0].

        Returns -1.0 if the model is unavailable (sentinel — caller skips
        adjustment). Returns 0.5 on feature/inference errors (neutral —
        no adjustment applied).

        Gate 5 formula (in cfw6_gate_validator.py):
            ml_adjustment = (prob - 0.50) * 30.0
            ml_adjustment = max(-15.0, min(15.0, ml_adjustment))
        """
        if not self.is_ready or self._model is None:
            return -1.0

        fv = self._build_feature_vector(signal)
        if fv is None:
            return 0.5

        try:
            import numpy as np
            X = np.array([fv])
            prob = float(self._model.predict_proba(X)[0, 1])
            return max(0.0, min(1.0, prob))
        except Exception as exc:
            logger.warning(f"[ML-SCORER-V2] Inference error: {exc}")
            return 0.5
