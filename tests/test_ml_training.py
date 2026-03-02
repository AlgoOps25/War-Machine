"""Test script for ML training with fixed imports."""

import sys
import os

# Fix import path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sqlite3

try:
    from app.ml.ml_confidence_boost import MLConfidenceBooster
except ImportError as e:
    print(f"Import error: {e}")
    print(f"Current path: {sys.path}")
    sys.exit(1)

DB_PATH = "marketmemory.db"

def get_connection(db_path):
    return sqlite3.connect(db_path)

def dict_cursor_helper(conn):
    conn.row_factory = sqlite3.Row
    return conn.cursor()

def load_trade_logs() -> pd.DataFrame:
    print("[TEST] Loading trade logs from database...")
    
    try:
        conn = get_connection(DB_PATH)
        cursor = dict_cursor_helper(conn)
        
        # Check if trade_logs table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_logs'")
        if not cursor.fetchone():
            print("[TEST] ❌ No trade_logs table found in database")
            conn.close()
            return pd.DataFrame()
        
        query = """
            SELECT * FROM trade_logs
            WHERE entry_time >= datetime('now', '-90 days')
            ORDER BY entry_time DESC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("[TEST] No trade logs found")
            return pd.DataFrame()
        
        df = pd.DataFrame([dict(row) for row in rows])
        print(f"[TEST] Loaded {len(df)} trades")
        print(f"[TEST] Columns: {list(df.columns)}")
        return df
    
    except Exception as e:
        print(f"[TEST] Error: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    features = pd.DataFrame()
    
    if 'entry_time' in df.columns:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        features['hour_of_day'] = df['entry_time'].dt.hour
        features['day_of_week'] = df['entry_time'].dt.dayofweek
    
    features['time_since_open_min'] = df.get('time_since_open_min', 0).fillna(0)
    features['gap_pct'] = df.get('gap_pct', 0.0).fillna(0.0)
    features['gap_abs'] = features['gap_pct'].abs()
    features['gap_direction'] = (features['gap_pct'] > 0).astype(int)
    features['entry_volume'] = df.get('entry_volume', 0).fillna(0)
    features['volume_surge_ratio'] = df.get('volume_surge_ratio', 1.0).fillna(1.0)
    features['or_volume'] = df.get('or_volume', 0).fillna(0)
    features['volume_log'] = np.log1p(features['entry_volume'])
    features['price_vs_pdh'] = df.get('price_vs_pdh', 0.0).fillna(0.0)
    features['price_vs_or_high'] = df.get('price_vs_or_high', 0.0).fillna(0.0)
    features['vix_level'] = df.get('vix_level', 15.0).fillna(15.0)
    
    if 'pdh' in df.columns and 'pdl' in df.columns and 'entry_price' in df.columns:
        features['pdh_distance_pct'] = ((df['entry_price'] - df['pdh']) / df['pdh'] * 100).fillna(0)
        features['pdl_distance_pct'] = ((df['entry_price'] - df['pdl']) / df['pdl'] * 100).fillna(0)
        features['pd_range_pct'] = ((df['pdh'] - df['pdl']) / df['pdl'] * 100).fillna(0)
    
    if 'or_high' in df.columns and 'or_low' in df.columns and 'entry_price' in df.columns:
        features['or_breakout_size_pct'] = ((df['entry_price'] - df['or_high']) / df['or_high'] * 100).fillna(0)
        features['or_range_pct'] = ((df['or_high'] - df['or_low']) / df['or_low'] * 100).fillna(0)
    
    if 'signal_type' in df.columns:
        signal_dummies = pd.get_dummies(df['signal_type'], prefix='signal')
        features = pd.concat([features, signal_dummies], axis=1)
    
    features = features.fillna(0)
    print(f"[TEST] Extracted {len(features.columns)} features")
    return features

def extract_labels(df: pd.DataFrame) -> pd.Series:
    if 'win' in df.columns:
        return df['win'].astype(int)
    elif 'pnl' in df.columns:
        return (df['pnl'] > 0).astype(int)
    else:
        raise ValueError("No 'win' or 'pnl' column found")

def main():
    print("[TEST] ========== ML Training Test ==========")
    print(f"[TEST] Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[TEST] Working directory: {os.getcwd()}")
    print(f"[TEST] Python path: {sys.path[0]}")
    
    # Test model loading
    print("\n[TEST] Testing model loading...")
    try:
        booster = MLConfidenceBooster()
        print(f"[TEST] ✅ Model class loaded, trained: {booster.is_trained}")
    except Exception as e:
        print(f"[TEST] ❌ Model loading failed: {e}")
        return
    
    # Load data
    print("\n[TEST] Loading trade data...")
    df = load_trade_logs()
    
    if df.empty:
        print("[TEST] ❌ No trade logs available")
        print("[TEST] To test ML training:")
        print("[TEST]   1. Run War Machine to generate trades")
        print("[TEST]   2. Or use the generate_test_trades.py script")
        return
    
    if len(df) < 50:
        print(f"[TEST] ⚠️  Only {len(df)} trades (need 50 minimum)")
        print(f"[TEST] Need {50 - len(df)} more trades to train")
        return
    
    # Extract features
    print("\n[TEST] Extracting features...")
    try:
        X = extract_features(df)
        y = extract_labels(df)
        print(f"[TEST] ✅ Features: {X.shape}")
        print(f"[TEST] ✅ Labels: {y.value_counts().to_dict()}")
    except Exception as e:
        print(f"[TEST] ❌ Feature extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Train
    print("\n[TEST] Starting training...")
    try:
        metrics = booster.train(X, y, test_size=0.25)
        booster.save_model()
        
        print("\n[TEST] ========== Training Complete ==========")
        print(f"[TEST] ✅ Accuracy: {metrics['accuracy']:.3f}")
        print(f"[TEST] ✅ Precision: {metrics['precision']:.3f}")
        print(f"[TEST] ✅ Recall: {metrics['recall']:.3f}")
        print(f"[TEST] ✅ AUC: {metrics['auc']:.3f}")
        print(f"[TEST] Model saved to: app/models/confidence_booster.pkl")
        
    except Exception as e:
        print(f"[TEST] ❌ Training failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
