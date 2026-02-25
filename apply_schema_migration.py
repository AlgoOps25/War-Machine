#!/usr/bin/env python3
"""
Auto-Migration Script: Positions Table P&L Columns

Applies schema changes to add missing realized_pnl, unrealized_pnl,
and current_price columns to the positions table.

Runs automatically on container startup (called by scanner.py).
Idempotent: safe to run multiple times (uses IF NOT EXISTS).
"""
from db_connection import get_conn

def apply_positions_pnl_migration():
    """
    Add missing P&L tracking columns to positions table.
    
    Adds:
      - realized_pnl: actual profit/loss when closed
      - unrealized_pnl: floating profit/loss for open positions  
      - current_price: real-time price for P&L calculation
    
    Returns:
        bool: True if migration succeeded, False otherwise
    """
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        print("[MIGRATION] Checking positions table schema...")
        
        # Add realized_pnl column
        cursor.execute("""
            ALTER TABLE positions 
            ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0
        """)
        
        # Add unrealized_pnl column
        cursor.execute("""
            ALTER TABLE positions 
            ADD COLUMN IF NOT EXISTS unrealized_pnl REAL DEFAULT 0
        """)
        
        # Add current_price column (no default - NULL until updated)
        cursor.execute("""
            ALTER TABLE positions 
            ADD COLUMN IF NOT EXISTS current_price REAL
        """)
        
        conn.commit()
        
        # Verify columns exist
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'positions' 
              AND column_name IN ('realized_pnl', 'unrealized_pnl', 'current_price')
        """)
        
        added_columns = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if len(added_columns) == 3:
            print(f"[MIGRATION] ✅ Positions table schema updated: {', '.join(added_columns)}")
            return True
        else:
            print(f"[MIGRATION] ⚠️ Partial migration: {len(added_columns)}/3 columns found")
            return False
            
    except Exception as e:
        print(f"[MIGRATION] ❌ Error applying schema migration: {e}")
        return False

if __name__ == "__main__":
    # Manual execution for testing
    success = apply_positions_pnl_migration()
    if success:
        print("\n✅ Migration completed successfully")
    else:
        print("\n❌ Migration failed")
