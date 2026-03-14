"""
confidence_model.py — Hybrid Confidence Model
Extracted from sniper.py (Phase 2 win rate enhancement)

Provides:
    GRADE_CONFIDENCE_RANGES  — dict mapping grade → (min, max) confidence tuple
    compute_confidence()     — returns midpoint confidence for a given grade
"""

GRADE_CONFIDENCE_RANGES = {
    "A+":  (0.88, 0.92),
    "A":   (0.83, 0.87),
    "A-":  (0.78, 0.82),
    "B+":  (0.72, 0.76),
    "B":   (0.66, 0.70),
    "B-":  (0.60, 0.64),
    "C+":  (0.55, 0.60),
    "C":   (0.50, 0.55),
    "C-":  (0.45, 0.50),
}


def compute_confidence(grade: str, timeframe: str, ticker: str) -> float:
    """
    Return the midpoint confidence for the given grade.
    Falls back to 0.75 for unrecognised grades.
    timeframe and ticker are accepted for call-site compatibility but unused.
    """
    if grade not in GRADE_CONFIDENCE_RANGES:
        return 0.75
    min_conf, max_conf = GRADE_CONFIDENCE_RANGES[grade]
    return (min_conf + max_conf) / 2.0
