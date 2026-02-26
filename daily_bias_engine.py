"""
Daily Bias Engine - Compatibility Stub (Phase 3D)

This file has been consolidated into market_analysis.py.
All imports are redirected to maintain zero breaking changes.

Migration Path:
  OLD: from daily_bias_engine import bias_engine, get_daily_bias
  NEW: from market_analysis import bias_engine, get_daily_bias

Both work identically - use whichever you prefer.
"""

# Re-export everything from consolidated module
from market_analysis import (
    DailyBiasEngine,
    bias_engine,
    get_daily_bias,
    should_filter_signal,
    print_bias_summary,
    reset_bias,
)

__all__ = [
    'DailyBiasEngine',
    'bias_engine',
    'get_daily_bias',
    'should_filter_signal',
    'print_bias_summary',
    'reset_bias',
]
