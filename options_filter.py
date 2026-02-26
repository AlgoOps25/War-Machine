"""
COMPATIBILITY STUB - Deprecated

Options filtering has been consolidated into validation.py (Phase 3A - Feb 26, 2026).
This stub maintains backwards compatibility for existing imports.

OLD USAGE (still works):
    from options_filter import OptionsFilter, get_options_recommendation

NEW USAGE (preferred):
    from validation import OptionsFilter, get_options_filter, get_options_recommendation

This file can be safely deleted after verifying no external dependencies.
All functionality is now in validation.py.

CHANGELOG:
  - Phase 3A (Feb 26, 2026): Consolidated into validation.py
  - Original size: 18KB (~450 lines)
  - New stub size: <1KB
  - Reduction: ~94.4%
"""

# Forward all imports to the unified validation module
from validation import (
    OptionsFilter,
    get_options_filter,
    get_options_recommendation
)

# Maintain original singleton pattern for backwards compatibility
options_filter = get_options_filter()

__all__ = [
    'OptionsFilter',
    'options_filter',
    'get_options_filter',
    'get_options_recommendation'
]
