#!/usr/bin/env python3
"""
Signal Outcomes CSV Inspector
Analyzes signal_outcomes.csv to understand available features for ML training.
"""
import pandas as pd
import numpy as np
from datetime import datetime

print("\n" + "="*80)
print("SIGNAL OUTCOMES DATA INSPECTION - Task 4")
print("="*80)

try:
    # Load the CSV
    df = pd.read_csv('signal_outcomes.csv')
    
    print(f"\n📊 Dataset Overview:")
    print(f"  Total Records: {len(df):,}")
    print(f"  Total Columns: {len(df.columns)}")
    print(f"  Memory Usage: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
    
    # Column analysis
    print(f"\n📋 Columns ({len(df.columns)}):")
    print("-" * 80)
    for col in df.columns:
        dtype = df[col].dtype
        null_count = df[col].isnull().sum()
        null_pct = (null_count / len(df)) * 100
        unique_vals = df[col].nunique()
        
        print(f"  • {col:25} {str(dtype):15} {null_count:>6} nulls ({null_pct:>5.1f}%)  {unique_vals:>6} unique")
    
    # Target variable analysis (if exists)
    print(f"\n🎯 Target Variable Analysis:")
    print("-" * 80)
    
    target_candidates = ['win', 'outcome', 'success', 'hit_target', 'profitable', 'result']
    target_col = None
    
    for candidate in target_candidates:
        if candidate in df.columns:
            target_col = candidate
            break
    
    if target_col:
        print(f"  Target Column: {target_col}")
        print(f"\n  Distribution:")
        value_counts = df[target_col].value_counts()
        for val, count in value_counts.items():
            pct = (count / len(df)) * 100
            print(f"    {val}: {count:>6} ({pct:>5.1f}%)")
        
        # Win rate
        if df[target_col].dtype in ['int64', 'bool'] or set(df[target_col].dropna().unique()).issubset({0, 1, True, False}):
            win_rate = df[target_col].mean() * 100
            print(f"\n  ✅ Win Rate: {win_rate:.1f}%")
    else:
        print("  ⚠️  No obvious target column found")
        print("  Available columns:", ', '.join(df.columns.tolist()))
    
    # Feature categories
    print(f"\n🔍 Feature Categories:")
    print("-" * 80)
    
    feature_categories = {
        'Technical': ['fvg_size', 'bos_strength', 'volume', 'rvol', 'candle', 'pattern'],
        'Pricing': ['entry', 'stop', 'target', 't1', 't2', 'exit', 'price'],
        'Performance': ['pnl', 'rr', 'return', 'profit', 'loss'],
        'Classification': ['grade', 'confidence', 'score', 'quality'],
        'Context': ['ticker', 'direction', 'timeframe', 'time', 'hour'],
        'Confirmation': ['vwap', 'institutional', 'prev_day', 'options', 'confirm'],
    }
    
    found_features = {}
    for category, keywords in feature_categories.items():
        matches = [col for col in df.columns if any(kw in col.lower() for kw in keywords)]
        if matches:
            found_features[category] = matches
            print(f"\n  {category} Features ({len(matches)}):")
            for col in matches:
                print(f"    • {col}")
    
    # Sample data
    print(f"\n📄 Sample Data (first 3 rows):")
    print("-" * 80)
    print(df.head(3).to_string())
    
    # Statistics
    print(f"\n📊 Numeric Column Statistics:")
    print("-" * 80)
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        stats = df[numeric_cols].describe()
        print(stats.to_string())
    
    # Categorical analysis
    print(f"\n📋 Categorical Features:")
    print("-" * 80)
    
    categorical_cols = df.select_dtypes(include=['object']).columns
    for col in categorical_cols[:10]:  # First 10 categorical columns
        unique_count = df[col].nunique()
        if unique_count <= 20:  # Only show if reasonable number of categories
            print(f"\n  {col} ({unique_count} categories):")
            value_counts = df[col].value_counts().head(10)
            for val, count in value_counts.items():
                pct = (count / len(df)) * 100
                print(f"    {val}: {count:>6} ({pct:>5.1f}%)")
    
    # ML Readiness Assessment
    print(f"\n" + "="*80)
    print("ML FEATURE READINESS")
    print("="*80)
    
    ml_features = {
        'Target Variable': target_col is not None,
        'Technical Features': 'Technical' in found_features,
        'Classification Features': 'Classification' in found_features,
        'Context Features': 'Context' in found_features,
        'Performance Metrics': 'Performance' in found_features,
        'Sufficient Records': len(df) >= 1000,
        'Low Missing Data': (df.isnull().sum().sum() / (len(df) * len(df.columns))) < 0.1
    }
    
    print(f"\n✅ ML Requirements:")
    for requirement, met in ml_features.items():
        emoji = "✅" if met else "❌"
        print(f"  {emoji} {requirement}")
    
    all_ready = all(ml_features.values())
    
    if all_ready:
        print(f"\n🎉 Dataset is READY for ML training!")
        print(f"\nRecommended next steps:")
        print(f"  1. Feature engineering: Extract/engineer features from available columns")
        print(f"  2. Train/test split: 80/20 with chronological ordering")
        print(f"  3. Model selection: RandomForest or XGBoost classifier")
        print(f"  4. Evaluation: ROC-AUC, precision, recall, F1-score")
        print(f"  5. Feature importance: Identify key predictors")
    else:
        print(f"\n⚠️  Dataset needs preparation")
        missing = [req for req, met in ml_features.items() if not met]
        print(f"\nMissing requirements:")
        for req in missing:
            print(f"  • {req}")
    
    # Save summary
    summary = {
        'total_records': len(df),
        'total_columns': len(df.columns),
        'target_column': target_col,
        'feature_categories': {k: len(v) for k, v in found_features.items()},
        'win_rate': win_rate if target_col else None,
        'ml_ready': all_ready
    }
    
    import json
    with open('signal_outcomes_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n💾 Summary saved to: signal_outcomes_summary.json")
    
except FileNotFoundError:
    print("\n❌ Error: signal_outcomes.csv not found in current directory")
    print("\nSearching for CSV files...")
    import glob
    csv_files = glob.glob('*.csv')
    if csv_files:
        print(f"\nFound {len(csv_files)} CSV files:")
        for f in csv_files[:10]:
            print(f"  • {f}")
    else:
        print("  No CSV files found in current directory")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80 + "\n")
