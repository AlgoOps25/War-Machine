"""
Annotation Bot
==============
Minimal discord.py Gateway client that listens to the #chart-annotations
channel and routes valid R:R messages into the War Machine signal pipeline
via annotation_resolver.resolve_annotation().

DESIGN
------
- Runs on a daemon thread inside the existing War Machine process.
- No separate bot process, no listener class boilerplate.
- Reads two env vars (set in Railway / .env):
    DISCORD_BOT_TOKEN       — bot token (required)
    ANNOTATION_CHANNEL_ID   — numeric channel ID (required)
- Gracefully no-ops if either env var is missing or discord.py is not
  installed (so existing deployments without the package are unaffected).

BOOT
----
Called once from app/core/__main__.py:
    from app.notifications.annotation_bot import start_annotation_bot
    start_annotation_bot()   # non-blocking — starts daemon thread

MESSAGE FORMAT ACCEPTED
-----------------------
    "3.31"          -> auto-detect direction from BOS
    "4.1"           -> same
    "LONG 3.31"     -> bull hint
    "SHORT 4.1"     -> bear hint
    "bull 2.5"      -> bull hint
    "bear 3.0"      -> bear hint

FUTURES SYMBOL
--------------
Defaults to the value of ANNOTATION_FUTURES_SYMBOL env var, falling back
to "NQM25". Update the env var when rolling to the next contract.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

_FUTURES_SYMBOL = os.environ.get("ANNOTATION_FUTURES_SYMBOL", "NQM25")


def start_annotation_bot() -> bool:
    """
    Start the annotation Discord bot on a daemon thread.

    Returns True if the bot thread was launched, False if skipped
    (missing env vars or missing discord.py package).
    """
    token      = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("ANNOTATION_CHANNEL_ID", "").strip()

    if not token:
        logger.info("[ANNOTATION BOT] DISCORD_BOT_TOKEN not set — annotation bot disabled")
        return False
    if not channel_id:
        logger.info("[ANNOTATION BOT] ANNOTATION_CHANNEL_ID not set — annotation bot disabled")
        return False

    try:
        channel_id_int = int(channel_id)
    except ValueError:
        logger.warning("[ANNOTATION BOT] ANNOTATION_CHANNEL_ID is not a valid integer — skipping")
        return False

    try:
        import discord  # type: ignore
    except ImportError:
        logger.warning(
            "[ANNOTATION BOT] discord.py not installed — run `pip install discord.py`. "
            "Annotation bot disabled."
        )
        return False

    # Import resolver here (not at module level) so annotation_bot can be
    # imported safely even when War Machine's DB pool isn't ready yet.
    from app.signals.annotation_resolver import parse_annotation, resolve_annotation

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info(
            "[ANNOTATION BOT] ✅ Logged in as %s — watching channel ID %s for annotations",
            client.user,
            channel_id_int,
        )

    @client.event
    async def on_message(message: discord.Message):
        # Ignore other channels and bots
        if message.channel.id != channel_id_int:
            return
        if message.author.bot:
            return

        result = parse_annotation(message.content)
        if result is None:
            return  # not an annotation message

        rr_ratio, direction_hint = result
        posted_at: datetime = message.created_at  # UTC-aware from discord.py

        logger.info(
            "[ANNOTATION BOT] Received annotation R:R=%.2f dir=%s from %s",
            rr_ratio,
            direction_hint or "auto",
            message.author,
        )

        # resolve_annotation is synchronous — run off the event loop
        # so it never blocks Discord's async heartbeat.
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            resolve_annotation,
            rr_ratio,
            direction_hint,
            _FUTURES_SYMBOL,
            posted_at,
        )

    def _run_bot():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.start(token))
        except Exception as exc:
            logger.error("[ANNOTATION BOT] Bot exited with error: %s", exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run_bot, daemon=True, name="annotation_bot")
    t.start()
    logger.info("[ANNOTATION BOT] Daemon thread started (symbol=%s)", _FUTURES_SYMBOL)
    return True
