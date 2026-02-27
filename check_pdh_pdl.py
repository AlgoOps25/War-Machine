#!/usr/bin/env python3
"""
Diagnostic script to check if PDH/PDL data is available.
"""

import sqlite3
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

db_path = "market_memory.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("\n" + "="*70)
print("PDH/PDL DATA AVAILABILITY CHECK")
print("="*70)
print()

# Check what dates we have for SPY
print("Checking dates in database for SPY:")
cur.execute("""
    SELECT DISTINCT date(datetime) as dt
    FROM intraday_bars
    WHERE ticker = 'SPY'
    ORDER BY dt DESC
    LIMIT 20
""")

rows = cur.fetchall()
if rows:
    print("\nAvailable dates (most recent first):")
    for row in rows:
        dt_str = row["dt"]
        # Parse the date
        if isinstance(dt_str, str):
            dt = datetime.strptime(dt_str, "%Y-%m-%d").date()
        else:
            dt = dt_str
        
        # Count bars for this date
        cur.execute("""
            SELECT COUNT(*) as cnt
            FROM intraday_bars
            WHERE ticker = 'SPY'
              AND date(datetime) = ?
        """, (dt_str,))
        count = cur.fetchone()["cnt"]
        
        print(f"  {dt} ({dt.strftime('%A')}): {count:,} bars")
else:
    print("  No data found for SPY!")

print()

# Now test the PDH/PDL loading logic
print("Testing PDH/PDL loading for test period:")
print()

test_start = datetime.now(ET).date() - timedelta(days=10)
test_end = datetime.now(ET).date()

print(f"Test period: {test_start} to {test_end}")
print()

# Try to find previous day data
for days_back in range(1, 10):
    prev_date = test_start - timedelta(days=days_back)
    
    # Query bars for this date
    cur.execute("""
        SELECT datetime, high, low
        FROM intraday_bars
        WHERE ticker = 'SPY'
          AND date(datetime) = ?
        ORDER BY datetime
    """, (prev_date.isoformat(),))
    
    rows = cur.fetchall()
    
    if rows:
        pdh = max(float(r["high"]) for r in rows)
        pdl = min(float(r["low"]) for r in rows)
        
        print(f"✅ Found data for {prev_date} ({prev_date.strftime('%A')}):")
        print(f"   PDH: ${pdh:.2f}")
        print(f"   PDL: ${pdl:.2f}")
        print(f"   Bars: {len(rows)}")
        break
    else:
        print(f"⚠️  No data for {prev_date} ({prev_date.strftime('%A')})")

conn.close()

print()
print("="*70)
print()
