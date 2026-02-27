#!/usr/bin/env python3
"""
Historical Parameter Tuning System

Optimizes system parameters using existing trade history from the positions table.
Provides immediate parameter recommendations without waiting for live data collection.

Advantages:
  - Immediate optimization using past performance
  - No need to wait 10-14 days for data collection
  - Analyzes actual trade outcomes (P&L, R:R, win rate)
  - Validates grading system accuracy
  - Identifies best performing setups and timeframes

Requirements:
  - Minimum 50 closed trades in positions table
  - Trades should have grade, entry/exit prices, stop loss
  - More data = better statistical significance

Usage:
  from historical_tuner import historical_tuner
  
  # Generate full historical tuning report:
  report = historical_tuner.generate_historical_tuning_report()
  print(report)
  
  # Apply recommendations to config.py and redeploy
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter
import statistics
from db_connection import get_conn, ph, dict_cursor
import config

ET = ZoneInfo("America/New_York")


class HistoricalParameterTuner:
    """Optimizes parameters using historical trade data."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.min_sample_size = 15  # Minimum trades per bucket
    
    def _get_historical_trades(self, min_trades: int = 50) -> List[Dict]:
        """
        Retrieve historical closed trades from positions table.
        
        Args:
            min_trades: Minimum number of trades required
        
        Returns:
            List of trade dicts
        """
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
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
                base_confidence,
                sector
            FROM positions
            WHERE status = 'closed'
              AND grade IS NOT NULL
              AND entry_price IS NOT NULL
              AND exit_price IS NOT NULL
            ORDER BY exit_time DESC
            LIMIT 500
        """)
        
        trades = cursor.fetchall()
        conn.close()
        
        if len(trades) < min_trades:
            print(f"[HISTORICAL TUNER] Warning: Only {len(trades)} trades found. Need minimum {min_trades} for reliable analysis.")
        
        return trades
    
    def analyze_historical_confidence_thresholds(self, trades: List[Dict] = None) -> Dict:
        """
        Analyze win rate by confidence bucket using historical trades.
        
        Returns:
            {
                'by_grade': {
                    'A+': {
                        'confidence_buckets': [...],
                        'current_threshold': float,
                        'recommended_threshold': float,
                        'expected_improvement': str
                    },
                    ...
                }
            }
        """
        if trades is None:
            trades = self._get_historical_trades()
        
        if not trades:
            return {'by_grade': {}, 'insufficient_data': True}
        
        # Filter trades with confidence data
        trades_with_conf = [t for t in trades if t.get('base_confidence') is not None]
        
        if not trades_with_conf:
            print("[HISTORICAL TUNER] No trades with confidence data found. Using grade-based analysis only.")
            trades_with_conf = trades  # Fall back to all trades
        
        # Group by grade and confidence bucket
        by_grade = defaultdict(lambda: defaultdict(list))
        
        for trade in trades_with_conf:
            grade = trade['grade']
            # Use base_confidence if available, otherwise estimate from grade
            if trade.get('base_confidence'):
                confidence = trade['base_confidence']
            else:
                # Estimate confidence from grade (middle of typical range)
                grade_estimates = {'A+': 0.78, 'A': 0.72, 'A-': 0.68}
                confidence = grade_estimates.get(grade, 0.70)
            
            pnl = trade['realized_pnl']
            
            # Bucket into 0.05 ranges
            bucket = int(confidence * 20) / 20
            by_grade[grade][bucket].append(pnl)
        
        results = {'by_grade': {}}
        
        for grade in ['A+', 'A', 'A-']:
            grade_buckets = []
            
            for conf_bucket in sorted(by_grade[grade].keys()):
                pnls = by_grade[grade][conf_bucket]
                count = len(pnls)
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / count * 100) if count > 0 else 0
                avg_pnl = statistics.mean(pnls) if pnls else 0
                
                grade_buckets.append({
                    'range': f"{conf_bucket:.2f}-{conf_bucket+0.05:.2f}",
                    'count': count,
                    'win_rate': round(win_rate, 1),
                    'avg_pnl': round(avg_pnl, 2)
                })
            
            # Find optimal threshold (65%+ win rate with sufficient samples)
            recommended = None
            current = config.MIN_CONFIDENCE.get(grade, 0.70)
            
            for bucket in sorted(grade_buckets, key=lambda x: float(x['range'].split('-')[0])):
                if bucket['win_rate'] >= 65 and bucket['count'] >= self.min_sample_size:
                    recommended = float(bucket['range'].split('-')[0])
                    break
            
            # Fallback: find confidence where win rate crosses 60%
            if recommended is None:
                for bucket in sorted(grade_buckets, key=lambda x: float(x['range'].split('-')[0]), reverse=True):
                    if bucket['win_rate'] >= 60:
                        recommended = float(bucket['range'].split('-')[0])
                        break
            
            # Calculate expected improvement
            if recommended and abs(recommended - current) >= 0.03:
                # Find current win rate at current threshold
                current_wr = next(
                    (b['win_rate'] for b in grade_buckets if float(b['range'].split('-')[0]) <= current < float(b['range'].split('-')[1])),
                    None
                )
                # Find expected win rate at recommended threshold
                recommended_wr = next(
                    (b['win_rate'] for b in grade_buckets if float(b['range'].split('-')[0]) <= recommended < float(b['range'].split('-')[1])),
                    None
                )
                
                if current_wr and recommended_wr:
                    improvement = recommended_wr - current_wr
                    expected_improvement = f"+{improvement:.1f}% win rate"
                else:
                    expected_improvement = "Unknown"
            else:
                expected_improvement = "N/A (threshold optimal)"
            
            results['by_grade'][grade] = {
                'confidence_buckets': grade_buckets,
                'current_threshold': current,
                'recommended_threshold': recommended if recommended else current,
                'expected_improvement': expected_improvement,
                'total_trades': sum(b['count'] for b in grade_buckets)
            }
        
        return results
    
    def analyze_historical_stop_widths(self, trades: List[Dict] = None) -> Dict:
        """
        Analyze stop loss effectiveness using historical trades.
        
        Returns:
            {
                'by_grade': {
                    'A+': {
                        'avg_stop_width_pct': float,
                        'stop_hit_rate': float,
                        'avg_rr_achieved': float,
                        'recommended_width_pct': float,
                        'recommendation': str
                    },
                    ...
                },
                'overall': {...}
            }
        """
        if trades is None:
            trades = self._get_historical_trades()
        
        if not trades:
            return {'by_grade': {}, 'insufficient_data': True}
        
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {'by_grade': {}}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            # Calculate stop metrics
            stop_widths = []
            stop_hits = 0
            rr_achieved = []
            
            for trade in grade_trades:
                if trade['entry_price'] and trade['stop_loss']:
                    width = abs(trade['stop_loss'] - trade['entry_price']) / trade['entry_price'] * 100
                    stop_widths.append(width)
                    
                    if trade['exit_reason'] == 'stop_loss':
                        stop_hits += 1
                    
                    # Calculate R:R achieved
                    risk = abs(trade['entry_price'] - trade['stop_loss'])
                    reward = abs(trade['exit_price'] - trade['entry_price'])
                    rr = (reward / risk) if risk > 0 else 0
                    rr_achieved.append(rr)
            
            avg_width = statistics.mean(stop_widths) if stop_widths else 0
            stop_hit_rate = (stop_hits / len(grade_trades) * 100) if grade_trades else 0
            avg_rr = statistics.mean(rr_achieved) if rr_achieved else 0
            
            # Recommendation logic
            # Target: 20-30% stop hit rate
            if stop_hit_rate > 35:
                recommended_width = avg_width * 1.15  # 15% wider
                recommendation = f"🚨 High stop hit rate ({stop_hit_rate:.1f}%) - WIDEN stops by 15%"
            elif stop_hit_rate < 15:
                recommended_width = avg_width * 0.90  # 10% tighter
                recommendation = f"⚠️ Low stop hit rate ({stop_hit_rate:.1f}%) - Consider TIGHTENING stops by 10%"
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
    
    def analyze_grade_performance(self, trades: List[Dict] = None) -> Dict:
        """
        Validate grading system accuracy.
        
        Returns:
            {
                'A+': {'win_rate': float, 'avg_rr': float, 'count': int, 'assessment': str},
                'A': {...},
                'A-': {...}
            }
        """
        if trades is None:
            trades = self._get_historical_trades()
        
        if not trades:
            return {'insufficient_data': True}
        
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {}
        
        # Expected win rates by grade
        expected_wr = {'A+': 75, 'A': 65, 'A-': 55}
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            wins = sum(1 for t in grade_trades if t['realized_pnl'] > 0)
            win_rate = (wins / len(grade_trades) * 100) if grade_trades else 0
            
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
            
            # Assessment
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
    
    def analyze_time_patterns(self, trades: List[Dict] = None) -> Dict:
        """
        Identify best performing times and days.
        
        Returns:
            {
                'by_hour': {hour: {'win_rate': float, 'count': int}},
                'by_day': {day: {'win_rate': float, 'count': int}},
                'best_hours': [list of hours],
                'worst_hours': [list of hours]
            }
        """
        if trades is None:
            trades = self._get_historical_trades()
        
        if not trades:
            return {'insufficient_data': True}
        
        by_hour = defaultdict(list)
        by_day = defaultdict(list)
        
        for trade in trades:
            if trade['entry_time']:
                try:
                    if isinstance(trade['entry_time'], str):
                        dt = datetime.fromisoformat(trade['entry_time'])
                    else:
                        dt = trade['entry_time']
                    
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ET)
                    
                    hour = dt.hour
                    day = dt.strftime('%A')
                    
                    by_hour[hour].append(trade['realized_pnl'])
                    by_day[day].append(trade['realized_pnl'])
                except Exception:
                    continue
        
        # Analyze by hour
        hour_results = {}
        for hour, pnls in by_hour.items():
            if len(pnls) >= 5:  # Min 5 trades
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / len(pnls) * 100)
                hour_results[hour] = {
                    'win_rate': round(win_rate, 1),
                    'count': len(pnls),
                    'avg_pnl': round(statistics.mean(pnls), 2)
                }
        
        # Analyze by day
        day_results = {}
        for day, pnls in by_day.items():
            if len(pnls) >= 5:
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / len(pnls) * 100)
                day_results[day] = {
                    'win_rate': round(win_rate, 1),
                    'count': len(pnls),
                    'avg_pnl': round(statistics.mean(pnls), 2)
                }
        
        # Identify best/worst hours
        sorted_hours = sorted(hour_results.items(), key=lambda x: x[1]['win_rate'], reverse=True)
        best_hours = [h for h, d in sorted_hours[:3] if d['count'] >= 10]
        worst_hours = [h for h, d in sorted_hours[-3:] if d['count'] >= 10]
        
        return {
            'by_hour': hour_results,
            'by_day': day_results,
            'best_hours': best_hours,
            'worst_hours': worst_hours
        }
    
    def analyze_ticker_performance(self, trades: List[Dict] = None) -> Dict:
        """
        Identify best/worst performing tickers.
        
        Returns:
            {
                'by_ticker': {ticker: {'win_rate': float, 'count': int, 'avg_pnl': float}},
                'recommended_whitelist': [tickers],
                'recommended_blacklist': [tickers]
            }
        """
        if trades is None:
            trades = self._get_historical_trades()
        
        if not trades:
            return {'insufficient_data': True}
        
        by_ticker = defaultdict(list)
        for trade in trades:
            by_ticker[trade['ticker']].append(trade['realized_pnl'])
        
        ticker_results = {}
        for ticker, pnls in by_ticker.items():
            if len(pnls) >= 3:  # Min 3 trades
                wins = sum(1 for pnl in pnls if pnl > 0)
                win_rate = (wins / len(pnls) * 100)
                ticker_results[ticker] = {
                    'count': len(pnls),
                    'win_rate': round(win_rate, 1),
                    'avg_pnl': round(statistics.mean(pnls), 2)
                }
        
        # Recommend whitelist (70%+ win rate, 5+ trades)
        whitelist = [
            ticker for ticker, data in ticker_results.items()
            if data['win_rate'] >= 70 and data['count'] >= 5
        ]
        
        # Recommend blacklist (<40% win rate, 5+ trades)
        blacklist = [
            ticker for ticker, data in ticker_results.items()
            if data['win_rate'] < 40 and data['count'] >= 5
        ]
        
        return {
            'by_ticker': ticker_results,
            'recommended_whitelist': sorted(whitelist),
            'recommended_blacklist': sorted(blacklist)
        }
    
    def generate_historical_tuning_report(self) -> str:
        """
        Generate comprehensive historical tuning report.
        
        Returns:
            Formatted report string
        """
        trades = self._get_historical_trades()
        
        if len(trades) < 50:
            return (
                f"\n[HISTORICAL TUNER] Insufficient data for analysis.\n"
                f"Found {len(trades)} trades. Need minimum 50 closed trades.\n"
                f"Continue trading to accumulate more data.\n"
            )
        
        lines = []
        lines.append("\n" + "="*100)
        lines.append("HISTORICAL PARAMETER TUNING REPORT")
        lines.append("="*100)
        lines.append(f"Total Historical Trades Analyzed: {len(trades)}")
        lines.append(f"Generated: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}\n")
        
        # ══════ GRADE PERFORMANCE ══════
        lines.append("═"*100)
        lines.append("GRADE PERFORMANCE VALIDATION")
        lines.append("═"*100)
        
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
        
        # ══════ CONFIDENCE THRESHOLDS ══════
        lines.append("═"*100)
        lines.append("CONFIDENCE THRESHOLD OPTIMIZATION")
        lines.append("═"*100)
        
        conf_analysis = self.analyze_historical_confidence_thresholds(trades)
        for grade in ['A+', 'A', 'A-']:
            if grade in conf_analysis.get('by_grade', {}):
                data = conf_analysis['by_grade'][grade]
                current = data['current_threshold']
                recommended = data['recommended_threshold']
                improvement = data['expected_improvement']
                
                if abs(recommended - current) >= 0.03:
                    direction = "INCREASE" if recommended > current else "DECREASE"
                    lines.append(f"\n📊 {grade}: {direction} threshold from {current:.2f} to {recommended:.2f}")
                    lines.append(f"   Expected Improvement: {improvement}")
                    lines.append(f"   Based on {data['total_trades']} historical trades")
                else:
                    lines.append(f"\n✅ {grade}: Current threshold ({current:.2f}) is optimal")
                    lines.append(f"   Based on {data['total_trades']} historical trades")
        lines.append("")
        
        # ══════ STOP LOSS OPTIMIZATION ══════
        lines.append("═"*100)
        lines.append("STOP LOSS WIDTH OPTIMIZATION")
        lines.append("═"*100)
        
        stop_analysis = self.analyze_historical_stop_widths(trades)
        for grade in ['A+', 'A', 'A-']:
            if grade in stop_analysis.get('by_grade', {}):
                data = stop_analysis['by_grade'][grade]
                lines.append(f"\n{grade}:")
                lines.append(f"  Trades: {data['trades']}  |  Stop Hit Rate: {data['stop_hit_rate']:.1f}%")
                lines.append(f"  Current Width: {data['avg_stop_width_pct']:.2f}%  |  Recommended: {data['recommended_width_pct']:.2f}%")
                lines.append(f"  Avg R:R Achieved: {data['avg_rr_achieved']:.2f}")
                lines.append(f"  {data['recommendation']}")
        lines.append("")
        
        # ══════ TIME PATTERNS ══════
        lines.append("═"*100)
        lines.append("TIME-BASED PERFORMANCE PATTERNS")
        lines.append("═"*100)
        
        time_analysis = self.analyze_time_patterns(trades)
        
        if time_analysis.get('best_hours'):
            lines.append("\nBest Performing Hours (ET):")
            for hour in time_analysis['best_hours']:
                data = time_analysis['by_hour'][hour]
                time_str = f"{hour}:00-{hour}:59"
                lines.append(f"  {time_str}  |  Win Rate: {data['win_rate']:.1f}%  ({data['count']} trades)")
        
        if time_analysis.get('worst_hours'):
            lines.append("\nWorst Performing Hours (ET):")
            for hour in time_analysis['worst_hours']:
                data = time_analysis['by_hour'][hour]
                time_str = f"{hour}:00-{hour}:59"
                lines.append(f"  {time_str}  |  Win Rate: {data['win_rate']:.1f}%  ({data['count']} trades)")
        lines.append("")
        
        # ══════ TICKER PERFORMANCE ══════
        lines.append("═"*100)
        lines.append("TICKER PERFORMANCE ANALYSIS")
        lines.append("═"*100)
        
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
        
        # ══════ ACTION ITEMS ══════
        lines.append("═"*100)
        lines.append("RECOMMENDED ACTIONS")
        lines.append("═"*100)
        lines.append("1. Update config.py with recommended confidence thresholds")
        lines.append("2. Adjust stop loss ATR multipliers based on width recommendations")
        lines.append("3. Consider time-based filtering (avoid worst performing hours)")
        lines.append("4. Review ticker whitelist/blacklist for position selection")
        lines.append("5. Deploy Phase 4 monitoring for ongoing optimization")
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═════════════════════════════════════════════════════════════════════════════

historical_tuner = HistoricalParameterTuner()


# ═════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Historical Parameter Tuner...\n")
    print(historical_tuner.generate_historical_tuning_report())
