#!/usr/bin/env python3
"""
ML Trainer for Signal Analytics

Trains a simple Random Forest model on historical signal outcomes
from the signal_analytics table (generated from cached data).

This is a lightweight version that works with the synthetic backtest data.
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
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'ml_booster_analytics.pkl')


def train_model(min_samples: int = 100):
    """
    Train ML model on signal_analytics data.
    
    Args:
        min_samples: Minimum number of samples required (default: 100)
    
    Returns:
        Trained model and metrics
    """
    logger.info("=" * 80)
    logger.info("ML CONFIDENCE BOOSTER TRAINING - Signal Analytics")
    logger.info("=" * 80)
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    # ========================================================================
    # STEP 1: Load Data
    # ========================================================================
    logger.info("[1/5] Loading signal outcomes from database...")
    
    try:
        from app.data.database import get_db_connection
        
        conn = get_db_connection()
        
        # Check if table exists
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_name = 'signal_analytics'
        """)
        
        if cur.fetchone()[0] == 0:
            logger.error("❌ signal_analytics table not found")
            logger.info("Run: python scripts/generate_ml_training_data.py")
            return None, None
        
        # Load data
        query = """
        SELECT 
            ticker,
            timestamp,
            direction,
            entry_price,
            confidence,
            volume_ratio,
            pattern_type,
            outcome,
            pnl_pct,
            exit_price,
            bars_held
        FROM signal_analytics
        WHERE outcome IN ('WIN', 'LOSS')
        ORDER BY timestamp DESC
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        logger.info(f"✅ Loaded {len(df)} signal outcomes")
        
        if len(df) < min_samples:
            logger.warning(f"⚠️  Insufficient data: {len(df)} samples (need {min_samples})")
            logger.info("Generate more signals with: python scripts/generate_ml_training_data.py --days 90")
            return None, None
        
    except Exception as e:
        logger.error(f"❌ Failed to load data: {e}")
        import traceback
        traceback.print_exc()
        return None, None
    
    # ========================================================================
    # STEP 2: Feature Engineering
    # ========================================================================
    logger.info("")
    logger.info("[2/5] Engineering features...")
    
    try:
        # Time-based features
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['minute'] = pd.to_datetime(df['timestamp']).dt.minute
        df['time_of_day'] = df['hour'] * 60 + df['minute']
        
        # Direction encoding
        df['is_bullish'] = (df['direction'] == 'BULLISH').astype(int)
        
        # Pattern type encoding
        df['has_fvg'] = df['pattern_type'].str.contains('FVG', na=False).astype(int)
        
        # Target variable (1 = WIN, 0 = LOSS)
        df['target'] = (df['outcome'] == 'WIN').astype(int)
        
        # Feature list
        features = [
            'confidence',
            'volume_ratio',
            'time_of_day',
            'is_bullish',
            'has_fvg'
        ]
        
        # Handle missing values
        for col in features:
            if df[col].isnull().any():
                df[col].fillna(df[col].median(), inplace=True)
        
        logger.info(f"✅ Engineered {len(features)} features")
        logger.info(f"   Features: {', '.join(features)}")
        
    except Exception as e:
        logger.error(f"❌ Feature engineering failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None
    
    # ========================================================================
    # STEP 3: Train/Test Split
    # ========================================================================
    logger.info("")
    logger.info("[3/5] Splitting data...")
    
    X = df[features].values
    y = df['target'].values
    
    # Check class balance
    n_wins = sum(y)
    n_losses = len(y) - n_wins
    win_rate = n_wins / len(y)
    
    logger.info(f"   Total samples: {len(y)}")
    logger.info(f"   Wins: {n_wins} ({win_rate:.1%})")
    logger.info(f"   Losses: {n_losses} ({1-win_rate:.1%})")
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    logger.info(f"✅ Train: {len(X_train)}, Test: {len(X_test)}")
    
    # ========================================================================
    # STEP 4: Train Model
    # ========================================================================
    logger.info("")
    logger.info("[4/5] Training Random Forest model...")
    
    try:
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            class_weight='balanced',
            n_jobs=-1
        )
        
        model.fit(X_train, y_train)
        logger.info("✅ Model trained successfully")
        
    except Exception as e:
        logger.error(f"❌ Training failed: {e}")
        return None, None
    
    # ========================================================================
    # STEP 5: Evaluate Model
    # ========================================================================
    logger.info("")
    logger.info("[5/5] Evaluating model performance...")
    
    try:
        # Predictions
        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        
        # Metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        tn, fp, fn, tp = cm.ravel()
        
        # Cross-validation
        cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
        
        # Feature importance
        feature_importance = dict(zip(features, model.feature_importances_))
        sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
        
        # Win rate on predicted wins
        predicted_wins = y_pred == 1
        if predicted_wins.sum() > 0:
            predicted_win_rate = y_test[predicted_wins].sum() / predicted_wins.sum()
        else:
            predicted_win_rate = 0
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("MODEL PERFORMANCE")
        logger.info("=" * 80)
        logger.info(f"Accuracy:           {accuracy:.1%}")
        logger.info(f"Precision:          {precision:.1%}")
        logger.info(f"Recall:             {recall:.1%}")
        logger.info(f"CV Score:           {cv_scores.mean():.1%} (+/- {cv_scores.std():.1%})")
        logger.info(f"")
        logger.info(f"Win Rate (predicted winners): {predicted_win_rate:.1%}")
        logger.info(f"")
        logger.info("Confusion Matrix:")
        logger.info(f"  True Negatives:  {tn}")
        logger.info(f"  False Positives: {fp}")
        logger.info(f"  False Negatives: {fn}")
        logger.info(f"  True Positives:  {tp}")
        logger.info("")
        logger.info("Feature Importance:")
        for feat, importance in sorted_features:
            logger.info(f"  {feat:20s}: {importance:.3f}")
        logger.info("=" * 80)
        
        # Metrics dictionary
        metrics = {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'predicted_win_rate': predicted_win_rate,
            'confusion_matrix': cm.tolist(),
            'feature_importance': dict(sorted_features),
            'n_train': len(X_train),
            'n_test': len(X_test),
            'trained_at': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return model, {}
    
    # ========================================================================
    # Save Model
    # ========================================================================
    logger.info("")
    logger.info("Saving model...")
    
    try:
        # Create models directory if it doesn't exist
        os.makedirs(MODEL_DIR, exist_ok=True)
        
        # Save model with metadata
        model_data = {
            'model': model,
            'features': features,
            'metrics': metrics,
            'trained_at': datetime.now().isoformat(),
            'version': '1.0'
        }
        
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"✅ Model saved to: {MODEL_PATH}")
        
    except Exception as e:
        logger.error(f"⚠️  Failed to save model: {e}")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("✅ TRAINING COMPLETE")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Deploy to War Machine (model auto-loads on restart)")
    logger.info("2. Monitor ML-boosted signals in Discord")
    logger.info("3. Retrain weekly as more live data accumulates")
    logger.info("")
    
    return model, metrics


def load_model():
    """
    Load trained model from disk.
    
    Returns:
        dict: Model data with 'model', 'features', 'metrics'
    """
    if not os.path.exists(MODEL_PATH):
        return None
    
    try:
        model_data = joblib.load(MODEL_PATH)
        return model_data
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        return None


if __name__ == "__main__":
    model, metrics = train_model(min_samples=100)
    
    if model is None:
        sys.exit(1)
    else:
        sys.exit(0)
