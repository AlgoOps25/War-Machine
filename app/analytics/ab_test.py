# ab_test.py — logic merged into app/analytics/ab_test_framework.py
# This shim keeps all imports from app.analytics.ab_test working.

try:
    from app.analytics.ab_test_framework import (  # noqa: F401
        ABTestFramework,
        ab_test_framework,
        run_ab_test,
    )
except ImportError:
    ABTestFramework    = None
    ab_test_framework  = None
    def run_ab_test(*a, **kw): return {}

# Legacy name expected by app/analytics/__init__.py
ab_test = ab_test_framework  # alias
