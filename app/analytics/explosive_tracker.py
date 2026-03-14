"""
Shim: app.analytics.explosive_tracker
--------------------------------------
sniper.py imports:  from app.analytics.explosive_tracker import explosive_tracker

The real implementation lives in app.analytics.explosive_mover_tracker.
This file re-exports the singleton so the old import path keeps working.
"""
from app.analytics.explosive_mover_tracker import (  # noqa: F401
    explosive_tracker,
    ExplosiveMoverTracker,
    track_explosive_override,
    update_override_outcome,
    print_explosive_override_summary,
    get_daily_override_stats,
)

__all__ = [
    "explosive_tracker",
    "ExplosiveMoverTracker",
    "track_explosive_override",
    "update_override_outcome",
    "print_explosive_override_summary",
    "get_daily_override_stats",
]
