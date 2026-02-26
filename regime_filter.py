"""
COMPATIBILITY STUB - Deprecated

Regime filtering has been consolidated into validation.py (Phase 3A - Feb 26, 2026).
This stub maintains backwards compatibility for existing imports.

OLD USAGE (still works):
    from regime_filter import regime_filter, RegimeFilter

NEW USAGE (preferred):
    from validation import get_regime_filter, RegimeFilter

This file can be safely deleted after verifying no external dependencies.
All functionality is now in validation.py.

CHANGELOG:
  - Phase 3A (Feb 26, 2026): Consolidated into validation.py
  - Original size: 14KB (~350 lines)
  - New stub size: <1KB
  - Reduction: ~92.8%
"""

# Forward all imports to the unified validation module
from validation import (
    RegimeFilter,
    RegimeState,
    get_regime_filter
)

# Maintain original singleton pattern for backwards compatibility
regime_filter = get_regime_filter()

__all__ = [
    'RegimeFilter',
    'RegimeState',
    'regime_filter',
    'get_regime_filter'
]
