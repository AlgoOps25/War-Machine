#!/usr/bin/env python3
"""
Explosive Mover Override Tracker - Issue #22

Tracks effectiveness of the explosive mover override feature:
- How many signals bypass regime filter due to high score + RVOL
- Win rate comparison: explosive override signals vs regular signals
- Threshold optimization data (score >= 80, RVOL >= 4.0x)

Metrics:
- Override trigger count
- Override win/loss record
- Average score and RVOL of override signals
- Regime conditions at time of override
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════════════════════════════════════
_override_signals: Dict[str, Dict] = {}  # {ticker: override_data}
_daily_stats = {
    'total_overrides': 0,
    'by_hour': {},
    'by_regime': {},
    'total_score': 0.0,
    'total_rvol': 0.0,
}


# ══════════════════════════════════════════════════════════════════════════════
# Database Persistence
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_explosive_override_table():
    """Create explosive_mover_overrides table if it doesn't exist."""
    try:
        from app.data.db_connection import get_connection, serial_pk
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS explosive_mover_overrides (
                    id {serial_pk()},
                    ticker TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    rvol REAL NOT NULL,
                    tier TEXT,
                    regime_type TEXT,
                    vix_level REAL,
                    entry_price REAL,
                    grade TEXT,
                    confidence REAL,
                    outcome TEXT,
                    pnl_pct REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    except Exception as e:
        print(f"[EXPLOSIVE-TRACKER] Init error: {e}")


_ensure_explosive_override_table()


# ══════════════════════════════════════════════════════════════════════════════
# Tracking Functions
# ══════════════════════════════════════════════════════════════════════════════

def track_explosive_override(
    ticker: str,
    direction: str,
    score: int,
    rvol: float,
    tier: str,
    regime_type: str,
    vix_level: float,
    entry_price: float,
    grade: str,
    confidence: float
):
    """
    Record when a signal bypasses regime filter due to explosive mover override.
    """
    try:
        from app.data.db_connection import get_connection, ph as _ph

        now = datetime.now(ZoneInfo("America/New_York"))
        hour = now.hour

        _daily_stats['total_overrides'] += 1
        _daily_stats['by_hour'][hour] = _daily_stats['by_hour'].get(hour, 0) + 1
        _daily_stats['by_regime'][regime_type] = _daily_stats['by_regime'].get(regime_type, 0) + 1
        _daily_stats['total_score'] += score
        _daily_stats['total_rvol'] += rvol

        _override_signals[ticker] = {
            'direction': direction,
            'score': score,
            'rvol': rvol,
            'tier': tier,
            'regime_type': regime_type,
            'vix_level': vix_level,
            'entry_price': entry_price,
            'grade': grade,
            'confidence': confidence,
            'timestamp': now
        }

        p = _ph()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO explosive_mover_overrides
                    (ticker, direction, score, rvol, tier, regime_type, vix_level,
                     entry_price, grade, confidence, outcome, pnl_pct, timestamp)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                """,
                (ticker, direction, score, rvol, tier, regime_type, vix_level,
                 entry_price, grade, confidence, 'PENDING', None, now)
            )
            conn.commit()

        print(
            f"[EXPLOSIVE-OVERRIDE] 🚀 {ticker} {direction.upper()} tracked | "
            f"Score: {score}, RVOL: {rvol:.1f}x ({tier}), "
            f"Regime: {regime_type} (VIX: {vix_level:.1f})"
        )

    except Exception as e:
        print(f"[EXPLOSIVE-TRACKER] Track error for {ticker}: {e}")


def update_override_outcome(ticker: str, outcome: str, pnl_pct: float):
    """
    Update outcome for an explosive override signal when trade closes.
    """
    try:
        from app.data.db_connection import get_connection, ph as _ph

        if ticker not in _override_signals:
            return

        p = _ph()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE explosive_mover_overrides
                SET outcome = {p}, pnl_pct = {p}
                WHERE ticker = {p}
                  AND outcome = 'PENDING'
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (outcome, pnl_pct, ticker)
            )
            conn.commit()

        del _override_signals[ticker]
        print(f"[EXPLOSIVE-OVERRIDE] {ticker} outcome: {outcome} ({pnl_pct:+.2f}%)")

    except Exception as e:
        print(f"[EXPLOSIVE-TRACKER] Update outcome error for {ticker}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Reporting Functions
# ══════════════════════════════════════════════════════════════════════════════

def get_daily_override_stats() -> Dict:
    """Get daily statistics for explosive overrides."""
    try:
        from app.data.db_connection import get_connection

        today = datetime.now(ZoneInfo("America/New_York")).date()

        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM explosive_mover_overrides WHERE DATE(timestamp) = ?",
                (today,)
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT outcome, COUNT(*) FROM explosive_mover_overrides "
                "WHERE DATE(timestamp) = ? AND outcome != 'PENDING' "
                "GROUP BY outcome",
                (today,)
            )
            outcomes = dict(cursor.fetchall())

            cursor.execute(
                "SELECT AVG(score), AVG(rvol), AVG(confidence) "
                "FROM explosive_mover_overrides WHERE DATE(timestamp) = ?",
                (today,)
            )
            avg_row = cursor.fetchone()

        wins = outcomes.get('WIN', 0)
        losses = outcomes.get('LOSS', 0)
        total_closed = wins + losses
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        return {
            'total_overrides': total,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'avg_score': avg_row[0] if avg_row[0] else 0.0,
            'avg_rvol': avg_row[1] if avg_row[1] else 0.0,
            'avg_confidence': avg_row[2] if avg_row[2] else 0.0,
            'pending': total - total_closed
        }

    except Exception as e:
        print(f"[EXPLOSIVE-TRACKER] Stats error: {e}")
        return {}


def print_explosive_override_summary():
    """Print end-of-day explosive override summary."""
    stats = get_daily_override_stats()

    if not stats or stats['total_overrides'] == 0:
        return

    print("\n" + "="*80)
    print("🚀 EXPLOSIVE MOVER OVERRIDE - DAILY SUMMARY")
    print("="*80)
    print(f"Total Overrides: {stats['total_overrides']}")
    print(f"Closed Trades: {stats['wins'] + stats['losses']} (Pending: {stats['pending']})")
    print(f"Win Rate: {stats['win_rate']:.1f}% ({stats['wins']}W / {stats['losses']}L)")
    print(f"\nAverage Metrics:")
    print(f"  Score: {stats['avg_score']:.1f}")
    print(f"  RVOL: {stats['avg_rvol']:.2f}x")
    print(f"  Confidence: {stats['avg_confidence']:.1%}")

    if _daily_stats['by_hour']:
        print(f"\nHourly Distribution:")
        for hour in sorted(_daily_stats['by_hour'].keys()):
            count = _daily_stats['by_hour'][hour]
            print(f"  {hour:02d}:00 - {count} override(s)")

    if _daily_stats['by_regime']:
        print(f"\nRegime Distribution:")
        for regime, count in sorted(_daily_stats['by_regime'].items(), key=lambda x: -x[1]):
            print(f"  {regime}: {count} override(s)")

    print("="*80 + "\n")


def get_threshold_optimization_data(days: int = 30) -> Dict:
    """
    Get data for optimizing explosive override thresholds.
    """
    try:
        from app.data.db_connection import get_connection

        cutoff_date = (datetime.now(ZoneInfo("America/New_York")) - timedelta(days=days)).date()

        with get_connection() as conn:
            cursor = conn.cursor()

            score_brackets = [(70, 80), (80, 90), (90, 100)]
            score_analysis = {}
            for low, high in score_brackets:
                cursor.execute(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) "
                    "FROM explosive_mover_overrides "
                    "WHERE DATE(timestamp) >= ? AND score >= ? AND score < ? "
                    "AND outcome IN ('WIN', 'LOSS')",
                    (cutoff_date, low, high)
                )
                row = cursor.fetchone()
                total, wins = row[0], row[1]
                win_rate = (wins / total * 100) if total > 0 else 0.0
                score_analysis[f"{low}-{high}"] = {'total': total, 'wins': wins, 'win_rate': win_rate}

            rvol_brackets = [(3.0, 4.0), (4.0, 5.0), (5.0, 10.0)]
            rvol_analysis = {}
            for low, high in rvol_brackets:
                cursor.execute(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) "
                    "FROM explosive_mover_overrides "
                    "WHERE DATE(timestamp) >= ? AND rvol >= ? AND rvol < ? "
                    "AND outcome IN ('WIN', 'LOSS')",
                    (cutoff_date, low, high)
                )
                row = cursor.fetchone()
                total, wins = row[0], row[1]
                win_rate = (wins / total * 100) if total > 0 else 0.0
                rvol_analysis[f"{low:.1f}-{high:.1f}x"] = {'total': total, 'wins': wins, 'win_rate': win_rate}

        return {
            'days_analyzed': days,
            'score_brackets': score_analysis,
            'rvol_brackets': rvol_analysis
        }

    except Exception as e:
        print(f"[EXPLOSIVE-TRACKER] Optimization data error: {e}")
        return {}


def print_threshold_recommendations():
    """Print threshold optimization recommendations based on historical data."""
    data = get_threshold_optimization_data(days=30)

    if not data:
        return

    print("\n" + "="*80)
    print("🎯 EXPLOSIVE OVERRIDE THRESHOLD OPTIMIZATION (30 days)")
    print("="*80)

    print("\nScore Bracket Analysis:")
    print(f"{'Bracket':<12} {'Total':<8} {'Wins':<8} {'Win Rate':<12}")
    print("-" * 45)
    for bracket, stats in data['score_brackets'].items():
        print(
            f"{bracket:<12} {stats['total']:<8} {stats['wins']:<8} "
            f"{stats['win_rate']:.1f}%"
        )

    print("\nRVOL Bracket Analysis:")
    print(f"{'Bracket':<12} {'Total':<8} {'Wins':<8} {'Win Rate':<12}")
    print("-" * 45)
    for bracket, stats in data['rvol_brackets'].items():
        print(
            f"{bracket:<12} {stats['total']:<8} {stats['wins']:<8} "
            f"{stats['win_rate']:.1f}%"
        )

    print("\n💡 Recommendations:")
    print("  - Review brackets with >60% win rate for threshold tightening")
    print("  - Review brackets with <45% win rate for threshold loosening")
    print("  - Minimum 20 samples per bracket for statistical significance")
    print("="*80 + "\n")
