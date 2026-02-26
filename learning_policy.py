"""
COMPATIBILITY STUB - Deprecated

This module has been consolidated into ai_learning.py
Imports are redirected for backwards compatibility.

New code should import from ai_learning.py directly:
    from ai_learning import compute_confidence, grade_to_label, MIN_CONFIDENCE

This stub will be removed in a future release.
"""

# Redirect all imports to unified module
from ai_learning import (
    compute_confidence,
    grade_to_label,
    MIN_CONFIDENCE,
    _GRADE_BASE,
    _TF_MULTIPLIER,
)

print("[DEPRECATED] learning_policy.py is deprecated. Use ai_learning.py instead.")
