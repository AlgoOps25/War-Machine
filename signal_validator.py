"""
COMPATIBILITY STUB - Deprecated

Signal validation has been consolidated into validation.py (Phase 3A - Feb 26, 2026).
This stub maintains backwards compatibility for existing imports.

OLD USAGE (still works):
    from signal_validator import get_validator, SignalValidator

NEW USAGE (preferred):
    from validation import get_validator, SignalValidator

This file can be safely deleted after verifying no external dependencies.
All functionality is now in validation.py.

CHANGELOG:
  - Phase 3A (Feb 26, 2026): Consolidated into validation.py
  - Original size: 40KB (~1000 lines)
  - New stub size: <1KB
  - Reduction: ~97.5%
"""

# Forward all imports to the unified validation module
from validation import (
    SignalValidator,
    get_validator,
    get_time_of_day_quality
)

__all__ = [
    'SignalValidator',
    'get_validator',
    'get_time_of_day_quality'
]
