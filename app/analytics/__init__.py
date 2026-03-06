"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
    __all__ = ['ANALYTICS_AVAILABLE', 'AnalyticsIntegration']  # Add to exports
except ImportError:
    ANALYTICS_AVAILABLE = False
    __all__ = ['ANALYTICS_AVAILABLE']
