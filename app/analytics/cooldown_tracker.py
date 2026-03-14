"""
DEPRECATED — merged into app.core.signal_generator_cooldown

This module is kept as a thin re-export shim so any missed import paths
don't crash the process. All logic lives in signal_generator_cooldown.
"""
from app.core.signal_generator_cooldown import (  # noqa: F401
    CooldownTracker,
    cooldown_tracker,
    is_on_cooldown,
    set_cooldown,
    clear_cooldown,
    clear_all_cooldowns,
    get_active_cooldowns,
    print_cooldown_summary,
)
