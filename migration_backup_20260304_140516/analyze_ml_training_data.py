#!/usr/bin/env python3
"""
ML Training Data Analyzer for Task 4
Analyzes available historical data to determine ML model viability.
"""
import os
import json
import glob
from datetime import datetime
from utils import db_connection

print("\n" + "="*80)
print("ML TRAINING DATA ANALYSIS - Task 4: Signal Scoring")
print("="*80)

data_sources = {
    'database_signals': 0,
    'database_trades': 0,
    'backtest_csvs': 0,
    'backtest_jsons': 0,
    'ai_learning_trades': 0,
    'validation_signals': 0
}

# ============================================================================
# 1. DATABASE ANALYSIS
# ============================================================================
print("\n📊 DATABASE ANALYSIS")
print("-" * 80)

try:
    conn = db_connection.get_conn()
    cursor = db_connection.dict_cursor(conn)
    
    # Check for armed_signals table
    try:
        if db_connection.USE_POSTGRES:
            cursor.execute("SELECT COUNT(*) as count FROM armed_signals")
        else:
            cursor.execute("SELECT COUNT(*) as count FROM armed_signals")
        result = cursor.fetchone()
        count = result['count'] if isinstance(result, dict) else result[0]
        data_sources['database_signals'] = count
        print(f"✅ armed_signals: {count:,} records")
        
        # Get date range
        cursor.execute("SELECT MIN(armed_at) as min_date, MAX(armed_at) as max_date FROM armed_signals")
        dates = cursor.fetchone()
        if dates:
            print(f"   Date range: {dates['min_date'] if isinstance(dates, dict) else dates[0]} → {dates['max_date'] if isinstance(dates, dict) else dates[1]}")
    except:
        print("❌ armed_signals table not found")
    
    # Check for trades/outcomes
    try:
        cursor.execute("SELECT COUNT(*) as count FROM trades")
        result = cursor.fetchone()
        count = result['count'] if isinstance(result, dict) else result[0]
        data_sources['database_trades'] = count
        print(f"✅ trades: {count:,} records")
    except:
        try:
            cursor.execute("SELECT COUNT(*) as count FROM trade_outcomes")
            result = cursor.fetchone()
            count = result['count'] if isinstance(result, dict) else result[0]
            data_sources['database_trades'] = count
            print(f"✅ trade_outcomes: {count:,} records")
        except:
            print("❌ No trades/outcomes table found")
    
    conn.close()
    
except Exception as e:
    print(f"⚠️  Database connection error: {e}")

# ============================================================================
# 2. BACKTEST FILE ANALYSIS
# ============================================================================
print("\n💾 BACKTEST FILE ANALYSIS")
print("-" * 80)

# CSV files
csv_files = glob.glob("*.csv") + glob.glob("**/*.csv", recursive=True)
backtest_csvs = [f for f in csv_files if 'backtest' in f.lower() or 'result' in f.lower() or 'signal' in f.lower()]

if backtest_csvs:
    print(f"\n📄 Found {len(backtest_csvs)} backtest CSV files:")
    for csv_file in backtest_csvs[:10]:  # Show first 10
        try:
            with open(csv_file, 'r') as f:
                lines = f.readlines()
                row_count = len(lines) - 1  # Exclude header
                data_sources['backtest_csvs'] += row_count
                file_size = os.path.getsize(csv_file) / 1024  # KB
                print(f"  • {csv_file:50} {row_count:>6} rows, {file_size:>7.1f} KB")
        except Exception as e:
            print(f"  • {csv_file:50} [Error reading: {e}]")
    
    if len(backtest_csvs) > 10:
        print(f"  ... and {len(backtest_csvs) - 10} more files")
else:
    print("❌ No backtest CSV files found")

# JSON files
json_files = glob.glob("*.json") + glob.glob("**/*.json", recursive=True)
backtest_jsons = [f for f in json_files if any(k in f.lower() for k in ['backtest', 'result', 'optimization', 'learning'])]

if backtest_jsons:
    print(f"\n📋 Found {len(backtest_jsons)} backtest JSON files:")
    for json_file in backtest_jsons[:10]:
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                
                # Try to count records
                record_count = 0
                if isinstance(data, list):
                    record_count = len(data)
                elif isinstance(data, dict):
                    if 'trades' in data:
                        record_count = len(data['trades'])
                    elif 'results' in data:
                        record_count = len(data['results'])
                    elif 'signals' in data:
                        record_count = len(data['signals'])
                
                data_sources['backtest_jsons'] += record_count
                file_size = os.path.getsize(json_file) / 1024  # KB
                print(f"  • {json_file:50} {record_count:>6} records, {file_size:>7.1f} KB")
        except Exception as e:
            print(f"  • {json_file:50} [Error: {e}]")
    
    if len(backtest_jsons) > 10:
        print(f"  ... and {len(backtest_jsons) - 10} more files")
else:
    print("❌ No backtest JSON files found")

# ============================================================================
# 3. AI LEARNING STATE
# ============================================================================
print("\n🧠 AI LEARNING ENGINE STATE")
print("-" * 80)

try:
    from app.ai.ai_learning import learning_engine
    
    # Check learning data
    trades_count = len(learning_engine.data.get('trades', []))
    data_sources['ai_learning_trades'] = trades_count
    
    print(f"✅ AI Learning Engine initialized")
    print(f"  • Recorded trades: {trades_count}")
    print(f"  • Pattern performance: {len(learning_engine.data.get('pattern_performance', {}))} grades tracked")
    print(f"  • Ticker performance: {len(learning_engine.data.get('ticker_performance', {}))} tickers tracked")
    
    if trades_count > 0:
        # Show recent trades
        recent_trades = learning_engine.data['trades'][-5:]
        print(f"\n  📊 Recent Trades (last 5):")
        for trade in recent_trades:
            win_emoji = "✅" if trade.get('win') else "❌"
            print(f"    {win_emoji} {trade.get('ticker', 'N/A'):6} {trade.get('direction', 'N/A'):4} "
                  f"Grade: {trade.get('grade', 'N/A'):3} PnL: ${trade.get('pnl', 0):+.2f}")
    else:
        print("\n  ⚠️  No trades recorded yet in AI learning engine")
        
except Exception as e:
    print(f"❌ AI Learning Engine not available: {e}")

# ============================================================================
# 4. SUMMARY & RECOMMENDATIONS
# ============================================================================
print("\n" + "="*80)
print("SUMMARY & ML VIABILITY")
print("="*80)

total_records = sum(data_sources.values())

print(f"\n📊 Total Training Data Available:")
for source, count in data_sources.items():
    emoji = "✅" if count > 0 else "❌"
    print(f"  {emoji} {source:25} {count:>10,} records")

print(f"\n  🏆 TOTAL: {total_records:,} data points\n")

# ML Viability Assessment
print("=" * 80)
print("🧠 ML MODEL VIABILITY ASSESSMENT")
print("=" * 80)

min_required = 100
recommended = 500
ideal = 1000

if total_records >= ideal:
    print(f"\n🎉 EXCELLENT: {total_records:,} records (>= {ideal} ideal)")
    print("   ✅ Ready for full ML model training")
    print("   ✅ Can use train/test/validation split")
    print("   ✅ Sufficient for walk-forward optimization")
    recommendation = "PROCEED_FULL"
elif total_records >= recommended:
    print(f"\n✅ GOOD: {total_records:,} records (>= {recommended} recommended)")
    print("   ✅ Ready for ML model training")
    print("   ⚠️  Use k-fold cross-validation")
    print("   ⚠️  Monitor for overfitting")
    recommendation = "PROCEED_CAUTIOUS"
elif total_records >= min_required:
    print(f"\n⚠️  MINIMAL: {total_records:,} records (>= {min_required} minimum)")
    print("   ⚠️  Can train simple model (logistic regression)")
    print("   ❌ Avoid complex models (random forest, XGBoost)")
    print("   ❌ Risk of overfitting")
    recommendation = "PROCEED_SIMPLE"
else:
    print(f"\n❌ INSUFFICIENT: {total_records:,} records (< {min_required} minimum)")
    print("   ❌ Not enough data for ML training")
    print("   🛠️  Continue with rule-based AI learning engine")
    print("   🛠️  Collect more trade data (aim for 100+ trades)")
    recommendation = "COLLECT_MORE_DATA"

print(f"\n🎯 RECOMMENDATION: {recommendation}")

# Next steps
print("\n" + "="*80)
print("🚀 NEXT STEPS FOR TASK 4")
print("="*80)

if recommendation == "PROCEED_FULL":
    print("\n1. Extract features from armed_signals + outcomes")
    print("2. Build feature engineering pipeline")
    print("3. Train RandomForest or XGBoost classifier")
    print("4. Implement walk-forward validation")
    print("5. Deploy real-time win probability scoring")
elif recommendation == "PROCEED_CAUTIOUS":
    print("\n1. Consolidate data from all sources into single dataset")
    print("2. Build feature extraction module")
    print("3. Start with simple RandomForest model")
    print("4. Use k-fold cross-validation (k=5)")
    print("5. Monitor model performance closely")
elif recommendation == "PROCEED_SIMPLE":
    print("\n1. Merge available data sources")
    print("2. Extract basic features (grade, ticker WR, timeframe)")
    print("3. Train logistic regression model")
    print("4. Use as confidence multiplier (not primary filter)")
    print("5. Continue collecting data for better models")
else:
    print("\n1. Enable trade outcome tracking in sniper.py")
    print("2. Run live trading for 2-4 weeks")
    print("3. Target 100+ completed trades")
    print("4. Re-run this analysis when data >= 100 records")
    print("5. Use rule-based AI learning engine in the meantime")

print("\n" + "="*80 + "\n")
