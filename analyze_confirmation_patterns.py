"""
Data-Driven Confirmation Analysis

Mines signal_analytics database and EODHD historical data to determine:
  1. What differentiates A+/A winners from losers?
  2. How long do winning breakouts hold before confirming?
  3. What volume/price patterns exist in the bars AFTER breakout?
  4. What EODHD indicators correlate with signal success?

Goal: Replace arbitrary confirmation timers with data-backed criteria.
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
from zoneinfo import ZoneInfo

# EODHD integration
try:
    from eodhd_client import eodhd_client
    EODHD_AVAILABLE = True
except ImportError:
    EODHD_AVAILABLE = False
    print("[ANALYSIS] ⚠️ EODHD client not available - limited to local DB analysis")

# Database connection
try:
    from data_manager import data_manager
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("[ANALYSIS] ⚠️ data_manager not available")

ET = ZoneInfo("America/New_York")


class ConfirmationAnalyzer:
    """Analyze historical signals to extract confirmation patterns."""
    
    def __init__(self, db_path: str = "signal_analytics.db"):
        """Initialize analyzer with signal analytics database."""
        self.db_path = db_path
        self.conn = None
        
        try:
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row
            print(f"[ANALYSIS] ✅ Connected to {db_path}")
        except Exception as e:
            print(f"[ANALYSIS] ❌ Database connection error: {e}")
    
    def get_grade_performance(self) -> pd.DataFrame:
        """
        Get win rate by signal grade.
        
        Returns:
            DataFrame with grade, win_rate, total_signals, avg_return
        """
        query = """
        SELECT 
            grade,
            COUNT(*) as total_signals,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            AVG(CASE WHEN outcome = 'win' THEN return_pct ELSE NULL END) as avg_win_pct,
            AVG(CASE WHEN outcome = 'loss' THEN return_pct ELSE NULL END) as avg_loss_pct,
            AVG(return_pct) as avg_return_pct,
            AVG(confidence) as avg_confidence
        FROM signals
        WHERE outcome IN ('win', 'loss')
        GROUP BY grade
        ORDER BY grade
        """
        
        df = pd.read_sql_query(query, self.conn)
        df['win_rate'] = df['wins'] / df['total_signals'] * 100
        
        return df
    
    def get_signal_characteristics(self, grade_filter: Optional[str] = None) -> pd.DataFrame:
        """
        Get detailed signal characteristics.
        
        Args:
            grade_filter: Filter by grade (e.g., 'A+', 'A')
        
        Returns:
            DataFrame with signal details
        """
        query = """
        SELECT 
            signal_id,
            ticker,
            grade,
            direction,
            confidence,
            entry_price,
            stop_price,
            t1_price,
            t2_price,
            exit_price,
            outcome,
            return_pct,
            hold_time_minutes,
            generated_at,
            filled_at,
            closed_at
        FROM signals
        WHERE outcome IN ('win', 'loss')
        """
        
        if grade_filter:
            query += f" AND grade = '{grade_filter}'"
        
        query += " ORDER BY generated_at DESC"
        
        df = pd.read_sql_query(query, self.conn)
        
        # Calculate signal characteristics
        df['risk_dollars'] = abs(df['entry_price'] - df['stop_price'])
        df['reward_dollars'] = abs(df['t2_price'] - df['entry_price'])
        df['rr_ratio'] = df['reward_dollars'] / df['risk_dollars']
        df['stop_distance_pct'] = abs(df['entry_price'] - df['stop_price']) / df['entry_price'] * 100
        
        return df
    
    def analyze_time_to_failure(self) -> Dict:
        """
        Analyze how quickly losing signals fail.
        
        Key Question: Do losing signals fail IMMEDIATELY or after holding?
        
        Returns:
            Dict with timing statistics for losses
        """
        query = """
        SELECT 
            ticker,
            grade,
            confidence,
            hold_time_minutes,
            return_pct,
            generated_at,
            filled_at,
            closed_at
        FROM signals
        WHERE outcome = 'loss'
        ORDER BY hold_time_minutes
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        if len(df) == 0:
            return {'error': 'No losing signals found'}
        
        # Categorize losses by timing
        immediate_losses = df[df['hold_time_minutes'] < 5]  # <5 minutes
        quick_losses = df[(df['hold_time_minutes'] >= 5) & (df['hold_time_minutes'] < 15)]  # 5-15 min
        delayed_losses = df[df['hold_time_minutes'] >= 15]  # 15+ minutes
        
        return {
            'total_losses': len(df),
            'immediate_losses': len(immediate_losses),
            'quick_losses': len(quick_losses),
            'delayed_losses': len(delayed_losses),
            'immediate_pct': len(immediate_losses) / len(df) * 100,
            'quick_pct': len(quick_losses) / len(df) * 100,
            'delayed_pct': len(delayed_losses) / len(df) * 100,
            'median_hold_time': df['hold_time_minutes'].median(),
            'avg_hold_time': df['hold_time_minutes'].mean(),
            'immediate_avg_loss': immediate_losses['return_pct'].mean() if len(immediate_losses) > 0 else None,
            'delayed_avg_loss': delayed_losses['return_pct'].mean() if len(delayed_losses) > 0 else None
        }
    
    def analyze_winning_patterns(self) -> Dict:
        """
        Analyze characteristics of winning signals.
        
        Key Questions:
        - How long do winners hold before hitting target?
        - Do winners pullback first or go straight to target?
        - What's the typical hold time for A+/A winners?
        
        Returns:
            Dict with winning signal patterns
        """
        query = """
            SELECT
                ticker,
                grade,
                confidence,
                CAST((julianday(closed_at) - julianday(filled_at)) * 24 * 60 AS REAL) as hold_time_minutes,
                return_pct,
                generated_at,
                filled_at,
                closed_at
            FROM signals
            WHERE outcome = 'loss'
                AND filled_at IS NOT NULL
                AND closed_at IS NOT NULL
            ORDER BY hold_time_minutes
        """
                
        df = pd.read_sql_query(query, self.conn)
        
        if len(df) == 0:
            return {'error': 'No winning signals found'}
        
        # Separate by grade
        a_plus = df[df['grade'] == 'A+']
        a_grade = df[df['grade'] == 'A']
        b_plus = df[df['grade'] == 'B+']
        
        def grade_stats(df_grade, grade_name):
            if len(df_grade) == 0:
                return None
            return {
                'grade': grade_name,
                'count': len(df_grade),
                'median_hold_time': df_grade['hold_time_minutes'].median(),
                'avg_hold_time': df_grade['hold_time_minutes'].mean(),
                'min_hold_time': df_grade['hold_time_minutes'].min(),
                'max_hold_time': df_grade['hold_time_minutes'].max(),
                'avg_return': df_grade['return_pct'].mean(),
                'avg_confidence': df_grade['confidence'].mean()
            }
        
        return {
            'total_winners': len(df),
            'a_plus_stats': grade_stats(a_plus, 'A+'),
            'a_stats': grade_stats(a_grade, 'A'),
            'b_plus_stats': grade_stats(b_plus, 'B+'),
            'overall_median_hold': df['hold_time_minutes'].median(),
            'overall_avg_hold': df['hold_time_minutes'].mean()
        }
    
    def get_post_breakout_bars(self, ticker: str, breakout_time: datetime, num_bars: int = 5) -> Optional[pd.DataFrame]:
        """
        Fetch bars AFTER breakout from data_manager.
        
        Args:
            ticker: Stock ticker
            breakout_time: Time of breakout signal
            num_bars: Number of bars after breakout to fetch
        
        Returns:
            DataFrame with OHLCV data for bars following breakout
        """
        if not DB_AVAILABLE:
            return None
        
        try:
            # Get bars from database
            bars = data_manager.get_today_5m_bars(ticker)
            
            if not bars:
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(bars)
            df['time'] = pd.to_datetime(df['time'])
            
            # Filter to bars after breakout
            post_breakout = df[df['time'] > breakout_time].head(num_bars)
            
            return post_breakout
        
        except Exception as e:
            print(f"[ANALYSIS] Error fetching post-breakout bars: {e}")
            return None
    
    def analyze_post_breakout_behavior(self) -> Dict:
        """
        Analyze price/volume behavior in the bars AFTER breakout.
        
        Key Questions:
        - Do winning signals show sustained volume?
        - Do winning signals hold above breakout level?
        - How many bars does it take to confirm?
        
        Returns:
            Dict with post-breakout patterns
        """
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
            return {'error': 'No signals with fill data'}
        
        # Analyze post-breakout behavior for each signal
        results = []
        
        for _, signal in df.iterrows():
            try:
                breakout_time = datetime.fromisoformat(signal['generated_at'])
                
                # Get 5 bars after breakout (25 minutes on 5m chart)
                post_bars = self.get_post_breakout_bars(
                    signal['ticker'],
                    breakout_time,
                    num_bars=5
                )
                
                if post_bars is not None and len(post_bars) > 0:
                    entry = signal['entry_price']
                    
                    # Calculate holding pattern
                    bars_above_entry = sum(post_bars['close'] > entry)
                    bars_below_entry = sum(post_bars['close'] < entry)
                    
                    # Calculate volume pattern
                    avg_volume = post_bars['volume'].mean()
                    first_bar_volume = post_bars.iloc[0]['volume']
                    
                    results.append({
                        'signal_id': signal['signal_id'],
                        'ticker': signal['ticker'],
                        'grade': signal['grade'],
                        'outcome': signal['outcome'],
                        'bars_above_entry': bars_above_entry,
                        'bars_below_entry': bars_below_entry,
                        'avg_volume': avg_volume,
                        'first_bar_volume': first_bar_volume
                    })
            
            except Exception as e:
                print(f"[ANALYSIS] Error analyzing signal {signal['signal_id']}: {e}")
                continue
        
        if len(results) == 0:
            return {'error': 'No post-breakout data available'}
        
        results_df = pd.DataFrame(results)
        
        # Compare winners vs losers
        winners = results_df[results_df['outcome'] == 'win']
        losers = results_df[results_df['outcome'] == 'loss']
        
        return {
            'total_analyzed': len(results_df),
            'winners': {
                'count': len(winners),
                'avg_bars_above_entry': winners['bars_above_entry'].mean() if len(winners) > 0 else None,
                'avg_bars_below_entry': winners['bars_below_entry'].mean() if len(winners) > 0 else None
            },
            'losers': {
                'count': len(losers),
                'avg_bars_above_entry': losers['bars_above_entry'].mean() if len(losers) > 0 else None,
                'avg_bars_below_entry': losers['bars_below_entry'].mean() if len(losers) > 0 else None
            }
        }
    
    def fetch_eodhd_indicators(self, ticker: str, start_date: str, end_date: str) -> Optional[Dict]:
        """
        Fetch EODHD technical indicators for analysis.
        
        Indicators to analyze:
        - RSI (momentum)
        - ADX (trend strength)
        - MACD (trend direction)
        - Bollinger Bands (volatility)
        - Volume indicators
        
        Args:
            ticker: Stock ticker
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
        
        Returns:
            Dict with indicator data
        """
        if not EODHD_AVAILABLE:
            return None
        
        try:
            # Fetch multiple indicators
            indicators = {}
            
            # RSI
            rsi_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='rsi',
                period=14,
                from_date=start_date,
                to_date=end_date
            )
            indicators['rsi'] = rsi_data
            
            # ADX (trend strength)
            adx_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='adx',
                period=14,
                from_date=start_date,
                to_date=end_date
            )
            indicators['adx'] = adx_data
            
            # MACD
            macd_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='macd',
                from_date=start_date,
                to_date=end_date
            )
            indicators['macd'] = macd_data
            
            return indicators
        
        except Exception as e:
            print(f"[ANALYSIS] Error fetching EODHD indicators: {e}")
            return None
    
    def generate_full_report(self) -> str:
        """
        Generate comprehensive analysis report.
        
        Returns:
            Formatted string report
        """
        report = []
        report.append("="*80)
        report.append("CONFIRMATION PATTERN ANALYSIS - DATA-DRIVEN INSIGHTS")
        report.append("="*80)
        report.append("")
        
        # 1. Grade Performance
        report.append("[1] SIGNAL GRADE PERFORMANCE")
        report.append("-"*80)
        grade_perf = self.get_grade_performance()
        report.append(grade_perf.to_string(index=False))
        report.append("")
        
        # 2. Time to Failure Analysis
        report.append("[2] LOSING SIGNAL TIMING ANALYSIS")
        report.append("-"*80)
        failure_timing = self.analyze_time_to_failure()
        
        if 'error' not in failure_timing:
            report.append(f"Total Losses: {failure_timing['total_losses']}")
            report.append(f"Immediate Failures (<5 min): {failure_timing['immediate_losses']} ({failure_timing['immediate_pct']:.1f}%)")
            report.append(f"Quick Failures (5-15 min): {failure_timing['quick_losses']} ({failure_timing['quick_pct']:.1f}%)")
            report.append(f"Delayed Failures (15+ min): {failure_timing['delayed_losses']} ({failure_timing['delayed_pct']:.1f}%)")
            report.append(f"Median Hold Time: {failure_timing['median_hold_time']:.1f} minutes")
            
            if failure_timing['immediate_avg_loss']:
                report.append(f"Avg Immediate Loss: {failure_timing['immediate_avg_loss']:.2f}%")
            if failure_timing['delayed_avg_loss']:
                report.append(f"Avg Delayed Loss: {failure_timing['delayed_avg_loss']:.2f}%")
        else:
            report.append(failure_timing['error'])
        
        report.append("")
        
        # 3. Winning Signal Patterns
        report.append("[3] WINNING SIGNAL HOLD TIME ANALYSIS")
        report.append("-"*80)
        winning_patterns = self.analyze_winning_patterns()
        
        if 'error' not in winning_patterns:
            report.append(f"Total Winners: {winning_patterns['total_winners']}")
            report.append(f"Overall Median Hold: {winning_patterns['overall_median_hold']:.1f} minutes")
            report.append(f"Overall Avg Hold: {winning_patterns['overall_avg_hold']:.1f} minutes")
            report.append("")
            
            for grade_key in ['a_plus_stats', 'a_stats', 'b_plus_stats']:
                if winning_patterns[grade_key]:
                    stats = winning_patterns[grade_key]
                    report.append(f"{stats['grade']} Grade ({stats['count']} signals):")
                    report.append(f"  Median Hold: {stats['median_hold_time']:.1f} minutes")
                    report.append(f"  Avg Hold: {stats['avg_hold_time']:.1f} minutes")
                    report.append(f"  Range: {stats['min_hold_time']:.0f} - {stats['max_hold_time']:.0f} minutes")
                    report.append(f"  Avg Return: {stats['avg_return']:.2f}%")
                    report.append("")
        else:
            report.append(winning_patterns['error'])
        
        report.append("")
        
        # 4. Post-Breakout Behavior
        report.append("[4] POST-BREAKOUT PRICE ACTION ANALYSIS")
        report.append("-"*80)
        post_breakout = self.analyze_post_breakout_behavior()
        
        if 'error' not in post_breakout:
            report.append(f"Signals Analyzed: {post_breakout['total_analyzed']}")
            report.append("")
            
            if post_breakout['winners']['count'] > 0:
                report.append("Winners (bars holding above entry in next 25 minutes):")
                report.append(f"  Avg Bars Above Entry: {post_breakout['winners']['avg_bars_above_entry']:.1f} / 5")
                report.append(f"  Avg Bars Below Entry: {post_breakout['winners']['avg_bars_below_entry']:.1f} / 5")
                report.append("")
            
            if post_breakout['losers']['count'] > 0:
                report.append("Losers (bars holding above entry in next 25 minutes):")
                report.append(f"  Avg Bars Above Entry: {post_breakout['losers']['avg_bars_above_entry']:.1f} / 5")
                report.append(f"  Avg Bars Below Entry: {post_breakout['losers']['avg_bars_below_entry']:.1f} / 5")
        else:
            report.append(post_breakout['error'])
        
        report.append("")
        report.append("="*80)
        report.append("RECOMMENDED CONFIRMATION CRITERIA (DATA-DRIVEN)")
        report.append("="*80)
        report.append("")
        report.append("Based on analysis above, recommendations will be generated...")
        report.append("(To be implemented based on actual data patterns found)")
        report.append("")
        
        return "\n".join(report)
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


# ========================================
# MAIN EXECUTION
# ========================================
if __name__ == "__main__":
    print("\n" + "="*80)
    print("DATA-DRIVEN CONFIRMATION ANALYSIS")
    print("Mining signal_analytics.db for optimal confirmation criteria")
    print("="*80 + "\n")
    
    analyzer = ConfirmationAnalyzer()
    
    try:
        # Generate full report
        report = analyzer.generate_full_report()
        print(report)
        
        # Save report to file
        timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        filename = f"confirmation_analysis_{timestamp}.txt"
        
        with open(filename, 'w') as f:
            f.write(report)
        
        print(f"\n✅ Report saved to: {filename}\n")
    
    finally:
        analyzer.close()
