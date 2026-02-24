#!/usr/bin/env python3
"""
Database Diagnostic Tool

Quickly check what data exists in your positions table.
"""
import os
import sys

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[ERROR] psycopg2 not installed.")
    sys.exit(1)


def diagnose():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        db_url = input("DATABASE_URL: ").strip()
    
    print("\n" + "="*80)
    print("DATABASE DIAGNOSTIC")
    print("="*80 + "\n")
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Total count
        cursor.execute("SELECT COUNT(*) as count FROM positions")
        total = cursor.fetchone()['count']
        print(f"Total positions in database: {total}\n")
        
        if total == 0:
            print("[INFO] No positions found. War Machine hasn't opened any trades yet.\n")
            conn.close()
            return
        
        # Status breakdown
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM positions 
            GROUP BY status
            ORDER BY count DESC
        """)
        
        print("Status Breakdown:")
        for row in cursor.fetchall():
            print(f"  {row['status']}: {row['count']}")
        print()
        
        # Grade breakdown (if exists)
        cursor.execute("""
            SELECT grade, COUNT(*) as count 
            FROM positions 
            WHERE grade IS NOT NULL
            GROUP BY grade
            ORDER BY grade
        """)
        
        grades = cursor.fetchall()
        if grades:
            print("Grade Breakdown:")
            for row in grades:
                print(f"  {row['grade']}: {row['count']}")
            print()
        
        # Sample records
        cursor.execute("""
            SELECT 
                ticker, 
                grade, 
                status, 
                entry_price, 
                exit_price, 
                pnl,
                entry_time,
                exit_time
            FROM positions 
            ORDER BY entry_time DESC 
            LIMIT 10
        """)
        
        print("Sample of 10 most recent positions:")
        print("\nTicker | Grade | Status | Entry | Exit | P&L | Entry Time | Exit Time")
        print("-" * 100)
        
        for row in cursor.fetchall():
            ticker = row['ticker'] or 'N/A'
            grade = row['grade'] or 'N/A'
            status = row['status'] or 'N/A'
            entry = f"${row['entry_price']:.2f}" if row['entry_price'] else 'N/A'
            exit_p = f"${row['exit_price']:.2f}" if row['exit_price'] else 'N/A'
            pnl = f"${row['pnl']:.2f}" if row['pnl'] else 'N/A'
            entry_time = str(row['entry_time'])[:19] if row['entry_time'] else 'N/A'
            exit_time = str(row['exit_time'])[:19] if row['exit_time'] else 'N/A'
            
            print(f"{ticker:<6} | {grade:<5} | {status:<6} | {entry:<8} | {exit_p:<8} | {pnl:<8} | {entry_time} | {exit_time}")
        
        print("\n" + "="*80 + "\n")
        
        conn.close()
        
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    diagnose()
