import sqlite3

conn = sqlite3.connect('signal_analytics.db')
cursor = conn.cursor()

# Create signals table
cursor.execute('''
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    grade TEXT,
    confidence REAL,
    signal_time TIMESTAMP,
    entry_price REAL,
    stop_price REAL,
    t1_price REAL,
    t2_price REAL,
    outcome TEXT,
    return_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Add these three columns:
    generated_at TIMESTAMP,
    filled_at TIMESTAMP,
    closed_at TIMESTAMP,
    hold_time_minutes REAL
)
''')

conn.commit()
conn.close()
print("✅ signal_analytics.db schema created successfully!")
