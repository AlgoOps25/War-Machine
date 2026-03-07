"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
    __all__ = ['ANALYTICS_AVAILABLE', 'AnalyticsIntegration']
except ImportError as e:
    # Gracefully disable if analytics_integration is missing
    print(f"[ANALYTICS] Module unavailable: {e}")
    ANALYTICS_AVAILABLE = False
    AnalyticsIntegration = None
    __all__ = ['ANALYTICS_AVAILABLE', 'AnalyticsIntegration']
