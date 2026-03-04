"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False
    AnalyticsIntegration = None

__all__ = ['AnalyticsIntegration', 'ANALYTICS_AVAILABLE']
