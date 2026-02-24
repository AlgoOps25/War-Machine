#!/usr/bin/env python3
"""Quick check - run this on Railway to see signals."""
from db_connection import get_conn, dict_cursor

conn = get_conn()
cursor = dict_cursor(conn)

print("\n" + "="*70)
print("SIGNAL CHECK")
print("="*70)

# Count total signals
cursor.execute("SELECT COUNT(*) as cnt FROM signals")
count = cursor.fetchone()[0] if cursor.fetchone() else 0
print(f"\nTotal signals in database: {count}")

if count > 0:
    # Show recent signals
    cursor.execute("""
        SELECT ticker, direction, signal_time, entry_price, confidence
        FROM signals
        ORDER BY signal_time DESC
        LIMIT 10
    """)
    print("\nMost recent signals:")
    for row in cursor.fetchall():
        print(f"  {row['signal_time']} | {row['ticker']} {row['direction']} @ ${row['entry_price']:.2f} | Conf: {row['confidence']}%")
else:
    print("\n⚠️  No signals found in database")

conn.close()
print("\n" + "="*70 + "\n")
