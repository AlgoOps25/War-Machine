#!/usr/bin/env python3
"""
Remote Historical Parameter Tuner

Connects to Railway PostgreSQL database to analyze historical trades
and generate parameter optimization recommendations.

Usage:
  1. Get your Railway PostgreSQL connection string:
     - Go to Railway dashboard
     - Click on your database service
     - Copy DATABASE_URL from Variables tab
  
  2. Set environment variable:
     export DATABASE_URL="postgresql://user:pass@host:port/dbname"
  
  3. Run script:
     python remote_historical_tuner.py

Note: This uses the same analysis logic as historical_tuner.py but
connects to Railway's PostgreSQL instead of local SQLite.
"""
import os
import sys
from typing import Dict, List
from datetime import datetime
from collections import defaultdict
import statistics

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("[ERROR] psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)


class RemoteHistoricalTuner:
    """Analyzes historical trades from Railway database."""
    
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv('DATABASE_URL')
        
        if not self.db_url:
            print("\n[ERROR] DATABASE_URL not found!")
            print("\nPlease provide your Railway PostgreSQL connection string:")
            print("Example: postgresql://user:pass@host:port/dbname\n")
            self.db_url = input("DATABASE_URL: ").strip()
        
        self.min_sample_size = 15
        print(f"[INFO] Connecting to Railway database...")
    
    def _get_connection(self):
        """Create PostgreSQL connection."""
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            print(f"[ERROR] Failed to connect to database: {e}")
            sys.exit(1)
    
    def _get_historical_trades(self, min_trades: int = 50) -> List[Dict]:
        """Retrieve historical trades from Railway database."""
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT 
                    ticker,
                    signal_type,
                    direction,
                    grade,
                    entry_price,
                    exit_price,
                    stop_loss,
                    target_1,
                    target_2,
                    realized_pnl,
                    exit_reason,
                    entry_time,
                    exit_time,
                    sector
                FROM positions
                WHERE status = 'closed'
                  AND grade IS NOT NULL
                  AND entry_price IS NOT NULL
                  AND exit_price IS NOT NULL
                ORDER BY exit_time DESC
                LIMIT 500
            """)
            
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            print(f"[INFO] Found {len(trades)} historical trades")
            
            if len(trades) < min_trades:
                print(f"[WARNING] Only {len(trades)} trades found. Need minimum {min_trades} for reliable analysis.")
                print(f"[WARNING] Results may not be statistically significant.\n")
            
            return trades
            
        except Exception as e:
            print(f"[ERROR] Failed to query database: {e}")
            conn.close()
            return []
    
    def analyze_grade_performance(self, trades: List[Dict]) -> Dict:
        """Validate grading system accuracy."""
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {}
        expected_wr = {'A+': 75, 'A': 65, 'A-': 55}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            wins = sum(1 for t in grade_trades if t['realized_pnl'] > 0)
            win_rate = (wins / len(grade_trades) * 100)
            
            # Calculate avg R:R
            rr_list = []
            for t in grade_trades:
                if t['entry_price'] and t['stop_loss']:
                    risk = abs(t['entry_price'] - t['stop_loss'])
                    reward = abs(t['exit_price'] - t['entry_price'])
                    rr = (reward / risk) if risk > 0 else 0
                    rr_list.append(rr)
            
            avg_rr = statistics.mean(rr_list) if rr_list else 0
            avg_pnl = statistics.mean([t['realized_pnl'] for t in grade_trades])
            
            expected = expected_wr[grade]
            if win_rate >= expected:
                assessment = f"✅ Exceeds target ({expected}%) - Grading accurate"
            elif win_rate >= expected - 5:
                assessment = f"⚠️ Slightly below target ({expected}%) - Acceptable"
            else:
                assessment = f"🚨 Below target ({expected}%) - Review grading criteria"
            
            results[grade] = {
                'count': len(grade_trades),
                'win_rate': round(win_rate, 1),
                'expected_win_rate': expected,
                'avg_rr_achieved': round(avg_rr, 2),
                'avg_pnl': round(avg_pnl, 2),
                'assessment': assessment
            }
        
        return results
    
    def analyze_stop_widths(self, trades: List[Dict]) -> Dict:
        """Analyze stop loss effectiveness."""
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {'by_grade': {}}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            stop_widths = []
            stop_hits = 0
            rr_achieved = []
            
            for trade in grade_trades:
                if trade['entry_price'] and trade['stop_loss']:
                    width = abs(trade['stop_loss'] - trade['entry_price']) / trade['entry_price'] * 100
                    stop_widths.append(width)
                    
                    if trade['exit_reason'] == 'stop_loss':
                        stop_hits += 1
                    
                    risk = abs(trade['entry_price'] - trade['stop_loss'])
                    reward = abs(trade['exit_price'] - trade['entry_price'])
                    rr = (reward / risk) if risk > 0 else 0
                    rr_achieved.append(rr)
            
            avg_width = statistics.mean(stop_widths) if stop_widths else 0
            stop_hit_rate = (stop_hits / len(grade_trades) * 100)
            avg_rr = statistics.mean(rr_achieved) if rr_achieved else 0
            
            # Recommendation
            if stop_hit_rate > 35:
                recommended_width = avg_width * 1.15
                recommendation = f"🚨 High stop hit rate ({stop_hit_rate:.1f}%) - WIDEN stops by 15%"
            elif stop_hit_rate < 15:
                recommended_width = avg_width * 0.90
                recommendation = f"⚠️ Low stop hit rate ({stop_hit_rate:.1f}%) - Consider TIGHTENING by 10%"
            else:
                recommended_width = avg_width
                recommendation = f"✅ Optimal stop hit rate ({stop_hit_rate:.1f}%) - Keep current width"
            
            results['by_grade'][grade] = {
                'trades': len(grade_trades),
                'avg_stop_width_pct': round(avg_width, 2),
                'stop_hit_rate': round(stop_hit_rate, 1),
                'avg_rr_achieved': round(avg_rr, 2),
                'recommended_width_pct': round(recommended_width, 2),
                'recommendation': recommendation
            }
        
        return results
    
    def analyze_ticker_performance(self, trades: List[Dict]) -> Dict:
        """Identify best/worst performing tickers."""
        by_ticker = defaultdict(list)
        for trade in trades:
            by_ticker[trade['ticker']].append(trade['realized_pnl'])
        
        ticker_results = {}
        for ticker, pnls in by_ticker.items():
            if len(pnls) >= 3:
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / len(pnls) * 100)
                ticker_results[ticker] = {
                    'count': len(pnls),
                    'win_rate': round(win_rate, 1),
                    'avg_pnl': round(statistics.mean(pnls), 2)
                }
        
        whitelist = [
            ticker for ticker, data in ticker_results.items()
            if data['win_rate'] >= 70 and data['count'] >= 5
        ]
        
        blacklist = [
            ticker for ticker, data in ticker_results.items()
            if data['win_rate'] < 40 and data['count'] >= 5
        ]
        
        return {
            'by_ticker': ticker_results,
            'recommended_whitelist': sorted(whitelist),
            'recommended_blacklist': sorted(blacklist)
        }
    
    def generate_report(self) -> str:
        """Generate comprehensive tuning report."""
        print("[INFO] Analyzing historical trades...\n")
        
        trades = self._get_historical_trades()
        
        if len(trades) < 20:
            return (
                f"\n[ERROR] Insufficient data for analysis.\n"
                f"Found {len(trades)} trades. Need minimum 20 closed trades.\n"
                f"Continue trading to accumulate more data.\n"
            )
        
        lines = []
        lines.append("\n" + "="*100)
        lines.append("HISTORICAL PARAMETER TUNING REPORT (RAILWAY DATABASE)")
        lines.append("="*100)
        lines.append(f"Total Historical Trades Analyzed: {len(trades)}")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Grade Performance
        lines.append("="*100)
        lines.append("GRADE PERFORMANCE VALIDATION")
        lines.append("="*100)
        
        grade_analysis = self.analyze_grade_performance(trades)
        for grade in ['A+', 'A', 'A-']:
            if grade in grade_analysis:
                data = grade_analysis[grade]
                lines.append(f"\n{grade}:")
                lines.append(f"  Trades: {data['count']}")
                lines.append(f"  Win Rate: {data['win_rate']:.1f}% (target: {data['expected_win_rate']}%)")
                lines.append(f"  Avg R:R: {data['avg_rr_achieved']:.2f}")
                lines.append(f"  Avg P&L: ${data['avg_pnl']:.2f}")
                lines.append(f"  {data['assessment']}")
        lines.append("")
        
        # Stop Loss Analysis
        lines.append("="*100)
        lines.append("STOP LOSS WIDTH OPTIMIZATION")
        lines.append("="*100)
        
        stop_analysis = self.analyze_stop_widths(trades)
        for grade in ['A+', 'A', 'A-']:
            if grade in stop_analysis.get('by_grade', {}):
                data = stop_analysis['by_grade'][grade]
                lines.append(f"\n{grade}:")
                lines.append(f"  Trades: {data['trades']}  |  Stop Hit Rate: {data['stop_hit_rate']:.1f}%")
                lines.append(f"  Current Width: {data['avg_stop_width_pct']:.2f}%  |  Recommended: {data['recommended_width_pct']:.2f}%")
                lines.append(f"  Avg R:R Achieved: {data['avg_rr_achieved']:.2f}")
                lines.append(f"  {data['recommendation']}")
        lines.append("")
        
        # Ticker Performance
        lines.append("="*100)
        lines.append("TICKER PERFORMANCE ANALYSIS")
        lines.append("="*100)
        
        ticker_analysis = self.analyze_ticker_performance(trades)
        
        if ticker_analysis.get('recommended_whitelist'):
            lines.append("\nRecommended Whitelist (70%+ win rate, 5+ trades):")
            for ticker in ticker_analysis['recommended_whitelist']:
                data = ticker_analysis['by_ticker'][ticker]
                lines.append(f"  {ticker:<6} |  Win Rate: {data['win_rate']:.1f}%  ({data['count']} trades)  |  Avg P&L: ${data['avg_pnl']:.2f}")
        
        if ticker_analysis.get('recommended_blacklist'):
            lines.append("\nRecommended Blacklist (<40% win rate, 5+ trades):")
            for ticker in ticker_analysis['recommended_blacklist']:
                data = ticker_analysis['by_ticker'][ticker]
                lines.append(f"  {ticker:<6} |  Win Rate: {data['win_rate']:.1f}%  ({data['count']} trades)  |  Avg P&L: ${data['avg_pnl']:.2f}")
        
        if not ticker_analysis.get('recommended_whitelist') and not ticker_analysis.get('recommended_blacklist'):
            lines.append("\nNo strong ticker patterns identified yet. Continue collecting data.")
        lines.append("")
        
        # Action Items
        lines.append("="*100)
        lines.append("RECOMMENDED ACTIONS")
        lines.append("="*100)
        lines.append("1. Adjust stop loss widths based on recommendations above")
        lines.append("2. Review ticker whitelist/blacklist for position selection")
        lines.append("3. Deploy Phase 4 monitoring for ongoing optimization")
        lines.append("4. Re-run this analysis after 50+ more trades for updated recommendations")
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("REMOTE HISTORICAL PARAMETER TUNER")
    print("Analyzing Railway Production Database")
    print("="*80 + "\n")
    
    tuner = RemoteHistoricalTuner()
    report = tuner.generate_report()
    print(report)
    
    # Save to file
    output_file = f"historical_tuning_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(output_file, 'w') as f:
        f.write(report)
    
    print(f"\n[INFO] Report saved to: {output_file}")
