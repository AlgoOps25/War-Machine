"""
Analytics Module for War Machine
Central import point for signal tracking and performance analytics
"""

try:
    from app.analytics.funnel_tracker import funnel_tracker, log_screened
except ImportError as e:
    print(f"[ANALYTICS] funnel_tracker unavailable: {e}")
    funnel_tracker = None
    log_screened = None

try:
    from app.analytics.ab_test import ab_test
except ImportError as e:
    print(f"[ANALYTICS] ab_test unavailable: {e}")
    ab_test = None

try:
    from app.core.analytics_integration import AnalyticsIntegration
    ANALYTICS_AVAILABLE = True
except Exception as e:
    print(f"[ANALYTICS] Module unavailable: {e}")
    ANALYTICS_AVAILABLE = False
    AnalyticsIntegration = None

__all__ = [
    'ANALYTICS_AVAILABLE',
    'AnalyticsIntegration',
    'funnel_tracker',
    'ab_test',
    'log_screened',
]
