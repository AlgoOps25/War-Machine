#!/usr/bin/env python3
"""
Extract Position History from Database
Queries your PostgreSQL/SQLite database to create position_history.csv
"""

import csv
import argparse
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    print("Note: psycopg2 not installed. PostgreSQL support disabled.")

try:
    import sqlite3
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False

def extract_from_postgres(db_url: str, output_csv: str):
    """
    Extract positions from PostgreSQL database
    """
    if not HAS_POSTGRES:
        print("Error: psycopg2 not installed. Install with: pip install psycopg2-binary")
        return
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Adjust query based on your schema
        query = """
            SELECT 
                entry_time,
                exit_time,
                symbol,
                strike,
                dte,
                entry_price,
                exit_price,
                pnl,
                pnl_pct
            FROM positions
            WHERE exit_time IS NOT NULL
            ORDER BY entry_time DESC
            LIMIT 1000
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} closed positions")
        
        # Write to CSV
        with open(output_csv, 'w', newline='') as csvfile:
            fieldnames = ['entry_time', 'exit_time', 'symbol', 'strike', 'dte',
                         'entry_price', 'exit_price', 'pnl', 'pnl_pct']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'entry_time': row[0],
                    'exit_time': row[1],
                    'symbol': row[2],
                    'strike': row[3],
                    'dte': row[4],
                    'entry_price': row[5],
                    'exit_price': row[6],
                    'pnl': row[7],
                    'pnl_pct': row[8]
                })
        
        print(f"Saved to {output_csv}")
        
        cursor.close()
        conn.close()
    
    except Exception as e:
        print(f"Error extracting from PostgreSQL: {e}")

def extract_from_sqlite(db_path: str, output_csv: str):
    """
    Extract positions from SQLite database
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Adjust query based on your schema
        query = """
            SELECT 
                entry_time,
                exit_time,
                symbol,
                strike,
                dte,
                entry_price,
                exit_price,
                pnl,
                pnl_pct
            FROM positions
            WHERE exit_time IS NOT NULL
            ORDER BY entry_time DESC
            LIMIT 1000
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} closed positions")
        
        # Write to CSV
        with open(output_csv, 'w', newline='') as csvfile:
            fieldnames = ['entry_time', 'exit_time', 'symbol', 'strike', 'dte',
                         'entry_price', 'exit_price', 'pnl', 'pnl_pct']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'entry_time': row[0],
                    'exit_time': row[1],
                    'symbol': row[2],
                    'strike': row[3],
                    'dte': row[4],
                    'entry_price': row[5],
                    'exit_price': row[6],
                    'pnl': row[7],
                    'pnl_pct': row[8]
                })
        
        print(f"Saved to {output_csv}")
        
        cursor.close()
        conn.close()
    
    except Exception as e:
        print(f"Error extracting from SQLite: {e}")

def main():
    parser = argparse.ArgumentParser(description='Extract position history from database')
    parser.add_argument('--db-type', choices=['postgres', 'sqlite'], required=True,
                       help='Database type')
    parser.add_argument('--db-url', help='PostgreSQL connection URL (for postgres type)')
    parser.add_argument('--db-path', help='SQLite database path (for sqlite type)')
    parser.add_argument('--output', default='backtests/position_history.csv',
                       help='Output CSV file (default: backtests/position_history.csv)')
    
    args = parser.parse_args()
    
    if args.db_type == 'postgres':
        if not args.db_url:
            print("Error: --db-url required for PostgreSQL")
            return
        extract_from_postgres(args.db_url, args.output)
    
    elif args.db_type == 'sqlite':
        if not args.db_path:
            print("Error: --db-path required for SQLite")
            return
        extract_from_sqlite(args.db_path, args.output)

if __name__ == '__main__':
    main()
