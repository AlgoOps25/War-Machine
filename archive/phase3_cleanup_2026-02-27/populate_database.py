# Save as: populate_database.py
"""
Populate market_memory.db with historical data from EODHD
"""

import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# Get API key from environment variable
API_KEY = os.getenv('EODHD_API_KEY')

if not API_KEY:
    print("❌ EODHD_API_KEY not found in environment variables")
    print("Set it with: $env:EODHD_API_KEY = 'your_key_here'")
    exit(1)

BASE_URL = "https://eodhd.com/api/eod"

# Symbols from validation signals
signals = pd.read_csv('validation_signals.csv')
symbols = signals['symbol'].unique().tolist()

print(f"Found {len(symbols)} unique symbols to download")
print(f"Symbols: {symbols[:10]}..." if len(symbols) > 10 else f"Symbols: {symbols}")

# Create database table if not exists
conn = sqlite3.connect('market_memory.db')
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_bars (
        symbol TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        PRIMARY KEY (symbol, date)
    )
""")
conn.commit()

# Download data for each symbol
start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
end_date = datetime.now().strftime('%Y-%m-%d')

print(f"\nDownloading data from {start_date} to {end_date}")
print("="*70)

success_count = 0
error_count = 0

for i, symbol in enumerate(symbols, 1):
    try:
        url = f"{BASE_URL}/{symbol}.US"
        params = {
            'api_token': API_KEY,
            'from': start_date,
            'to': end_date,
            'fmt': 'json'
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                # Insert data
                for bar in data:
                    cursor.execute("""
                        INSERT OR REPLACE INTO daily_bars 
                        (symbol, date, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        bar['date'],
                        bar['open'],
                        bar['high'],
                        bar['low'],
                        bar['close'],
                        bar['volume']
                    ))
                
                conn.commit()
                print(f"  {i:3d}. {symbol:6s} ✅ Downloaded {len(data)} bars")
                success_count += 1
            else:
                print(f"  {i:3d}. {symbol:6s} ⚠️  No data returned")
                error_count += 1
        else:
            print(f"  {i:3d}. {symbol:6s} ❌ HTTP {response.status_code}")
            error_count += 1
            
    except Exception as e:
        print(f"  {i:3d}. {symbol:6s} ❌ Error: {str(e)[:50]}")
        error_count += 1

conn.close()

print("="*70)
print(f"\n✅ Complete!")
print(f"Success: {success_count}")
print(f"Errors: {error_count}")
print(f"\nDatabase updated: market_memory.db")
