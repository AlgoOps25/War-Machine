#!/usr/bin/env python3
"""
Test Discord EOD Report System
Run: python tests/test_discord_reports.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.reporting.performance_reporter import PerformanceReporter
from datetime import date
import psycopg2

def main():
    print("=" * 60)
    print("DISCORD EOD REPORT TEST")
    print("=" * 60)
    print()
    
    # Connect to database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ ERROR: DATABASE_URL not set")
        print("Set it: $env:DATABASE_URL=\"postgresql://...\"")
        return
    
    webhook = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook:
        print("⚠️ WARNING: DISCORD_WEBHOOK_URL not set")
        print("Report will generate but not send to Discord")
        print("To test Discord: $env:DISCORD_WEBHOOK_URL=\"https://discord.com/api/webhooks/...\"")
        print()
    
    db = psycopg2.connect(db_url)
    reporter = PerformanceReporter(db, webhook)
    
    # Generate today's report
    print("📊 Generating EOD report for today...")
    report = reporter.generate_eod_report(date.today())
    
    if report:
        print()
        print("✅ EOD Report Generated:")
        print("=" * 40)
        print(f"   Date: {report['date']}")
        print(f"   Total Signals: {report['total_signals']}")
        print(f"   Wins: {report['wins']}")
        print(f"   Losses: {report['losses']}")
        print(f"   Win Rate: {report['win_rate']:.1f}%")
        print(f"   Total P&L: {report['total_profit']:.2f}%")
        print(f"   Avg P&L: {report['avg_profit']:.2f}%")
        print()
        
        if report.get('best_trade'):
            best = report['best_trade']
            print(f"   🎯 Best Trade: {best['ticker']} ({best['profit']:.2f}%)")
        
        if report.get('worst_trade'):
            worst = report['worst_trade']
            print(f"   🔴 Worst Trade: {worst['ticker']} ({worst['profit']:.2f}%)")
        
        print()
        
        # Pattern breakdown
        if report.get('patterns'):
            print("   Pattern Performance:")
            for pattern in report['patterns']:
                print(f"      - {pattern['pattern']}: {pattern['count']} signals, {pattern['win_rate']:.0f}% WR")
        
        print()
        print("=" * 40)
        print()
        
        # Send to Discord
        if webhook:
            print("👌 Sending to Discord...")
            success = reporter.send_to_discord(report)
            if success:
                print("✅ Report sent to Discord successfully!")
            else:
                print("❌ Failed to send to Discord")
        else:
            print("⚠️ Skipping Discord (no webhook URL)")
    else:
        print("⚠️ No data for today")
        print("This is normal if no signals have been logged yet")
    
    print()
    print("✅ Discord report test complete!")
    
    db.close()

if __name__ == "__main__":
    main()
