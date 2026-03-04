#!/usr/bin/env python3
"""
Database Schema Inspector for Task 4: ML-Based Signal Scoring
Investigates existing database structure to determine what trade data is available.
"""
import sys
from utils import db_connection

print("\n" + "="*80)
print("DATABASE SCHEMA INSPECTION - Task 4: ML Signal Scoring")
print("="*80)

print(f"\nDatabase Mode: {'PostgreSQL' if db_connection.USE_POSTGRES else 'SQLite'}")

try:
    conn = db_connection.get_conn()
    cursor = db_connection.dict_cursor(conn)
    
    # Get all tables
    if db_connection.USE_POSTGRES:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        tables = [row['table_name'] for row in cursor.fetchall()]
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row['name'] if isinstance(row, dict) else row[0] for row in cursor.fetchall()]
    
    print(f"\n📊 Found {len(tables)} tables:\n")
    
    # Key tables for ML signal scoring
    ml_relevant_tables = [
        'armed_signals',
        'watching_signals', 
        'trade_outcomes',
        'trades',
        'ai_learning_state',
        'signal_history',
        'positions'
    ]
    
    # Inspect each table
    for table_name in tables:
        is_ml_relevant = table_name in ml_relevant_tables
        emoji = "⭐" if is_ml_relevant else "📁"
        
        print(f"{emoji} {table_name.upper()}")
        print("-" * 80)
        
        # Get schema
        if db_connection.USE_POSTGRES:
            cursor.execute(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            columns = cursor.fetchall()
            
            print(f"  Columns ({len(columns)}):")
            for col in columns:
                nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                print(f"    • {col['column_name']:25} {col['data_type']:15} {nullable}")
        else:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            print(f"  Columns ({len(columns)}):")
            for col in columns:
                if isinstance(col, dict):
                    name, col_type = col['name'], col['type']
                else:
                    col_id, name, col_type, notnull, default, pk = col
                print(f"    • {name:25} {col_type:15}")
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
        result = cursor.fetchone()
        count = result['count'] if isinstance(result, dict) else result[0]
        
        print(f"\n  📈 Row Count: {count:,}")
        
        # If ML-relevant table with data, show sample
        if is_ml_relevant and count > 0:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            samples = cursor.fetchall()
            
            print(f"\n  📋 Sample Data (first 3 rows):")
            for i, row in enumerate(samples, 1):
                print(f"\n    Row {i}:")
                if isinstance(row, dict):
                    for key, value in list(row.items())[:10]:  # First 10 columns only
                        print(f"      {key:20} = {value}")
                    if len(row) > 10:
                        print(f"      ... ({len(row) - 10} more columns)")
        
        print("\n")
    
    conn.close()
    
    # Summary for ML readiness
    print("="*80)
    print("ML READINESS ASSESSMENT")
    print("="*80)
    
    has_armed_signals = 'armed_signals' in tables
    has_trades = 'trades' in tables or 'trade_outcomes' in tables
    has_ai_state = 'ai_learning_state' in tables
    
    print(f"\n✅ Required Tables:")
    print(f"  {'✅' if has_armed_signals else '❌'} armed_signals - Signal features storage")
    print(f"  {'✅' if has_trades else '❌'} trades/trade_outcomes - Win/loss outcomes")
    print(f"  {'✅' if has_ai_state else '❌'} ai_learning_state - ML model storage")
    
    if has_armed_signals and has_trades:
        print(f"\n🎯 STATUS: Ready for ML training!")
        print(f"   Next step: Extract features from armed_signals + outcomes")
    elif has_armed_signals:
        print(f"\n⚠️  STATUS: Partial readiness")
        print(f"   Issue: No trade outcomes table found")
        print(f"   Next step: Add outcome tracking to armed signals")
    else:
        print(f"\n❌ STATUS: Not ready for ML")
        print(f"   Issue: Missing signal tracking tables")
        print(f"   Next step: Enable signal persistence in sniper.py")
    
    print("\n" + "="*80)
    print("\nInspection complete! ✅")
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
