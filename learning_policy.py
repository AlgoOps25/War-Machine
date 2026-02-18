"""
Learning Policy - Confidence Scoring for CFW6 Signals

Provides compute_confidence() used by sniper.py to score
signal quality based on grade, timeframe, and ticker history.
"""
import config

# Grade baseline confidence map (CFW6 video rules)
_GRADE_BASE = {
    "A+": 0.85,
    "A":  0.70,
    "A-": 0.55,
}

# Timeframe multiplier: higher timeframe = higher weight
_TF_MULTIPLIER = {
    "5m": 1.05,
    "3m": 1.02,
    "2m": 1.00,
    "1m": 0.97,
}

# Minimum threshold - signals below this are dropped upstream
MIN_CONFIDENCE = 0.50


def compute_confidence(
    grade: str,
    timeframe: str = "1m",
    ticker: str = ""
) -> float:
    """
    Compute base confidence score for a CFW6 signal.

    Args:
        grade:     Signal grade string - "A+", "A", "A-"
        timeframe: Bar timeframe - "1m", "2m", "3m", "5m"
        ticker:    Ticker symbol (reserved for future per-ticker tuning)

    Returns:
        Float in [0.0, 1.0] representing signal confidence.
    """
    # Base score from grade
    base = _GRADE_BASE.get(grade, 0.50)

    # Timeframe multiplier
    tf_mult = _TF_MULTIPLIER.get(timeframe, 1.00)

    # Compute raw score
    score = base * tf_mult

    # Clamp to valid range
    return round(min(max(score, 0.0), 1.0), 4)


def grade_to_label(confidence: float) -> str:
    """
    Convert a numeric confidence back to a readable label.
    Used for logging and Discord alerts.
    """
    if confidence >= 0.80:
        return "A+"
    elif confidence >= 0.65:
        return "A"
    elif confidence >= 0.50:
        return "A-"
    else:
        return "reject"
