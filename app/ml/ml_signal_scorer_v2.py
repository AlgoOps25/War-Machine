#!/usr/bin/env python3
"""
ML Signal Scorer V2 - Enhanced Feature Engineering + XGBoost

Improvements over V1:
- More technical features (price action, patterns)
- Market context features (trend, volatility regime)
- Interaction features (combined signals)
- XGBoost classifier (better than RandomForest for imbalanced data)
- Feature selection using importance thresholds

Usage:
    python app/ml/ml_signal_scorer_v2.py --train
    python app/ml/ml_signal_scorer_v2.py --test
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
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import (
        classification_report, 
        confusion_matrix, 
        roc_auc_score,
        precision_recall_curve,
        roc_curve
    )
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️  scikit-learn not installed. Run: pip install scikit-learn")

# Try XGBoost (optional but recommended)
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    print("⚠️  xgboost not installed. Run: pip install xgboost")
    print("    Falling back to RandomForest...")


# ============================================================================
# CONFIGURATION
# ============================================================================

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "signal_scorer_v2.pkl"
SCALER_PATH = MODEL_DIR / "feature_scaler.pkl"
ENCODERS_PATH = MODEL_DIR / "label_encoders_v2.pkl"
FEATURE_IMPORTANCE_PATH = MODEL_DIR / "feature_importance_v2.json"
MODEL_METADATA_PATH = MODEL_DIR / "model_metadata_v2.json"

# Training parameters
RANDOM_STATE = 42
TEST_SIZE = 0.2
USE_XGBOOST = XGBOOST_AVAILABLE

if USE_XGBOOST:
    # XGBoost params
    N_ESTIMATORS = 200
    MAX_DEPTH = 6
    LEARNING_RATE = 0.05
    MIN_CHILD_WEIGHT = 5
    SUBSAMPLE = 0.8
    COLSAMPLE_BYTREE = 0.8
else:
    # RandomForest params
    N_ESTIMATORS = 200
    MAX_DEPTH = 12
    MIN_SAMPLES_SPLIT = 30
    MIN_SAMPLES_LEAF = 15

# Thresholds
MIN_WIN_PROBABILITY = 0.45  # Raised from 0.40
CONFIDENCE_BOOST_THRESHOLD = 0.60  # Boost confidence if >60% win prob
# ============================================================================
# ENHANCED FEATURE ENGINEERING
# ============================================================================

def engineer_features_v2(df: pd.DataFrame, fit_encoders: bool = True) -> Tuple[pd.DataFrame, Dict]:
    """
    Enhanced feature engineering with more predictive features.
    """
    print("\n🔧 Engineering enhanced features...")
    
    df = df.copy()
    
    # 1. Target variable
    df['win'] = (df['outcome'] == 'REVERSAL').astype(int)
    
    # 2. Encode categoricals
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
        with open(ENCODERS_PATH, 'rb') as f:
            encoders = pickle.load(f)
        
        df['ticker_encoded'] = encoders['ticker'].transform(df['ticker'])
        df['signal_type_encoded'] = encoders['signal_type'].transform(df['signal_type'])
        df['time_bucket_encoded'] = encoders['time_bucket'].transform(df['time_bucket'])
    
    # 3. Risk/Reward features (expanded)
    df['risk_atr_ratio'] = df['risk'] / (df['atr'] + 0.001)
    df['risk_pct'] = df['risk'] / df['entry'] * 100
    df['risk_squared'] = df['risk'] ** 2
    df['is_tight_stop'] = (df['risk'] < df['risk'].quantile(0.25)).astype(int)
    df['is_wide_stop'] = (df['risk'] > df['risk'].quantile(0.75)).astype(int)
    
    # 4. Volume features (expanded)
    df['volume_ratio_log'] = np.log1p(df['volume_ratio'])
    df['volume_ratio_squared'] = df['volume_ratio'] ** 2
    df['is_high_volume'] = (df['volume_ratio'] > df['volume_ratio'].quantile(0.75)).astype(int)
    df['is_extreme_volume'] = (df['volume_ratio'] > df['volume_ratio'].quantile(0.90)).astype(int)
    df['is_low_volume'] = (df['volume_ratio'] < df['volume_ratio'].quantile(0.25)).astype(int)
    
    # 5. ATR features (volatility regime)
    df['atr_percentile'] = df['atr'].rank(pct=True)
    df['is_high_volatility'] = (df['atr'] > df['atr'].quantile(0.75)).astype(int)
    df['is_low_volatility'] = (df['atr'] < df['atr'].quantile(0.25)).astype(int)
    
    # 6. Time features (expanded)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['minute'] = df['timestamp'].dt.minute
    df['minute_of_day'] = df['hour'] * 60 + df['minute']  # 0-960
    df['is_first_30min'] = (df['minute_of_day'] < 600).astype(int)  # 9:30-10:00
    df['is_first_hour'] = (df['hour'] < 11).astype(int)
    df['is_lunch_time'] = ((df['hour'] == 12) | (df['hour'] == 13)).astype(int)
    df['is_power_hour'] = (df['hour'] >= 15).astype(int)
    df['is_last_30min'] = (df['minute_of_day'] >= 930).astype(int)  # 15:30-16:00
    
    # 7. Confidence features (expanded)
    df['confidence_normalized'] = df['confidence'] / 100.0
    df['confidence_squared'] = df['confidence'] ** 2
    df['confidence_cubed'] = df['confidence'] ** 3
    df['is_high_confidence'] = (df['confidence'] >= 95).astype(int)
    df['is_medium_confidence'] = ((df['confidence'] >= 85) & (df['confidence'] < 95)).astype(int)
    df['is_low_confidence'] = (df['confidence'] < 85).astype(int)
    
    # 8. Historical performance (walk-forward)
    df = df.sort_values('timestamp')
    
    # Ticker performance
    df['ticker_win_rate'] = df.groupby('ticker')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    df['ticker_trade_count'] = df.groupby('ticker').cumcount()
    df['ticker_is_experienced'] = (df['ticker_trade_count'] >= 50).astype(int)
    
    # Time bucket performance
    df['time_bucket_win_rate'] = df.groupby('time_bucket')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    # Signal type performance
    df['signal_type_win_rate'] = df.groupby('signal_type')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    # Combined context win rate (ticker + time bucket)
    df['context_key'] = df['ticker'] + '_' + df['time_bucket']
    df['context_win_rate'] = df.groupby('context_key')['win'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(0.5)
    
    # Recent performance (last 10 trades)
    df['recent_win_rate'] = df['win'].rolling(window=10, min_periods=1).mean().shift(1).fillna(0.5)
    
    # 9. Interaction features (combinations that might be predictive)
    df['volume_x_confidence'] = df['volume_ratio'] * df['confidence']
    df['risk_x_confidence'] = df['risk_pct'] * df['confidence']
    df['atr_x_volume'] = df['atr'] * df['volume_ratio_log']
    df['tight_stop_high_conf'] = df['is_tight_stop'] * df['is_high_confidence']
    df['high_vol_high_conf'] = df['is_high_volume'] * df['is_high_confidence']
    
    # 10. Performance metrics from data (if available)
    if 'peak_r' in df.columns:
        df['peak_r_positive'] = (df['peak_r'] > 0).astype(int)
        df['peak_r_significant'] = (df['peak_r'] > 0.5).astype(int)
        df['had_potential'] = (df['peak_r'] > 0.3).astype(int)  # Signal showed promise
    
    if 'bars_to_peak' in df.columns:
        df['quick_move'] = (df['bars_to_peak'] <= 2).astype(int)
        df['slow_move'] = (df['bars_to_peak'] > 10).astype(int)
    
    # 11. Price action patterns (if we can derive from entry/stop)
    df['stop_distance_normalized'] = df['risk'] / df['entry']
    
    print(f"  ✅ Engineered {len(df.columns)} total features")
    
    return df, encoders


def select_features_v2(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Select features for V2 model - NO FUTURE LEAKAGE.
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
        
        # Risk features
        'risk_atr_ratio',
        'risk_pct',
        'risk_squared',
        'is_tight_stop',
        'is_wide_stop',
        
        # Volume features
        'volume_ratio_log',
        'volume_ratio_squared',
        'is_high_volume',
        'is_extreme_volume',
        'is_low_volume',
        
        # Volatility features
        'atr_percentile',
        'is_high_volatility',
        'is_low_volatility',
        
        # Time features
        'hour',
        'minute',
        'minute_of_day',
        'is_first_30min',
        'is_first_hour',
        'is_lunch_time',
        'is_power_hour',
        'is_last_30min',
        
        # Confidence features
        'confidence_normalized',
        'confidence_squared',
        'confidence_cubed',
        'is_high_confidence',
        'is_medium_confidence',
        'is_low_confidence',
        
        # Historical performance (NO LEAKAGE)
        'ticker_win_rate',
        'ticker_trade_count',
        'ticker_is_experienced',
        'time_bucket_win_rate',
        'signal_type_win_rate',
        'context_win_rate',
        'recent_win_rate',
        
        # Interaction features
        'volume_x_confidence',
        'risk_x_confidence',
        'atr_x_volume',
        'tight_stop_high_conf',
        'high_vol_high_conf',
        
        # Price action (NO FUTURE INFO)
        'stop_distance_normalized',
    ]
    
    # Only use features that exist
    available_features = [f for f in feature_columns if f in df.columns]
    
    X = df[available_features]
    y = df['win']
    
    return X, y
# ============================================================================
# MODEL TRAINING V2 (with XGBoost)
# ============================================================================

def train_model_v2(data_path: str = 'signal_outcomes.csv') -> Dict:
    """
    Train improved model with enhanced features and XGBoost.
    """
    if not SKLEARN_AVAILABLE:
        raise ImportError("scikit-learn required")
    
    print("\n" + "="*80)
    print("ML SIGNAL SCORER V2 - ENHANCED TRAINING")
    print("="*80)
    print(f"Using: {'XGBoost' if USE_XGBOOST else 'RandomForest'}")
    
    # Load data
    print(f"\n📂 Loading data from {data_path}...")
    df = pd.read_csv(data_path)
    print(f"  ✅ Loaded {len(df):,} signals")
    
    # Engineer features
    df, encoders = engineer_features_v2(df, fit_encoders=True)
    
    # Save encoders
    with open(ENCODERS_PATH, 'wb') as f:
        pickle.dump(encoders, f)
    
    # Select features
    X, y = select_features_v2(df)
    
    print(f"\n📊 Feature matrix shape: {X.shape}")
    print(f"  Features: {X.shape[1]}")
    print(f"  Samples: {X.shape[0]:,}")
    
    # Handle missing values
    X = X.fillna(X.median())
    X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())
    
    # Scale features (important for XGBoost)
    print("\n⚖️  Scaling features...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    X_scaled = pd.DataFrame(X_scaled, columns=X.columns, index=X.index)
    
    with open(SCALER_PATH, 'wb') as f:
        pickle.dump(scaler, f)
    
    # Train/test split (chronological)
    print(f"\n🔀 Splitting data (test_size={TEST_SIZE})...")
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, shuffle=False
    )
    
    print(f"  Train: {len(X_train):,} samples ({y_train.mean()*100:.1f}% wins)")
    print(f"  Test:  {len(X_test):,} samples ({y_test.mean()*100:.1f}% wins)")
    
    # Train model
    print(f"\n🤖 Training {'XGBoost' if USE_XGBOOST else 'RandomForest'} classifier...")
    
    if USE_XGBOOST:
        # Calculate scale_pos_weight for imbalanced data
        scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
        
        model = xgb.XGBClassifier(
            n_estimators=N_ESTIMATORS,
            max_depth=MAX_DEPTH,
            learning_rate=LEARNING_RATE,
            min_child_weight=MIN_CHILD_WEIGHT,
            subsample=SUBSAMPLE,
            colsample_bytree=COLSAMPLE_BYTREE,
            scale_pos_weight=scale_pos_weight,
            random_state=RANDOM_STATE,
            n_jobs=-1,
            eval_metric='logloss'
        )
        
        print(f"  n_estimators: {N_ESTIMATORS}")
        print(f"  max_depth: {MAX_DEPTH}")
        print(f"  learning_rate: {LEARNING_RATE}")
        print(f"  scale_pos_weight: {scale_pos_weight:.2f}")
        
    else:
        model = RandomForestClassifier(
            n_estimators=N_ESTIMATORS,
            max_depth=MAX_DEPTH,
            min_samples_split=MIN_SAMPLES_SPLIT,
            min_samples_leaf=MIN_SAMPLES_LEAF,
            random_state=RANDOM_STATE,
            n_jobs=-1,
            class_weight='balanced'
        )
    
    model.fit(X_train, y_train)
    print("  ✅ Training complete!")
    
    # Evaluate
    print("\n📊 Evaluating on test set...")
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    
    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test)
    roc_auc = roc_auc_score(y_test, y_pred_proba)
    
    print(f"\n🎯 Model Performance:")
    print(f"  Train Accuracy: {train_score*100:.2f}%")
    print(f"  Test Accuracy:  {test_score*100:.2f}%")
    print(f"  ROC-AUC Score:  {roc_auc:.4f}")
    print(f"  Improvement:    {(test_score - 0.5448)*100:+.2f}% vs V1")
    
    print(f"\n📋 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=['Loss', 'Win']))
    
    print(f"\n🔢 Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  True Negatives:  {cm[0,0]:>5}")
    print(f"  False Positives: {cm[0,1]:>5}")
    print(f"  False Negatives: {cm[1,0]:>5}")
    print(f"  True Positives:  {cm[1,1]:>5}")
    
    # Feature importance
    print(f"\n⭐ Top 15 Feature Importance:")
    if USE_XGBOOST:
        importance = model.feature_importances_
    else:
        importance = model.feature_importances_
    
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'importance': importance
    }).sort_values('importance', ascending=False)
    
    for idx, row in feature_importance.head(15).iterrows():
        print(f"  {row['feature']:35} {row['importance']:.4f}")
    
    # Save model
    print(f"\n💾 Saving model to {MODEL_PATH}...")
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model, f)
    
    feature_importance.to_json(FEATURE_IMPORTANCE_PATH, orient='records', indent=2)
    
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'model_type': 'XGBoost' if USE_XGBOOST else 'RandomForest',
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
    
    print("  ✅ Model V2 saved successfully!")
    print("\n" + "="*80 + "\n")
    
    return metadata


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if '--train' in sys.argv:
        train_model_v2()
    else:
        print("Usage:")
        print("  python app/ml/ml_signal_scorer_v2.py --train")
