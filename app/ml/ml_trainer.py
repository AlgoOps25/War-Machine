"""
ML Confidence Model Trainer

This module trains a machine learning model to predict signal outcomes (Win/Loss)
based on historical data. The model adjusts confidence scores to improve win rate.

Features Used:
- Base confidence score
- Relative volume (RVOL)
- ADX (trend strength)
- Time of day
- SPY correlation
- Pattern type (BOS vs FVG)
- Opening range classification
- IV Rank
- Multi-timeframe convergence

Model:
- Random Forest Classifier (sklearn)
- 80/20 train/test split
- Cross-validation
- Exports to ml_model.joblib for production use

Usage:
    from app.ml.ml_trainer import train_model, should_retrain
    
    # Check if enough data for training
    if should_retrain():
        model, metrics = train_model()
        print(f"Model accuracy: {metrics['accuracy']:.2%}")
        print(f"Precision: {metrics['precision']:.2%}")
        print(f"Recall: {metrics['recall']:.2%}")
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
from sklearn.metrics import accuracy_score, precision_score, recall_score, confusion_matrix

logger = logging.getLogger(__name__)

# Model configuration
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'ml_model.joblib')
MIN_TRAINING_SAMPLES = 100  # Minimum signals needed for training
RETRAIN_THRESHOLD = 50  # Retrain when 50+ new signals since last training


def train_model(
    min_samples: int = MIN_TRAINING_SAMPLES,
    test_size: float = 0.2,
    n_estimators: int = 100
) -> Tuple[Optional[object], dict]:
    """
    Train ML model on historical signal outcomes.
    
    Args:
        min_samples: Minimum number of samples required for training
        test_size: Fraction of data to use for testing (0.2 = 20%)
        n_estimators: Number of trees in Random Forest
    
    Returns:
        tuple: (trained_model, metrics_dict)
    """
    logger.info("[ML-TRAIN] Starting model training...")
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 1: FETCH TRAINING DATA FROM DATABASE
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        df = _fetch_training_data()
        
        if df is None or len(df) < min_samples:
            logger.warning(
                f"[ML-TRAIN] Insufficient data: {len(df) if df is not None else 0} samples "
                f"(need {min_samples} minimum)"
            )
            return None, {'error': 'Insufficient training data'}
        
        logger.info(f"[ML-TRAIN] Loaded {len(df)} training samples")
        
    except Exception as e:
        logger.error(f"[ML-TRAIN] Failed to fetch training data: {e}")
        return None, {'error': str(e)}
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 2: PREPARE FEATURES AND LABELS
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        X, y, feature_names = _prepare_features(df)
        
        if X is None or y is None:
            logger.error("[ML-TRAIN] Feature preparation failed")
            return None, {'error': 'Feature preparation failed'}
        
        logger.info(f"[ML-TRAIN] Prepared {len(feature_names)} features")
        
    except Exception as e:
        logger.error(f"[ML-TRAIN] Feature preparation error: {e}")
        return None, {'error': str(e)}
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 3: TRAIN/TEST SPLIT
    # ════════════════════════════════════════════════════════════════════════════════
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )
    
    logger.info(
        f"[ML-TRAIN] Split: {len(X_train)} train, {len(X_test)} test "
        f"(Wins: {sum(y_train)}, Losses: {len(y_train) - sum(y_train)})"
    )
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 4: TRAIN RANDOM FOREST MODEL
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        
        model.fit(X_train, y_train)
        logger.info("[ML-TRAIN] ✅ Model training complete")
        
    except Exception as e:
        logger.error(f"[ML-TRAIN] Model training failed: {e}")
        return None, {'error': str(e)}
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 5: EVALUATE MODEL
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        # Predictions on test set
        y_pred = model.predict(X_test)
        
        # Calculate metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        
        # Cross-validation score (5-fold)
        cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        
        # Feature importance
        feature_importance = dict(zip(feature_names, model.feature_importances_))
        sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
        
        metrics = {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'confusion_matrix': cm.tolist(),
            'feature_importance': dict(sorted_features[:10]),  # Top 10 features
            'n_train': len(X_train),
            'n_test': len(X_test),
            'trained_at': datetime.now().isoformat()
        }
        
        logger.info(f"[ML-TRAIN] ✅ Model Performance:")
        logger.info(f"[ML-TRAIN]   Accuracy: {accuracy:.2%}")
        logger.info(f"[ML-TRAIN]   Precision: {precision:.2%}")
        logger.info(f"[ML-TRAIN]   Recall: {recall:.2%}")
        logger.info(f"[ML-TRAIN]   CV Score: {cv_scores.mean():.2%} (+/- {cv_scores.std():.2%})")
        logger.info(f"[ML-TRAIN]   Confusion Matrix:")
        logger.info(f"[ML-TRAIN]     TN={cm[0,0]}, FP={cm[0,1]}")
        logger.info(f"[ML-TRAIN]     FN={cm[1,0]}, TP={cm[1,1]}")
        
        logger.info(f"[ML-TRAIN] Top 5 Features:")
        for feat, importance in sorted_features[:5]:
            logger.info(f"[ML-TRAIN]   {feat}: {importance:.3f}")
        
    except Exception as e:
        logger.error(f"[ML-TRAIN] Model evaluation failed: {e}")
        return None, {'error': str(e)}
    
    # ════════════════════════════════════════════════════════════════════════════════
    # STEP 6: SAVE MODEL
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        # Save model and metadata
        model_data = {
            'model': model,
            'feature_names': feature_names,
            'metrics': metrics,
            'trained_at': datetime.now().isoformat()
        }
        
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"[ML-TRAIN] ✅ Model saved to {MODEL_PATH}")
        
    except Exception as e:
        logger.error(f"[ML-TRAIN] Failed to save model: {e}")
        return model, metrics  # Return model even if save fails
    
    return model, metrics


def _fetch_training_data() -> Optional[pd.DataFrame]:
    """
    Fetch historical signal outcomes from database.
    
    Returns:
        pd.DataFrame with columns:
        - confidence, rvol, adx, time_of_day, correlation, pattern_type,
          or_type, iv_rank, mtf_convergence, outcome (0=loss, 1=win)
    """
    try:
        import psycopg2
        DATABASE_URL = os.getenv('DATABASE_URL')
        
        if not DATABASE_URL:
            logger.error("[ML-TRAIN] DATABASE_URL not set")
            return None
        
        # Add SSL for Railway
        conn_url = DATABASE_URL
        if 'sslmode=' not in conn_url.lower():
            separator = '&' if '?' in conn_url else '?'
            conn_url = f"{conn_url}{separator}sslmode=require"
        
        conn = psycopg2.connect(conn_url)
        
        # Query signal outcomes (completed signals with known results)
        query = """
        SELECT 
            confidence,
            rvol,
            adx,
            EXTRACT(HOUR FROM signal_time) * 60 + EXTRACT(MINUTE FROM signal_time) as time_minutes,
            spy_correlation,
            pattern_type,
            or_classification,
            iv_rank,
            mtf_convergence,
            CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END as outcome
        FROM signals
        WHERE outcome IN ('WIN', 'LOSS')
          AND completed_at IS NOT NULL
          AND signal_time >= NOW() - INTERVAL '90 days'
        ORDER BY signal_time DESC
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        logger.info(f"[ML-TRAIN] Fetched {len(df)} completed signals from database")
        return df
    
    except Exception as e:
        logger.error(f"[ML-TRAIN] Database fetch failed: {e}")
        return None


def _prepare_features(df: pd.DataFrame) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], list]:
    """
    Prepare feature matrix X and labels y from DataFrame.
    
    Returns:
        tuple: (X, y, feature_names)
    """
    try:
        # Feature list
        features = [
            'confidence',
            'rvol',
            'adx',
            'time_minutes',
            'spy_correlation',
            'iv_rank',
            'mtf_convergence'
        ]
        
        # Add one-hot encoding for categorical features
        # Pattern type (BOS, FVG, OR_BREAKOUT)
        if 'pattern_type' in df.columns:
            pattern_dummies = pd.get_dummies(df['pattern_type'], prefix='pattern')
            df = pd.concat([df, pattern_dummies], axis=1)
            features.extend(pattern_dummies.columns.tolist())
        
        # OR classification (TIGHT, WIDE, NEUTRAL)
        if 'or_classification' in df.columns:
            or_dummies = pd.get_dummies(df['or_classification'], prefix='or')
            df = pd.concat([df, or_dummies], axis=1)
            features.extend(or_dummies.columns.tolist())
        
        # Handle missing values (fill with median/mode)
        for col in features:
            if col in df.columns:
                if df[col].dtype in ['float64', 'int64']:
                    df[col].fillna(df[col].median(), inplace=True)
                else:
                    df[col].fillna(0, inplace=True)
        
        # Extract features and labels
        X = df[features].values
        y = df['outcome'].values
        
        return X, y, features
    
    except Exception as e:
        logger.error(f"[ML-TRAIN] Feature preparation failed: {e}")
        return None, None, []


def should_retrain() -> bool:
    """
    Check if model should be retrained based on new data availability.
    
    Returns:
        bool: True if retraining recommended
    """
    try:
        # Check if model exists
        if not os.path.exists(MODEL_PATH):
            logger.info("[ML-TRAIN] No existing model found - training recommended")
            return True
        
        # Load model metadata
        model_data = joblib.load(MODEL_PATH)
        trained_at = datetime.fromisoformat(model_data['trained_at'])
        
        # Check age of model (retrain if > 30 days old)
        days_old = (datetime.now() - trained_at).days
        if days_old > 30:
            logger.info(f"[ML-TRAIN] Model is {days_old} days old - retraining recommended")
            return True
        
        # Check if enough new samples available
        df = _fetch_training_data()
        if df is None:
            return False
        
        n_samples_at_training = model_data['metrics']['n_train'] + model_data['metrics']['n_test']
        new_samples = len(df) - n_samples_at_training
        
        if new_samples >= RETRAIN_THRESHOLD:
            logger.info(
                f"[ML-TRAIN] {new_samples} new samples available "
                f"(threshold={RETRAIN_THRESHOLD}) - retraining recommended"
            )
            return True
        
        logger.info(f"[ML-TRAIN] Model is current ({new_samples} new samples, need {RETRAIN_THRESHOLD})")
        return False
    
    except Exception as e:
        logger.error(f"[ML-TRAIN] Error checking retrain status: {e}")
        return False


def get_model_info() -> dict:
    """
    Get information about the current trained model.
    
    Returns:
        dict: Model metadata and performance metrics
    """
    try:
        if not os.path.exists(MODEL_PATH):
            return {'status': 'no_model', 'message': 'No trained model found'}
        
        model_data = joblib.load(MODEL_PATH)
        
        return {
            'status': 'trained',
            'trained_at': model_data['trained_at'],
            'metrics': model_data['metrics'],
            'feature_count': len(model_data['feature_names']),
            'top_features': list(model_data['metrics']['feature_importance'].keys())[:5]
        }
    
    except Exception as e:
        logger.error(f"[ML-TRAIN] Failed to load model info: {e}")
        return {'status': 'error', 'message': str(e)}
