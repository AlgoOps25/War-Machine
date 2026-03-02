"""
Training script for ML Confidence Booster - Fixed for local execution.
"""

import sys
import os

# Fix import path
if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict
import sqlite3

# Try to import from app structure, fallback to local
try:
    from app.ml.ml_confidence_boost import MLConfidenceBooster
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app', 'ml'))
    from ml_confidence_boost import MLConfidenceBooster

DB_PATH = "marketmemory.db"

def get_connection(db_path):
    return sqlite3.connect(db_path)

def dict_cursor_helper(conn):
    conn.row_factory = sqlite3.Row
    return conn.cursor()

def load_trade_logs() -> pd.DataFrame:
    print("[TRAIN] Loading trade logs from database...")

    try:
        conn = get_connection(DB_PATH)
        cursor = dict_cursor_helper(conn)

        # Check if trade_logs table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_logs'")
        if not cursor.fetchone():
            print("[TRAIN] ❌ No trade_logs table found in database")
            print("[TRAIN] Run War Machine to start accumulating trade logs")
            conn.close()
            return pd.DataFrame()

        query = """
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

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("[TRAIN] No trade logs found - cannot train model")
            return pd.DataFrame()

        df = pd.DataFrame([dict(row) for row in rows])
        print(f"[TRAIN] Loaded {len(df)} historical trades")
        return df

    except Exception as e:
        print(f"[TRAIN] Error loading trade logs: {e}")
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

    if 'pdh' in df.columns and 'pdl' in df.columns and 'entry_price' in df.columns:
        features['pdh_distance_pct'] = ((df['entry_price'] - df['pdh']) / df['pdh'] * 100).fillna(0)
        features['pdl_distance_pct'] = ((df['entry_price'] - df['pdl']) / df['pdl'] * 100).fillna(0)
        features['pd_range_pct'] = ((df['pdh'] - df['pdl']) / df['pdl'] * 100).fillna(0)

    if 'or_high' in df.columns and 'or_low' in df.columns and 'entry_price' in df.columns:
        features['or_breakout_size_pct'] = ((df['entry_price'] - df['or_high']) / df['or_high'] * 100).fillna(0)
        features['or_range_pct'] = ((df['or_high'] - df['or_low']) / df['or_low'] * 100).fillna(0)

    features['vix_level'] = df.get('vix_level', 15.0).fillna(15.0)

    if 'signal_type' in df.columns:
        signal_dummies = pd.get_dummies(df['signal_type'], prefix='signal')
        features = pd.concat([features, signal_dummies], axis=1)

    features = features.fillna(0)
    print(f"[TRAIN] Extracted {len(features.columns)} features")
    return features

def extract_labels(df: pd.DataFrame) -> pd.Series:
    if 'win' in df.columns:
        return df['win'].astype(int)
    elif 'pnl' in df.columns:
        return (df['pnl'] > 0).astype(int)
    else:
        raise ValueError("No 'win' or 'pnl' column found")

def main():
    print("[TRAIN] ========== ML Confidence Booster Training ==========")
    print(f"[TRAIN] Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    df = load_trade_logs()

    if df.empty:
        print("[TRAIN] ❌ No trade logs available")
        print("[TRAIN] System will use default confidence (no ML adjustment)")
        return

    if len(df) < 50:
        print(f"[TRAIN] ⚠️  Insufficient data: {len(df)}/50 samples needed")
        print(f"[TRAIN] Need {50 - len(df)} more trade logs")
        return

    try:
        X = extract_features(df)
        y = extract_labels(df)
        print(f"[TRAIN] Label distribution: {y.value_counts().to_dict()}")

        booster = MLConfidenceBooster()
        metrics = booster.train(X, y, test_size=0.25)
        booster.save_model()

        print("[TRAIN] ========== Training Complete ==========")
        print(f"[TRAIN] ✅ Metrics: {metrics}")
        print("[TRAIN] Model saved to: app/models/confidence_booster.pkl")

    except Exception as e:
        print(f"[TRAIN] ❌ Training failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()