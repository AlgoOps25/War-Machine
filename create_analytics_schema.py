import sqlite3

DB_PATH = "signal_analytics.db"

def create_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Signals table with ALL columns needed by analyze_confirmation_patterns.py
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE,  -- Add this for compatibility
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            grade TEXT,
            confidence REAL,
            generated_at TIMESTAMP,  -- When signal was generated
            filled_at TIMESTAMP,     -- When position was entered
            closed_at TIMESTAMP,     -- When position was closed
            signal_time TIMESTAMP,   -- Alias for generated_at if needed
            entry_price REAL,
            stop_price REAL,
            t1_price REAL,
            t2_price REAL,
            outcome TEXT,            -- 'win', 'loss', 'pending'
            return_pct REAL,
            hold_time_minutes REAL,  -- Duration of trade
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Confirmations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            confirmation_type TEXT NOT NULL,
            value REAL,
            passed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
        )
    """)
    
    # Create indexes for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_outcome ON signals(outcome)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_grade ON signals(grade)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_generated_at ON signals(generated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_confirmations_signal_id ON confirmations(signal_id)")
    
    conn.commit()
    conn.close()
    print(f"✅ {DB_PATH} schema created successfully!")

if __name__ == "__main__":
    create_schema()
