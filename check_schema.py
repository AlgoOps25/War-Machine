import sqlite3

conn = sqlite3.connect('signal_analytics.db')
cursor = conn.cursor()

# Get signals table schema
print("=" * 60)
print("SIGNALS TABLE SCHEMA")
print("=" * 60)
cursor.execute("PRAGMA table_info(signals)")
for row in cursor.fetchall():
    col_id, col_name, col_type, not_null, default, pk = row
    print(f"{col_name:25} {col_type:15} {'PRIMARY KEY' if pk else ''}")

print("\n" + "=" * 60)
print("COMPLETE TABLE STRUCTURE")
print("=" * 60)
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
result = cursor.fetchone()
if result:
    print(result[0])

conn.close()
