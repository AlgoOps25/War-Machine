"""
Analytics Module - Signal Performance Tracking and Optimization

Provides:
  - Funnel analytics (conversion rates at each stage)
  - A/B testing framework (parameter optimization)
  - Discord reporting (EOD summaries)
"""
from app.analytics.funnel_analytics import (
    funnel_tracker,
    log_screened,
    log_bos,
    log_fvg,
    log_validator,
    log_armed,
    log_fired,
    log_filled
)
from app.analytics.ab_test_framework import ab_test

__all__ = [
    'funnel_tracker',
    'ab_test',
    'log_screened',
    'log_bos',
    'log_fvg',
    'log_validator',
    'log_armed',
    'log_fired',
    'log_filled'
]
