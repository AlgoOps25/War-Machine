"""
VPVR Calculator - Compatibility Stub (Phase 3D)

This file has been consolidated into market_analysis.py.
All imports are redirected to maintain zero breaking changes.

Migration Path:
  OLD: from vpvr_calculator import vpvr_calculator, VPVRCalculator
  NEW: from market_analysis import vpvr_calculator, VPVRCalculator

Both work identically - use whichever you prefer.
"""

# Re-export everything from consolidated module
from market_analysis import (
    VPVRCalculator,
    vpvr_calculator,
)

__all__ = [
    'VPVRCalculator',
    'vpvr_calculator',
]
