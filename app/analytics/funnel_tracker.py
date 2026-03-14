# funnel_tracker.py — logic merged into app/analytics/funnel_analytics.py
# This shim keeps all imports from app.analytics.funnel_tracker working.

try:
    from app.analytics.funnel_analytics import (  # noqa: F401
        FunnelTracker,
        funnel_tracker,
        record_scan,
        get_funnel_stats,
    )
except ImportError:
    FunnelTracker  = None
    funnel_tracker = None
    def record_scan(*a, **kw): pass
    def get_funnel_stats(*a, **kw): return {}

# Legacy log_* names expected by app/analytics/__init__.py
def log_screened(*a, **kw): pass
def log_bos(*a, **kw): pass
def log_fvg(*a, **kw): pass
def log_validator(*a, **kw): pass
def log_armed(*a, **kw): pass
def log_fired(*a, **kw): pass
def log_filled(*a, **kw): pass
