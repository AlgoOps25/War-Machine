import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from app.data.db_connection import get_connection, USE_POSTGRES

print(f"USE_POSTGRES: {USE_POSTGRES}")
print(f"DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")

if not USE_POSTGRES:
    print("\nWARNING: Connected to SQLite — DATABASE_URL not loaded.")
    sys.exit(1)

with get_connection() as conn:
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = [r[0] for r in cur.fetchall()]
    print(f"\nPostgreSQL tables ({len(tables)}):")
    for t in tables:
        print(f"  {t}")

    candle_tables = [t for t in ['bars', 'intraday_bars', 'intraday_bars_5m', 'candle_cache'] if t in tables]

    print("\nCandle-related tables:")
    for t in candle_tables:
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s 
              AND data_type IN ('timestamp', 'timestamp without time zone', 
                                'timestamp with time zone', 'date')
            ORDER BY ordinal_position
            LIMIT 1
        """, (t,))
        row = cur.fetchone()
        if not row:
            print(f"  {t}: no datetime column found")
            continue

        dt_col = row[0]
        cur.execute(f'SELECT MIN("{dt_col}"), MAX("{dt_col}"), COUNT(*) FROM {t}')
        mn, mx, cnt = cur.fetchone()
        print(f"  {t} [{dt_col}]: {mn} → {mx} ({cnt:,} rows)")

    cur.close()