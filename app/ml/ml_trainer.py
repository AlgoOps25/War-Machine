"""
ML Confidence Model Trainer

Trains a HistGradientBoosting classifier to predict signal outcomes (WIN/LOSS)
from the 17-feature vector produced by HistoricalMLTrainer.

Two entry points:
  train_from_dataframe() — called by train_historical.py (pre-training pipeline)
  train_model()          — called by EOD auto-retrain hook (live DB outcomes)

Key improvements (Mar 2026)
---------------------------
* Swapped RandomForestClassifier → HistGradientBoostingClassifier (Mar 11 2026)
* Added ticker_win_rate + spy_regime features (Mar 11 2026)
* Precision-first threshold tuning (Mar 11 2026)
* Pandas CoW fix: all inplace fillna() calls replaced (Mar 11 2026)
* Feature audit (Mar 2026, BUG-11): HIST_FEATURE_COLS updated
* FIX (Mar 12 2026):
  - walk_forward_cv() — 3-fold time-series cross-validation replaces single
    75/25 split.  Each fold trains on all data up to fold boundary, validates
    on the next window.  Final model is retrained on 100% of data then wrapped
    with CalibratedClassifierCV(method='sigmoid') for Platt-scaled probabilities.
  - train_from_dataframe() now calls walk_forward_cv() internally.
  - Platt scaling (CalibratedClassifierCV) applied after walk-forward so
    predict_proba() outputs are proper calibrated probabilities.
* FIX (Mar 26 2026) — issues #25 / #26 / #27:
  - #25: train_model() (EOD live path) now uses walk_forward_cv() instead of a
    single 80/20 split.  Platt calibration is applied on the last-fold val set
    (not the test set used for eval metrics) to avoid data leakage — consistent
    with train_from_dataframe() behaviour.
  - #26: _fetch_training_data() now uses db_connection.get_conn() /
    return_conn() instead of a raw psycopg2.connect().  The direct conn.close()
    is gone; pool is used consistently throughout the codebase.
  - #27: LIVE_FEATURE_COLS constant added below HIST_FEATURE_COLS to make the
    feature-set divergence between the two training paths explicit and
    searchable.  A WARNING is emitted at train_model() startup so the
    difference is visible in logs.
"""
import logging
import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from sklearn.inspection import permutation_importance
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    confusion_matrix, precision_recall_curve, f1_score,
    fbeta_score,
)

from app.data.db_connection import get_conn, return_conn

logger = logging.getLogger(__name__)

# ── Paths & constants ────────────────────────────────────────────────────────
MODEL_PATH           = os.path.join(os.path.dirname(__file__), '..', '..', 'ml_model.joblib')
MIN_TRAINING_SAMPLES = 100
RETRAIN_THRESHOLD    = 50
MODEL_VERSION        = 'historical_v6'

MIN_RECALL_FLOOR = 0.30

# Feature set used by train_from_dataframe() — historical pre-training path.
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

# Feature set used by train_model() — live EOD retrain path.
# NOTE (#27): These two sets are intentionally different because the live DB
# schema (signals table) does not yet expose all HIST_FEATURE_COLS columns.
# If you hot-swap the historical model with the live EOD model the feature
# vector will mismatch → silent wrong predictions.  Do not swap without
# aligning features first.
LIVE_FEATURE_COLS = [
    'confidence', 'rvol', 'adx', 'time_minutes',
    'spy_correlation', 'iv_rank', 'mtf_convergence',
    # pattern_type and or_classification are one-hot encoded dynamically
    # in _prepare_features() — do not add them here.
]


# ── Threshold tuning ─────────────────────────────────────────────────────────

def _find_optimal_threshold(
    model,
    X_val: np.ndarray,
    y_val: np.ndarray,
    min_recall: float = MIN_RECALL_FLOOR,
) -> float:
    """
    Find the probability threshold that maximises precision on the val set
    subject to a minimum recall floor.
    Pass 1 — max precision where recall >= min_recall
    Pass 2 — max F-beta (beta=0.5) fallback
    Pass 3 — hard fallback: 0.50
    Result clamped to [0.40, 0.80].
    """
    try:
        probs = model.predict_proba(X_val)[:, 1]
        precisions, recalls, thresholds = precision_recall_curve(y_val, probs)
        prec_t = precisions[:-1]
        rec_t  = recalls[:-1]

        valid_mask = rec_t >= min_recall
        if valid_mask.any():
            best_idx      = np.argmax(prec_t[valid_mask])
            best_idx_full = np.where(valid_mask)[0][best_idx]
            best_thresh   = float(thresholds[best_idx_full])
            best_prec     = float(prec_t[best_idx_full])
            best_rec      = float(rec_t[best_idx_full])
            logger.info(
                f"[ML-TRAIN-DF] Threshold (pass 1 — max precision, recall>={min_recall:.0%}): "
                f"{best_thresh:.3f}  Prec={best_prec:.2%}  Rec={best_rec:.2%}"
            )
        else:
            logger.warning(
                f"[ML-TRAIN-DF] No threshold with recall>={min_recall:.0%} — "
                f"falling back to F-beta (beta=0.5)"
            )
            denom      = (0.5**2 * prec_t) + rec_t
            denom      = np.where(denom == 0, 1e-9, denom)
            fbeta      = (1 + 0.5**2) * prec_t * rec_t / denom
            best_idx   = np.argmax(fbeta)
            best_thresh = float(thresholds[best_idx])
            best_prec   = float(prec_t[best_idx])
            best_rec    = float(rec_t[best_idx])
            logger.info(
                f"[ML-TRAIN-DF] Threshold (pass 2 — F0.5): "
                f"{best_thresh:.3f}  Prec={best_prec:.2%}  Rec={best_rec:.2%}"
            )

        return max(0.40, min(0.80, best_thresh))

    except Exception as exc:
        logger.warning(f"[ML-TRAIN-DF] Threshold tuning failed ({exc}), using 0.50")
        return 0.50


def predict_with_threshold(model, X: np.ndarray, threshold: float = 0.50) -> np.ndarray:
    """Apply a custom probability threshold to model.predict_proba()."""
    return (model.predict_proba(X)[:, 1] >= threshold).astype(int)


# ── Walk-forward cross-validation (FIX: 3-fold, not single split) ────────────

def walk_forward_cv(
    X: np.ndarray,
    y: np.ndarray,
    n_folds: int = 3,
    n_estimators: int = 300,
) -> Tuple[List[dict], np.ndarray, np.ndarray]:
    """
    Time-series aware walk-forward cross-validation.

    For each fold k in 0..n_folds-1:
      - train on X[0 : fold_end_k]
      - validate on X[fold_end_k : fold_end_k + fold_size]

    Returns
    -------
    fold_metrics : list of dicts with accuracy/precision/recall per fold
    X_last_val   : validation array from the final fold (used for threshold tuning)
    y_last_val   : labels from the final fold
    """
    n = len(X)
    fold_size = n // (n_folds + 1)   # +1 so first train window is meaningful
    fold_metrics: List[dict] = []

    logger.info(f"[WF-CV] Starting {n_folds}-fold walk-forward CV  (n={n}, fold_size≈{fold_size})")

    X_last_val = None
    y_last_val = None

    for k in range(n_folds):
        train_end = fold_size * (k + 1)
        val_end   = min(train_end + fold_size, n)

        X_tr, y_tr = X[:train_end], y[:train_end]
        X_vl, y_vl = X[train_end:val_end], y[train_end:val_end]

        if len(X_vl) < 10 or len(np.unique(y_vl)) < 2:
            logger.warning(f"[WF-CV] Fold {k+1} skipped — too few samples or single class")
            continue

        clf = HistGradientBoostingClassifier(
            max_iter=n_estimators, max_depth=4, learning_rate=0.05,
            l2_regularization=0.1, class_weight='balanced', random_state=42,
        )
        clf.fit(X_tr, y_tr)
        y_pred = clf.predict(X_vl)

        m = {
            'fold':      k + 1,
            'n_train':   len(X_tr),
            'n_val':     len(X_vl),
            'accuracy':  accuracy_score(y_vl, y_pred),
            'precision': precision_score(y_vl, y_pred, zero_division=0),
            'recall':    recall_score(y_vl, y_pred, zero_division=0),
            'f1':        f1_score(y_vl, y_pred, zero_division=0),
        }
        fold_metrics.append(m)
        logger.info(
            f"[WF-CV] Fold {k+1}/{n_folds}  train={len(X_tr)}  val={len(X_vl)}  "
            f"Prec={m['precision']:.2%}  Rec={m['recall']:.2%}  F1={m['f1']:.2%}"
        )

        X_last_val = X_vl
        y_last_val = y_vl

    if X_last_val is None:
        # Fallback: use last 20% as val
        split = int(n * 0.8)
        X_last_val, y_last_val = X[split:], y[split:]

    return fold_metrics, X_last_val, y_last_val


# ── Main training function (historical pre-training path) ────────────────────

def train_from_dataframe(
    train_df:     pd.DataFrame,
    val_df:       Optional[pd.DataFrame] = None,
    model_path:   Optional[str] = None,
    n_estimators: int = 300,
) -> Tuple[Optional[object], dict]:
    """
    Train (and validate) an ML model from a pre-built labelled DataFrame.
    Now uses 3-fold walk-forward CV instead of a single 75/25 split.
    Final model is retrained on ALL data then Platt-calibrated.
    """
    logger.info("[ML-TRAIN-DF] Starting train_from_dataframe() — 3-fold walk-forward + Platt scaling")

    # ── Merge train + val if both supplied (we'll do our own CV split) ────────
    if val_df is not None and not val_df.empty:
        full_df = pd.concat([train_df, val_df], ignore_index=True)
    else:
        full_df = train_df.copy()

    available_feats = [c for c in HIST_FEATURE_COLS if c in full_df.columns]
    if not available_feats:
        msg = (
            f"DataFrame has none of the expected feature columns. "
            f"Expected: {HIST_FEATURE_COLS[:5]}...  Got: {list(full_df.columns)[:5]}..."
        )
        logger.error(f"[ML-TRAIN-DF] {msg}")
        return None, {'error': msg}

    label_col = 'outcome_binary'
    if label_col not in full_df.columns:
        msg = f"DataFrame missing label column '{label_col}'"
        logger.error(f"[ML-TRAIN-DF] {msg}")
        return None, {'error': msg}

    missing = [c for c in HIST_FEATURE_COLS if c not in full_df.columns]
    if missing:
        logger.warning(f"[ML-TRAIN-DF] Missing features (will be zero-filled at inference): {missing}")

    # Sort by time if available so walk-forward is chronological
    for time_col in ('signal_time', 'timestamp', 'date', 'created_at'):
        if time_col in full_df.columns:
            full_df = full_df.sort_values(time_col).reset_index(drop=True)
            logger.info(f"[ML-TRAIN-DF] Sorted by '{time_col}' for walk-forward ordering")
            break

    medians = {col: full_df[col].median() for col in available_feats}
    for col in available_feats:
        full_df[col] = full_df[col].fillna(medians[col])

    X_all = full_df[available_feats].values
    y_all = full_df[label_col].values

    logger.info(
        f"[ML-TRAIN-DF] Full dataset: {len(X_all)} samples, {len(available_feats)} features  "
        f"(WIN={int(y_all.sum())}, LOSS={len(y_all)-int(y_all.sum())})"
    )

    # ── Step 1: 3-fold walk-forward CV for honest metrics ────────────────────
    fold_metrics, X_last_val, y_last_val = walk_forward_cv(
        X_all, y_all, n_folds=3, n_estimators=n_estimators
    )

    if not fold_metrics:
        logger.error("[ML-TRAIN-DF] All walk-forward folds failed — aborting")
        return None, {'error': 'Walk-forward CV produced no valid folds'}

    cv_acc  = float(np.mean([m['accuracy']  for m in fold_metrics]))
    cv_prec = float(np.mean([m['precision'] for m in fold_metrics]))
    cv_rec  = float(np.mean([m['recall']    for m in fold_metrics]))
    cv_f1   = float(np.mean([m['f1']        for m in fold_metrics]))
    logger.info(
        f"[ML-TRAIN-DF] WF-CV mean — Acc={cv_acc:.2%}  Prec={cv_prec:.2%}  "
        f"Rec={cv_rec:.2%}  F1={cv_f1:.2%}"
    )

    # ── Step 2: Final model — train on ALL data ───────────────────────────────
    try:
        base_model = HistGradientBoostingClassifier(
            max_iter=n_estimators, max_depth=4, learning_rate=0.05,
            l2_regularization=0.1, class_weight='balanced', random_state=42,
        )
        base_model.fit(X_all, y_all)
        logger.info("[ML-TRAIN-DF] ✅ Base model trained on full dataset")
    except Exception as exc:
        logger.error(f"[ML-TRAIN-DF] Training failed: {exc}")
        return None, {'error': str(exc)}

    # ── Step 3: Platt scaling (CalibratedClassifierCV, sigmoid) ─────────────
    # cv='prefit' means the base model is already fitted; calibration is done
    # on the last-fold val set to avoid data leakage.
    try:
        model = CalibratedClassifierCV(estimator=base_model, method='sigmoid', cv='prefit')
        model.fit(X_last_val, y_last_val)
        logger.info("[ML-TRAIN-DF] ✅ Platt scaling applied (CalibratedClassifierCV sigmoid)")
    except Exception as exc:
        logger.warning(f"[ML-TRAIN-DF] Platt scaling failed ({exc}) — using uncalibrated model")
        model = base_model

    # ── Step 4: Threshold tuning on last-fold val set ────────────────────────
    opt_threshold = _find_optimal_threshold(model, X_last_val, y_last_val)
    y_pred_opt    = predict_with_threshold(model, X_last_val, opt_threshold)
    accuracy      = accuracy_score(y_last_val, y_pred_opt)
    precision     = precision_score(y_last_val, y_pred_opt, zero_division=0)
    recall        = recall_score(y_last_val, y_pred_opt, zero_division=0)
    f1            = f1_score(y_last_val, y_pred_opt, zero_division=0)
    cm            = confusion_matrix(y_last_val, y_pred_opt)

    # ── Step 5: Permutation importance on last-fold val set ──────────────────
    try:
        pi = permutation_importance(
            model, X_last_val, y_last_val,
            n_repeats=10, random_state=42, n_jobs=-1,
        )
        feat_imp = dict(zip(available_feats, pi.importances_mean))
    except Exception as exc:
        logger.warning(f"[ML-TRAIN-DF] Permutation importance failed: {exc}")
        feat_imp = {col: 0.0 for col in available_feats}
    feat_imp_sorted = dict(sorted(feat_imp.items(), key=lambda x: x[1], reverse=True))

    metrics = {
        'accuracy':           accuracy,
        'precision':          precision,
        'recall':             recall,
        'f1':                 f1,
        'threshold':          opt_threshold,
        'cv_mean':            cv_acc,
        'cv_std':             float(np.std([m['accuracy'] for m in fold_metrics])),
        'cv_precision_mean':  cv_prec,
        'cv_recall_mean':     cv_rec,
        'cv_f1_mean':         cv_f1,
        'fold_metrics':       fold_metrics,
        'confusion_matrix':   cm.tolist(),
        'feature_importance': feat_imp_sorted,
        'feature_names':      available_feats,
        'n_train':            len(X_all),
        'n_val':              len(X_last_val),
        'calibrated':         True,
        'trained_at':         datetime.now().isoformat(),
        'source':             'historical_pretraining',
        'model_version':      MODEL_VERSION,
        'model_type':         'HistGradientBoostingClassifier+PlattScaling',
    }

    logger.info(
        f"[ML-TRAIN-DF] Final @thresh={opt_threshold:.3f}  "
        f"Accuracy={accuracy:.2%}  Precision={precision:.2%}  "
        f"Recall={recall:.2%}  F1={f1:.2%}"
    )

    save_path = model_path or os.path.join(
        os.path.dirname(__file__), '..', '..', 'models', 'ml_model_historical.pkl'
    )
    try:
        import pickle
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        bundle = {
            'model':          model,
            'feature_names':  available_feats,
            'metrics':        metrics,
            'trained_at':     metrics['trained_at'],
            'threshold':      opt_threshold,
            'model_version':  MODEL_VERSION,
            'model_type':     'HistGradientBoostingClassifier+PlattScaling',
            'calibrated':     True,
        }
        with open(save_path, 'wb') as f:
            pickle.dump(bundle, f)
        logger.info(f"[ML-TRAIN-DF] ✅ Model saved -> {save_path}")
    except Exception as exc:
        logger.warning(f"[ML-TRAIN-DF] Save failed (model still returned): {exc}")

    return model, metrics


# ── Live EOD retrain path ────────────────────────────────────────────────────

def train_model(
    min_samples:  int   = MIN_TRAINING_SAMPLES,
    test_size:    float = 0.2,
    n_estimators: int   = 300,
) -> Tuple[Optional[object], dict]:
    """
    Train ML model on live signal_outcomes from the PostgreSQL DB.
    Called by the EOD auto-retrain hook in scanner.py.

    FIX #25 (Mar 26 2026): Now uses walk_forward_cv() (3-fold time-series CV)
    instead of a single 80/20 random split.  Platt calibration is applied on
    the last-fold val set — the same holdout used for threshold tuning — so
    the calibration data is fully disjoint from both training and eval data.

    NOTE (#27): This path uses LIVE_FEATURE_COLS (7 base + dummies), not
    HIST_FEATURE_COLS (20 features).  Do not hot-swap the two model files
    without aligning feature sets.
    """
    logger.info("[ML-TRAIN] Starting live retrain from DB...")
    logger.warning(
        "[ML-TRAIN] Live path uses LIVE_FEATURE_COLS — different from HIST_FEATURE_COLS. "
        "Do NOT hot-swap historical and live model files without aligning features."
    )

    try:
        df = _fetch_training_data()
        if df is None or len(df) < min_samples:
            logger.warning(
                f"[ML-TRAIN] Insufficient data: "
                f"{len(df) if df is not None else 0} samples (need {min_samples})"
            )
            return None, {'error': 'Insufficient training data'}
        logger.info(f"[ML-TRAIN] Loaded {len(df)} training samples")
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Failed to fetch training data: {exc}")
        return None, {'error': str(exc)}

    try:
        X, y, feature_names = _prepare_features(df)
        if X is None or y is None:
            return None, {'error': 'Feature preparation failed'}
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Feature prep error: {exc}")
        return None, {'error': str(exc)}

    # ── FIX #25: walk-forward CV instead of single split ─────────────────────
    fold_metrics, X_last_val, y_last_val = walk_forward_cv(
        X, y, n_folds=3, n_estimators=n_estimators
    )

    if not fold_metrics:
        logger.error("[ML-TRAIN] All walk-forward folds failed — aborting")
        return None, {'error': 'Walk-forward CV produced no valid folds'}

    cv_acc  = float(np.mean([m['accuracy']  for m in fold_metrics]))
    cv_prec = float(np.mean([m['precision'] for m in fold_metrics]))
    cv_rec  = float(np.mean([m['recall']    for m in fold_metrics]))
    cv_f1   = float(np.mean([m['f1']        for m in fold_metrics]))
    logger.info(
        f"[ML-TRAIN] WF-CV mean — Acc={cv_acc:.2%}  Prec={cv_prec:.2%}  "
        f"Rec={cv_rec:.2%}  F1={cv_f1:.2%}"
    )

    try:
        base_model = HistGradientBoostingClassifier(
            max_iter=n_estimators, max_depth=4, learning_rate=0.05,
            l2_regularization=0.1, class_weight='balanced', random_state=42,
        )
        base_model.fit(X, y)
        # FIX #25: calibrate on last-fold val set, not the eval split
        model = CalibratedClassifierCV(estimator=base_model, method='sigmoid', cv='prefit')
        model.fit(X_last_val, y_last_val)
        logger.info("[ML-TRAIN] ✅ Model trained on full dataset + Platt-calibrated on last-fold val")
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Training failed: {exc}")
        return None, {'error': str(exc)}

    opt_threshold = _find_optimal_threshold(model, X_last_val, y_last_val)
    y_pred = predict_with_threshold(model, X_last_val, opt_threshold)

    accuracy  = accuracy_score(y_last_val, y_pred)
    precision = precision_score(y_last_val, y_pred, zero_division=0)
    recall    = recall_score(y_last_val, y_pred, zero_division=0)
    cm        = confusion_matrix(y_last_val, y_pred)

    try:
        feature_importance = dict(zip(feature_names, base_model.feature_importances_))
    except AttributeError:
        feature_importance = {col: 0.0 for col in feature_names}
    sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)

    metrics = {
        'accuracy':           accuracy,
        'precision':          precision,
        'recall':             recall,
        'threshold':          opt_threshold,
        'cv_mean':            cv_acc,
        'cv_std':             float(np.std([m['accuracy'] for m in fold_metrics])),
        'cv_precision_mean':  cv_prec,
        'cv_recall_mean':     cv_rec,
        'cv_f1_mean':         cv_f1,
        'fold_metrics':       fold_metrics,
        'confusion_matrix':   cm.tolist(),
        'feature_importance': dict(sorted_features[:10]),
        'feature_names':      feature_names,
        'n_train':            len(X),
        'n_val':              len(X_last_val),
        'calibrated':         True,
        'trained_at':         datetime.now().isoformat(),
        'model_version':      MODEL_VERSION,
        'model_type':         'HistGradientBoostingClassifier+PlattScaling',
    }

    logger.info(
        f"[ML-TRAIN] Acc={accuracy:.2%}  Prec={precision:.2%}  "
        f"Rec={recall:.2%}  Thresh={opt_threshold:.3f}"
    )

    try:
        model_data = {
            'model':         model,
            'feature_names': feature_names,
            'metrics':       metrics,
            'trained_at':    metrics['trained_at'],
            'threshold':     opt_threshold,
            'model_version': MODEL_VERSION,
            'model_type':    'HistGradientBoostingClassifier+PlattScaling',
            'calibrated':    True,
        }
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"[ML-TRAIN] ✅ Model saved -> {MODEL_PATH}")
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Save failed: {exc}")

    return model, metrics


# ── DB helpers ───────────────────────────────────────────────────────────────

def _fetch_training_data() -> Optional[pd.DataFrame]:
    """
    Fetch historical signal outcomes from PostgreSQL.
    FIX #26 (Mar 26 2026): Uses db_connection pool (get_conn/return_conn)
    instead of a raw psycopg2.connect() — consistent with the rest of the
    codebase and benefits from pool config / SSL settings.
    """
    conn = None
    try:
        conn = get_conn()
        query = """
            SELECT
                confidence, rvol, adx,
                EXTRACT(HOUR FROM signal_time) * 60
                    + EXTRACT(MINUTE FROM signal_time) AS time_minutes,
                spy_correlation, pattern_type, or_classification, iv_rank,
                mtf_convergence,
                CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END AS outcome
            FROM signals
            WHERE outcome IN ('WIN', 'LOSS')
              AND completed_at IS NOT NULL
              AND signal_time >= NOW() - INTERVAL '90 days'
            ORDER BY signal_time DESC
        """
        df = pd.read_sql_query(query, conn)
        logger.info(f"[ML-TRAIN] Fetched {len(df)} completed signals from DB")
        return df
    except Exception as exc:
        logger.error(f"[ML-TRAIN] DB fetch failed: {exc}")
        return None
    finally:
        if conn:
            return_conn(conn)


def _prepare_features(df: pd.DataFrame) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], list]:
    """Prepare feature matrix X and labels y from live DB DataFrame."""
    try:
        features = list(LIVE_FEATURE_COLS)  # start from canonical live feature list
        if 'pattern_type' in df.columns:
            dummies = pd.get_dummies(df['pattern_type'], prefix='pattern')
            df = pd.concat([df, dummies], axis=1)
            features.extend(dummies.columns.tolist())
        if 'or_classification' in df.columns:
            dummies = pd.get_dummies(df['or_classification'], prefix='or')
            df = pd.concat([df, dummies], axis=1)
            features.extend(dummies.columns.tolist())
        for col in features:
            if col in df.columns:
                if df[col].dtype in ['float64', 'int64']:
                    df[col] = df[col].fillna(df[col].median())
                else:
                    df[col] = df[col].fillna(0)
        return df[features].values, df['outcome'].values, features
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Feature prep failed: {exc}")
        return None, None, []


# ── Retrain check ────────────────────────────────────────────────────────────

def should_retrain() -> bool:
    """Check if model should be retrained based on new data availability."""
    try:
        if not os.path.exists(MODEL_PATH):
            logger.info("[ML-TRAIN] No existing model — training recommended")
            return True
        model_data = joblib.load(MODEL_PATH)
        trained_at = datetime.fromisoformat(model_data['trained_at'])
        days_old   = (datetime.now() - trained_at).days
        if days_old > 30:
            logger.info(f"[ML-TRAIN] Model is {days_old}d old — retraining recommended")
            return True
        df = _fetch_training_data()
        if df is None:
            return False
        n_at_train  = model_data['metrics']['n_train'] + model_data['metrics'].get('n_val', 0)
        new_samples = len(df) - n_at_train
        if new_samples >= RETRAIN_THRESHOLD:
            logger.info(f"[ML-TRAIN] {new_samples} new samples — retraining recommended")
            return True
        logger.info(f"[ML-TRAIN] Model current ({new_samples} new samples, need {RETRAIN_THRESHOLD})")
        return False
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Error checking retrain status: {exc}")
        return False


def get_model_info() -> dict:
    """Get metadata and performance metrics of the current trained model."""
    try:
        if not os.path.exists(MODEL_PATH):
            return {'status': 'no_model', 'message': 'No trained model found'}
        model_data = joblib.load(MODEL_PATH)
        return {
            'status':        'trained',
            'trained_at':    model_data['trained_at'],
            'metrics':       model_data['metrics'],
            'threshold':     model_data.get('threshold', 0.50),
            'model_version': model_data.get('model_version', 'unknown'),
            'model_type':    model_data.get('model_type', 'unknown'),
            'calibrated':    model_data.get('calibrated', False),
            'feature_count': len(model_data['feature_names']),
            'top_features':  list(model_data['metrics']['feature_importance'].keys())[:5],
        }
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Failed to load model info: {exc}")
        return {'status': 'error', 'message': str(exc)}
