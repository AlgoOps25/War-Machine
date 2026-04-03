"""
Discord Annotation Listener
===========================
Monitors the #chart-annotations Discord channel for human-posted R:R ratio
messages (e.g. "3.31", "LONG 4.1", "bear 2.5") and dispatches them to the
annotation_resolver for validation against live candle data before routing
into the War Machine position pipeline.

Usage (standalone thread launched from main.py or scanner.py):

    from app.notifications.discord_annotation_listener import start_annotation_listener
    import threading
    threading.Thread(target=start_annotation_listener, daemon=True).start()

Environment / config required:
    DISCORD_BOT_TOKEN            - bot token with MESSAGE_CONTENT intent
    DISCORD_ANNOTATION_CHANNEL_ID - integer channel ID for #chart-annotations
    ANNOTATION_DEFAULT_SYMBOL    - futures symbol to trade (default: "NQM25")

Message format accepted:
    "3.31"          -> R:R 3.31, direction inferred from last BOS
    "LONG 4.1"      -> R:R 4.1, forced LONG
    "bear 2.5"      -> R:R 2.5, forced SHORT
    Anything else is silently ignored.
"""

import re
import asyncio
import logging
import threading

import discord

from utils import config
from app.signals.annotation_resolver import resolve_annotation

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_BOT_TOKEN    = getattr(config, "DISCORD_BOT_TOKEN", None)
_CHANNEL_ID   = int(getattr(config, "DISCORD_ANNOTATION_CHANNEL_ID", 0))
_DEFAULT_SYM  = getattr(config, "ANNOTATION_DEFAULT_SYMBOL", "NQM25")

# Pattern: optional direction prefix + float R:R
# Accepts: "3.31"  "LONG 4.1"  "bull 2.5"  "SHORT 3.0"  "bear 2.0"
_MSG_RE = re.compile(
    r"^\s*(?:(long|bull|short|bear)\s+)?(\d+\.\d+)\s*$",
    re.IGNORECASE,
)


class _AnnotationClient(discord.Client):
    """Minimal discord.py client — listens for annotation messages only."""

    async def on_ready(self):
        logger.info(f"[ANNOTATION] Bot connected as {self.user} "
                    f"| watching channel {_CHANNEL_ID}")

    async def on_message(self, message: discord.Message):
        if message.channel.id != _CHANNEL_ID:
            return
        if message.author.bot:
            return

        m = _MSG_RE.match(message.content)
        if not m:
            return

        direction_hint = m.group(1)  # "long" | "bull" | "short" | "bear" | None
        rr_ratio       = float(m.group(2))

        # Normalise to "bull" / "bear" / None
        if direction_hint:
            direction_hint = (
                "bull" if direction_hint.lower() in ("long", "bull") else "bear"
            )

        logger.info(
            f"[ANNOTATION] Received R:R={rr_ratio} "
            f"dir_hint={direction_hint or 'auto'} "
            f"from {message.author.name}"
        )

        # Fire-and-forget: run resolver in background without blocking bot loop
        asyncio.create_task(
            _dispatch(rr_ratio, direction_hint, message.created_at)
        )


async def _dispatch(rr_ratio: float, direction_hint, posted_at):
    """Async wrapper so errors in the resolver never crash the bot."""
    try:
        await asyncio.to_thread(
            resolve_annotation,
            rr_ratio,
            direction_hint,
            _DEFAULT_SYM,
            posted_at,
        )
    except Exception as exc:
        logger.error(f"[ANNOTATION] resolve_annotation raised: {exc}", exc_info=True)


def start_annotation_listener():
    """
    Entry point — call from a daemon thread.
    Creates a fresh event loop so the bot doesn't compete with any existing
    asyncio loop in the main process.
    """
    if not _BOT_TOKEN:
        logger.warning("[ANNOTATION] DISCORD_BOT_TOKEN not set — listener disabled")
        return
    if not _CHANNEL_ID:
        logger.warning("[ANNOTATION] DISCORD_ANNOTATION_CHANNEL_ID not set — listener disabled")
        return

    intents                  = discord.Intents.default()
    intents.message_content  = True
    client                   = _AnnotationClient(intents=intents)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.start(_BOT_TOKEN))
    except Exception as exc:
        logger.error(f"[ANNOTATION] Bot loop exited: {exc}", exc_info=True)
    finally:
        loop.close()
