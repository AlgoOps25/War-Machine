"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
except ImportError:
    # Do NOT set AnalyticsIntegration = None here.
    # Exporting None lets callers import it without error, then crash
    # when they call it ('NoneType' object is not callable).
    # Leave it undefined so 'from app.analytics import AnalyticsIntegration'
    # raises ImportError, which scanner.py's try/except already handles.
    ANALYTICS_AVAILABLE = False

__all__ = ['ANALYTICS_AVAILABLE']
