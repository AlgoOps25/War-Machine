#!/usr/bin/env python3
"""Test database connection and show detailed error info."""
import os
import sys

print("\n" + "="*70)
print("DATABASE CONNECTION DIAGNOSTIC")
print("="*70)

# Check environment variable
db_url = os.getenv("DATABASE_URL", "")
if db_url:
    # Mask password for display
    display_url = db_url
    if '@' in display_url:
        parts = display_url.split('@')
        user_pass = parts[0].split('//')[-1]
        if ':' in user_pass:
            user = user_pass.split(':')[0]
            display_url = display_url.replace(user_pass, f"{user}:****")
    print(f"\n✓ DATABASE_URL is set")
    print(f"  {display_url}")
else:
    print("\n✗ DATABASE_URL is NOT set")
    print("  Will use SQLite fallback")
    sys.exit(0)

# Check if it needs normalization
if db_url.startswith("postgres://"):
    print("\n⚠ URL starts with postgres:// (needs normalization to postgresql://)")
    db_url = db_url.replace("postgres://", "postgresql://", 1)
    print(f"  Normalized to: postgresql://...")

# Try to import psycopg2
print("\n" + "-"*70)
print("Checking psycopg2...")
try:
    import psycopg2
    import psycopg2.extras
    print("✓ psycopg2 is installed")
except ImportError as e:
    print(f"✗ psycopg2 import failed: {e}")
    sys.exit(1)

# Try to connect
print("\n" + "-"*70)
print("Testing PostgreSQL connection...")
try:
    conn = psycopg2.connect(db_url)
    print("✓ Connection successful!")
    
    # Try a simple query
    cursor = conn.cursor()
    cursor.execute("SELECT version()")
    version = cursor.fetchone()[0]
    print(f"\n✓ PostgreSQL version: {version.split(',')[0]}")
    
    # Check if signals table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'signals'
        )
    """)
    signals_exists = cursor.fetchone()[0]
    
    if signals_exists:
        print("\n✓ 'signals' table exists")
        
        # Count signals
        cursor.execute("SELECT COUNT(*) FROM signals")
        count = cursor.fetchone()[0]
        print(f"  Total signals in database: {count}")
        
        if count > 0:
            # Get most recent
            cursor.execute("""
                SELECT ticker, direction, signal_time, entry_price, confidence
                FROM signals
                ORDER BY signal_time DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            print(f"\n  Most recent signal:")
            print(f"    {row[0]} {row[1]} @ ${row[3]:.2f}")
            print(f"    Time: {row[2]}")
            print(f"    Confidence: {row[4]}%")
        else:
            print("  ⚠ Table is empty - no signals logged yet")
    else:
        print("\n✗ 'signals' table does NOT exist")
        print("  Table needs to be created by signal_analytics initialization")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"\n✗ Connection FAILED: {e}")
    print(f"\nError type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*70)
print("✓ ALL CHECKS PASSED")
print("="*70 + "\n")
