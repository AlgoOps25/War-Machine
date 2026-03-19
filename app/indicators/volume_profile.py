# DELETED — PR #33 (Mar 19, 2026)
#
# app/indicators/volume_profile.py was an unwired dead-code calculator that
# was never imported by any live module.  Its functionality (POC/VAH/VAL,
# HVN/LVN, 5-min TTL cache) has been merged into
# app/validation/volume_profile.py with the following upgrades:
#
#   - Fixed 20¢ bin resolution  (was 50¢ / 50-bin)
#   - CME two-bar value area expansion  (was single-bar)
#   - Module-level TTL cache shared across instances
#   - numpy dependency removed
#   - confidence_boost + options_bias output keys added
#
# This file is intentionally left as a tombstone comment so git history is
# self-documenting.  It is safe to delete the file entirely; the tombstone
# just prevents accidental re-creation.
#
# If you need the old standalone API for backtesting / notebooks, restore
# from tag pre-pr33 or commit 57f418d.
raise ImportError(
    "app.indicators.volume_profile has been removed.  "
    "Use app.validation.volume_profile.get_volume_analyzer() instead."
)
