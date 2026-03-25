#!/usr/bin/env python3
"""
ML Trainer for Signal Analytics

Moved from app/ml/train_from_analytics.py (Batch B audit, 2026-03-16).
Standalone CLI dev tool — not a runtime module.

Trains a simple Random Forest model on historical signal outcomes
from the signal_analytics table (generated from cached data).

Usage:
    python scripts/ml/train_from_analytics.py
"""

import os
import sys
import joblib
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, precision_score, recall_score, confusion_matrix, classification_report

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Paths
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'ml_booster_analytics.pkl')


def train_model(min_samples: int = 100):
    logger.info("=" * 80)
    logger.info("ML CONFIDENCE BOOSTER TRAINING - Signal Analytics")
    logger.info("=" * 80)
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    logger.info("[1/5] Loading signal outcomes from database...")

    try:
        from app.data.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'signal_analytics'
        """)
        if cur.fetchone()[0] == 0:
            logger.error("signal_analytics table not found")
            logger.info("Run: python scripts/generate_ml_training_data.py")
            return None, None
        query = """
        SELECT ticker, timestamp, direction, entry_price, confidence,
               volume_ratio, pattern_type, outcome, pnl_pct, exit_price, bars_held
        FROM signal_analytics
        WHERE outcome IN ('WIN', 'LOSS')
        ORDER BY timestamp DESC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        logger.info(f"Loaded {len(df)} signal outcomes")
        if len(df) < min_samples:
            logger.warning(f"Insufficient data: {len(df)} samples (need {min_samples})")
            return None, None
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        import traceback; traceback.print_exc()
        return None, None

    logger.info("[2/5] Engineering features...")
    try:
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['minute'] = pd.to_datetime(df['timestamp']).dt.minute
        df['time_of_day'] = df['hour'] * 60 + df['minute']
        df['is_bullish'] = (df['direction'] == 'BULLISH').astype(int)
        df['has_fvg'] = df['pattern_type'].str.contains('FVG', na=False).astype(int)
        df['target'] = (df['outcome'] == 'WIN').astype(int)
        features = ['confidence', 'volume_ratio', 'time_of_day', 'is_bullish', 'has_fvg']
        for col in features:
            if df[col].isnull().any():
                df[col].fillna(df[col].median(), inplace=True)
        logger.info(f"Engineered {len(features)} features: {', '.join(features)}")
    except Exception as e:
        logger.error(f"Feature engineering failed: {e}")
        import traceback; traceback.print_exc()
        return None, None

    logger.info("[3/5] Splitting data...")
    X = df[features].values
    y = df['target'].values
    n_wins = sum(y)
    logger.info(f"   Wins: {n_wins} ({n_wins/len(y):.1%})  Losses: {len(y)-n_wins}")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    logger.info(f"   Train: {len(X_train)}, Test: {len(X_test)}")

    logger.info("[4/5] Training Random Forest...")
    try:
        model = RandomForestClassifier(
            n_estimators=100, max_depth=8, min_samples_split=10,
            min_samples_leaf=5, random_state=42, class_weight='balanced', n_jobs=-1
        )
        model.fit(X_train, y_train)
        logger.info("Model trained successfully")
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return None, None

    logger.info("[5/5] Evaluating...")
    try:
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
        cm = confusion_matrix(y_test, y_pred)
        tn, fp, fn, tp = cm.ravel()
        feature_importance = dict(zip(features, model.feature_importances_))
        predicted_wins = y_pred == 1
        predicted_win_rate = y_test[predicted_wins].sum() / predicted_wins.sum() if predicted_wins.sum() > 0 else 0
        logger.info(f"Accuracy: {accuracy:.1%}  Precision: {precision:.1%}  Recall: {recall:.1%}")
        logger.info(f"CV: {cv_scores.mean():.1%} (±{cv_scores.std():.1%})")
        logger.info(f"Predicted win rate: {predicted_win_rate:.1%}")
        metrics = {
            'accuracy': accuracy, 'precision': precision, 'recall': recall,
            'cv_mean': cv_scores.mean(), 'cv_std': cv_scores.std(),
            'predicted_win_rate': predicted_win_rate,
            'confusion_matrix': cm.tolist(),
            'feature_importance': dict(sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)),
            'n_train': len(X_train), 'n_test': len(X_test),
            'trained_at': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback; traceback.print_exc()
        return model, {}

    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_data = {'model': model, 'features': features, 'metrics': metrics,
                      'trained_at': datetime.now().isoformat(), 'version': '1.0'}
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"Model saved to: {MODEL_PATH}")
    except Exception as e:
        logger.error(f"Failed to save model: {e}")

    logger.info("TRAINING COMPLETE")
    return model, metrics


if __name__ == "__main__":
    model, metrics = train_model(min_samples=100)
    sys.exit(0 if model is not None else 1)
