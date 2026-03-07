# Grade Gate Tracker - Tracks confidence threshold decisions
# Purpose: Monitor how many signals pass/fail confidence gates
# Helps tune dynamic thresholds and understand signal quality distribution

from datetime import datetime
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

class GradeGateTracker:
    """
    Tracks confidence gate decisions (pass/reject) for signal quality analysis.
    Monitors grade distribution, threshold effectiveness, and gate performance.
    """
    
    def __init__(self):
        self._passes: List[Dict] = []  # Signals that passed gate
        self._rejections: List[Dict] = []  # Signals rejected by gate
        self._stats = {
            'total_evaluated': 0,
            'total_passed': 0,
            'total_rejected': 0,
            'grade_breakdown': {},  # grade -> {passed: int, rejected: int}
            'signal_type_breakdown': {},  # signal_type -> {passed: int, rejected: int}
            'avg_threshold': 0.0,
            'avg_passed_confidence': 0.0,
            'avg_rejected_confidence': 0.0
        }
    
    def _now_et(self) -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))
    
    def record_gate_pass(
        self,
        ticker: str,
        grade: str,
        confidence: float,
        threshold: float,
        signal_type: str = "CFW6_OR"
    ) -> None:
        """Record a signal that passed the confidence gate."""
        timestamp = self._now_et()
        
        pass_event = {
            'ticker': ticker,
            'grade': grade,
            'confidence': confidence,
            'threshold': threshold,
            'signal_type': signal_type,
            'timestamp': timestamp,
            'margin': confidence - threshold
        }
        
        self._passes.append(pass_event)
        
        # Update stats
        self._stats['total_evaluated'] += 1
        self._stats['total_passed'] += 1
        
        # Grade breakdown
        if grade not in self._stats['grade_breakdown']:
            self._stats['grade_breakdown'][grade] = {'passed': 0, 'rejected': 0}
        self._stats['grade_breakdown'][grade]['passed'] += 1
        
        # Signal type breakdown
        if signal_type not in self._stats['signal_type_breakdown']:
            self._stats['signal_type_breakdown'][signal_type] = {'passed': 0, 'rejected': 0}
        self._stats['signal_type_breakdown'][signal_type]['passed'] += 1
        
        # Update running averages
        total_passed = self._stats['total_passed']
        self._stats['avg_passed_confidence'] = (
            (self._stats['avg_passed_confidence'] * (total_passed - 1) + confidence) / total_passed
        )
        
        total = self._stats['total_evaluated']
        self._stats['avg_threshold'] = (
            (self._stats['avg_threshold'] * (total - 1) + threshold) / total
        )
    
    def record_gate_rejection(
        self,
        ticker: str,
        grade: str,
        confidence: float,
        threshold: float,
        signal_type: str = "CFW6_OR"
    ) -> None:
        """Record a signal that was rejected by the confidence gate."""
        timestamp = self._now_et()
        
        reject_event = {
            'ticker': ticker,
            'grade': grade,
            'confidence': confidence,
            'threshold': threshold,
            'signal_type': signal_type,
            'timestamp': timestamp,
            'shortfall': threshold - confidence
        }
        
        self._rejections.append(reject_event)
        
        # Update stats
        self._stats['total_evaluated'] += 1
        self._stats['total_rejected'] += 1
        
        # Grade breakdown
        if grade not in self._stats['grade_breakdown']:
            self._stats['grade_breakdown'][grade] = {'passed': 0, 'rejected': 0}
        self._stats['grade_breakdown'][grade]['rejected'] += 1
        
        # Signal type breakdown
        if signal_type not in self._stats['signal_type_breakdown']:
            self._stats['signal_type_breakdown'][signal_type] = {'passed': 0, 'rejected': 0}
        self._stats['signal_type_breakdown'][signal_type]['rejected'] += 1
        
        # Update running averages
        total_rejected = self._stats['total_rejected']
        self._stats['avg_rejected_confidence'] = (
            (self._stats['avg_rejected_confidence'] * (total_rejected - 1) + confidence) / total_rejected
        )
        
        total = self._stats['total_evaluated']
        self._stats['avg_threshold'] = (
            (self._stats['avg_threshold'] * (total - 1) + threshold) / total
        )
    
    def get_pass_rate(self) -> float:
        """Calculate overall pass rate."""
        total = self._stats['total_evaluated']
        if total == 0:
            return 0.0
        return (self._stats['total_passed'] / total) * 100
    
    def get_grade_pass_rate(self, grade: str) -> float:
        """Calculate pass rate for specific grade."""
        if grade not in self._stats['grade_breakdown']:
            return 0.0
        breakdown = self._stats['grade_breakdown'][grade]
        total = breakdown['passed'] + breakdown['rejected']
        if total == 0:
            return 0.0
        return (breakdown['passed'] / total) * 100
    
    def print_eod_report(self) -> None:
        """Print end-of-day grade gate statistics."""
        stats = self._stats
        total = stats['total_evaluated']
        
        print("\n" + "="*80)
        print("GRADE GATE TRACKER - END OF DAY REPORT")
        print("="*80)
        
        if total == 0:
            print("\n⚠️  No signals evaluated at confidence gate today")
            print("="*80 + "\n")
            return
        
        passed = stats['total_passed']
        rejected = stats['total_rejected']
        pass_rate = (passed / total) * 100
        
        print(f"Total Signals Evaluated: {total}")
        print(f"  • Passed: {passed} ({pass_rate:.1f}%)")
        print(f"  • Rejected: {rejected} ({100-pass_rate:.1f}%)")
        
        print(f"\nAverage Metrics:")
        print(f"  • Threshold: {stats['avg_threshold']:.2f}")
        if passed > 0:
            print(f"  • Passed Confidence: {stats['avg_passed_confidence']:.2f}")
        if rejected > 0:
            print(f"  • Rejected Confidence: {stats['avg_rejected_confidence']:.2f}")
        
        # Grade breakdown
        if stats['grade_breakdown']:
            print(f"\nGrade Breakdown:")
            for grade in sorted(stats['grade_breakdown'].keys()):
                breakdown = stats['grade_breakdown'][grade]
                grade_total = breakdown['passed'] + breakdown['rejected']
                grade_pass_rate = (breakdown['passed'] / grade_total * 100) if grade_total > 0 else 0
                print(
                    f"  • {grade}: {grade_total} signals | "
                    f"Passed: {breakdown['passed']} ({grade_pass_rate:.1f}%) | "
                    f"Rejected: {breakdown['rejected']}"
                )
        
        # Signal type breakdown
        if stats['signal_type_breakdown']:
            print(f"\nSignal Type Breakdown:")
            for sig_type in sorted(stats['signal_type_breakdown'].keys()):
                breakdown = stats['signal_type_breakdown'][sig_type]
                type_total = breakdown['passed'] + breakdown['rejected']
                type_pass_rate = (breakdown['passed'] / type_total * 100) if type_total > 0 else 0
                print(
                    f"  • {sig_type}: {type_total} signals | "
                    f"Passed: {breakdown['passed']} ({type_pass_rate:.1f}%) | "
                    f"Rejected: {breakdown['rejected']}"
                )
        
        # Top rejections (if any)
        if self._rejections:
            print(f"\nTop 5 Rejections (largest shortfall):")
            top_rejects = sorted(
                self._rejections, 
                key=lambda x: x['shortfall'], 
                reverse=True
            )[:5]
            for i, reject in enumerate(top_rejects, 1):
                time_str = reject['timestamp'].strftime('%I:%M %p')
                print(
                    f"  {i}. {reject['ticker']} ({reject['grade']}) @ {time_str} | "
                    f"Conf: {reject['confidence']:.2f} | Thresh: {reject['threshold']:.2f} | "
                    f"Short: -{reject['shortfall']:.2f}"
                )
        
        # Closest passes (if any)
        if self._passes:
            print(f"\nTop 5 Closest Passes (smallest margin):")
            close_passes = sorted(
                self._passes,
                key=lambda x: x['margin']
            )[:5]
            for i, pass_event in enumerate(close_passes, 1):
                time_str = pass_event['timestamp'].strftime('%I:%M %p')
                print(
                    f"  {i}. {pass_event['ticker']} ({pass_event['grade']}) @ {time_str} | "
                    f"Conf: {pass_event['confidence']:.2f} | Thresh: {pass_event['threshold']:.2f} | "
                    f"Margin: +{pass_event['margin']:.2f}"
                )
        
        print("\n💡 Insight: Monitor grade distribution and thresholds to optimize")
        print("   signal quality vs. signal quantity balance.")
        print("="*80 + "\n")
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at market close)."""
        self._passes.clear()
        self._rejections.clear()
        self._stats = {
            'total_evaluated': 0,
            'total_passed': 0,
            'total_rejected': 0,
            'grade_breakdown': {},
            'signal_type_breakdown': {},
            'avg_threshold': 0.0,
            'avg_passed_confidence': 0.0,
            'avg_rejected_confidence': 0.0
        }

# Global singleton instance
grade_gate_tracker = GradeGateTracker()
