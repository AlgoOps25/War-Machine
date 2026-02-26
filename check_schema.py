"""Check signal_analytics.db schema."""

import sqlite3

DB_PATH = "signal_analytics.db"

def check_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n" + "="*60)
    print("SIGNALS TABLE SCHEMA")
    print("="*60)
    
    # Get column info
    cursor.execute("PRAGMA table_info(signals)")
    columns = cursor.fetchall()
    
    for col in columns:
        col_id, name, type_, notnull, default, pk = col
        pk_str = "PRIMARY KEY" if pk else ""
        print(f"{name:25} {type_:15} {pk_str}")
    
    print("\n" + "="*60)
    print("COMPLETE TABLE STRUCTURE")
    print("="*60)
    
    # Get full CREATE statement
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
    create_sql = cursor.fetchone()[0]
    print(create_sql)
    
    conn.close()

if __name__ == "__main__":
    check_schema()
