#!/usr/bin/env python3
"""
probe_railway.py  —  List all Railway Postgres tables and row counts
Usage:
    $env:DATABASE_URL = "postgresql://..."
    python scripts/backtesting/campaign/probe_railway.py
"""
import os, sys

def load_dotenv():
    env = os.path.join(os.path.dirname(__file__), '../../../.env')
    if not os.path.exists(env): return
    with open(env) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k not in os.environ: os.environ[k] = v

load_dotenv()
url = os.getenv('DATABASE_URL', '').strip()
if not url:
    print('ERROR: DATABASE_URL not set')
    sys.exit(1)
if url.startswith('postgres://'):
    url = url.replace('postgres://', 'postgresql://', 1)

try:
    import psycopg2
except ImportError:
    print('Run: pip install psycopg2-binary')
    sys.exit(1)

conn = psycopg2.connect(url, connect_timeout=15)
cur  = conn.cursor()

print('\nRAILWAY POSTGRES — TABLE INVENTORY')
print('='*55)

cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
""")
tables = [r[0] for r in cur.fetchall()]
print(f'Tables found: {tables}\n')

for t in tables:
    try:
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        n = cur.fetchone()[0]
        print(f'  {t:<35} {n:>10,} rows')
    except Exception as e:
        conn.rollback()
        print(f'  {t:<35}  ERROR: {e}')

# Extra: show candle_cache columns if it exists
if 'candle_cache' in tables:
    print()
    print('candle_cache columns:')
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'candle_cache'
        ORDER BY ordinal_position
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<25} {r[1]}')
    # Sample a row
    cur.execute('SELECT * FROM candle_cache LIMIT 1')
    row = cur.fetchone()
    if row:
        print()
        print('Sample row:')
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='candle_cache' ORDER BY ordinal_position
        """)
        cols = [r[0] for r in cur2.fetchall()]
        for col, val in zip(cols, row):
            val_str = str(val)[:120]
            print(f'  {col:<25} {val_str}')

conn.close()
print()
print('Done.')
