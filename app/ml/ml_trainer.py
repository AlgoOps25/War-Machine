"""
ML Confidence Model Trainer

Trains a RandomForest classifier to predict signal outcomes (WIN/LOSS)
from the 15-feature vector produced by HistoricalMLTrainer.

Two entry points:
  train_from_dataframe() — called by train_historical.py (pre-training pipeline)
  train_model()          — called by EOD auto-retrain hook (live DB outcomes)

Key improvements (Mar 2026)
---------------------------
* Precision-first threshold tuning: sweeps the full probability curve and
  picks the highest threshold (most selective) where recall >= 30%.  This
  raises precision from ~36% → 50%+ while keeping enough signals to trade.
  Stored in the model bundle so MLSignalScorerV2 uses it at score time.
* Pandas CoW fix: all inplace fillna() calls replaced with
  df[col] = df[col].fillna(val) to suppress DeprecationWarning.
* class_weight='balanced' retained — handles WIN/LOSS imbalance.
* Feature audit (Mar 2026, BUG-11): HIST_FEATURE_COLS updated to match
  the 15 real, non-redundant features produced by HistoricalMLTrainer.
  Dropped: grade_norm, mtf_boost, is_bull, explosive_mover.
  Added:   vwap_side, atr_ratio, time_bucket_norm, resist_proximity.

Usage:
    # Historical pre-training (primary path)
    from app.backtesting.historical_trainer import HistoricalMLTrainer
    trainer = HistoricalMLTrainer()
    df = trainer.build_dataset(['AAPL', 'TSLA', ...], months_back=4)
    train_df, val_df = trainer.walk_forward_split(df)
    model, metrics = train_from_dataframe(train_df, val_df)

    # Live EOD retrain (secondary path — requires signal_outcomes DB table)
    from app.ml.ml_trainer import should_retrain, train_model
    if should_retrain():
        model, metrics = train_model()
"""
import logging
import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    confusion_matrix, precision_recall_curve, f1_score,
    fbeta_score,
)

logger = logging.getLogger(__name__)

# ── Paths & constants ────────────────────────────────────────────────────────
MODEL_PATH           = os.path.join(os.path.dirname(__file__), '..', '..', 'ml_model.joblib')
MIN_TRAINING_SAMPLES = 100
RETRAIN_THRESHOLD    = 50
MODEL_VERSION        = 'historical_v4'

MIN_RECALL_FLOOR = 0.30

# Feature columns produced by HistoricalMLTrainer — 15 real, non-redundant
# features. Must stay in sync with FEATURE_NAMES in historical_trainer.py.
#
# Dropped (BUG-11, correlation audit):
#   grade_norm      — redundant transform of confidence/score_norm
#   mtf_boost       — redundant float encoding of mtf_convergence_count
#   is_bull         — constant 1.0 (direction always 'bull'), NaN corr
#   explosive_mover — redundant binary bucket of continuous rvol
#
# Added (BUG-11, outcome-correlated replacements):
#   vwap_side        — +1/-1 sign of vwap_distance (above/below VWAP)
#   atr_ratio        — current ATR / 20-bar avg ATR (volatility expansion)
#   time_bucket_norm — session period: 0=open/1=mid/2=close, norm /2
#   resist_proximity — (close - resistance) / atr, clipped [0,3]/3
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
                f"[ML-TRAIN-DF] Threshold (pass 1 — max precision, recall≥{min_recall:.0%}): "
                f"{best_thresh:.3f}  Prec={best_prec:.2%}  Rec={best_rec:.2%}"
            )
        else:
            logger.warning(
                f"[ML-TRAIN-DF] No threshold with recall≥{min_recall:.0%} — "
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


# ── Main training function (historical pre-training path) ────────────────────

def train_from_dataframe(
    train_df:     pd.DataFrame,
    val_df:       Optional[pd.DataFrame] = None,
    model_path:   Optional[str] = None,
    n_estimators: int = 200,
) -> Tuple[Optional[object], dict]:
    """
    Train (and validate) an ML model from a pre-built labelled DataFrame.
    Accepts output of HistoricalMLTrainer.build_dataset() / walk_forward_split().
    Saves a bundle compatible with MLSignalScorerV2.
    """
    logger.info("[ML-TRAIN-DF] Starting train_from_dataframe()")

    available_feats = [c for c in HIST_FEATURE_COLS if c in train_df.columns]
    if not available_feats:
        msg = (
            f"train_df has none of the expected feature columns. "
            f"Expected: {HIST_FEATURE_COLS[:5]}...  Got: {list(train_df.columns)[:5]}..."
        )
        logger.error(f"[ML-TRAIN-DF] {msg}")
        return None, {'error': msg}

    label_col = 'outcome_binary'
    if label_col not in train_df.columns:
        msg = f"train_df missing label column '{label_col}'"
        logger.error(f"[ML-TRAIN-DF] {msg}")
        return None, {'error': msg}

    missing = [c for c in HIST_FEATURE_COLS if c not in train_df.columns]
    if missing:
        logger.warning(f"[ML-TRAIN-DF] Missing features (will be skipped): {missing}")

    train_df = train_df.copy()
    train_medians = {col: train_df[col].median() for col in available_feats}
    for col in available_feats:
        train_df[col] = train_df[col].fillna(train_medians[col])

    X_train = train_df[available_feats].values
    y_train = train_df[label_col].values

    logger.info(
        f"[ML-TRAIN-DF] Train: {len(X_train)} samples, "
        f"{len(available_feats)} features  "
        f"(WIN={int(y_train.sum())}, LOSS={len(y_train)-int(y_train.sum())})"
    )

    if val_df is not None and not val_df.empty:
        val_df = val_df.copy()
        for col in available_feats:
            if col in val_df.columns:
                val_df[col] = val_df[col].fillna(train_medians.get(col, 0.0))
        X_val = val_df[available_feats].values
        y_val = val_df[label_col].values
    else:
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
        )

    logger.info(f"[ML-TRAIN-DF] Val:   {len(X_val)} samples")

    try:
        model = RandomForestClassifier(
            n_estimators      = n_estimators,
            max_depth         = 10,
            min_samples_split = 5,
            min_samples_leaf  = 2,
            class_weight      = 'balanced',
            random_state      = 42,
            n_jobs            = -1,
        )
        model.fit(X_train, y_train)
        logger.info("[ML-TRAIN-DF] ✅ Model training complete")
    except Exception as exc:
        logger.error(f"[ML-TRAIN-DF] Training failed: {exc}")
        return None, {'error': str(exc)}

    y_pred_default = model.predict(X_val)
    acc_default    = accuracy_score(y_val, y_pred_default)
    prec_default   = precision_score(y_val, y_pred_default, zero_division=0)
    rec_default    = recall_score(y_val, y_pred_default, zero_division=0)

    opt_threshold = _find_optimal_threshold(model, X_val, y_val)
    y_pred_opt    = predict_with_threshold(model, X_val, opt_threshold)
    accuracy      = accuracy_score(y_val, y_pred_opt)
    precision     = precision_score(y_val, y_pred_opt, zero_division=0)
    recall        = recall_score(y_val, y_pred_opt, zero_division=0)
    f1            = f1_score(y_val, y_pred_opt, zero_division=0)
    cm            = confusion_matrix(y_val, y_pred_opt)

    X_all     = np.vstack([X_train, X_val])
    y_all     = np.concatenate([y_train, y_val])
    n_splits  = min(5, max(2, len(X_all) // 20))
    cv_scores = cross_val_score(model, X_all, y_all, cv=n_splits, scoring='accuracy')

    feat_imp        = dict(zip(available_feats, model.feature_importances_))
    feat_imp_sorted = dict(sorted(feat_imp.items(), key=lambda x: x[1], reverse=True))

    metrics = {
        'accuracy':           accuracy,
        'precision':          precision,
        'recall':             recall,
        'f1':                 f1,
        'threshold':          opt_threshold,
        'accuracy_default':   acc_default,
        'precision_default':  prec_default,
        'recall_default':     rec_default,
        'cv_mean':            float(cv_scores.mean()),
        'cv_std':             float(cv_scores.std()),
        'confusion_matrix':   cm.tolist(),
        'feature_importance': feat_imp_sorted,
        'feature_names':      available_feats,
        'n_train':            len(X_train),
        'n_val':              len(X_val),
        'trained_at':         datetime.now().isoformat(),
        'source':             'historical_pretraining',
        'model_version':      MODEL_VERSION,
    }

    logger.info(
        f"[ML-TRAIN-DF] @thresh={opt_threshold:.3f}  "
        f"Accuracy={accuracy:.2%}  Precision={precision:.2%}  "
        f"Recall={recall:.2%}  F1={f1:.2%}  "
        f"CV={cv_scores.mean():.2%}(\u00b1{cv_scores.std():.2%})"
    )
    logger.info(
        f"[ML-TRAIN-DF] Default @0.50: "
        f"Acc={acc_default:.2%}  Prec={prec_default:.2%}  Rec={rec_default:.2%}"
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
        }
        with open(save_path, 'wb') as f:
            pickle.dump(bundle, f)
        logger.info(f"[ML-TRAIN-DF] ✅ Model saved → {save_path}")
    except Exception as exc:
        logger.warning(f"[ML-TRAIN-DF] Save failed (model still returned): {exc}")

    return model, metrics


# ── Live EOD retrain path ────────────────────────────────────────────────────

def train_model(
    min_samples:  int   = MIN_TRAINING_SAMPLES,
    test_size:    float = 0.2,
    n_estimators: int   = 100,
) -> Tuple[Optional[object], dict]:
    """
    Train ML model on live signal_outcomes from the PostgreSQL DB.
    Called by the EOD auto-retrain hook in scanner.py.
    """
    logger.info("[ML-TRAIN] Starting live retrain from DB...")

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

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )

    try:
        model = RandomForestClassifier(
            n_estimators      = n_estimators,
            max_depth         = 10,
            min_samples_split = 5,
            min_samples_leaf  = 2,
            class_weight      = 'balanced',
            random_state      = 42,
            n_jobs            = -1,
        )
        model.fit(X_train, y_train)
        logger.info("[ML-TRAIN] ✅ Model training complete")
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Training failed: {exc}")
        return None, {'error': str(exc)}

    opt_threshold = _find_optimal_threshold(model, X_test, y_test)
    y_pred = predict_with_threshold(model, X_test, opt_threshold)

    accuracy  = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall    = recall_score(y_test, y_pred, zero_division=0)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    cm        = confusion_matrix(y_test, y_pred)

    feature_importance = dict(zip(feature_names, model.feature_importances_))
    sorted_features    = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)

    metrics = {
        'accuracy':           accuracy,
        'precision':          precision,
        'recall':             recall,
        'threshold':          opt_threshold,
        'cv_mean':            cv_scores.mean(),
        'cv_std':             cv_scores.std(),
        'confusion_matrix':   cm.tolist(),
        'feature_importance': dict(sorted_features[:10]),
        'feature_names':      feature_names,
        'n_train':            len(X_train),
        'n_val':              len(X_test),
        'trained_at':         datetime.now().isoformat(),
        'model_version':      MODEL_VERSION,
    }

    logger.info(
        f"[ML-TRAIN] Acc={accuracy:.2%}  Prec={precision:.2%}  "
        f"Rec={recall:.2%}  CV={cv_scores.mean():.2%}  Thresh={opt_threshold:.3f}"
    )

    try:
        model_data = {
            'model':         model,
            'feature_names': feature_names,
            'metrics':       metrics,
            'trained_at':    metrics['trained_at'],
            'threshold':     opt_threshold,
            'model_version': MODEL_VERSION,
        }
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"[ML-TRAIN] ✅ Model saved → {MODEL_PATH}")
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Save failed: {exc}")

    return model, metrics


# ── DB helpers ───────────────────────────────────────────────────────────────

def _fetch_training_data() -> Optional[pd.DataFrame]:
    """Fetch historical signal outcomes from PostgreSQL."""
    try:
        import psycopg2
        DATABASE_URL = os.getenv('DATABASE_URL')
        if not DATABASE_URL:
            logger.error("[ML-TRAIN] DATABASE_URL not set")
            return None
        conn_url = DATABASE_URL
        if 'sslmode=' not in conn_url.lower():
            sep = '&' if '?' in conn_url else '?'
            conn_url = f"{conn_url}{sep}sslmode=require"
        conn  = psycopg2.connect(conn_url)
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
        conn.close()
        logger.info(f"[ML-TRAIN] Fetched {len(df)} completed signals from DB")
        return df
    except Exception as exc:
        logger.error(f"[ML-TRAIN] DB fetch failed: {exc}")
        return None


def _prepare_features(df: pd.DataFrame) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], list]:
    """Prepare feature matrix X and labels y from live DB DataFrame."""
    try:
        features = ['confidence', 'rvol', 'adx', 'time_minutes', 'spy_correlation', 'iv_rank', 'mtf_convergence']
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
            'feature_count': len(model_data['feature_names']),
            'top_features':  list(model_data['metrics']['feature_importance'].keys())[:5],
        }
    except Exception as exc:
        logger.error(f"[ML-TRAIN] Failed to load model info: {exc}")
        return {'status': 'error', 'message': str(exc)}
