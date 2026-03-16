# app/discord_helpers.py
# Centralized Discord messaging helpers for War Machine.
# Reads DISCORD_WEBHOOK_URL (and optional channel-specific overrides) from env.
# All functions are fire-and-forget: errors are logged but never raised,
# so a Discord outage never crashes the trading system.

import os
import logging
import requests

logger = logging.getLogger(__name__)

# ── Webhook URLs ──────────────────────────────────────────────────────────────
_DEFAULT_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
_ALERTS_WEBHOOK  = os.environ.get("DISCORD_ALERTS_WEBHOOK_URL", _DEFAULT_WEBHOOK)
_EXIT_WEBHOOK    = os.environ.get("DISCORD_EXIT_WEBHOOK_URL",   _DEFAULT_WEBHOOK)

_TIMEOUT = 5  # seconds


def _post(webhook_url: str, payload: dict) -> bool:
    """Low-level POST to a Discord webhook. Returns True on success."""
    if not webhook_url:
        logger.warning("[DISCORD] No webhook URL configured — message skipped")
        return False
    try:
        resp = requests.post(webhook_url, json=payload, timeout=_TIMEOUT)
        if resp.status_code not in (200, 204):
            logger.warning("[DISCORD] Webhook returned %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.warning("[DISCORD] Post failed (non-fatal): %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_simple_message(message: str, webhook_url: str = None) -> bool:
    """
    Send a plain-text message to Discord.

    Args:
        message:     The text to send.
        webhook_url: Override webhook. Falls back to DISCORD_WEBHOOK_URL env var.

    Returns:
        True if the message was delivered successfully.
    """
    url = webhook_url or _DEFAULT_WEBHOOK
    return _post(url, {"content": str(message)})


def send_alert(message: str, webhook_url: str = None) -> bool:
    """
    Send an alert message (uses DISCORD_ALERTS_WEBHOOK_URL if set).
    """
    url = webhook_url or _ALERTS_WEBHOOK
    return _post(url, {"content": str(message)})


def send_exit_alert(message: str, webhook_url: str = None) -> bool:
    """
    Send a position-exit alert (uses DISCORD_EXIT_WEBHOOK_URL if set).
    """
    url = webhook_url or _EXIT_WEBHOOK
    return _post(url, {"content": str(message)})


def send_scaling_alert(message: str, webhook_url: str = None) -> bool:
    """
    Send a position-scaling alert.
    """
    return send_alert(message, webhook_url)


def send_embed(title: str, description: str = "", color: int = 0x00FF00,
               fields: list = None, webhook_url: str = None) -> bool:
    """
    Send a rich embed message to Discord.

    Args:
        title:       Embed title.
        description: Embed body text.
        color:       Sidebar color as integer (default green).
        fields:      List of dicts with 'name', 'value', optional 'inline' keys.
        webhook_url: Override webhook.
    """
    url = webhook_url or _DEFAULT_WEBHOOK
    embed = {
        "title":       title,
        "description": description,
        "color":       color,
    }
    if fields:
        embed["fields"] = fields
    return _post(url, {"embeds": [embed]})
