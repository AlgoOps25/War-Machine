# ab_test.py — logic merged into app/analytics/ab_test_framework.py
# This shim keeps scanner.py optional import from raising a hard error.
try:
    from app.analytics.ab_test_framework import (  # noqa: F401
        ABTestFramework,
        ab_test_framework,
        run_ab_test,
    )
except ImportError:
    pass
