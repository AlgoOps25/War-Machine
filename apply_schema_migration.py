#!/usr/bin/env python3
"""
Auto-Migration Script: Positions Table P&L Columns

Applies schema changes to add missing realized_pnl, unrealized_pnl,
and current_price columns to the positions table.

Runs automatically on container startup (called by scanner.py).
Idempotent: safe to run multiple times (uses IF NOT EXISTS).

FIXED: Now checks if positions table exists before attempting migration.
"""
from db_connection import get_conn, USE_POSTGRES

def table_exists(cursor, table_name: str) -> bool:
    """
    Check if a table exists in the database.
    
    Args:
        cursor: Database cursor
        table_name: Name of table to check
    
    Returns:
        True if table exists, False otherwise
    """
    if USE_POSTGRES:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = %s
            )
        """, (table_name,))
        return cursor.fetchone()[0]
    else:
        # SQLite
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """, (table_name,))
        return cursor.fetchone() is not None

def column_exists(cursor, table_name: str, column_name: str) -> bool:
    """
    Check if a column exists in a table.
    
    Args:
        cursor: Database cursor
        table_name: Name of table
        column_name: Name of column to check
    
    Returns:
        True if column exists, False otherwise
    """
    if USE_POSTGRES:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = %s AND column_name = %s
            )
        """, (table_name, column_name))
        return cursor.fetchone()[0]
    else:
        # SQLite - get all column names
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns

def apply_positions_pnl_migration():
    """
    Add missing P&L tracking columns to positions table.
    
    Adds:
      - realized_pnl: actual profit/loss when closed
      - unrealized_pnl: floating profit/loss for open positions  
      - current_price: real-time price for P&L calculation
    
    Returns:
        bool: True if migration succeeded or not needed, False if error
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        print("[MIGRATION] Checking positions table schema...")
        
        # Check if positions table exists
        if not table_exists(cursor, "positions"):
            print("[MIGRATION] ✅ Positions table will be created on first trade")
            if conn:
                conn.close()
            return True
        
        # Table exists - check and add missing columns
        columns_to_add = [
            ("realized_pnl", "REAL DEFAULT 0"),
            ("unrealized_pnl", "REAL DEFAULT 0"),
            ("current_price", "REAL")  # No default - NULL until updated
        ]
        
        columns_added = []
        for col_name, col_def in columns_to_add:
            if not column_exists(cursor, "positions", col_name):
                try:
                    if USE_POSTGRES:
                        cursor.execute(f"""
                            ALTER TABLE positions 
                            ADD COLUMN IF NOT EXISTS {col_name} {col_def}
                        """)
                    else:
                        # SQLite doesn't support IF NOT EXISTS in ALTER TABLE
                        cursor.execute(f"""
                            ALTER TABLE positions 
                            ADD COLUMN {col_name} {col_def}
                        """)
                    columns_added.append(col_name)
                except Exception as e:
                    # Column might already exist (SQLite)
                    if "duplicate column" not in str(e).lower():
                        print(f"[MIGRATION] ⚠️  Error adding {col_name}: {e}")
        
        conn.commit()
        
        if columns_added:
            print(f"[MIGRATION] ✅ Added columns: {', '.join(columns_added)}")
        else:
            print("[MIGRATION] ✅ All P&L columns already exist")
        
        if conn:
            conn.close()
        return True
            
    except Exception as e:
        print(f"[MIGRATION] ❌ Error applying schema migration: {e}")
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        return False

if __name__ == "__main__":
    # Manual execution for testing
    success = apply_positions_pnl_migration()
    if success:
        print("\n✅ Migration completed successfully")
    else:
        print("\n❌ Migration failed")
