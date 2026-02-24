#!/usr/bin/env python3
"""
Parameter Optimization System

Data-driven optimization framework for tuning system parameters based on
live performance data. Uses monitoring infrastructure to identify optimal
settings for confidence thresholds, validator checks, multipliers, and stops.

Optimization Areas:
  1. Confidence Thresholds - Calibrate minimum confidence per grade
  2. Validator Checks - Tune check sensitivity and rejection thresholds
  3. Multipliers - Optimize IVR/UOA/GEX/MTF ranges for maximum edge
  4. Stop Losses - Reduce whipsaw while maintaining protection
  5. A/B Testing - Statistical validation of parameter changes

Methodology:
  - Collect 10-14 days of live signal and trade data
  - Segment by grade, signal type, market condition
  - Analyze win rate, R:R, and profitability by parameter range
  - Recommend adjustments with expected impact
  - Backtest proposed changes on historical data
  - A/B test in production for validation

Usage:
  # Generate full optimization report:
  from parameter_optimizer import optimizer
  report = optimizer.generate_optimization_report(days=14)
  
  # Get specific recommendations:
  confidence_recs = optimizer.recommend_confidence_adjustments()
  validator_recs = optimizer.analyze_validator_effectiveness()
  multiplier_recs = optimizer.optimize_multiplier_ranges()
  stop_loss_recs = optimizer.optimize_stop_loss_widths()
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import statistics
from db_connection import get_conn, ph, dict_cursor
import config

ET = ZoneInfo("America/New_York")


class ParameterOptimizer:
    """Optimizes system parameters using live performance data."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.min_sample_size = 20  # Minimum trades per bucket for significance
    
    def analyze_confidence_thresholds(self, days: int = 14) -> Dict:
        """
        Analyze win rate by confidence bucket to identify optimal thresholds.
        
        Args:
            days: Lookback period for analysis
        
        Returns:
            {
                'by_grade': {
                    'A+': {
                        'confidence_buckets': [
                            {'range': '0.70-0.75', 'count': int, 'win_rate': float, 'avg_pnl': float},
                            ...
                        ],
                        'current_threshold': float,
                        'recommended_threshold': float
                    },
                    ...
                },
                'overall': {...}
            }
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Get trades with confidence scores
        cursor.execute(f"""
            SELECT 
                p.grade,
                p.realized_pnl,
                se.final_confidence
            FROM positions p
            JOIN signal_events se ON p.ticker = se.ticker 
                AND DATE(p.entry_time) = se.session_date
                AND se.stage = 'ARMED'
            WHERE p.status = 'closed'
              AND DATE(p.exit_time) >= {p}
              AND se.final_confidence IS NOT NULL
        """, (cutoff,))
        
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return {'by_grade': {}, 'overall': {}}
        
        # Group by grade and confidence bucket
        buckets = {
            'A+': defaultdict(list),
            'A': defaultdict(list),
            'A-': defaultdict(list)
        }
        
        for trade in trades:
            grade = trade['grade']
            confidence = trade['final_confidence']
            pnl = trade['realized_pnl']
            
            # Bucket confidence into 0.05 ranges
            bucket = int(confidence * 20) / 20  # Round down to nearest 0.05
            buckets[grade][bucket].append(pnl)
        
        # Analyze each grade
        results = {'by_grade': {}}
        
        for grade in ['A+', 'A', 'A-']:
            grade_buckets = []
            
            for conf_bucket in sorted(buckets[grade].keys()):
                pnls = buckets[grade][conf_bucket]
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
            
            # Determine recommended threshold (first bucket with >65% win rate and >20 samples)
            recommended = None
            for bucket in sorted(grade_buckets, key=lambda x: float(x['range'].split('-')[0])):
                if bucket['win_rate'] >= 65 and bucket['count'] >= self.min_sample_size:
                    recommended = float(bucket['range'].split('-')[0])
                    break
            
            # Fallback: use weighted average of win rates
            if recommended is None and grade_buckets:
                total_trades = sum(b['count'] for b in grade_buckets)
                if total_trades >= self.min_sample_size:
                    # Find confidence level where win rate crosses 60%
                    for bucket in sorted(grade_buckets, key=lambda x: float(x['range'].split('-')[0]), reverse=True):
                        if bucket['win_rate'] >= 60:
                            recommended = float(bucket['range'].split('-')[0])
                            break
            
            results['by_grade'][grade] = {
                'confidence_buckets': grade_buckets,
                'current_threshold': config.MIN_CONFIDENCE.get(grade, 0.70),
                'recommended_threshold': recommended if recommended else config.MIN_CONFIDENCE.get(grade, 0.70)
            }
        
        return results
    
    def recommend_confidence_adjustments(self, days: int = 14) -> List[str]:
        """
        Generate actionable recommendations for confidence threshold adjustments.
        
        Args:
            days: Lookback period
        
        Returns:
            List of recommendation strings
        """
        analysis = self.analyze_confidence_thresholds(days)
        recommendations = []
        
        for grade, data in analysis['by_grade'].items():
            current = data['current_threshold']
            recommended = data['recommended_threshold']
            
            if recommended is None:
                recommendations.append(
                    f"⚠️ {grade}: Insufficient data ({sum(b['count'] for b in data['confidence_buckets'])} trades) - keep current threshold ({current:.2f})"
                )
            elif abs(recommended - current) >= 0.05:
                direction = "INCREASE" if recommended > current else "DECREASE"
                change = abs(recommended - current)
                recommendations.append(
                    f"📊 {grade}: {direction} threshold from {current:.2f} to {recommended:.2f} (Δ{change:.2f})"
                )
            else:
                recommendations.append(
                    f"✅ {grade}: Current threshold ({current:.2f}) is optimal"
                )
        
        return recommendations
    
    def analyze_validator_effectiveness(self, days: int = 14) -> Dict:
        """
        Analyze which validator checks are overly restrictive or ineffective.
        
        Returns:
            {
                'rejection_reasons': [
                    {
                        'reason': str,
                        'count': int,
                        'pct_of_total': float,
                        'recommendation': str
                    },
                    ...
                ],
                'pass_rate': float,
                'recommended_pass_rate': float
            }
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Get validation statistics
        cursor.execute(f"""
            SELECT 
                rejection_reason,
                COUNT(*) as count
            FROM signal_events
            WHERE session_date >= {p}
              AND stage = 'REJECTED'
              AND rejection_reason IS NOT NULL
              AND rejection_reason != ''
            GROUP BY rejection_reason
            ORDER BY count DESC
        """, (cutoff,))
        
        rejections = cursor.fetchall()
        
        # Get total signals
        cursor.execute(f"""
            SELECT COUNT(*) as total
            FROM signal_events
            WHERE session_date >= {p}
              AND stage IN ('VALIDATED', 'REJECTED')
        """, (cutoff,))
        
        total_row = cursor.fetchone()
        total_checked = total_row['total'] if total_row else 0
        
        # Get pass count
        cursor.execute(f"""
            SELECT COUNT(*) as passed
            FROM signal_events
            WHERE session_date >= {p}
              AND stage = 'VALIDATED'
        """, (cutoff,))
        
        pass_row = cursor.fetchone()
        passed = pass_row['passed'] if pass_row else 0
        
        conn.close()
        
        pass_rate = (passed / total_checked * 100) if total_checked > 0 else 0
        total_rejected = sum(r['count'] for r in rejections)
        
        # Analyze each rejection reason
        rejection_analysis = []
        for rejection in rejections:
            reason = rejection['reason']
            count = rejection['count']
            pct = (count / total_rejected * 100) if total_rejected > 0 else 0
            
            # Generate recommendation based on frequency
            if pct >= 30:
                recommendation = "🚨 HIGH IMPACT - Consider relaxing this check"
            elif pct >= 15:
                recommendation = "⚠️ MODERATE IMPACT - Review threshold"
            else:
                recommendation = "✅ LOW IMPACT - Keep current setting"
            
            rejection_analysis.append({
                'reason': reason,
                'count': count,
                'pct_of_total': round(pct, 1),
                'recommendation': recommendation
            })
        
        # Recommended pass rate: 55-65%
        if pass_rate < 50:
            recommended_pass_rate = 55.0
            recommendation = "Validator is too restrictive - consider loosening checks"
        elif pass_rate > 70:
            recommended_pass_rate = 65.0
            recommendation = "Validator may be too permissive - consider tightening checks"
        else:
            recommended_pass_rate = pass_rate
            recommendation = "Validator pass rate is within optimal range"
        
        return {
            'rejection_reasons': rejection_analysis,
            'pass_rate': round(pass_rate, 1),
            'recommended_pass_rate': recommended_pass_rate,
            'recommendation': recommendation
        }
    
    def optimize_multiplier_ranges(self, days: int = 14) -> Dict:
        """
        Evaluate multiplier effectiveness and recommend range adjustments.
        
        Returns:
            {
                'ivr': {'avg': float, 'effective': bool, 'recommendation': str},
                'uoa': {...},
                'gex': {...},
                'mtf': {...}
            }
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Get trades with multiplier data
        cursor.execute(f"""
            SELECT 
                p.realized_pnl,
                se.ivr_multiplier,
                se.uoa_multiplier,
                se.gex_multiplier,
                se.mtf_boost,
                se.base_confidence,
                se.final_confidence
            FROM positions p
            JOIN signal_events se ON p.ticker = se.ticker
                AND DATE(p.entry_time) = se.session_date
                AND se.stage = 'TRADED'
            WHERE p.status = 'closed'
              AND DATE(p.exit_time) >= {p}
        """, (cutoff,))
        
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return {}
        
        # Analyze each multiplier
        multipliers = {
            'ivr': [t['ivr_multiplier'] for t in trades if t['ivr_multiplier']],
            'uoa': [t['uoa_multiplier'] for t in trades if t['uoa_multiplier']],
            'gex': [t['gex_multiplier'] for t in trades if t['gex_multiplier']],
            'mtf': [t['mtf_boost'] for t in trades if t['mtf_boost']]
        }
        
        results = {}
        
        for mult_name, values in multipliers.items():
            if not values:
                continue
            
            avg_value = statistics.mean(values)
            
            # Determine effectiveness (multipliers >1.0 or MTF boosts >0.05 are effective)
            if mult_name == 'mtf':
                effective = avg_value >= 0.05
                threshold = 0.05
            else:
                effective = avg_value >= 1.02  # At least 2% lift
                threshold = 1.02
            
            # Generate recommendation
            if effective:
                recommendation = f"✅ Effective (avg {avg_value:.3f}) - Keep current range"
            else:
                recommendation = f"⚠️ Ineffective (avg {avg_value:.3f}) - Consider expanding range or removing"
            
            results[mult_name] = {
                'avg': round(avg_value, 3),
                'min': round(min(values), 3),
                'max': round(max(values), 3),
                'effective': effective,
                'recommendation': recommendation
            }
        
        # Calculate total confidence lift
        base_confidences = [t['base_confidence'] for t in trades if t['base_confidence']]
        final_confidences = [t['final_confidence'] for t in trades if t['final_confidence']]
        
        if base_confidences and final_confidences:
            avg_base = statistics.mean(base_confidences)
            avg_final = statistics.mean(final_confidences)
            total_lift = ((avg_final - avg_base) / avg_base * 100)
            
            results['total_lift'] = {
                'base_avg': round(avg_base, 3),
                'final_avg': round(avg_final, 3),
                'lift_pct': round(total_lift, 1)
            }
        
        return results
    
    def optimize_stop_loss_widths(self, days: int = 14) -> Dict:
        """
        Analyze stop loss effectiveness to reduce whipsaw.
        
        Returns:
            {
                'by_grade': {
                    'A+': {
                        'stop_hit_rate': float,
                        'avg_atr_multiplier': float,
                        'recommended_multiplier': float,
                        'recommendation': str
                    },
                    ...
                },
                'overall_stop_hit_rate': float
            }
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Get trades with stop loss data
        cursor.execute(f"""
            SELECT 
                grade,
                entry_price,
                stop_loss,
                exit_price,
                exit_reason,
                realized_pnl
            FROM positions
            WHERE status = 'closed'
              AND DATE(exit_time) >= {p}
              AND stop_loss IS NOT NULL
        """, (cutoff,))
        
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return {}
        
        # Group by grade
        by_grade = defaultdict(list)
        for trade in trades:
            by_grade[trade['grade']].append(trade)
        
        results = {'by_grade': {}}
        total_stops = 0
        total_trades = 0
        
        for grade in ['A+', 'A', 'A-']:
            grade_trades = by_grade[grade]
            if not grade_trades:
                continue
            
            # Calculate stop hit rate
            stop_hits = sum(1 for t in grade_trades if t['exit_reason'] == 'stop_loss')
            stop_hit_rate = (stop_hits / len(grade_trades) * 100)
            
            total_stops += stop_hits
            total_trades += len(grade_trades)
            
            # Calculate average stop width (as % of entry)
            stop_widths = [
                abs(t['stop_loss'] - t['entry_price']) / t['entry_price'] * 100
                for t in grade_trades if t['entry_price'] > 0
            ]
            avg_stop_width = statistics.mean(stop_widths) if stop_widths else 0
            
            # Recommendation based on stop hit rate
            # Target: 20-30% stop hit rate (means 70-80% hit targets)
            if stop_hit_rate > 35:
                recommendation = f"🚨 High stop hit rate ({stop_hit_rate:.1f}%) - WIDEN stops (reduce ATR multiplier)"
                # Suggest 10% wider stops
                recommended_width = avg_stop_width * 1.10
            elif stop_hit_rate < 15:
                recommendation = f"⚠️ Low stop hit rate ({stop_hit_rate:.1f}%) - Consider TIGHTENING stops (increase ATR multiplier)"
                # Suggest 5% tighter stops
                recommended_width = avg_stop_width * 0.95
            else:
                recommendation = f"✅ Optimal stop hit rate ({stop_hit_rate:.1f}%) - Keep current width"
                recommended_width = avg_stop_width
            
            results['by_grade'][grade] = {
                'trades': len(grade_trades),
                'stop_hit_rate': round(stop_hit_rate, 1),
                'avg_stop_width_pct': round(avg_stop_width, 2),
                'recommended_width_pct': round(recommended_width, 2),
                'recommendation': recommendation
            }
        
        results['overall_stop_hit_rate'] = round((total_stops / total_trades * 100) if total_trades > 0 else 0, 1)
        
        return results
    
    def generate_optimization_report(self, days: int = 14) -> str:
        """
        Generate comprehensive parameter optimization report.
        
        Args:
            days: Lookback period for analysis
        
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("\n" + "="*100)
        lines.append("PARAMETER OPTIMIZATION REPORT")
        lines.append("="*100)
        lines.append(f"Analysis Period: Last {days} days")
        lines.append(f"Generated: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}\n")
        
        # ═══ CONFIDENCE THRESHOLDS ═══
        lines.append("═"*100)
        lines.append("CONFIDENCE THRESHOLD OPTIMIZATION")
        lines.append("═"*100)
        
        confidence_recs = self.recommend_confidence_adjustments(days)
        for rec in confidence_recs:
            lines.append(f"  {rec}")
        lines.append("")
        
        # ═══ VALIDATOR EFFECTIVENESS ═══
        lines.append("═"*100)
        lines.append("VALIDATOR EFFECTIVENESS ANALYSIS")
        lines.append("═"*100)
        
        validator_analysis = self.analyze_validator_effectiveness(days)
        lines.append(f"  Current Pass Rate:      {validator_analysis['pass_rate']:.1f}%")
        lines.append(f"  Recommended Pass Rate:  {validator_analysis['recommended_pass_rate']:.1f}%")
        lines.append(f"  Assessment: {validator_analysis['recommendation']}")
        lines.append("\n  Top Rejection Reasons:")
        
        for rejection in validator_analysis['rejection_reasons'][:5]:
            lines.append(f"    {rejection['reason']:<50} {rejection['count']:>3} ({rejection['pct_of_total']:>5.1f}%)")
            lines.append(f"      → {rejection['recommendation']}")
        lines.append("")
        
        # ═══ MULTIPLIER OPTIMIZATION ═══
        lines.append("═"*100)
        lines.append("MULTIPLIER EFFECTIVENESS ANALYSIS")
        lines.append("═"*100)
        
        multiplier_analysis = self.optimize_multiplier_ranges(days)
        
        for mult_name in ['ivr', 'uoa', 'gex', 'mtf']:
            if mult_name in multiplier_analysis:
                data = multiplier_analysis[mult_name]
                lines.append(f"  {mult_name.upper()}:")
                lines.append(f"    Avg: {data['avg']:.3f}  |  Min: {data['min']:.3f}  |  Max: {data['max']:.3f}")
                lines.append(f"    {data['recommendation']}")
                lines.append("")
        
        if 'total_lift' in multiplier_analysis:
            lift = multiplier_analysis['total_lift']
            lines.append(f"  Total Confidence Lift: {lift['base_avg']:.3f} → {lift['final_avg']:.3f}  ({lift['lift_pct']:+.1f}%)")
        lines.append("")
        
        # ═══ STOP LOSS OPTIMIZATION ═══
        lines.append("═"*100)
        lines.append("STOP LOSS WIDTH OPTIMIZATION")
        lines.append("═"*100)
        
        stop_analysis = self.optimize_stop_loss_widths(days)
        
        if 'by_grade' in stop_analysis:
            for grade in ['A+', 'A', 'A-']:
                if grade in stop_analysis['by_grade']:
                    data = stop_analysis['by_grade'][grade]
                    lines.append(f"  {grade}:")
                    lines.append(f"    Trades: {data['trades']}  |  Stop Hit Rate: {data['stop_hit_rate']:.1f}%")
                    lines.append(f"    Current Width: {data['avg_stop_width_pct']:.2f}%  |  Recommended: {data['recommended_width_pct']:.2f}%")
                    lines.append(f"    {data['recommendation']}")
                    lines.append("")
        
        lines.append(f"  Overall Stop Hit Rate: {stop_analysis.get('overall_stop_hit_rate', 0):.1f}%")
        lines.append(f"  Target Range: 20-30% (means 70-80% reach targets)")
        lines.append("")
        
        # ═══ ACTION ITEMS ═══
        lines.append("═"*100)
        lines.append("RECOMMENDED ACTIONS")
        lines.append("═"*100)
        lines.append("  1. Review confidence threshold adjustments above")
        lines.append("  2. Consider relaxing high-impact validator checks")
        lines.append("  3. Verify multiplier effectiveness and adjust ranges")
        lines.append("  4. Optimize stop widths to reduce whipsaw")
        lines.append("  5. A/B test proposed changes before full deployment")
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

optimizer = ParameterOptimizer()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Parameter Optimizer...\n")
    print(optimizer.generate_optimization_report(days=14))
