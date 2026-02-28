"""
signal_validator.py - Compatibility wrapper for validation.py

PHASE 3A CONSOLIDATION: This module was merged into validation.py
This wrapper maintains backward compatibility for imports.

For new code, use:
    from app.validation.validation import get_validator, SignalValidator
"""

# Import everything from the consolidated validation module
from app.validation.validation import (
    SignalValidator,
    get_validator,
    validate_signal,
    RegimeFilter,
    get_regime_filter,
    OptionsFilter,
    get_options_filter
)

# Expose for backward compatibility
__all__ = [
    'SignalValidator',
    'get_validator',
    'validate_signal',
    'RegimeFilter',
    'get_regime_filter',
    'OptionsFilter',
    'get_options_filter'
]

# Default instance for direct use
_validator_instance = None

def get_instance():
    """Get singleton validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = get_validator()
    return _validator_instance


