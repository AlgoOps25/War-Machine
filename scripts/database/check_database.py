"""
scripts/database/check_database.py

Standalone diagnostic: lists all tables, columns, and row counts
from the legacy SQLite marketmemory.db.

Usage:
    python scripts/database/check_database.py
    python scripts/database/check_database.py --db /path/to/other.db
"""
import argparse
import sqlite3
import sys


def inspect_database(db_path: str):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        print("=" * 60)
        print(f"DATABASE: {db_path}")
        print("=" * 60)
        print(f"\nFound {len(tables)} tables:\n")

        for table in tables:
            table_name = table[0]
            print(f"\U0001f4ca {table_name}")

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()

            print(f"   Columns ({len(columns)}):")
            for col in columns:
                col_id, name, col_type, notnull, default, pk = col
                print(f"     - {name} ({col_type})")

            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"   Rows: {count}")

        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect a SQLite database")
    parser.add_argument("--db", default="marketmemory.db",
                        help="Path to SQLite database (default: marketmemory.db)")
    args = parser.parse_args()
    inspect_database(args.db)
