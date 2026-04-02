"""
run_migration_006.py
Run once to create the futures_signals table and indexes.
Usage: python run_migration_006.py
"""
import os
import psycopg2

SQL = """
CREATE TABLE IF NOT EXISTS futures_signals (
    id               SERIAL PRIMARY KEY,
    symbol           VARCHAR(10)   NOT NULL,
    direction        VARCHAR(10)   NOT NULL,
    entry_price      NUMERIC(12,4),
    stop_price       NUMERIC(12,4),
    t1               NUMERIC(12,4),
    t2               NUMERIC(12,4),
    confidence       NUMERIC(6,4),
    grade            VARCHAR(5),
    signal_type      VARCHAR(32)   DEFAULT 'FUTURES_ORB',
    entry_type       VARCHAR(32),
    validation_data  JSONB,
    outcome          VARCHAR(16),
    exit_price       NUMERIC(12,4),
    pnl_pts          NUMERIC(10,4),
    pnl_usd          NUMERIC(12,2),
    saved_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    closed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_futures_signals_symbol
    ON futures_signals (symbol);

CREATE INDEX IF NOT EXISTS idx_futures_signals_saved_at
    ON futures_signals (saved_at);

CREATE INDEX IF NOT EXISTS idx_futures_signals_outcome
    ON futures_signals (outcome)
    WHERE outcome IS NOT NULL;
"""

if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("ERROR: DATABASE_URL environment variable not set.")
    conn = psycopg2.connect(url)
    cur  = conn.cursor()
    cur.execute(SQL)
    conn.commit()
    cur.close()
    conn.close()
    print("Migration 006 applied successfully — futures_signals table ready.")
