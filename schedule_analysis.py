"""Scheduler for automated analysis reports."""

import schedule
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import subprocess

ET = ZoneInfo("America/New_York")

def run_daily_report():
    """Execute daily analysis report."""
    print(f"\n[SCHEDULER] Running daily analysis - {datetime.now(ET).strftime('%I:%M %p ET')}")
    
    try:
        # Run daily analysis
        subprocess.run(['python', 'daily_analysis.py'], check=True)
        
        # Optionally run full analysis weekly on Fridays
        if datetime.now(ET).weekday() == 4:  # Friday
            print("[SCHEDULER] Running weekly full analysis...")
            subprocess.run(['python', 'run_full_analysis.py'], check=True)
            
    except Exception as e:
        print(f"[SCHEDULER] ❌ Error running analysis: {e}")

def main():
    """Main scheduler loop."""
    print("="*80)
    print("WAR MACHINE - ANALYSIS SCHEDULER")
    print("="*80)
    print(f"Started: {datetime.now(ET).strftime('%Y-%m-%d %I:%M %p ET')}")
    print("\nScheduled Tasks:")
    print("  - Daily Analysis: 4:15 PM ET (after market close)")
    print("  - Full Analysis: Fridays at 4:15 PM ET")
    print("\nPress Ctrl+C to stop\n")
    print("="*80 + "\n")
    
    # Schedule daily report at 4:15 PM ET (after market close)
    schedule.every().day.at("16:15").do(run_daily_report)
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[SCHEDULER] Stopped by user")
