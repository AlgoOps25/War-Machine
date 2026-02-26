import sqlite3

DB_PATH = "signal_analytics.db"

def create_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Signals table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            grade TEXT,
            confidence REAL,
            generated_at TIMESTAMP,
            filled_at TIMESTAMP,
            closed_at TIMESTAMP,
            signal_time TIMESTAMP,
            entry_price REAL,
            stop_price REAL,
            t1_price REAL,
            t2_price REAL,
            outcome TEXT,
            return_pct REAL,
            hold_time_minutes REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Confirmations table (for detailed analysis)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT,
            ticker TEXT,
            timestamp TIMESTAMP,
            volume_ratio REAL,
            breakout_hold_rate REAL,
            bars_above_entry INTEGER,
            post_breakout_high REAL,
            post_breakout_low REAL,
            immediate_rejection BOOLEAN,
            FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✅ {DB_PATH} schema created successfully!")

if __name__ == "__main__":
    create_schema()
