"""
Options Data Manager - STUB (Phase 3C)

This module has been consolidated into options_intelligence.py.
This stub provides backward compatibility.

Consolidated modules:
  - options_data_manager.py
  - uoa_scanner.py
  → options_intelligence.py
"""

# Forward all imports to the new consolidated module
from options_intelligence import (
    OptionsIntelligence,
    options_intelligence,
    options_dm,
    get_options_score,
    validate_for_trading,
    get_live_gex,
    scan_chain_for_uoa,
    clear_options_cache
)

# Alias for backward compatibility
OptionsDataManager = OptionsIntelligence

__all__ = [
    'OptionsDataManager',
    'OptionsIntelligence',
    'options_intelligence',
    'options_dm',
    'get_options_score',
    'validate_for_trading',
    'get_live_gex',
    'scan_chain_for_uoa',
    'clear_options_cache'
]
