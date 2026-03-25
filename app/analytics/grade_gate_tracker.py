#!/usr/bin/env python3
"""
Grade Gate Tracker — app.analytics.grade_gate_tracker

Tracks every signal that hits the confidence gate (pass + reject)
so we can measure gate efficiency, grade distribution, and
threshold calibration over time.

sniper.py imports:
    from app.analytics.grade_gate_tracker import grade_gate_tracker

Used via:
    grade_gate_tracker.record_gate_rejection(ticker, grade, confidence, threshold, signal_type)
    grade_gate_tracker.record_gate_pass(ticker, grade, confidence, threshold, signal_type)
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional
import logging
logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────────────────────
# In-memory session state
# ─────────────────────────────────────────────────────────────────────────────
_daily_stats: Dict = {
    'total_evaluated': 0,
    'total_passed': 0,
    'total_rejected': 0,
    'by_grade': {},       # {grade: {'passed': int, 'rejected': int}}
    'by_signal_type': {}, # {signal_type: {'passed': int, 'rejected': int}}
}


# ─────────────────────────────────────────────────────────────────────────────
# DB bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_table():
    try:
        from app.data.db_connection import get_conn, serial_pk, return_conn
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS grade_gate_events (
                    id {serial_pk()},
                    ticker TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    threshold REAL NOT NULL,
                    passed BOOLEAN NOT NULL,
                    session_date DATE,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        logger.info(f"[GRADE-GATE-TRACKER] DB init error (non-fatal): {e}")


_ensure_table()


# ─────────────────────────────────────────────────────────────────────────────
# Core recording
# ─────────────────────────────────────────────────────────────────────────────
def _record(ticker: str, grade: str, confidence: float, threshold: float,
            signal_type: str, passed: bool):
    try:
        now = datetime.now(_ET)

        # In-memory
        _daily_stats['total_evaluated'] += 1
        if passed:
            _daily_stats['total_passed'] += 1
        else:
            _daily_stats['total_rejected'] += 1

        g = _daily_stats['by_grade'].setdefault(grade, {'passed': 0, 'rejected': 0})
        g['passed' if passed else 'rejected'] += 1

        s = _daily_stats['by_signal_type'].setdefault(signal_type, {'passed': 0, 'rejected': 0})
        s['passed' if passed else 'rejected'] += 1

        # DB
        from app.data.db_connection import get_conn, ph as _ph, return_conn
        conn = get_conn()
        try:
            cursor = conn.cursor()
            p = _ph()
            cursor.execute(
                f"INSERT INTO grade_gate_events "
                f"(ticker, grade, signal_type, confidence, threshold, passed, session_date, ts) "
                f"VALUES ({p},{p},{p},{p},{p},{p},{p},{p})",
                (ticker, grade, signal_type, confidence, threshold,
                 passed, now.date(), now)
            )
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        logger.info(f"[GRADE-GATE-TRACKER] Record error (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton class (matches sniper.py call sites)
# ─────────────────────────────────────────────────────────────────────────────
class GradeGateTracker:
    def record_gate_rejection(self, ticker: str, grade: str, confidence: float,
                               threshold: float, signal_type: str) -> None:
        label = 'passed' if False else 'rejected'
        print(
            f"[GRADE-GATE] ❌ {ticker} | {grade} | {signal_type} | "
            f"{confidence:.2f} < {threshold:.2f}"
        )
        _record(ticker, grade, confidence, threshold, signal_type, passed=False)

    def record_gate_pass(self, ticker: str, grade: str, confidence: float,
                          threshold: float, signal_type: str) -> None:
        print(
            f"[GRADE-GATE] ✅ {ticker} | {grade} | {signal_type} | "
            f"{confidence:.2f} >= {threshold:.2f}"
        )
        _record(ticker, grade, confidence, threshold, signal_type, passed=True)

    def get_daily_stats(self) -> Dict:
        total = _daily_stats['total_evaluated']
        passed = _daily_stats['total_passed']
        rejected = _daily_stats['total_rejected']
        pass_rate = (passed / total * 100) if total > 0 else 0.0
        return {
            'total_evaluated': total,
            'total_passed': passed,
            'total_rejected': rejected,
            'pass_rate_pct': pass_rate,
            'by_grade': dict(_daily_stats['by_grade']),
            'by_signal_type': dict(_daily_stats['by_signal_type']),
        }

    def print_eod_report(self) -> None:
        stats = self.get_daily_stats()
        if stats['total_evaluated'] == 0:
            return
        logger.info("\n" + "="*60)
        logger.info("📊 GRADE GATE TRACKER — EOD REPORT")
        logger.info("="*60)
        logger.info(f"  Evaluated : {stats['total_evaluated']}")
        logger.info(f"  Passed    : {stats['total_passed']} ({stats['pass_rate_pct']:.1f}%)")
        logger.info(f"  Rejected  : {stats['total_rejected']}")
        if stats['by_grade']:
            logger.info("\n  By Grade:")
            for grade, counts in sorted(stats['by_grade'].items()):
                logger.info(f"    {grade:<5}  ✅{counts['passed']}  ❌{counts['rejected']}")
        if stats['by_signal_type']:
            logger.info("\n  By Signal Type:")
            for st, counts in sorted(stats['by_signal_type'].items()):
                logger.info(f"    {st:<18}  ✅{counts['passed']}  ❌{counts['rejected']}")
        logger.info("="*60 + "\n")

    def reset_daily_stats(self) -> None:
        _daily_stats.update({
            'total_evaluated': 0,
            'total_passed': 0,
            'total_rejected': 0,
            'by_grade': {},
            'by_signal_type': {},
        })


# Singleton
grade_gate_tracker = GradeGateTracker()
