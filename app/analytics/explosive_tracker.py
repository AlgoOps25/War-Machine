"""
DEPRECATED NAME — explosive_tracker is the old import path.
This shim re-exports explosive_mover_tracker so sniper.py imports don't fail.

Real implementation: app/analytics/explosive_mover_tracker.py
"""
from app.analytics.explosive_mover_tracker import *  # noqa: F401, F403
from app.analytics.explosive_mover_tracker import (  # noqa: F401
    explosive_mover_tracker,
)
