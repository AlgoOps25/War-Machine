"""Analyze confirmation patterns from closed signals."""

import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, Optional


class ConfirmationAnalyzer:
    """Analyzes patterns in signal confirmations and outcomes."""
    
    def __init__(self, db_path: str = "signal_analytics.db"):
        self.db_path = db_path
        try:
            self.conn = sqlite3.connect(db_path)
            print(f"[ANALYSIS] ✅ Connected to {db_path}")
        except Exception as e:
            print(f"[ANALYSIS] ❌ Database connection failed: {e}")
            self.conn = None
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
    
    def analyze_grade_performance(self) -> pd.DataFrame:
        """Analyze win rates by signal grade."""
        query = """
        SELECT 
            grade,
            COUNT(*) as total_signals,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            ROUND(AVG(CASE WHEN outcome = 'win' THEN return_pct END), 2) as avg_win_pct,
            ROUND(AVG(CASE WHEN outcome = 'loss' THEN return_pct END), 2) as avg_loss_pct,
            ROUND(AVG(return_pct), 2) as avg_return_pct,
            ROUND(AVG(confidence), 2) as avg_confidence,
            ROUND(100.0 * SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) / COUNT(*), 2) as win_rate
        FROM signals
        WHERE outcome IN ('win', 'loss')
        GROUP BY grade
        ORDER BY win_rate DESC
        """
        
        return pd.read_sql_query(query, self.conn)
    
    def analyze_time_to_failure(self) -> Optional[Dict]:
        """Analyze how quickly losing signals fail."""
        query = """
        SELECT hold_time_minutes
        FROM signals
        WHERE outcome = 'loss'
        AND hold_time_minutes IS NOT NULL
        ORDER BY hold_time_minutes
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        if len(df) == 0:
            return None
        
        return {
            'total_losses': len(df),
            'immediate_count': len(df[df['hold_time_minutes'] < 5]),
            'immediate_pct': (len(df[df['hold_time_minutes'] < 5]) / len(df)) * 100,
            'quick_count': len(df[(df['hold_time_minutes'] >= 5) & (df['hold_time_minutes'] < 15)]),
            'quick_pct': (len(df[(df['hold_time_minutes'] >= 5) & (df['hold_time_minutes'] < 15)]) / len(df)) * 100,
            'delayed_count': len(df[df['hold_time_minutes'] >= 15]),
            'delayed_pct': (len(df[df['hold_time_minutes'] >= 15]) / len(df)) * 100,
            'median_hold_time': df['hold_time_minutes'].median()
        }
    
    def analyze_winning_patterns(self) -> Optional[Dict]:
        """Analyze patterns in winning signals."""
        query = """
        SELECT 
            grade,
            hold_time_minutes,
            return_pct
        FROM signals
        WHERE outcome = 'win'
        AND hold_time_minutes IS NOT NULL
        ORDER BY grade, hold_time_minutes
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        if len(df) == 0:
            return None
        
        by_grade = {}
        for grade in df['grade'].unique():
            grade_df = df[df['grade'] == grade]
            by_grade[grade] = {
                'count': len(grade_df),
                'median_hold': grade_df['hold_time_minutes'].median(),
                'avg_hold': grade_df['hold_time_minutes'].mean(),
                'min_hold': grade_df['hold_time_minutes'].min(),
                'max_hold': grade_df['hold_time_minutes'].max(),
                'avg_return': grade_df['return_pct'].mean()
            }
        
        return {
            'total_winners': len(df),
            'overall_median_hold': df['hold_time_minutes'].median(),
            'overall_avg_hold': df['hold_time_minutes'].mean(),
            'by_grade': by_grade
        }
    
    def analyze_post_breakout_behavior(self) -> pd.DataFrame:
        """Analyze price behavior immediately after breakout."""
        query = """
        SELECT 
            signal_id,
            ticker,
            grade,
            outcome,
            confidence,
            entry_price,
            generated_at,
            filled_at
        FROM signals
        WHERE outcome IN ('win', 'loss')
        AND filled_at IS NOT NULL
        ORDER BY generated_at DESC
        LIMIT 50
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        if len(df) == 0:
            return pd.DataFrame()
        
        # Would fetch post-breakout bars here in production
        # For now, return empty since we need market_memory.db integration
        return pd.DataFrame()
    
    def generate_full_report(self) -> str:
        """Generate comprehensive analysis report."""
        lines = []
        lines.append("="*80)
        lines.append("CONFIRMATION PATTERN ANALYSIS - DATA-DRIVEN INSIGHTS")
        lines.append("="*80)
        lines.append("")
        
        # Section 1: Grade Performance
        lines.append("[1] SIGNAL GRADE PERFORMANCE")
        lines.append("-"*80)
        grade_perf = self.analyze_grade_performance()
        if len(grade_perf) > 0:
            lines.append(grade_perf.to_string(index=False))
        else:
            lines.append("No closed signals found")
        lines.append("")
        
        # Section 2: Losing Signal Timing
        lines.append("[2] LOSING SIGNAL TIMING ANALYSIS")
        lines.append("-"*80)
        timing = self.analyze_time_to_failure()
        if timing:
            lines.append(f"Total Losses: {timing['total_losses']}")
            lines.append(f"Immediate Failures (<5 min): {timing['immediate_count']} ({timing['immediate_pct']:.1f}%)")
            lines.append(f"Quick Failures (5-15 min): {timing['quick_count']} ({timing['quick_pct']:.1f}%)")
            lines.append(f"Delayed Failures (15+ min): {timing['delayed_count']} ({timing['delayed_pct']:.1f}%)")
            lines.append(f"Median Hold Time: {timing['median_hold_time']:.1f} minutes")
        else:
            lines.append("No losing signals found")
        lines.append("")
        
        # Section 3: Winning Patterns
        lines.append("[3] WINNING SIGNAL HOLD TIME ANALYSIS")
        lines.append("-"*80)
        winners = self.analyze_winning_patterns()
        if winners:
            lines.append(f"Total Winners: {timing['total_losses'] if timing else 0}")
            lines.append(f"Overall Median Hold: {timing['median_hold_time'] if timing else 0:.1f} minutes")
            lines.append(f"Overall Avg Hold: {winners['overall_avg_hold']:.1f} minutes")
            lines.append("")
            for grade, stats in winners['by_grade'].items():
                lines.append(f"{grade} Grade ({stats['count']} signals):")
                lines.append(f"  Median Hold: {stats['median_hold']:.1f} minutes")
                lines.append(f"  Avg Hold: {stats['avg_hold']:.1f} minutes")
                lines.append(f"  Range: {stats['min_hold']:.0f} - {stats['max_hold']:.0f} minutes")
                lines.append(f"  Avg Return: {timing['median_hold_time'] if timing else stats['avg_return']:.2f}%")
                lines.append("")
        else:
            lines.append("No winning signals found")
        lines.append("")
        
        # Section 4: Post-Breakout
        lines.append("[4] POST-BREAKOUT PRICE ACTION ANALYSIS")
        lines.append("-"*80)
        post_bo = self.analyze_post_breakout_behavior()
        if len(post_bo) > 0:
            lines.append(post_bo.to_string(index=False))
        else:
            lines.append("No post-breakout data available")
        lines.append("")
        
        # Recommendations
        lines.append("="*80)
        lines.append("RECOMMENDED CONFIRMATION CRITERIA (DATA-DRIVEN)")
        lines.append("="*80)
        lines.append("")
        lines.append("Based on analysis above, recommendations will be generated...")
        lines.append("(To be implemented based on actual data patterns found)")
        lines.append("")
        
        return "\n".join(lines)
