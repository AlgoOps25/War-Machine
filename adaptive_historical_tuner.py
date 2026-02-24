#!/usr/bin/env python3
"""
Adaptive Historical Parameter Tuner

Auto-detects the schema of your positions table and adapts analysis
to work with whatever columns are available.

Usage:
  $env:DATABASE_URL = "postgresql://..."
  python adaptive_historical_tuner.py
"""
import os
import sys
from typing import Dict, List, Set
from datetime import datetime
from collections import defaultdict
import statistics

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[ERROR] psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)


class AdaptiveHistoricalTuner:
    """Analyzes historical trades with auto-detected schema."""
    
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv('DATABASE_URL')
        
        if not self.db_url:
            print("\n[ERROR] DATABASE_URL not found!")
            self.db_url = input("DATABASE_URL: ").strip()
        
        self.available_columns: Set[str] = set()
        print(f"[INFO] Connecting to Railway database...")
    
    def _get_connection(self):
        """Create PostgreSQL connection."""
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            print(f"[ERROR] Failed to connect: {e}")
            sys.exit(1)
    
    def _detect_schema(self) -> Set[str]:
        """Detect which columns exist in positions table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'positions'
            """)
            
            columns = {row[0] for row in cursor.fetchall()}
            conn.close()
            
            print(f"\n[INFO] Detected {len(columns)} columns in positions table:")
            for col in sorted(columns):
                print(f"  - {col}")
            print()
            
            return columns
            
        except Exception as e:
            print(f"[ERROR] Failed to detect schema: {e}")
            conn.close()
            return set()
    
    def _build_query(self) -> str:
        """Build query based on available columns."""
        # Required columns (use 'pnl' instead of 'realized_pnl')
        required = ['ticker', 'grade', 'entry_price', 'exit_price', 'pnl', 'status']
        
        # Check if we have required columns
        missing = [col for col in required if col not in self.available_columns]
        if missing:
            print(f"[ERROR] Missing required columns: {missing}")
            return None
        
        # Build SELECT with available columns
        select_cols = required.copy()
        
        # Add optional columns if available
        optional = ['exit_reason', 'entry_time', 'exit_time', 'direction', 'stop_price', 't1_price', 't2_price', 'confidence']
        for col in optional:
            if col in self.available_columns:
                select_cols.append(col)
        
        query = f"""
            SELECT {', '.join(select_cols)}
            FROM positions
            WHERE status = 'closed'
              AND grade IS NOT NULL
              AND entry_price IS NOT NULL
              AND exit_price IS NOT NULL
              AND pnl IS NOT NULL
            ORDER BY 
        """
        
        # Use exit_time if available, otherwise entry_time, otherwise just id
        if 'exit_time' in self.available_columns:
            query += "exit_time DESC"
        elif 'entry_time' in self.available_columns:
            query += "entry_time DESC"
        else:
            query += "ticker DESC"  # Fallback
        
        query += " LIMIT 500"
        
        return query
    
    def _get_trades(self) -> List[Dict]:
        """Get historical trades."""
        query = self._build_query()
        if not query:
            return []
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(query)
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            print(f"[INFO] Found {len(trades)} closed trades\n")
            return trades
            
        except Exception as e:
            print(f"[ERROR] Failed to query: {e}")
            conn.close()
            return []
    
    def analyze_grade_performance(self, trades: List[Dict]) -> Dict:
        """Analyze win rate by grade."""
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {}
        expected_wr = {'A+': 75, 'A': 65, 'A-': 55}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            wins = sum(1 for t in grade_trades if float(t['pnl']) > 0)
            win_rate = (wins / len(grade_trades) * 100)
            avg_pnl = statistics.mean([float(t['pnl']) for t in grade_trades])
            
            expected = expected_wr[grade]
            if win_rate >= expected:
                assessment = f"✅ Exceeds target ({expected}%)"
            elif win_rate >= expected - 5:
                assessment = f"⚠️ Slightly below target ({expected}%)"
            else:
                assessment = f"🚨 Below target ({expected}%)"
            
            results[grade] = {
                'count': len(grade_trades),
                'win_rate': round(win_rate, 1),
                'expected': expected,
                'avg_pnl': round(avg_pnl, 2),
                'total_pnl': round(sum(float(t['pnl']) for t in grade_trades), 2),
                'assessment': assessment
            }
        
        return results
    
    def analyze_stop_effectiveness(self, trades: List[Dict]) -> Dict:
        """Analyze stop loss effectiveness if stop_price column exists."""
        if 'stop_price' not in self.available_columns:
            return {}
        
        by_grade = defaultdict(list)
        for trade in trades:
            if trade.get('stop_price'):
                by_grade[trade['grade']].append(trade)
        
        results = {}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            stop_hits = sum(1 for t in grade_trades if t.get('exit_reason') == 'stop_loss')
            stop_hit_rate = (stop_hits / len(grade_trades) * 100)
            
            # Calculate average stop width
            widths = []
            for t in grade_trades:
                entry = float(t['entry_price'])
                stop = float(t['stop_price'])
                width = abs(stop - entry) / entry * 100
                widths.append(width)
            
            avg_width = statistics.mean(widths) if widths else 0
            
            # Recommendation
            if stop_hit_rate > 35:
                recommendation = f"🚨 High stop hit rate ({stop_hit_rate:.1f}%) - Consider widening stops"
            elif stop_hit_rate < 15:
                recommendation = f"⚠️ Low stop hit rate ({stop_hit_rate:.1f}%) - Could tighten stops"
            else:
                recommendation = f"✅ Optimal stop hit rate ({stop_hit_rate:.1f}%)"
            
            results[grade] = {
                'trades': len(grade_trades),
                'stop_hit_rate': round(stop_hit_rate, 1),
                'avg_width_pct': round(avg_width, 2),
                'recommendation': recommendation
            }
        
        return results
    
    def analyze_ticker_performance(self, trades: List[Dict]) -> Dict:
        """Analyze performance by ticker."""
        by_ticker = defaultdict(list)
        for trade in trades:
            by_ticker[trade['ticker']].append(float(trade['pnl']))
        
        results = {}
        for ticker, pnls in by_ticker.items():
            if len(pnls) >= 2:
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / len(pnls) * 100)
                results[ticker] = {
                    'count': len(pnls),
                    'win_rate': round(win_rate, 1),
                    'avg_pnl': round(statistics.mean(pnls), 2),
                    'total_pnl': round(sum(pnls), 2)
                }
        
        # Sort by total P&L
        sorted_tickers = sorted(
            results.items(),
            key=lambda x: x[1]['total_pnl'],
            reverse=True
        )
        
        return dict(sorted_tickers)
    
    def generate_report(self) -> str:
        """Generate report."""
        # Detect schema
        self.available_columns = self._detect_schema()
        if not self.available_columns:
            return "[ERROR] Could not detect table schema."
        
        # Get trades
        trades = self._get_trades()
        if len(trades) < 5:
            return f"\n[ERROR] Only {len(trades)} trades found. Need at least 5 for analysis.\n"
        
        lines = []
        lines.append("\n" + "="*100)
        lines.append("HISTORICAL PERFORMANCE ANALYSIS")
        lines.append("="*100)
        lines.append(f"Total Trades: {len(trades)}")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Overall stats
        total_pnl = sum(float(t['pnl']) for t in trades)
        wins = sum(1 for t in trades if float(t['pnl']) > 0)
        overall_wr = (wins / len(trades) * 100)
        
        lines.append("="*100)
        lines.append("OVERALL PERFORMANCE")
        lines.append("="*100)
        lines.append(f"Total P&L: ${total_pnl:,.2f}")
        lines.append(f"Win Rate: {overall_wr:.1f}% ({wins}W-{len(trades)-wins}L)")
        lines.append(f"Avg P&L per trade: ${total_pnl/len(trades):,.2f}\n")
        
        # Grade performance
        lines.append("="*100)
        lines.append("GRADE PERFORMANCE")
        lines.append("="*100)
        
        grade_analysis = self.analyze_grade_performance(trades)
        for grade in ['A+', 'A', 'A-']:
            if grade in grade_analysis:
                data = grade_analysis[grade]
                lines.append(f"\n{grade}:")
                lines.append(f"  Trades: {data['count']}")
                lines.append(f"  Win Rate: {data['win_rate']:.1f}% (target: {data['expected']}%)")
                lines.append(f"  Avg P&L: ${data['avg_pnl']:.2f}")
                lines.append(f"  Total P&L: ${data['total_pnl']:.2f}")
                lines.append(f"  {data['assessment']}")
        lines.append("")
        
        # Stop loss analysis (if available)
        stop_analysis = self.analyze_stop_effectiveness(trades)
        if stop_analysis:
            lines.append("="*100)
            lines.append("STOP LOSS ANALYSIS")
            lines.append("="*100)
            
            for grade in ['A+', 'A', 'A-']:
                if grade in stop_analysis:
                    data = stop_analysis[grade]
                    lines.append(f"\n{grade}:")
                    lines.append(f"  Trades: {data['trades']}")
                    lines.append(f"  Stop Hit Rate: {data['stop_hit_rate']:.1f}%")
                    lines.append(f"  Avg Stop Width: {data['avg_width_pct']:.2f}%")
                    lines.append(f"  {data['recommendation']}")
            lines.append("")
        
        # Ticker performance
        lines.append("="*100)
        lines.append("TICKER PERFORMANCE (Top 10 by Total P&L)")
        lines.append("="*100 + "\n")
        
        ticker_analysis = self.analyze_ticker_performance(trades)
        for i, (ticker, data) in enumerate(list(ticker_analysis.items())[:10], 1):
            lines.append(
                f"{i:2d}. {ticker:<8} | "
                f"WR: {data['win_rate']:>5.1f}%  | "
                f"Trades: {data['count']:>3}  | "
                f"Avg: ${data['avg_pnl']:>7.2f}  | "
                f"Total: ${data['total_pnl']:>8.2f}"
            )
        lines.append("")
        
        # Recommendations
        lines.append("="*100)
        lines.append("RECOMMENDATIONS")
        lines.append("="*100)
        
        # Grade-based recommendations
        for grade, data in grade_analysis.items():
            if data['win_rate'] < data['expected'] - 10:
                lines.append(f"🚨 {grade} grade underperforming significantly - review grading criteria")
            elif data['count'] < 5:
                lines.append(f"⚠️ {grade} grade has limited data ({data['count']} trades) - collect more")
        
        # Ticker recommendations
        best_tickers = [t for t, d in ticker_analysis.items() if d['win_rate'] >= 70 and d['count'] >= 5]
        worst_tickers = [t for t, d in ticker_analysis.items() if d['win_rate'] < 40 and d['count'] >= 5]
        
        if best_tickers:
            lines.append(f"\n✅ High-performing tickers (70%+ WR, 5+ trades): {', '.join(best_tickers)}")
        if worst_tickers:
            lines.append(f"⚠️ Low-performing tickers (<40% WR, 5+ trades): {', '.join(worst_tickers)}")
        
        if not best_tickers and not worst_tickers:
            lines.append("\nℹ️  No clear ticker patterns yet (need 5+ trades per ticker with 70%+ or <40% WR)")
        
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("ADAPTIVE HISTORICAL PARAMETER TUNER")
    print("Auto-detecting Database Schema")
    print("="*80 + "\n")
    
    tuner = AdaptiveHistoricalTuner()
    report = tuner.generate_report()
    print(report)
    
    # Save to file
    output_file = f"historical_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(output_file, 'w') as f:
        f.write(report)
    
    print(f"[INFO] Report saved to: {output_file}")
