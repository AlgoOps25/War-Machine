"""Quick viewer for signal analytics database."""

import sqlite3
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', 20)

conn = sqlite3.connect('signal_analytics.db')

print("\n" + "="*80)
print("SIGNAL ANALYTICS DATABASE - QUICK VIEW")
print("="*80 + "\n")

print("[1] OVERALL STATISTICS")
print("-" * 80)
stats = pd.read_sql_query("""
    SELECT 
        COUNT(*) as total_signals,
        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
        ROUND(AVG(CASE WHEN outcome = 'win' THEN return_pct END), 2) as avg_win_pct,
        ROUND(AVG(CASE WHEN outcome = 'loss' THEN return_pct END), 2) as avg_loss_pct,
        ROUND(AVG(hold_time_minutes), 1) as avg_hold_minutes
    FROM signals
    WHERE outcome IN ('win', 'loss')
""", conn)
print(stats.to_string(index=False))

print("\n[2] PERFORMANCE BY GRADE")
print("-" * 80)
by_grade = pd.read_sql_query("""
    SELECT 
        grade,
        COUNT(*) as total,
        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
        ROUND(100.0 * SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate,
        ROUND(AVG(return_pct), 2) as avg_return
    FROM signals
    WHERE outcome IN ('win', 'loss')
    GROUP BY grade
    ORDER BY win_rate DESC
""", conn)
print(by_grade.to_string(index=False))

print("\n[3] RECENT SIGNALS (Last 10)")
print("-" * 80)
recent = pd.read_sql_query("""
    SELECT 
        ticker,
        direction,
        grade,
        ROUND(confidence * 100, 1) as conf_pct,
        outcome,
        ROUND(return_pct, 2) as return_pct,
        ROUND(hold_time_minutes, 0) as hold_min
    FROM signals
    WHERE outcome IN ('win', 'loss')
    ORDER BY generated_at DESC
    LIMIT 10
""", conn)
print(recent.to_string(index=False))

print("\n" + "="*80 + "\n")

conn.close()
