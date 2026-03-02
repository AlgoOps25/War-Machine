#!/usr/bin/env python3
"""
Database Migration: Add DTE Context Tracking Columns

Adds columns to positions table to track market context at entry time.
This enables the DTEHistoricalAdvisor to learn optimal DTE selection
from actual trade outcomes.

New Columns:
- dte_selected: INTEGER - Which DTE was selected (0 or 1)
- adx_at_entry: REAL - ADX value at signal entry
- vix_at_entry: REAL - VIX level at signal entry
- target_pct_t1: REAL - Distance to T1 target as percentage
- hour_of_day: INTEGER - Hour of day in ET (9-16)

Usage:
    python migrations/add_dte_context_columns.py

Reversible:
    Yes - run with --rollback flag to remove columns
"""
import sys
import sqlite3
from pathlib import Path

# Add app directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data.db_connection import get_conn


def migrate_up(db_path: str = "market_memory.db"):
    """
    Apply migration - add DTE context columns.
    """
    print("[MIGRATION] Starting migration: add_dte_context_columns")
    
    conn = get_conn(db_path)
    cursor = conn.cursor()
    
    # Check if columns already exist
    cursor.execute("PRAGMA table_info(positions)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    columns_to_add = [
        ("dte_selected", "INTEGER", "Which DTE was selected (0 or 1)"),
        ("adx_at_entry", "REAL", "ADX value at signal entry time"),
        ("vix_at_entry", "REAL", "VIX level at signal entry time"),
        ("target_pct_t1", "REAL", "Distance to T1 target as percentage"),
        ("hour_of_day", "INTEGER", "Hour of day in ET timezone (9-16)")
    ]
    
    added_count = 0
    skipped_count = 0
    
    for col_name, col_type, description in columns_to_add:
        if col_name in existing_columns:
            print(f"  ⏭️  Column '{col_name}' already exists, skipping")
            skipped_count += 1
            continue
        
        try:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
            print(f"  ✅ Added column: {col_name} ({description})")
            added_count += 1
        except Exception as e:
            print(f"  ❌ Failed to add column '{col_name}': {e}")
            conn.close()
            return False
    
    conn.commit()
    conn.close()
    
    print(f"\n[MIGRATION] Complete: {added_count} columns added, {skipped_count} already existed")
    print("\n💡 Next steps:")
    print("   1. Update position_manager.py to populate these fields at entry time")
    print("   2. Update sniper.py to pass ADX/VIX/target data to DTE selector")
    print("   3. Update options_dte_selector.py to use DTEHistoricalAdvisor")
    
    return True


def migrate_down(db_path: str = "market_memory.db"):
    """
    Rollback migration - remove DTE context columns.
    
    Note: SQLite doesn't support DROP COLUMN in older versions.
    This will only work on SQLite 3.35.0+ (2021-03-12).
    """
    print("[MIGRATION] Rolling back: add_dte_context_columns")
    
    conn = get_conn(db_path)
    cursor = conn.cursor()
    
    # Check SQLite version
    cursor.execute("SELECT sqlite_version()")
    version = cursor.fetchone()[0]
    print(f"  SQLite version: {version}")
    
    columns_to_remove = [
        "dte_selected",
        "adx_at_entry",
        "vix_at_entry",
        "target_pct_t1",
        "hour_of_day"
    ]
    
    try:
        for col_name in columns_to_remove:
            cursor.execute(f"ALTER TABLE positions DROP COLUMN {col_name}")
            print(f"  ✅ Removed column: {col_name}")
        
        conn.commit()
        conn.close()
        print("\n[MIGRATION] Rollback complete")
        return True
        
    except sqlite3.OperationalError as e:
        if "no such column" in str(e).lower():
            print(f"  ⚠️  Columns don't exist, nothing to rollback")
            conn.close()
            return True
        elif "drop column" in str(e).lower():
            print(f"\n  ⚠️  Your SQLite version doesn't support DROP COLUMN")
            print(f"     You'll need to manually recreate the table without these columns")
            conn.close()
            return False
        else:
            print(f"  ❌ Rollback failed: {e}")
            conn.close()
            return False


def verify_migration(db_path: str = "market_memory.db"):
    """
    Verify migration was successful.
    """
    print("\n[VERIFY] Checking positions table schema...")
    
    conn = get_conn(db_path)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(positions)")
    columns = cursor.fetchall()
    
    required_columns = [
        "dte_selected",
        "adx_at_entry",
        "vix_at_entry",
        "target_pct_t1",
        "hour_of_day"
    ]
    
    existing_names = [col[1] for col in columns]
    
    all_present = True
    for col_name in required_columns:
        if col_name in existing_names:
            print(f"  ✅ {col_name}")
        else:
            print(f"  ❌ {col_name} - MISSING")
            all_present = False
    
    conn.close()
    
    if all_present:
        print("\n[VERIFY] ✅ All required columns present")
    else:
        print("\n[VERIFY] ❌ Migration incomplete")
    
    return all_present


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate database to add DTE context columns")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback migration (remove columns)"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration status without making changes"
    )
    parser.add_argument(
        "--db",
        default="market_memory.db",
        help="Database file path (default: market_memory.db)"
    )
    
    args = parser.parse_args()
    
    if args.verify:
        verify_migration(args.db)
    elif args.rollback:
        success = migrate_down(args.db)
        if success:
            verify_migration(args.db)
    else:
        success = migrate_up(args.db)
        if success:
            verify_migration(args.db)
