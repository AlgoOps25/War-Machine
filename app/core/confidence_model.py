"""
confidence_model.py — DEPRECATED SHIM

This module is superseded by app.ai.ai_learning which now contains
the full 9-grade _GRADE_BASE map and compute_confidence() with
timeframe multiplier support.

This shim re-exports for backward compatibility during transition.
PENDING DELETE: Once sniper.py import is updated, this file will be removed.
Do NOT add new code here.
"""

from app.ai.ai_learning import compute_confidence, _GRADE_BASE as GRADE_CONFIDENCE_RANGES  # noqa: F401

__all__ = ["compute_confidence", "GRADE_CONFIDENCE_RANGES"]
