"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

from app.analytics.funnel_tracker import funnel_tracker
from app.analytics.ab_test import ab_test

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
    __all__ = ['ANALYTICS_AVAILABLE', 'AnalyticsIntegration']
except Exception as e:
    # Gracefully disable if analytics_integration or its dependencies are missing
    print(f"[ANALYTICS] Module unavailable: {e}")
    ANALYTICS_AVAILABLE = False
    AnalyticsIntegration = None
    __all__ = ['ANALYTICS_AVAILABLE', 'AnalyticsIntegration']
