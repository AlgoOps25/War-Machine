"""
app/core/logging_config.py
==========================
Centralized logging configuration for War Machine.

Call setup_logging() ONCE at process startup (in __main__.py) before
any other module is imported. All loggers across app/ and utils/ then
inherit this configuration automatically via the root logger.

Design decisions:
  - Single call, no repeated basicConfig() scattered across modules.
  - LOG_LEVEL env var lets Railway/local override level without a code change.
    Default: INFO in production, DEBUG if LOG_LEVEL=DEBUG is set.
  - Structured format includes timestamp, level, and module name so Railway
    logs are grep-friendly: grep '\[SCANNER\]' or filter by level instantly.
  - Third-party noisy loggers (websocket, urllib3, httpx) are quieted to
    WARNING so they don't drown out trading signals.
  - Idempotent: safe to call multiple times (only configures once).
"""

import logging
import os
import sys

_CONFIGURED = False

# Third-party loggers to quiet down to WARNING
_QUIET_LOGGERS = [
    "websocket",
    "urllib3",
    "urllib3.connectionpool",
    "httpx",
    "httpcore",
    "requests",
    "charset_normalizer",
    "asyncio",
    "psycopg2",
]


def setup_logging() -> None:
    """
    Configure the root logger once for the entire War Machine process.

    Environment variables:
        LOG_LEVEL   : Override log level (DEBUG / INFO / WARNING / ERROR).
                      Defaults to INFO.
        LOG_FORMAT  : Override format string. Defaults to structured format below.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    # ── Level ────────────────────────────────────────────────────────────────
    raw_level = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    level     = getattr(logging, raw_level, logging.INFO)

    # ── Format ───────────────────────────────────────────────────────────────
    # Default: 15:04:22 [INFO ] app.core.scanner: [SCANNER] Cycle #42 | ...
    fmt = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    )
    datefmt = "%H:%M:%S"

    # ── Handler ──────────────────────────────────────────────────────────────
    # Single StreamHandler → stdout (Railway captures stdout for log viewer)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    # ── Root logger ──────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers that basicConfig or imports may have added already
    root.handlers.clear()
    root.addHandler(handler)

    # ── Quiet noisy third-party loggers ──────────────────────────────────────
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True

    # Emit startup confirmation via the root logger itself
    logging.getLogger(__name__).info(
        f"[LOGGING] Configured — level={raw_level}  "
        f"format='{fmt}'  handler=stdout"
    )
