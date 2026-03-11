"""
ML Signal Scorer V2 — War Machine

STATUS: ACTIVE — wired into sniper._run_signal_pipeline() after validator block.
──────────────────────────────────────────────────────────────────────────────
Feature schema: 17 features matching HIST_FEATURE_COLS in ml_trainer.py.
Model path:     models/ml_model_historical.pkl
Interface:      score_signal(signal_data) -> float  (win probability 0.0–1.0)
                Returns -1.0 if model not loaded (graceful fallback).

Threshold:      Loaded from model bundle (precision-tuned at train time).
                Hard gate in sniper: drop signal if prob < threshold.
                Confidence boost:   final_conf += (prob - 0.50) * 0.10

Feature audit (BUG-11, Mar 2026):
    Matches ml_trainer.HIST_FEATURE_COLS exactly — 15 core features built by
    name not position, plus 2 new high-leverage features (Mar 11 2026):
      ticker_win_rate  — rolling 30-day per-ticker win rate normalised 0-1
      spy_regime       — 3-state SPY macro context (-1=down/0=flat/1=up)

To retrain with new features:
    python -m app.ml.train_historical --interval d --months 6 \\
        --tickers AAPL TSLA NVDA MSFT AMD META GOOGL AMZN SPY QQQ
See app/ml/INTEGRATION.md for full activation notes.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import numpy as np
    ML_DEPS_AVAILABLE = True
except ImportError:
    ML_DEPS_AVAILABLE = False
    logger.warning("[ML-SCORER-v2] numpy not available — scorer disabled")

try:
    from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: F401 — presence check only
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("[ML-SCORER-v2] scikit-learn not available — rule-based fallback active")


# ── Paths ────────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'models', 'ml_model_historical.pkl'
)
FEATURE_VERSION = 'v4.0'   # bumped — 17-feature schema (added ticker_win_rate, spy_regime)
FEATURE_COUNT   = 17

# Must stay in sync with HIST_FEATURE_COLS in ml_trainer.py
HIST_FEATURE_COLS = [
    'confidence',
    'rvol',
    'score_norm',
    'mtf_convergence',
    'mtf_convergence_count',
    'vwap_distance',
    'vwap_side',
    'or_range_pct',
    'adx_norm',
    'atr_pct',
    'atr_ratio',
    'is_or_signal',
    'hour_norm',
    'time_bucket_norm',
    'resist_proximity',
    'ticker_win_rate',
    'spy_regime',
    'conf_score',
    'fvg_size_pct',
    'bos_strength',
]

# Default decision threshold — overridden by the value stored in the model bundle
DEFAULT_THRESHOLD = 0.50


class MLSignalScorerV2:
    """
    V2 ML scorer — 17-feature HistGradientBoosting built from HIST_FEATURE_COLS.
    score_signal() returns a plain float (win probability 0.0–1.0) so
    sniper.py can use it directly without tuple unpacking.
    Returns -1.0 when the model is unavailable (caller must handle).
    """

    def __init__(self):
        self.model:     Any      = None
        self.trained:   bool     = False
        self.threshold: float    = DEFAULT_THRESHOLD
        self._feature_names: list = []
        self._try_load()

    # ── Model loading ─────────────────────────────────────────────────────────

    def _try_load(self) -> None:
        if not SKLEARN_AVAILABLE or not ML_DEPS_AVAILABLE:
            return
        path = os.path.abspath(MODEL_PATH)
        if not os.path.exists(path):
            logger.info(f"[ML-SCORER-v2] No model file at {path} — rule-based fallback active")
            return
        try:
            import pickle
            with open(path, 'rb') as f:
                bundle = pickle.load(f)
            self.model          = bundle.get('model')
            self._feature_names = bundle.get('feature_names', HIST_FEATURE_COLS)
            self.threshold      = float(bundle.get('threshold', DEFAULT_THRESHOLD))
            self.trained        = self.model is not None
            trained_at          = bundle.get('trained_at', 'unknown')
            model_type          = bundle.get('model_type', 'unknown')
            logger.info(
                f"[ML-SCORER-v2] ✅ Loaded model | "
                f"type={model_type} | "
                f"features={len(self._feature_names)} | "
                f"threshold={self.threshold:.3f} | "
                f"trained_at={trained_at}"
            )
        except Exception as exc:
            logger.warning(f"[ML-SCORER-v2] Model load failed: {exc}")

    # ── Feature builder — 17 features, built BY NAME ──────────────────────────
    # Matches HIST_FEATURE_COLS in ml_trainer.py exactly.
    # All values are normalised to [0,1] or meaningful floats.

    def _build_features(self, signal_data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """
        Build a feature dict keyed by HIST_FEATURE_COLS column names.
        Returns None on hard failure so the caller can fall back gracefully.
        """
        if not ML_DEPS_AVAILABLE:
            return None
        try:
            bars        = signal_data.get('bars') or []
            entry_price = float(signal_data.get('entry_price', 0.0))
            direction   = signal_data.get('direction', 'bull')
            signal_type = signal_data.get('signal_type', 'CFW6_INTRADAY')

            # ── confidence ───────────────────────────────────────────────────
            confidence = float(signal_data.get('confidence', 0.70))

            # ── rvol ─────────────────────────────────────────────────────────
            rvol = float(signal_data.get('rvol', 1.0))

            # ── score_norm  (composite screener score / 100) ─────────────────
            score_norm = float(signal_data.get('score', 50)) / 100.0

            # ── mtf_convergence  (bool -> 0/1) ───────────────────────────────
            mtf_convergence = 1.0 if signal_data.get('mtf_convergence') else 0.0

            # ── mtf_convergence_count  (0-4 timeframes / 4) ──────────────────
            mtf_convergence_count = (
                float(signal_data.get('mtf_convergence_count', 0)) / 4.0
            )

            # ── vwap_distance  (signed % from VWAP) ──────────────────────────
            vwap_distance = float(signal_data.get('vwap_distance', 0.0))
            if vwap_distance == 0.0 and bars and entry_price > 0:
                tpv = sum(
                    ((b['high'] + b['low'] + b['close']) / 3.0) * b.get('volume', 0)
                    for b in bars
                )
                total_vol = sum(b.get('volume', 0) for b in bars)
                if total_vol > 0:
                    vwap = tpv / total_vol
                    vwap_distance = (entry_price - vwap) / vwap

            # ── vwap_side  (+1 above VWAP / -1 below) ────────────────────────
            vwap_side = 1.0 if vwap_distance >= 0 else -1.0

            # ── or_range_pct  (opening range width as % of OR low) ───────────
            or_range_pct = float(signal_data.get('or_range_pct', 0.01))
            if or_range_pct == 0.01 and bars:
                from datetime import time as dtime
                or_bars = [
                    b for b in bars
                    if hasattr(b.get('datetime'), 'time')
                    and dtime(9, 30) <= b['datetime'].time() < dtime(9, 45)
                ]
                if len(or_bars) >= 2:
                    or_h = max(b['high'] for b in or_bars)
                    or_l = min(b['low']  for b in or_bars)
                    if or_l > 0:
                        or_range_pct = (or_h - or_l) / or_l

            # ── adx_norm  (ADX / 50 capped at 1.0) ───────────────────────────
            adx_norm = min(float(signal_data.get('adx', 20.0)) / 50.0, 1.0)

            # ── atr_pct  (ATR as % of close) ──────────────────────────────────
            atr_pct = float(signal_data.get('atr_pct', 0.01))
            if atr_pct == 0.01 and bars and len(bars) >= 2:
                highs  = [b['high'] for b in bars[-14:]]
                lows   = [b['low']  for b in bars[-14:]]
                closes = [b['close'] for b in bars[-14:]]
                trs    = [
                    max(highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i]  - closes[i - 1]))
                    for i in range(1, len(highs))
                ]
                if trs and entry_price > 0:
                    atr_pct = (sum(trs) / len(trs)) / entry_price

            # ── atr_ratio  (current ATR / 20-bar avg ATR) ────────────────────
            atr_ratio = float(signal_data.get('atr_ratio', 1.0))
            if atr_ratio == 1.0 and bars and len(bars) >= 20:
                def _atr_window(window):
                    trs = [
                        max(window[i]['high'] - window[i]['low'],
                            abs(window[i]['high'] - window[i - 1]['close']),
                            abs(window[i]['low']  - window[i - 1]['close']))
                        for i in range(1, len(window))
                    ]
                    return sum(trs) / len(trs) if trs else 1e-9
                atr_recent = _atr_window(bars[-5:])
                atr_avg20  = _atr_window(bars[-20:])
                atr_ratio  = atr_recent / atr_avg20 if atr_avg20 > 0 else 1.0

            # ── is_or_signal  (OR path vs intraday BOS) ───────────────────────
            is_or_signal = 1.0 if signal_type == 'CFW6_OR' else 0.0

            # ── hour_norm  (market hour 9-16 -> 0-1) ─────────────────────────
            now_hour   = signal_data.get('hour', datetime.now().hour)
            hour_norm  = max(0.0, min((float(now_hour) - 9.0) / 7.0, 1.0))

            # ── time_bucket_norm  (open=0 / mid=1 / close=2, norm /2) ─────────
            if now_hour < 11:
                time_bucket = 0
            elif now_hour < 14:
                time_bucket = 1
            else:
                time_bucket = 2
            time_bucket_norm = time_bucket / 2.0

            # ── resist_proximity  ((close - resistance) / atr, clipped 0-3)/3 ─
            resist_proximity = float(signal_data.get('resist_proximity', 0.0))
            if resist_proximity == 0.0 and bars and atr_pct > 0 and entry_price > 0:
                lookback   = bars[-20:] if len(bars) >= 20 else bars
                resistance = max(b['high'] for b in lookback)
                atr_abs    = atr_pct * entry_price
                if atr_abs > 0:
                    raw = (entry_price - resistance) / atr_abs
                    resist_proximity = max(0.0, min(raw, 3.0)) / 3.0

            # ── ticker_win_rate  (rolling 30-day per-ticker win rate, 0-1) ────
            # Pre-computed by sniper/scanner and passed in signal_data.
            # Falls back to 0.40 (neutral prior) if not supplied.
            ticker_win_rate = float(signal_data.get('ticker_win_rate', 0.40))
            ticker_win_rate = max(0.0, min(ticker_win_rate, 1.0))

            # ── spy_regime  (SPY macro context: -1=down / 0=flat / 1=up) ─────
            # Pre-computed from SPY 20-bar vs 50-bar EMA crossover + slope.
            # Falls back to live computation from spy_bars if supplied,
            # otherwise defaults to 0 (neutral / flat).
            spy_regime = signal_data.get('spy_regime', None)
            if spy_regime is None:
                spy_bars = signal_data.get('spy_bars') or []
                spy_regime = self._compute_spy_regime(spy_bars)
            spy_regime = float(spy_regime)

            return {
                'confidence':            confidence,
                'rvol':                  rvol,
                'score_norm':            score_norm,
                'mtf_convergence':       mtf_convergence,
                'mtf_convergence_count': mtf_convergence_count,
                'vwap_distance':         vwap_distance,
                'vwap_side':             vwap_side,
                'or_range_pct':          or_range_pct,
                'adx_norm':              adx_norm,
                'atr_pct':               atr_pct,
                'atr_ratio':             atr_ratio,
                'is_or_signal':          is_or_signal,
                'hour_norm':             hour_norm,
                'time_bucket_norm':      time_bucket_norm,
                'resist_proximity':      resist_proximity,
                'ticker_win_rate':       ticker_win_rate,
                'spy_regime':            spy_regime,
            }
        except Exception as exc:
            logger.warning(f"[ML-SCORER-v2] _build_features error: {exc}")
            return None

    # ── SPY regime helper ─────────────────────────────────────────────────────

    @staticmethod
    def _compute_spy_regime(spy_bars: list) -> float:
        """
        Compute SPY macro regime from bar list.
        Returns -1.0 (downtrend), 0.0 (flat), or 1.0 (uptrend).
        Requires at least 50 bars; falls back to 0.0 if insufficient.

        Logic:
          - EMA20 > EMA50 AND EMA20 slope positive  ->  1.0  (uptrend)
          - EMA20 < EMA50 AND EMA20 slope negative  -> -1.0  (downtrend)
          - otherwise                               ->  0.0  (flat)
        """
        try:
            if not spy_bars or len(spy_bars) < 50:
                return 0.0
            closes = [b['close'] for b in spy_bars]

            def _ema(values: list, period: int) -> list:
                k = 2.0 / (period + 1)
                result = [values[0]]
                for v in values[1:]:
                    result.append(v * k + result[-1] * (1 - k))
                return result

            ema20_series = _ema(closes, 20)
            ema50_series = _ema(closes, 50)
            ema20_now    = ema20_series[-1]
            ema50_now    = ema50_series[-1]
            # Slope: compare current EMA20 to 5 bars ago
            ema20_prev   = ema20_series[-6] if len(ema20_series) >= 6 else ema20_series[0]
            ema20_slope  = ema20_now - ema20_prev

            if ema20_now > ema50_now and ema20_slope > 0:
                return 1.0
            elif ema20_now < ema50_now and ema20_slope < 0:
                return -1.0
            else:
                return 0.0
        except Exception:
            return 0.0

    # ── Inference ─────────────────────────────────────────────────────────────

    def score_signal(self, signal_data: Dict[str, Any]) -> float:
        """
        Score a signal.  Returns win-probability float in [0.0, 1.0].
        Returns -1.0 if model is unavailable (caller should treat as no-op).
        """
        if not self.trained or not SKLEARN_AVAILABLE or not ML_DEPS_AVAILABLE:
            return self._rule_based_score(signal_data)

        feat_dict = self._build_features(signal_data)
        if feat_dict is None:
            return self._rule_based_score(signal_data)

        try:
            feature_order = self._feature_names if self._feature_names else HIST_FEATURE_COLS
            X = np.array(
                [feat_dict.get(col, 0.0) for col in feature_order],
                dtype=float
            ).reshape(1, -1)
            prob = float(self.model.predict_proba(X)[0][1])
            logger.debug(
                f"[ML-SCORER-v2] prob={prob:.3f} thresh={self.threshold:.3f} "
                f"features={len(feature_order)}"
            )
            return prob
        except Exception as exc:
            logger.warning(f"[ML-SCORER-v2] Inference error: {exc}")
            return self._rule_based_score(signal_data)

    def _rule_based_score(self, signal_data: Dict[str, Any]) -> float:
        """
        Fallback when model is not trained / unavailable.
        Returns -1.0 sentinel so sniper skips hard gate when no model present.
        """
        if not self.trained:
            return -1.0
        grade_map  = {'A+': 9, 'A': 8, 'A-': 7, 'B+': 6, 'B': 5,
                      'B-': 4, 'C+': 3, 'C': 2, 'C-': 1}
        confidence  = float(signal_data.get('confidence', 0.70))
        grade_score = grade_map.get(signal_data.get('grade', 'B'), 5) / 9.0
        rvol        = float(signal_data.get('rvol', 1.0))
        rvol_bonus  = min((rvol - 1.0) * 0.015, 0.08)
        score       = (confidence * 0.5) + (grade_score * 0.3) + (rvol_bonus * 0.2)
        return float(min(score, 0.95))


# ── Module-level singleton + convenience wrapper ──────────────────────────────

_scorer_v2: Optional[MLSignalScorerV2] = None


def get_scorer_v2() -> MLSignalScorerV2:
    global _scorer_v2
    if _scorer_v2 is None:
        _scorer_v2 = MLSignalScorerV2()
    return _scorer_v2


def score_signal_v2(signal_data: Dict[str, Any]) -> float:
    """Convenience wrapper — returns win-probability float."""
    return get_scorer_v2().score_signal(signal_data)
