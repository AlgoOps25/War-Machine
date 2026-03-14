# funnel_tracker.py — logic merged into app/analytics/funnel_analytics.py
# This shim keeps scanner.py optional import from raising a hard error.
try:
    from app.analytics.funnel_analytics import (  # noqa: F401
        FunnelTracker,
        funnel_tracker,
        record_scan,
        get_funnel_stats,
    )
except ImportError:
    pass
