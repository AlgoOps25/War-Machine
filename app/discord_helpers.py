# app/discord_helpers.py
# ─────────────────────────────────────────────────────────────────────────────
# Re-export shim — all Discord helpers now live in app.notifications.discord_helpers.
#
# This file exists solely so that legacy import paths like:
#   from app.discord_helpers import send_simple_message
#   from app.discord_helpers import send_options_signal_alert
# continue to resolve without touching every caller.
#
# DO NOT add new logic here.  Add it in app/notifications/discord_helpers.py.
# ─────────────────────────────────────────────────────────────────────────────

from app.notifications.discord_helpers import (  # noqa: F401
    send_simple_message,
    send_options_signal_alert,
    send_equity_bos_fvg_alert,
    send_scaling_alert,
    send_exit_alert,
    send_daily_summary,
    send_premarket_watchlist,
    test_webhook,
    _send_to_discord,
)

__all__ = [
    "send_simple_message",
    "send_options_signal_alert",
    "send_equity_bos_fvg_alert",
    "send_scaling_alert",
    "send_exit_alert",
    "send_daily_summary",
    "send_premarket_watchlist",
    "test_webhook",
    "_send_to_discord",
]
