# Canonical implementation moved to app/analytics/cooldown_tracker.py
# This shim keeps all existing imports from app.core.signal_generator_cooldown working.
from app.analytics.cooldown_tracker import (  # noqa: F401
    CooldownTracker,
    cooldown_tracker,
    is_on_cooldown,
    set_cooldown,
    clear_cooldown,
    clear_all_cooldowns,
    get_active_cooldowns,
    print_cooldown_summary,
    COOLDOWN_SAME_DIRECTION_MINUTES,
    COOLDOWN_OPPOSITE_DIRECTION_MINUTES,
)
