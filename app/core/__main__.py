"""
Entry point for running War Machine as a module:
    python -m app.core

This is the ONLY place setup_logging() is called so that log level
and format are configured once before any other module is imported.
"""

# ── Logging must be configured FIRST, before any War Machine import ──────────
from app.core.logging_config import setup_logging
setup_logging()

# ── Now safe to import the rest of the system ────────────────────────────────
from app.core.scanner import start_scanner_loop

if __name__ == "__main__":
    start_scanner_loop()
