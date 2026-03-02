#!/usr/bin/env python3
"""
Database Migration: Add DTE Tracking Columns

Adds columns to positions table to enable historical DTE learning:
- dte_selected: Which DTE was chosen (0 or 1)
- adx_at_entry: ADX value when signal fired
- vix_at_entry: VIX value when signal fired
- target_pct_t1: Target 1 distance as percentage

Run once: python migrations/add_dte_tracking_columns.py
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.data.db_connection import get_conn

def migrate():
    conn = get_conn("market_memory.db")
    cursor = conn.cursor()
    
    columns = [
        ("dte_selected", "INTEGER"),
        ("adx_at_entry", "REAL"),
        ("vix_at_entry", "REAL"),
        ("target_pct_t1", "REAL")
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
            print(f"✅ Added column: {col_name}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print(f"⏭️  Column {col_name} already exists")
            else:
                print(f"❌ Error adding {col_name}: {e}")
    
    conn.commit()
    conn.close()
    print("\n🎉 Migration complete!")

if __name__ == "__main__":
    migrate()
