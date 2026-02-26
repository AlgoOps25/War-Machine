"""Quick analytics commands for command-line use."""

import sys
import subprocess

def show_help():
    """Display available commands."""
    print("\n" + "="*80)
    print("WAR MACHINE ANALYTICS - QUICK COMMANDS")
    print("="*80 + "\n")
    print("Commands:")
    print("  python analytics_commands.py view       - View current signals")
    print("  python analytics_commands.py daily      - Run daily analysis")
    print("  python analytics_commands.py full       - Run full analysis")
    print("  python analytics_commands.py sample     - Generate sample data")
    print("  python analytics_commands.py clear      - Clear all signals")
    print("  python analytics_commands.py schema     - Recreate database schema")
    print("\n" + "="*80 + "\n")

def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == 'view':
        subprocess.run(['python', 'view_signals.py'])
    
    elif command == 'daily':
        subprocess.run(['python', 'daily_analysis.py'])
    
    elif command == 'full':
        subprocess.run(['python', 'run_full_analysis.py'])
    
    elif command == 'sample':
        subprocess.run(['python', 'populate_sample_signals.py'])
    
    elif command == 'clear':
        response = input("⚠️ This will delete all signals. Are you sure? (yes/no): ")
        if response.lower() == 'yes':
            import sqlite3
            conn = sqlite3.connect('signal_analytics.db')
            conn.execute("DELETE FROM signals")
            conn.execute("DELETE FROM confirmations")
            conn.commit()
            conn.close()
            print("✅ All signals cleared")
        else:
            print("❌ Cancelled")
    
    elif command == 'schema':
        response = input("⚠️ This will recreate the database. Continue? (yes/no): ")
        if response.lower() == 'yes':
            import os
            if os.path.exists('signal_analytics.db'):
                os.remove('signal_analytics.db')
            subprocess.run(['python', 'create_analytics_schema.py'])
        else:
            print("❌ Cancelled")
    
    else:
        print(f"❌ Unknown command: {command}")
        show_help()

if __name__ == "__main__":
    main()
