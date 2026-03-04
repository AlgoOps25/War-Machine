import sqlite3
import sys

db_path = 'marketmemory.db'

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print("=" * 60)
    print(f"DATABASE: {db_path}")
    print("=" * 60)
    print(f"\nFound {len(tables)} tables:\n")
    
    for table in tables:
        table_name = table[0]
        print(f"📊 {table_name}")
        
        # Get schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        print(f"   Columns ({len(columns)}):")
        for col in columns:
            col_id, name, col_type, notnull, default, pk = col
            print(f"     - {name} ({col_type})")
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"   Rows: {count}\n")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
