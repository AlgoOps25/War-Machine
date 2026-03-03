#!/usr/bin/env python3
"""
ML Signal Scorer - Task 4: ML-Based Signal Quality Prediction

Trains RandomForest classifier on historical signal outcomes to predict
win probability in real-time. Integrates with existing confidence scoring.

Usage:
    # Training mode
    python ml_signal_scorer.py --train
    
    # Test prediction
    python ml_signal_scorer.py --test
"""

import os
import json
import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Tuple, Optional
from pathlib import Path

# ML imports
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        classification_report, 
        confusion_matrix, 
        roc_auc_score,
        precision_recall_curve
    )
    from sklearn.preprocessing import LabelEncoder
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️  scikit-learn not installed. Run: pip install scikit-learn")


# ============================================================================
# CONFIGURATION
# ============================================================================

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "signal_scorer_rf.pkl"
ENCODERS_PATH = MODEL_DIR / "label_encoders.pkl"
FEATURE_IMPORTANCE_PATH = MODEL_DIR / "feature_importance.json"
MODEL_METADATA_PATH = MODEL_DIR / "model_metadata.json"

# Training parameters
RANDOM_STATE = 42
TEST_SIZE = 0.2
N_ESTIMATORS = 100
MAX_DEPTH = 10
MIN_SAMPLES_SPLIT = 50
MIN_SAMPLES_LEAF = 20

# Minimum confidence threshold for signal acceptance
MIN_WIN_PROBABILITY = 0.40  # Block signals with <40% predicted win rate
# ============================================================================
# FEATURE ENGINEERING
# ============================================================================

def engineer_features(df: pd.DataFrame, fit_encoders: bool = True) -> Tuple[pd.DataFrame, Dict]:
    """
    Engineer ML features from raw signal data.
    
    Args:
        df: DataFrame with signal outcomes
        fit_encoders: If True, fit new encoders. If False, use existing.
    
    Returns:
        (DataFrame with engineered features, dict of encoders)
    """
    print("\n🔧 Engineering features...")
    
    # Create copy to avoid modifying original
    df = df.copy()
    
    # 1. Target variable: Convert outcome to binary (1=win, 0=loss)
    df['win'] = (df['outcome'] == 'REVERSAL').astype(int)
    
    # 2. Encode categorical variables
    if fit_encoders:
        le_ticker = LabelEncoder()
        le_signal = LabelEncoder()
        le_time = LabelEncoder()
        
        df['ticker_encoded'] = le_ticker.fit_transform(df['ticker'])
        df['signal_type_encoded'] = le_signal.fit_transform(df['signal_type'])
        df['time_bucket_encoded'] = le_time.fit_transform(df['time_bucket'])
        
        encoders = {
            'ticker': le_ticker,
            'signal_type': le_signal,
            'time_bucket': le_time
        }
    else:
        # Load existing encoders
        with open(ENCODERS_PATH, 'rb') as f:
            encoders = pickle.load(f)
        
        df['ticker_encoded'] = encoders['ticker'].transform(df['ticker'])
        df['signal_type_encoded'] = encoders['signal_type'].transform(df['signal_type'])
        df['time_bucket_encoded'] = encoders['time_bucket'].transform(df['time_bucket'])
    
    # 3. Risk/Reward features
    df['risk_atr_ratio'] = df['risk'] / (df['atr'] + 0.001)  # Avoid div by zero
    df['risk_pct'] = df['risk'] / df['entry'] * 100
    
    # 4. Volume features
    df['volume_ratio_log'] = np.log1p(df['volume_ratio'])  # Log transform
    df['is_high_volume'] = (df['volume_ratio'] > df['volume_ratio'].quantile(0.75)).astype(int)
    
    # 5. Time features (extract hour from timestamp)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['minute'] = df['timestamp'].dt.minute
    df['is_first_hour'] = (df['hour'] < 11).astype(int)
    df['is_power_hour'] = (df['hour'] >= 15).astype(int)
    
    # 6. Confidence features
    df['confidence_squared'] = df['confidence'] ** 2
    df['is_high_confidence'] = (df['confidence'] >= 95).astype(int)
    
    # 7. Historical ticker performance (rolling win rate)
    # Calculate per-ticker win rate up to current point (walk-forward)
    df = df.sort_values('timestamp')
    df['ticker_win_rate'] = df.groupby('ticker')['win'].transform(
        lambda x: x.expanding().mean().shift(1)  # shift(1) prevents lookahead
    ).fillna(0.5)  # Default to 50% for first occurrence
    
    # 8. Time bucket performance
    df['time_bucket_win_rate'] = df.groupby('time_bucket')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    # 9. Signal type performance (BUY vs SELL)
    df['signal_type_win_rate'] = df.groupby('signal_type')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    print(f"  ✅ Engineered {len(df.columns)} total features")
    
    return df, encoders


def select_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Select features for ML model training.
    
    Returns:
        X: Feature matrix
        y: Target vector
    """
    feature_columns = [
        # Raw features
        'risk',
        'atr',
        'volume_ratio',
        'confidence',
        
        # Encoded categoricals
        'ticker_encoded',
        'signal_type_encoded',
        'time_bucket_encoded',
        
        # Engineered features
        'risk_atr_ratio',
        'risk_pct',
        'volume_ratio_log',
        'is_high_volume',
        'hour',
        'minute',
        'is_first_hour',
        'is_power_hour',
        'confidence_squared',
        'is_high_confidence',
        
        # Historical performance
        'ticker_win_rate',
        'time_bucket_win_rate',
        'signal_type_win_rate',
    ]
    
    X = df[feature_columns]
    y = df['win']
    
    return X, y
# ============================================================================
# MODEL TRAINING
# ============================================================================

def train_model(data_path: str = 'signal_outcomes.csv') -> Dict:
    """
    Train RandomForest classifier on historical signal data.
    
    Args:
        data_path: Path to signal outcomes CSV
    
    Returns:
        Dictionary with training results and metrics
    """
    if not SKLEARN_AVAILABLE:
        raise ImportError("scikit-learn required for training")
    
    print("\n" + "="*80)
    print("ML SIGNAL SCORER - TRAINING MODE")
    print("="*80)
    
    # Load data
    print(f"\n📂 Loading data from {data_path}...")
    df = pd.read_csv(data_path)
    print(f"  ✅ Loaded {len(df):,} signals")
    
    # Engineer features
    df, encoders = engineer_features(df, fit_encoders=True)
    
    # Save encoders for prediction
    with open(ENCODERS_PATH, 'wb') as f:
        pickle.dump(encoders, f)
    print(f"  ✅ Saved encoders to {ENCODERS_PATH}")
    
    # Select features
    X, y = select_features(df)
    
    print(f"\n📊 Feature matrix shape: {X.shape}")
    print(f"  Features: {X.shape[1]}")
    print(f"  Samples: {X.shape[0]:,}")
    
    # Check for NaN/Inf
    if X.isnull().any().any():
        print("\n⚠️  Found NaN values, filling with median...")
        X = X.fillna(X.median())
    
    if np.isinf(X.values).any():
        print("\n⚠️  Found Inf values, clipping...")
        X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())
    
    # Train/test split (chronological to prevent lookahead)
    print(f"\n🔀 Splitting data (test_size={TEST_SIZE})...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, shuffle=False  # No shuffle!
    )
    
    print(f"  Train: {len(X_train):,} samples ({y_train.mean()*100:.1f}% wins)")
    print(f"  Test:  {len(X_test):,} samples ({y_test.mean()*100:.1f}% wins)")
    
    # Train model
    print(f"\n🤖 Training RandomForest classifier...")
    print(f"  n_estimators: {N_ESTIMATORS}")
    print(f"  max_depth: {MAX_DEPTH}")
    print(f"  min_samples_split: {MIN_SAMPLES_SPLIT}")
    print(f"  min_samples_leaf: {MIN_SAMPLES_LEAF}")
    
    model = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        min_samples_split=MIN_SAMPLES_SPLIT,
        min_samples_leaf=MIN_SAMPLES_LEAF,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        class_weight='balanced'  # Handle class imbalance
    )
    
    model.fit(X_train, y_train)
    print("  ✅ Training complete!")
    
    # Evaluate on test set
    print("\n📊 Evaluating on test set...")
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    
    # Metrics
    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test)
    roc_auc = roc_auc_score(y_test, y_pred_proba)
    
    print(f"\n🎯 Model Performance:")
    print(f"  Train Accuracy: {train_score*100:.2f}%")
    print(f"  Test Accuracy:  {test_score*100:.2f}%")
    print(f"  ROC-AUC Score:  {roc_auc:.4f}")
    
    print(f"\n📋 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=['Loss', 'Win']))
    
    print(f"\n🔢 Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  True Negatives:  {cm[0,0]:>5}")
    print(f"  False Positives: {cm[0,1]:>5}")
    print(f"  False Negatives: {cm[1,0]:>5}")
    print(f"  True Positives:  {cm[1,1]:>5}")
    
    # Feature importance
    print(f"\n⭐ Top 10 Feature Importance:")
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    for idx, row in feature_importance.head(10).iterrows():
        print(f"  {row['feature']:30} {row['importance']:.4f}")
    
    # Save model
    print(f"\n💾 Saving model to {MODEL_PATH}...")
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model, f)
    
    # Save feature importance
    feature_importance.to_json(FEATURE_IMPORTANCE_PATH, orient='records', indent=2)
    
    # Save metadata
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'n_samples': len(df),
        'n_features': X.shape[1],
        'train_accuracy': float(train_score),
        'test_accuracy': float(test_score),
        'roc_auc': float(roc_auc),
        'baseline_win_rate': float(y.mean()),
        'feature_columns': X.columns.tolist()
    }
    
    with open(MODEL_METADATA_PATH, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print("  ✅ Model saved successfully!")
    
    print("\n" + "="*80 + "\n")
    
    return metadata
# ============================================================================
# PREDICTION (REAL-TIME)
# ============================================================================

# Global model cache
_model = None
_metadata = None
_encoders = None


def load_model():
    """Load trained model from disk (cached)."""
    global _model, _metadata, _encoders
    
    if _model is not None:
        return _model, _metadata, _encoders
    
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found at {MODEL_PATH}. Run training first: "
            f"python ml_signal_scorer.py --train"
        )
    
    with open(MODEL_PATH, 'rb') as f:
        _model = pickle.load(f)
    
    with open(MODEL_METADATA_PATH, 'r') as f:
        _metadata = json.load(f)
    
    with open(ENCODERS_PATH, 'rb') as f:
        _encoders = pickle.load(f)
    
    print(f"[ML] ✅ Loaded model trained on {_metadata['n_samples']:,} samples")
    print(f"[ML]    Test accuracy: {_metadata['test_accuracy']*100:.2f}%, ROC-AUC: {_metadata['roc_auc']:.4f}")
    
    return _model, _metadata, _encoders


def predict_win_probability(
    ticker: str,
    signal_type: str,
    entry: float,
    stop: float,
    confidence: float,
    volume_ratio: float,
    atr: float,
    timestamp: Optional[datetime] = None,
    time_bucket: str = "MIDDAY (10:30-15:00)",
    ticker_win_rate: float = 0.5,
    time_bucket_win_rate: float = 0.5,
    signal_type_win_rate: float = 0.5
) -> float:
    """
    Predict win probability for a real-time signal.
    
    Returns:
        win_probability (0.0 to 1.0)
    """
    if not SKLEARN_AVAILABLE:
        return confidence / 100.0  # Fallback
    
    try:
        model, metadata, encoders = load_model()
    except FileNotFoundError as e:
        print(f"[ML] ⚠️  {e}")
        return confidence / 100.0  # Fallback
    
    # Prepare features
    if timestamp is None:
        timestamp = datetime.now()
    
    risk = abs(stop - entry)
    
    # Encode categoricals
    try:
        ticker_encoded = encoders['ticker'].transform([ticker])[0]
    except:
        ticker_encoded = 0  # Unknown ticker
    
    try:
        signal_type_encoded = encoders['signal_type'].transform([signal_type])[0]
    except:
        signal_type_encoded = 0
    
    try:
        time_bucket_encoded = encoders['time_bucket'].transform([time_bucket])[0]
    except:
        time_bucket_encoded = 2  # Default to midday
    
    # Engineer features
    risk_atr_ratio = risk / (atr + 0.001)
    risk_pct = risk / entry * 100
    volume_ratio_log = np.log1p(volume_ratio)
    is_high_volume = 1 if volume_ratio > 5.97 else 0  # 75th percentile from training
    hour = timestamp.hour
    minute = timestamp.minute
    is_first_hour = 1 if hour < 11 else 0
    is_power_hour = 1 if hour >= 15 else 0
    confidence_squared = confidence ** 2
    is_high_confidence = 1 if confidence >= 95 else 0
    
    # Build feature vector
    features = pd.DataFrame([{
        'risk': risk,
        'atr': atr,
        'volume_ratio': volume_ratio,
        'confidence': confidence,
        'ticker_encoded': ticker_encoded,
        'signal_type_encoded': signal_type_encoded,
        'time_bucket_encoded': time_bucket_encoded,
        'risk_atr_ratio': risk_atr_ratio,
        'risk_pct': risk_pct,
        'volume_ratio_log': volume_ratio_log,
        'is_high_volume': is_high_volume,
        'hour': hour,
        'minute': minute,
        'is_first_hour': is_first_hour,
        'is_power_hour': is_power_hour,
        'confidence_squared': confidence_squared,
        'is_high_confidence': is_high_confidence,
        'ticker_win_rate': ticker_win_rate,
        'time_bucket_win_rate': time_bucket_win_rate,
        'signal_type_win_rate': signal_type_win_rate,
    }])
    
    # Predict
    win_prob = model.predict_proba(features)[0, 1]
    
    return float(win_prob)


# ============================================================================
# CLI
# ============================================================================

def test_prediction():
    """Test prediction with sample data."""
    print("\n🧪 Testing ML prediction...")
    
    # Sample signal
    win_prob = predict_win_probability(
        ticker='AAPL',
        signal_type='BUY',
        entry=215.50,
        stop=215.20,
        confidence=95,
        volume_ratio=4.5,
        atr=0.25,
        timestamp=datetime(2025, 12, 1, 10, 30)
    )
    
    print(f"\n✅ Sample prediction: {win_prob*100:.1f}% win probability")
    print(f"   Verdict: {'🟢 TAKE' if win_prob >= MIN_WIN_PROBABILITY else '🔴 SKIP'}")


if __name__ == "__main__":
    import sys
    
    if '--train' in sys.argv:
        train_model()
    elif '--test' in sys.argv:
        test_prediction()
    else:
        print("Usage:")
        print("  python ml_signal_scorer.py --train   # Train model")
        print("  python ml_signal_scorer.py --test    # Test prediction")
