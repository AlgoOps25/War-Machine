"""
gate_stats.py — Confidence Gate Distribution Tracker
Extracted from sniper.py (Issue #23)

Provides:
    _gate_stats                   — in-memory counters (grade / signal-type / histogram)
    _get_confidence_bucket()      — maps float → histogram label
    _track_gate_result()          — record one gate pass/fail
    print_gate_distribution_stats() — EOD report
"""

_gate_stats = {
    'by_grade': {
        'A+': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'A':  {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'A-': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'B+': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'B':  {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'B-': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'C+': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'C':  {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
        'C-': {'tested': 0, 'passed': 0, 'filtered': 0, 'avg_confidence': 0.0},
    },
    'by_signal_type': {
        'CFW6_OR':       {'tested': 0, 'passed': 0, 'filtered': 0},
        'CFW6_INTRADAY': {'tested': 0, 'passed': 0, 'filtered': 0},
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


def _get_confidence_bucket(confidence: float) -> str:
    """Map a confidence value to its histogram bucket label."""
    if confidence < 0.50: return '0.40-0.50'
    if confidence < 0.60: return '0.50-0.60'
    if confidence < 0.70: return '0.60-0.70'
    if confidence < 0.80: return '0.70-0.80'
    if confidence < 0.90: return '0.80-0.90'
    return '0.90-0.95'


def _track_gate_result(grade: str, signal_type: str, confidence: float, passed: bool):
    """Record one confidence gate result for EOD grade distribution analytics."""
    if grade in _gate_stats['by_grade']:
        stats = _gate_stats['by_grade'][grade]
        stats['tested'] += 1
        if passed:
            stats['passed'] += 1
        else:
            stats['filtered'] += 1
        n = stats['tested']
        stats['avg_confidence'] = (stats['avg_confidence'] * (n - 1) + confidence) / n

    if signal_type in _gate_stats['by_signal_type']:
        st = _gate_stats['by_signal_type'][signal_type]
        st['tested'] += 1
        if passed:
            st['passed'] += 1
        else:
            st['filtered'] += 1

    bucket = _get_confidence_bucket(confidence)
    if bucket in _gate_stats['confidence_ranges']:
        _gate_stats['confidence_ranges'][bucket] += 1


def print_gate_distribution_stats():
    """Print EOD confidence gate grade distribution report."""
    total_tested = sum(v['tested'] for v in _gate_stats['by_grade'].values())
    if total_tested == 0:
        return

    print("\n" + "=" * 80)
    print("CONFIDENCE GATE — GRADE DISTRIBUTION")
    print("=" * 80)

    print(f"\n{'Grade':<6} {'Tested':<8} {'Passed':<8} {'Filtered':<10} {'Pass Rate':<12} {'Avg Conf':<10}")
    print("-" * 80)
    for grade in ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-']:
        s = _gate_stats['by_grade'][grade]
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
    for sig_type, st in _gate_stats['by_signal_type'].items():
        if st['tested'] == 0:
            continue
        pr = st['passed'] / st['tested'] * 100
        print(f"{sig_type:<15} {st['tested']:<8} {st['passed']:<8} {st['filtered']:<10} {pr:>5.1f}%")

    print("\nConfidence Distribution:")
    max_count = max(_gate_stats['confidence_ranges'].values()) or 1
    for bucket, count in _gate_stats['confidence_ranges'].items():
        bar = '█' * int((count / max_count) * 40)
        print(f"{bucket}: {bar} ({count})")

    print("\n💡 Analysis:")
    b_plus = _gate_stats['by_grade']['B+']
    if b_plus['tested'] > 5 and (b_plus['passed'] / b_plus['tested']) < 0.30:
        print("  ⚠️  B+ signals heavily filtered (<30% pass rate) — consider lowering gate threshold")
    c_stats = _gate_stats['by_grade']['C']
    if c_stats['tested'] > 5 and (c_stats['passed'] / c_stats['tested']) > 0.50:
        print("  ⚠️  C signals passing frequently (>50% pass rate) — consider raising gate threshold")
    or_st = _gate_stats['by_signal_type']['CFW6_OR']
    id_st = _gate_stats['by_signal_type']['CFW6_INTRADAY']
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
        or_st['tested'] > 0 and id_st['tested'] > 0 and abs(
            or_st['passed'] / or_st['tested'] - id_st['passed'] / id_st['tested']
        ) > 0.30,
    ]):
        print("  ✅ Gate distribution looks healthy — no threshold adjustments needed")

    print("=" * 80 + "\n")
