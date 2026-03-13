# Grade Gate Tracker - Tracks confidence threshold decisions
# Purpose: Monitor how many signals pass/fail confidence gates
# Helps tune dynamic thresholds and understand signal quality distribution
# REFACTOR (Mar 12 2026): Absorbed _gate_stats histogram, track_gate_result,
#   and print_gate_distribution_stats from sniper.py (Phase 1, Step 1)

from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo


class GradeGateTracker:
    """
    Tracks confidence gate decisions (pass/reject) for signal quality analysis.
    Monitors grade distribution, threshold effectiveness, and gate performance.
    Also owns the per-session confidence histogram (absorbed from sniper.py).
    """

    GRADE_ORDER = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-']
    SIGNAL_TYPES = ['CFW6_OR', 'CFW6_INTRADAY']

    def __init__(self):
        self._passes: List[Dict] = []
        self._rejections: List[Dict] = []
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
        # Histogram buckets — absorbed from sniper._gate_stats
        self._histogram: Dict[str, Dict] = {
            'by_grade': {
                g: {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0}
                for g in self.GRADE_ORDER
            },
            'by_signal_type': {
                s: {'tested': 0, 'passed': 0, 'filtered': 0}
                for s in self.SIGNAL_TYPES
            },
            'confidence_ranges': {
                '0.40-0.50': 0,
                '0.50-0.60': 0,
                '0.60-0.70': 0,
                '0.70-0.80': 0,
                '0.80-0.90': 0,
                '0.90-0.95': 0,
            }
        }

    def _now_et(self) -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))

    # ── Histogram helpers (absorbed from sniper._get_confidence_bucket) ────────

    @staticmethod
    def get_confidence_bucket(confidence: float) -> str:
        if confidence < 0.50: return '0.40-0.50'
        if confidence < 0.60: return '0.50-0.60'
        if confidence < 0.70: return '0.60-0.70'
        if confidence < 0.80: return '0.70-0.80'
        if confidence < 0.90: return '0.80-0.90'
        return '0.90-0.95'

    def track_gate_result(self, grade: str, signal_type: str, confidence: float, passed: bool) -> None:
        """Record a gate result into the histogram (absorbed from sniper._track_gate_result)."""
        if grade in self._histogram['by_grade']:
            g = self._histogram['by_grade'][grade]
            g['tested'] += 1
            if passed:
                g['passed'] += 1
            else:
                g['filtered'] += 1
            n = g['tested']
            g['avg_confidence'] = (g['avg_confidence'] * (n - 1) + confidence) / n

        if signal_type in self._histogram['by_signal_type']:
            s = self._histogram['by_signal_type'][signal_type]
            s['tested'] += 1
            if passed:
                s['passed'] += 1
            else:
                s['filtered'] += 1

        bucket = self.get_confidence_bucket(confidence)
        if bucket in self._histogram['confidence_ranges']:
            self._histogram['confidence_ranges'][bucket] += 1

    # ── Existing record methods (unchanged) ────────────────────────────────────

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
        self._passes.append({
            'ticker': ticker, 'grade': grade, 'confidence': confidence,
            'threshold': threshold, 'signal_type': signal_type,
            'timestamp': timestamp, 'margin': confidence - threshold
        })
        self._stats['total_evaluated'] += 1
        self._stats['total_passed'] += 1
        if grade not in self._stats['grade_breakdown']:
            self._stats['grade_breakdown'][grade] = {'passed': 0, 'rejected': 0}
        self._stats['grade_breakdown'][grade]['passed'] += 1
        if signal_type not in self._stats['signal_type_breakdown']:
            self._stats['signal_type_breakdown'][signal_type] = {'passed': 0, 'rejected': 0}
        self._stats['signal_type_breakdown'][signal_type]['passed'] += 1
        n = self._stats['total_passed']
        self._stats['avg_passed_confidence'] = (
            (self._stats['avg_passed_confidence'] * (n - 1) + confidence) / n
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
        self._rejections.append({
            'ticker': ticker, 'grade': grade, 'confidence': confidence,
            'threshold': threshold, 'signal_type': signal_type,
            'timestamp': timestamp, 'shortfall': threshold - confidence
        })
        self._stats['total_evaluated'] += 1
        self._stats['total_rejected'] += 1
        if grade not in self._stats['grade_breakdown']:
            self._stats['grade_breakdown'][grade] = {'passed': 0, 'rejected': 0}
        self._stats['grade_breakdown'][grade]['rejected'] += 1
        if signal_type not in self._stats['signal_type_breakdown']:
            self._stats['signal_type_breakdown'][signal_type] = {'passed': 0, 'rejected': 0}
        self._stats['signal_type_breakdown'][signal_type]['rejected'] += 1
        n = self._stats['total_rejected']
        self._stats['avg_rejected_confidence'] = (
            (self._stats['avg_rejected_confidence'] * (n - 1) + confidence) / n
        )
        total = self._stats['total_evaluated']
        self._stats['avg_threshold'] = (
            (self._stats['avg_threshold'] * (total - 1) + threshold) / total
        )

    # ── Distribution report (absorbed from sniper.print_gate_distribution_stats) ─

    def print_gate_distribution_stats(self) -> None:
        """Print EOD confidence gate grade distribution report."""
        hist = self._histogram
        total_tested = sum(v['tested'] for v in hist['by_grade'].values())
        if total_tested == 0:
            return

        print("\n" + "=" * 80)
        print("CONFIDENCE GATE — GRADE DISTRIBUTION")
        print("=" * 80)
        print(f"\n{'Grade':<6} {'Tested':<8} {'Passed':<8} {'Filtered':<10} {'Pass Rate':<12} {'Avg Conf':<10}")
        print("-" * 80)
        for grade in self.GRADE_ORDER:
            s = hist['by_grade'][grade]
            if s['tested'] == 0:
                continue
            pass_rate = s['passed'] / s['tested'] * 100
            emoji = "✅" if pass_rate >= 80 else "⚠️ " if pass_rate >= 50 else "🚫"
            print(
                f"{grade:<6} {s['tested']:<8} {s['passed']:<8} "
                f"{s['filtered']:<10} {pass_rate:>5.1f}% {emoji:<4} "
                f"{s['avg_confidence']:.3f}"
            )

        print("\nBy Signal Type:")
        print(f"{'Type':<15} {'Tested':<8} {'Passed':<8} {'Filtered':<10} {'Pass Rate':<12}")
        print("-" * 80)
        for sig_type, st in hist['by_signal_type'].items():
            if st['tested'] == 0:
                continue
            pr = st['passed'] / st['tested'] * 100
            print(f"{sig_type:<15} {st['tested']:<8} {st['passed']:<8} {st['filtered']:<10} {pr:>5.1f}%")

        print("\nConfidence Distribution:")
        max_count = max(hist['confidence_ranges'].values()) or 1
        for bucket, count in hist['confidence_ranges'].items():
            bar = '█' * int((count / max_count) * 40)
            print(f"{bucket}: {bar} ({count})")

        print("\n💡 Analysis:")
        b_plus = hist['by_grade']['B+']
        if b_plus['tested'] > 5 and (b_plus['passed'] / b_plus['tested']) < 0.30:
            print("  ⚠️  B+ signals heavily filtered (<30% pass rate) — consider lowering gate threshold")
        c_stats = hist['by_grade']['C']
        if c_stats['tested'] > 5 and (c_stats['passed'] / c_stats['tested']) > 0.50:
            print("  ⚠️  C signals passing frequently (>50% pass rate) — consider raising gate threshold")
        or_st = hist['by_signal_type']['CFW6_OR']
        id_st = hist['by_signal_type']['CFW6_INTRADAY']
        if or_st['tested'] > 0 and id_st['tested'] > 0:
            or_pr = or_st['passed'] / or_st['tested']
            id_pr = id_st['passed'] / id_st['tested']
            if abs(or_pr - id_pr) > 0.30:
                print(
                    f"  ⚠️  Large pass rate gap: OR={or_pr:.1%} vs Intraday={id_pr:.1%} "
                    f"— gate thresholds may need adjustment"
                )
        if not any([
            b_plus['tested'] > 5 and (b_plus['passed'] / b_plus['tested']) < 0.30,
            c_stats['tested'] > 5 and (c_stats['passed'] / c_stats['tested']) > 0.50,
            or_st['tested'] > 0 and id_st['tested'] > 0 and
            abs(or_st['passed'] / or_st['tested'] - id_st['passed'] / id_st['tested']) > 0.30,
        ]):
            print("  ✅ Gate distribution looks healthy — no threshold adjustments needed")
        print("=" * 80 + "\n")

    # ── Existing EOD report (unchanged) ────────────────────────────────────────

    def get_pass_rate(self) -> float:
        total = self._stats['total_evaluated']
        if total == 0:
            return 0.0
        return (self._stats['total_passed'] / total) * 100

    def get_grade_pass_rate(self, grade: str) -> float:
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
        if self._rejections:
            print(f"\nTop 5 Rejections (largest shortfall):")
            top_rejects = sorted(self._rejections, key=lambda x: x['shortfall'], reverse=True)[:5]
            for i, reject in enumerate(top_rejects, 1):
                time_str = reject['timestamp'].strftime('%I:%M %p')
                print(
                    f"  {i}. {reject['ticker']} ({reject['grade']}) @ {time_str} | "
                    f"Conf: {reject['confidence']:.2f} | Thresh: {reject['threshold']:.2f} | "
                    f"Short: -{reject['shortfall']:.2f}"
                )
        if self._passes:
            print(f"\nTop 5 Closest Passes (smallest margin):")
            close_passes = sorted(self._passes, key=lambda x: x['margin'])[:5]
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
        # Also print histogram distribution
        self.print_gate_distribution_stats()

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
        self._histogram = {
            'by_grade': {
                g: {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0}
                for g in self.GRADE_ORDER
            },
            'by_signal_type': {
                s: {'tested': 0, 'passed': 0, 'filtered': 0}
                for s in self.SIGNAL_TYPES
            },
            'confidence_ranges': {
                '0.40-0.50': 0, '0.50-0.60': 0, '0.60-0.70': 0,
                '0.70-0.80': 0, '0.80-0.90': 0, '0.90-0.95': 0,
            }
        }


# Global singleton instance
grade_gate_tracker = GradeGateTracker()


if __name__ == "__main__":
    # Smoke test
    t = GradeGateTracker()
    t.track_gate_result('A+', 'CFW6_OR', 0.91, passed=True)
    t.track_gate_result('B+', 'CFW6_INTRADAY', 0.72, passed=False)
    t.record_gate_pass('AAPL', 'A+', 0.91, 0.85, 'CFW6_OR')
    t.record_gate_rejection('TSLA', 'B+', 0.72, 0.75, 'CFW6_INTRADAY')
    t.print_gate_distribution_stats()
    t.print_eod_report()
    print("✅ Smoke test passed")
