"""
Training script for ML Confidence Booster.

Workflow:
1. Load trade logs from PostgreSQL/SQLite
2. Load bootstrapped synthetic trades (if available)
3. Merge historical + synthetic datasets
4. Extract features from each trade
5. Train XGBoost classifier
6. Save model + feature importance
7. Run weekly via Railway cron: Sunday 2 AM ET

Usage:
    python train_ml_booster.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict
from app.ml.ml_confidence_boost import MLConfidenceBooster
from app.data.db_connection import get_conn, dict_cursor
from utils import config

def load_trade_logs() -> pd.DataFrame:
    """Load historical trade logs from database."""
    print("[TRAIN] Loading trade logs from database...")
    
    conn = get_conn(config.DB_PATH)
    cursor = dict_cursor(conn)
    
    # Adjust table name based on your schema
    query = """
        SELECT 
            ticker, entry_time, exit_time, entry_price, exit_price,
            pnl, win, hold_minutes, signal_type, 
            entry_volume, pdh, pdl, gap_pct, vix_level,
            time_since_open_min, or_high, or_low, or_volume,
            volume_surge_ratio, price_vs_pdh, price_vs_or_high
        FROM trade_logs
        WHERE entry_time >= NOW() - INTERVAL '90 days'
        ORDER BY entry_time DESC
    """
    
    # SQLite version (adjust if using PostgreSQL)
    query_sqlite = """
        SELECT 
            ticker, entry_time, exit_time, entry_price, exit_price,
            pnl, win, hold_minutes, signal_type,
            entry_volume, pdh, pdl, gap_pct, vix_level,
            time_since_open_min, or_high, or_low, or_volume,
            volume_surge_ratio, price_vs_pdh, price_vs_or_high
        FROM trade_logs
        WHERE entry_time >= datetime('now', '-90 days')
        ORDER BY entry_time DESC
    """
    
    try:
        cursor.execute(query_sqlite)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("[TRAIN] No trade logs found - cannot train model")
            return pd.DataFrame()
        
        df = pd.DataFrame(rows)
        print(f"[TRAIN] Loaded {len(df)} historical trades")
        return df
    
    except Exception as e:
        print(f"[TRAIN] Error loading trade logs: {e}")
        conn.close()
        return pd.DataFrame()

def load_bootstrapped_data() -> pd.DataFrame:
    """Load synthetic bootstrapped trades (if available)."""
    bootstrap_path = "/app/data/bootstrapped_trades.csv"
    
    if not os.path.exists(bootstrap_path):
        print("[TRAIN] No bootstrapped data found - using historical only")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(bootstrap_path)
        print(f"[TRAIN] Loaded {len(df)} bootstrapped trades")
        return df
    except Exception as e:
        print(f"[TRAIN] Error loading bootstrapped data: {e}")
        return pd.DataFrame()

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract ML features from trade log DataFrame.
    
    Initial wide feature set (will prune later by importance):
    - Time features: time_since_open_min, hour_of_day, day_of_week
    - Gap features: gap_pct, gap_direction
    - Volume features: entry_volume, volume_surge_ratio, or_volume_pct
    - Price features: price_vs_pdh, price_vs_pdl, price_vs_or_high, price_vs_or_low
    - Volatility: vix_level, atr_pct, or_range_pct
    - Market structure: pdh_distance, pdl_distance, or_breakout_size
    """
    features = pd.DataFrame()
    
    # Time features
    if 'entry_time' in df.columns:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        features['hour_of_day'] = df['entry_time'].dt.hour
        features['day_of_week'] = df['entry_time'].dt.dayofweek  # 0=Monday
    
    features['time_since_open_min'] = df.get('time_since_open_min', 0)
    
    # Gap features
    features['gap_pct'] = df.get('gap_pct', 0.0)
    features['gap_abs'] = features['gap_pct'].abs()
    features['gap_direction'] = (features['gap_pct'] > 0).astype(int)  # 1=gap up, 0=gap down
    
    # Volume features
    features['entry_volume'] = df.get('entry_volume', 0)
    features['volume_surge_ratio'] = df.get('volume_surge_ratio', 1.0)
    features['or_volume'] = df.get('or_volume', 0)
    features['volume_log'] = np.log1p(features['entry_volume'])
    
    # Price vs key levels
    features['price_vs_pdh'] = df.get('price_vs_pdh', 0.0)
    features['price_vs_or_high'] = df.get('price_vs_or_high', 0.0)
    
    if 'pdh' in df.columns and 'pdl' in df.columns and 'entry_price' in df.columns:
        features['pdh_distance_pct'] = ((df['entry_price'] - df['pdh']) / df['pdh'] * 100).fillna(0)
        features['pdl_distance_pct'] = ((df['entry_price'] - df['pdl']) / df['pdl'] * 100).fillna(0)
        features['pd_range_pct'] = ((df['pdh'] - df['pdl']) / df['pdl'] * 100).fillna(0)
    
    if 'or_high' in df.columns and 'or_low' in df.columns and 'entry_price' in df.columns:
        features['or_breakout_size_pct'] = ((df['entry_price'] - df['or_high']) / df['or_high'] * 100).fillna(0)
        features['or_range_pct'] = ((df['or_high'] - df['or_low']) / df['or_low'] * 100).fillna(0)
    
    # Volatility
    features['vix_level'] = df.get('vix_level', 15.0)
    
    # Signal type (one-hot encode if categorical)
    if 'signal_type' in df.columns:
        signal_dummies = pd.get_dummies(df['signal_type'], prefix='signal')
        features = pd.concat([features, signal_dummies], axis=1)
    
    # Fill any remaining NaN with 0
    features = features.fillna(0)
    
    print(f"[TRAIN] Extracted {len(features.columns)} features: {list(features.columns)}")
    
    return features

def extract_labels(df: pd.DataFrame) -> pd.Series:
    """
    Extract binary labels from trade logs.
    
    Label = 1 if profitable trade, 0 otherwise.
    """
    if 'win' in df.columns:
        return df['win'].astype(int)
    elif 'pnl' in df.columns:
        return (df['pnl'] > 0).astype(int)
    else:
        raise ValueError("No 'win' or 'pnl' column found for labeling")

def main():
    print("[TRAIN] ========== ML Confidence Booster Training ==========")
    print(f"[TRAIN] Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load data
    df_historical = load_trade_logs()
    df_bootstrap = load_bootstrapped_data()
    
    # Merge datasets
    if not df_bootstrap.empty:
        df = pd.concat([df_historical, df_bootstrap], ignore_index=True)
        print(f"[TRAIN] Combined dataset: {len(df)} trades")
    else:
        df = df_historical
    
    if df.empty or len(df) < 50:
        print("[TRAIN] Insufficient data for training (need at least 50 samples)")
        print("[TRAIN] Skipping training - system will use default confidence")
        return
    
    # Extract features and labels
    X = extract_features(df)
    y = extract_labels(df)
    
    print(f"[TRAIN] Label distribution: {y.value_counts().to_dict()}")
    
    # Train model
    booster = MLConfidenceBooster()
    metrics = booster.train(X, y, test_size=0.25)
    
    # Save model
    booster.save_model()
    
    print("[TRAIN] ========== Training Complete ==========")
    print(f"[TRAIN] Final metrics: {metrics}")
    print(f"[TRAIN] Model saved to: /app/models/confidence_booster.pkl")

if __name__ == "__main__":
    main()
