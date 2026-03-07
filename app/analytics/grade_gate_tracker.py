#!/usr/bin/env python3
"""
Grade Gate Distribution Tracker - Issue #23

Tracks which grades pass/fail at confidence threshold gates.
Provides data to optimize gate thresholds per grade:
- Are A- signals being over-filtered?
- Are C+ signals slipping through too easily?
- What's the win rate for each grade at different confidence levels?

Metrics by grade:
- Total signals generated
- Passed confidence gate
- Failed confidence gate
- Average confidence (base + after multipliers)
- Win rate for passed signals
- Optimal threshold recommendations
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════════════════════════════════════
_daily_stats: Dict[str, Dict] = {}  # {grade: {generated, passed, failed, ...}}


# ══════════════════════════════════════════════════════════════════════════════
# Database Persistence
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_grade_gate_table():
    """Create grade_gate_tracking table if it doesn't exist."""
    try:
        from app.data.db_connection import get_conn, serial_pk
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS grade_gate_tracking (
                id {serial_pk()},
                ticker TEXT NOT NULL,
                grade TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                base_confidence REAL NOT NULL,
                final_confidence REAL NOT NULL,
                threshold REAL NOT NULL,
                passed_gate INTEGER NOT NULL,
                outcome TEXT,
                pnl_pct REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[GRADE-GATE] Init error: {e}")


_ensure_grade_gate_table()


# ══════════════════════════════════════════════════════════════════════════════
# Tracking Functions
# ══════════════════════════════════════════════════════════════════════════════

def _init_grade_stats(grade: str):
    """Initialize stats dict for a grade if not exists."""
    if grade not in _daily_stats:
        _daily_stats[grade] = {
            'generated': 0,
            'passed': 0,
            'failed': 0,
            'base_conf_sum': 0.0,
            'final_conf_sum': 0.0,
            'threshold_sum': 0.0,
            'outcomes': {'WIN': 0, 'LOSS': 0, 'PENDING': 0}
        }


def track_grade_at_gate(
    ticker: str,
    grade: str,
    signal_type: str,
    base_confidence: float,
    final_confidence: float,
    threshold: float,
    passed_gate: bool
):
    """
    Track a signal's journey through the confidence gate.
    
    Args:
        ticker: Stock symbol
        grade: Signal grade (A+, A, A-, B+, B, B-, C+, C, C-)
        signal_type: 'CFW6_OR' or 'CFW6_INTRADAY'
        base_confidence: Base confidence from grade before multipliers
        final_confidence: Final confidence after all multipliers
        threshold: Confidence threshold that was applied
        passed_gate: True if signal passed the gate and was armed
    """
    try:
        from app.data.db_connection import get_conn, ph as _ph
        
        # Update session stats
        _init_grade_stats(grade)
        _daily_stats[grade]['generated'] += 1
        _daily_stats[grade]['base_conf_sum'] += base_confidence
        _daily_stats[grade]['final_conf_sum'] += final_confidence
        _daily_stats[grade]['threshold_sum'] += threshold
        
        if passed_gate:
            _daily_stats[grade]['passed'] += 1
            _daily_stats[grade]['outcomes']['PENDING'] += 1
        else:
            _daily_stats[grade]['failed'] += 1
        
        # Persist to DB
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        cursor.execute(
            f"""
            INSERT INTO grade_gate_tracking
                (ticker, grade, signal_type, base_confidence, final_confidence,
                 threshold, passed_gate, outcome, pnl_pct, timestamp)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            (ticker, grade, signal_type, base_confidence, final_confidence,
             threshold, 1 if passed_gate else 0, 'PENDING' if passed_gate else 'FILTERED',
             None, datetime.now(ZoneInfo("America/New_York")))
        )
        conn.commit()
        conn.close()
        
        gate_emoji = "✅" if passed_gate else "🚫"
        print(
            f"[GRADE-GATE] {gate_emoji} {ticker} {grade} | "
            f"Base: {base_confidence:.2f}, Final: {final_confidence:.2f}, "
            f"Threshold: {threshold:.2f}, Passed: {passed_gate}"
        )
        
    except Exception as e:
        print(f"[GRADE-GATE] Track error for {ticker}: {e}")


def update_grade_outcome(ticker: str, outcome: str, pnl_pct: float):
    """
    Update outcome for a signal that passed the gate when trade closes.
    
    Args:
        ticker: Stock symbol
        outcome: 'WIN' or 'LOSS'
        pnl_pct: P&L percentage
    """
    try:
        from app.data.db_connection import get_conn, ph as _ph
        
        conn = get_conn()
        cursor = conn.cursor()
        p = _ph()
        
        # Get grade for this signal
        cursor.execute(
            f"SELECT grade FROM grade_gate_tracking "
            f"WHERE ticker = {p} AND outcome = 'PENDING' "
            f"ORDER BY timestamp DESC LIMIT 1",
            (ticker,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return
        
        grade = row[0]
        
        # Update database
        cursor.execute(
            f"""
            UPDATE grade_gate_tracking
            SET outcome = {p}, pnl_pct = {p}
            WHERE ticker = {p} AND outcome = 'PENDING'
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (outcome, pnl_pct, ticker)
        )
        conn.commit()
        conn.close()
        
        # Update session stats
        if grade in _daily_stats:
            _daily_stats[grade]['outcomes']['PENDING'] -= 1
            _daily_stats[grade]['outcomes'][outcome] += 1
        
        print(f"[GRADE-GATE] {ticker} ({grade}) outcome: {outcome} ({pnl_pct:+.2f}%)")
        
    except Exception as e:
        print(f"[GRADE-GATE] Update outcome error for {ticker}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Reporting Functions
# ══════════════════════════════════════════════════════════════════════════════

def print_grade_gate_summary():
    """Print end-of-day grade gate summary."""
    if not _daily_stats:
        return
    
    print("\n" + "="*90)
    print("🎯 GRADE DISTRIBUTION AT CONFIDENCE GATES - DAILY SUMMARY")
    print("="*90)
    
    # Sort grades in quality order
    grade_order = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-']
    sorted_grades = [g for g in grade_order if g in _daily_stats]
    
    print(f"{'Grade':<8} {'Generated':<12} {'Passed':<10} {'Failed':<10} "
          f"{'Pass%':<10} {'Avg Base':<12} {'Avg Final':<12} {'Avg Threshold':<15}")
    print("-" * 90)
    
    for grade in sorted_grades:
        stats = _daily_stats[grade]
        generated = stats['generated']
        passed = stats['passed']
        failed = stats['failed']
        pass_pct = (passed / generated * 100) if generated > 0 else 0.0
        avg_base = stats['base_conf_sum'] / generated if generated > 0 else 0.0
        avg_final = stats['final_conf_sum'] / generated if generated > 0 else 0.0
        avg_threshold = stats['threshold_sum'] / generated if generated > 0 else 0.0
        
        print(
            f"{grade:<8} {generated:<12} {passed:<10} {failed:<10} "
            f"{pass_pct:<9.1f}% {avg_base:<11.2f} {avg_final:<11.2f} {avg_threshold:<14.2f}"
        )
    
    print("\n" + "="*90)
    print("WIN RATE BY GRADE (Closed Trades Only)")
    print("="*90)
    print(f"{'Grade':<8} {'Wins':<8} {'Losses':<10} {'Win Rate':<12} {'Pending':<10}")
    print("-" * 50)
    
    for grade in sorted_grades:
        stats = _daily_stats[grade]
        wins = stats['outcomes']['WIN']
        losses = stats['outcomes']['LOSS']
        pending = stats['outcomes']['PENDING']
        total_closed = wins + losses
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
        
        if total_closed > 0 or pending > 0:
            print(
                f"{grade:<8} {wins:<8} {losses:<10} {win_rate:<11.1f}% {pending:<10}"
            )
    
    print("="*90 + "\n")


def get_grade_optimization_data(days: int = 30) -> Dict:
    """
    Get historical data for optimizing confidence thresholds per grade.
    
    Args:
        days: Number of days to analyze
    
    Returns:
        Dict with per-grade threshold recommendations
    """
    try:
        from app.data.db_connection import get_conn
        
        conn = get_conn()
        cursor = conn.cursor()
        
        cutoff_date = (datetime.now(ZoneInfo("America/New_York")) - timedelta(days=days)).date()
        
        grades = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-']
        grade_analysis = {}
        
        for grade in grades:
            # Total signals at this grade
            cursor.execute(
                "SELECT COUNT(*) FROM grade_gate_tracking "
                "WHERE DATE(timestamp) >= ? AND grade = ?",
                (cutoff_date, grade)
            )
            total = cursor.fetchone()[0]
            
            # Passed gate
            cursor.execute(
                "SELECT COUNT(*) FROM grade_gate_tracking "
                "WHERE DATE(timestamp) >= ? AND grade = ? AND passed_gate = 1",
                (cutoff_date, grade)
            )
            passed = cursor.fetchone()[0]
            
            # Win rate for passed signals
            cursor.execute(
                "SELECT COUNT(*), SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) "
                "FROM grade_gate_tracking "
                "WHERE DATE(timestamp) >= ? AND grade = ? AND passed_gate = 1 "
                "AND outcome IN ('WIN', 'LOSS')",
                (cutoff_date, grade)
            )
            row = cursor.fetchone()
            total_closed, wins = row[0], row[1]
            win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
            
            # Average final confidence for passed signals
            cursor.execute(
                "SELECT AVG(final_confidence) FROM grade_gate_tracking "
                "WHERE DATE(timestamp) >= ? AND grade = ? AND passed_gate = 1",
                (cutoff_date, grade)
            )
            avg_conf = cursor.fetchone()[0] or 0.0
            
            # Average threshold used
            cursor.execute(
                "SELECT AVG(threshold) FROM grade_gate_tracking "
                "WHERE DATE(timestamp) >= ? AND grade = ?",
                (cutoff_date, grade)
            )
            avg_threshold = cursor.fetchone()[0] or 0.0
            
            grade_analysis[grade] = {
                'total': total,
                'passed': passed,
                'pass_rate': (passed / total * 100) if total > 0 else 0.0,
                'win_rate': win_rate,
                'avg_confidence': avg_conf,
                'avg_threshold': avg_threshold,
                'sample_size': total_closed
            }
        
        conn.close()
        
        return {
            'days_analyzed': days,
            'grades': grade_analysis
        }
    
    except Exception as e:
        print(f"[GRADE-GATE] Optimization data error: {e}")
        return {}


def print_threshold_recommendations():
    """Print threshold optimization recommendations based on historical data."""
    data = get_grade_optimization_data(days=30)
    
    if not data or not data.get('grades'):
        return
    
    print("\n" + "="*100)
    print("💡 CONFIDENCE THRESHOLD OPTIMIZATION RECOMMENDATIONS (30 days)")
    print("="*100)
    
    print(f"\n{'Grade':<8} {'Total':<8} {'Passed':<10} {'Pass%':<10} {'Win%':<10} "
          f"{'Avg Conf':<12} {'Avg Threshold':<15} {'Recommendation':<20}")
    print("-" * 100)
    
    grade_order = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-']
    
    for grade in grade_order:
        if grade not in data['grades']:
            continue
        
        stats = data['grades'][grade]
        
        # Skip grades with insufficient data
        if stats['sample_size'] < 5:
            continue
        
        # Generate recommendation
        if stats['win_rate'] >= 60 and stats['pass_rate'] < 50:
            recommendation = "✅ Lower threshold"
        elif stats['win_rate'] < 45 and stats['pass_rate'] > 70:
            recommendation = "⚠️ Raise threshold"
        elif stats['sample_size'] < 20:
            recommendation = "📈 Need more data"
        else:
            recommendation = "✔️ Threshold OK"
        
        print(
            f"{grade:<8} {stats['total']:<8} {stats['passed']:<10} "
            f"{stats['pass_rate']:<9.1f}% {stats['win_rate']:<9.1f}% "
            f"{stats['avg_confidence']:<11.2f} {stats['avg_threshold']:<14.2f} {recommendation:<20}"
        )
    
    print("\n🔑 Key:")
    print("  ✅ Lower threshold = High win rate + low pass rate (opportunity to capture more wins)")
    print("  ⚠️ Raise threshold = Low win rate + high pass rate (filtering too few losers)")
    print("  📈 Need more data = Sample size < 20 trades (not statistically significant)")
    print("  ✔️ Threshold OK = Win rate and pass rate are balanced")
    print("="*100 + "\n")
