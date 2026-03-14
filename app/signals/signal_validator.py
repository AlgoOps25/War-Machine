# signal_validator.py — merged into app/validation/validation.py
# This shim keeps all existing imports from app.signals.signal_validator working.
from app.validation.validation import (  # noqa: F401
    SignalValidator,
    get_validator,
    RegimeFilter,
    get_regime_filter,
    OptionsFilter,
    get_options_filter,
)


def get_instance():
    """Legacy singleton getter — delegates to get_validator()."""
    return get_validator()
