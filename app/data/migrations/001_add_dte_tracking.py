#!/usr/bin/env python3
"""
Database Migration: Add DTE Tracking Columns

Adds columns to positions table to track context at entry time.
Enables learning loop for DTE selection validation.

Run once to upgrade schema:
    python app/data/migrations/001_add_dte_tracking.py
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from app.data.db_connection import get_conn


def migrate():
    """Add DTE tracking columns to positions table."""
    conn = get_conn("market_memory.db")
    cursor = conn.cursor()
    
    print("[MIGRATION] Adding DTE tracking columns to positions table...")
    
    # Check if columns already exist
    cursor.execute("PRAGMA table_info(positions)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    columns_to_add = [
        ("dte_selected", "INTEGER"),
        ("adx_at_entry", "REAL"),
        ("vix_at_entry", "REAL"),
        ("target_pct_t1", "REAL"),
        ("target_pct_t2", "REAL"),
        ("hour_of_entry", "INTEGER")
    ]
    
    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            print(f"  Adding column: {col_name} ({col_type})")
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
        else:
            print(f"  Column {col_name} already exists, skipping")
    
    conn.commit()
    conn.close()
    
    print("[MIGRATION] ✅ Migration complete!")
    print("\nNext steps:")
    print("  1. Update position_manager.py to populate these fields at entry")
    print("  2. Run historical analyzer to build DTE recommendation database")
    print("  3. Update options_dte_selector.py to use historical recommendations")


if __name__ == "__main__":
    migrate()
