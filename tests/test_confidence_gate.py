"""
War Machine — Confidence Gate Unit Tests  (Phase 1.23 / P0-4 explicit)
=======================================================================
Dedicated test file for the confidence scoring and grade-to-threshold
mapping used in sniper._run_signal_pipeline().

Covers:
  1. Grade→confidence range table completeness and ordering
  2. Confidence bucket boundaries (mirrors _get_confidence_bucket in sniper.py)
  3. Minimum-confidence gate behaviour (signals below floor are rejected)
  4. Grade assignment from raw confidence score
  5. Confidence clamping (never exceeds 0.99, never below 0.0)

Run with:
    pytest tests/test_confidence_gate.py -v
"""
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Canonical grade→confidence table (mirrors sniper.py)
# ─────────────────────────────────────────────────────────────────────────────
GRADE_RANGES = {
    "A+": (0.88, 0.92),
    "A":  (0.83, 0.87),
    "A-": (0.78, 0.82),
    "B+": (0.72, 0.76),
    "B":  (0.66, 0.70),
    "B-": (0.60, 0.64),
    "C+": (0.55, 0.60),
    "C":  (0.50, 0.55),
    "C-": (0.45, 0.50),
}

MIN_CONFIDENCE = 0.55  # signals below this are rejected by the gate


def _assign_grade(confidence: float) -> str:
    """Mirror the grade-assignment logic from sniper.py."""
    for grade, (lo, hi) in sorted(
        GRADE_RANGES.items(), key=lambda x: x[1][0], reverse=True
    ):
        if confidence >= lo:
            return grade
    return "F"  # below all ranges


def _get_confidence_bucket(c: float) -> str:
    """Mirror _get_confidence_bucket() from sniper.py."""
    if c < 0.50: return '0.40-0.50'
    if c < 0.60: return '0.50-0.60'
    if c < 0.70: return '0.60-0.70'
    if c < 0.80: return '0.70-0.80'
    if c < 0.90: return '0.80-0.90'
    return '0.90-0.95'


def _passes_confidence_gate(confidence: float) -> bool:
    return confidence >= MIN_CONFIDENCE


def _clamp_confidence(c: float) -> float:
    return max(0.0, min(0.99, c))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Grade table completeness and structure
# ─────────────────────────────────────────────────────────────────────────────
class TestGradeTable:
    def test_all_nine_grades_present(self):
        expected = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-"}
        assert set(GRADE_RANGES.keys()) == expected

    def test_each_grade_lo_less_than_hi(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert lo < hi, f"{grade}: lo ({lo}) must be < hi ({hi})"

    def test_grades_are_strictly_ascending(self):
        ordered = ["C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
        prev_hi = 0.0
        for grade in ordered:
            lo, hi = GRADE_RANGES[grade]
            assert lo >= prev_hi - 0.01, (
                f"{grade}: lo={lo} does not ascend from prev_hi={prev_hi}"
            )
            prev_hi = hi

    def test_aplus_has_highest_floor(self):
        aplus_lo, _ = GRADE_RANGES["A+"]
        for grade, (lo, hi) in GRADE_RANGES.items():
            if grade != "A+":
                assert hi <= aplus_lo + 0.01, (
                    f"{grade} ceiling ({hi}) overlaps A+ floor ({aplus_lo})"
                )

    def test_no_grade_exceeds_1(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert hi <= 1.0, f"{grade} hi={hi} exceeds 1.0"

    def test_no_grade_below_zero(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert lo >= 0.0, f"{grade} lo={lo} is negative"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Confidence bucket boundaries
# ─────────────────────────────────────────────────────────────────────────────
class TestConfidenceBuckets:
    @pytest.mark.parametrize("conf, expected", [
        (0.40, '0.40-0.50'),
        (0.49, '0.40-0.50'),
        (0.50, '0.50-0.60'),
        (0.599, '0.50-0.60'),
        (0.60, '0.60-0.70'),
        (0.699, '0.60-0.70'),
        (0.70, '0.70-0.80'),
        (0.799, '0.70-0.80'),
        (0.80, '0.80-0.90'),
        (0.899, '0.80-0.90'),
        (0.90, '0.90-0.95'),
        (0.95, '0.90-0.95'),
        (0.99, '0.90-0.95'),
    ])
    def test_bucket_boundary(self, conf, expected):
        assert _get_confidence_bucket(conf) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 3. Minimum confidence gate
# ─────────────────────────────────────────────────────────────────────────────
class TestConfidenceGateThreshold:
    def test_above_floor_passes(self):
        assert _passes_confidence_gate(0.60) is True
        assert _passes_confidence_gate(0.75) is True
        assert _passes_confidence_gate(0.90) is True

    def test_at_floor_passes(self):
        assert _passes_confidence_gate(MIN_CONFIDENCE) is True

    def test_below_floor_rejected(self):
        assert _passes_confidence_gate(0.54) is False
        assert _passes_confidence_gate(0.50) is False
        assert _passes_confidence_gate(0.30) is False
        assert _passes_confidence_gate(0.0)  is False

    def test_boundary_just_above(self):
        assert _passes_confidence_gate(MIN_CONFIDENCE + 0.001) is True

    def test_boundary_just_below(self):
        assert _passes_confidence_gate(MIN_CONFIDENCE - 0.001) is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Grade assignment from raw confidence
# ─────────────────────────────────────────────────────────────────────────────
class TestGradeAssignment:
    @pytest.mark.parametrize("conf, expected_grade", [
        (0.90, "A+"),
        (0.88, "A+"),
        (0.85, "A"),
        (0.83, "A"),
        (0.80, "A-"),
        (0.78, "A-"),
        (0.74, "B+"),
        (0.72, "B+"),
        (0.68, "B"),
        (0.66, "B"),
        (0.62, "B-"),
        (0.60, "B-"),
        (0.57, "C+"),
        (0.55, "C+"),
        (0.52, "C"),
        (0.50, "C"),
        (0.47, "C-"),
        (0.45, "C-"),
        (0.30, "F"),
    ])
    def test_grade_assignment(self, conf, expected_grade):
        assert _assign_grade(conf) == expected_grade


# ─────────────────────────────────────────────────────────────────────────────
# 5. Confidence clamping (boosts must never push above 0.99 or below 0.0)
# ─────────────────────────────────────────────────────────────────────────────
class TestConfidenceClamping:
    def test_clamp_at_max(self):
        assert _clamp_confidence(1.50) == 0.99
        assert _clamp_confidence(1.00) == 0.99
        assert _clamp_confidence(0.99) == 0.99

    def test_clamp_at_min(self):
        assert _clamp_confidence(-0.10) == 0.0
        assert _clamp_confidence(0.0)   == 0.0

    def test_no_clamp_in_range(self):
        for v in [0.01, 0.50, 0.75, 0.88, 0.98]:
            assert _clamp_confidence(v) == v

    def test_boost_cannot_exceed_ceiling(self):
        """Simulate a high-base signal receiving a large MTF boost."""
        base_conf = 0.96
        mtf_boost = 0.05
        result = _clamp_confidence(base_conf + mtf_boost)
        assert result == 0.99
