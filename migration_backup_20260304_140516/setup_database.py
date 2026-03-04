# Create setup_database.py directly in PowerShell
# Run Database Schema on Railway PostgreSQL
import psycopg2
import os
import sys

db_url = os.getenv('DATABASE_URL')

if not db_url or db_url == 'None':
    print("❌ DATABASE_URL not set!")
    sys.exit(1)

print("📡 Connecting to Railway PostgreSQL...")
print(f"Host: {db_url.split('@')[1].split('/')[0] if '@' in db_url else 'Unknown'}")

try:
    with open('database/signal_outcomes_schema.sql', 'r') as f:
        schema = f.read()
    
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    
    statements = schema.split(';')
    for i, statement in enumerate(statements):
        statement = statement.strip()
        if statement:
            print(f"Executing statement {i+1}/{len(statements)}...")
            cursor.execute(statement)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("")
    print("✅ Database tables created successfully!")
    print("")
    print("Tables created:")
    print("  • signal_outcomes (main tracking)")
    print("  • pattern_performance (aggregate stats)")
    print("  • ml_training_data (ML features)")
    print("")
    print("Bootstrap data:")
    print("  • NVDA 60% winner from today loaded")
    
except psycopg2.Error as e:
    print(f"❌ Database error: {e}")
    sys.exit(1)
except FileNotFoundError:
    print("❌ Could not find database/signal_outcomes_schema.sql")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)

