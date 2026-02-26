"""Automated Daily Analysis Report."""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

ET = ZoneInfo("America/New_York")

def run_daily_analysis():
    """Generate daily analysis report."""
    
    print("\n" + "="*80)
    print("WAR MACHINE - DAILY ANALYSIS REPORT")
    print(datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET"))
    print("="*80 + "\n")
    
    if not os.path.exists('signal_analytics.db'):
        print("⚠️ No analytics database found. No signals logged yet.")
        return
    
    conn = sqlite3.connect('signal_analytics.db')
    
    today = datetime.now(ET).date()
    today_start = datetime.combine(today, datetime.min.time()).isoformat()
    
    print("[1] TODAY'S PERFORMANCE")
    print("-" * 80)
    
    today_query = """
    SELECT 
        COUNT(*) as total_signals,
        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN outcome = 'pending' THEN 1 ELSE 0 END) as pending,
        ROUND(AVG(CASE WHEN outcome = 'win' THEN return_pct END), 2) as avg_win,
        ROUND(AVG(CASE WHEN outcome = 'loss' THEN return_pct END), 2) as avg_loss,
        ROUND(SUM(return_pct), 2) as total_return
    FROM signals
    WHERE DATE(generated_at) = DATE(?)
    """
    
    today_stats = pd.read_sql_query(today_query, conn, params=(today_start,))
    
    if today_stats['total_signals'].iloc[0] == 0:
        print("No signals generated today.\n")
    else:
        print(today_stats.to_string(index=False))
        wins = today_stats['wins'].iloc[0] or 0
        losses = today_stats['losses'].iloc[0] or 0
        if wins + losses > 0:
            win_rate = (wins / (wins + losses)) * 100
            print(f"\nWin Rate: {win_rate:.1f}%")
        print()
    
    print("[2] LAST 7 DAYS PERFORMANCE")
    print("-" * 80)
    
    week_ago = (datetime.now(ET) - timedelta(days=7)).isoformat()
    
    week_query = """
    SELECT 
        DATE(generated_at) as trade_date,
        COUNT(*) as signals,
        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
        ROUND(SUM(return_pct), 2) as daily_return
    FROM signals
    WHERE generated_at >= ?
    AND outcome IN ('win', 'loss')
    GROUP BY DATE(generated_at)
    ORDER BY trade_date DESC
    """
    
    week_stats = pd.read_sql_query(week_query, conn, params=(week_ago,))
    
    if len(week_stats) == 0:
        print("No closed trades in last 7 days.\n")
    else:
        print(week_stats.to_string(index=False))
        print()
    
    print("[3] GRADE PERFORMANCE (ALL TIME)")
    print("-" * 80)
    
    grade_query = """
    SELECT 
        grade,
        COUNT(*) as total,
        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
        ROUND(100.0 * SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate,
        ROUND(AVG(return_pct), 2) as avg_return,
        ROUND(AVG(confidence) * 100, 1) as avg_conf
    FROM signals
    WHERE outcome IN ('win', 'loss')
    GROUP BY grade
    ORDER BY win_rate DESC
    """
    
    grade_stats = pd.read_sql_query(grade_query, conn)
    print(grade_stats.to_string(index=False))
    print()
    
    print("[4] QUICK FAILURE ANALYSIS")
    print("-" * 80)
    
    failure_query = """
    SELECT 
        COUNT(*) as total_losses,
        SUM(CASE WHEN hold_time_minutes < 15 THEN 1 ELSE 0 END) as quick_failures,
        ROUND(100.0 * SUM(CASE WHEN hold_time_minutes < 15 THEN 1 ELSE 0 END) / COUNT(*), 1) as quick_fail_pct
    FROM signals
    WHERE outcome = 'loss'
    AND hold_time_minutes IS NOT NULL
    """
    
    failure_stats = pd.read_sql_query(failure_query, conn)
    
    if failure_stats['total_losses'].iloc[0] > 0:
        print(failure_stats.to_string(index=False))
        print()
        
        quick_pct = failure_stats['quick_fail_pct'].iloc[0]
        if quick_pct > 60:
            print("⚠️ WARNING: High quick failure rate! Consider:")
            print("   - Implementing 2-bar holding period")
            print("   - Stricter entry confirmation")
            print("   - Review entry placement strategy")
            print()
    else:
        print("No losses recorded yet.\n")
    
    print("[5] RECENT SIGNALS (Last 10)")
    print("-" * 80)
    
    recent_query = """
    SELECT 
        SUBSTR(generated_at, 12, 5) as time,
        ticker,
        direction,
        grade,
        ROUND(confidence * 100, 0) as conf,
        outcome,
        ROUND(return_pct, 2) as return_pct,
        ROUND(hold_time_minutes, 0) as hold_min
    FROM signals
    ORDER BY generated_at DESC
    LIMIT 10
    """
    
    recent = pd.read_sql_query(recent_query, conn)
    print(recent.to_string(index=False))
    print()
    
    conn.close()
    
    print("="*80)
    print("Run full analysis: python run_full_analysis.py")
    print("="*80 + "\n")


if __name__ == "__main__":
    run_daily_analysis()
