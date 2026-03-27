"""
Entry point for running War Machine as a module:
    python -m app.core

This is the ONLY place setup_logging() is called so that log level
and format are configured once before any other module is imported.

BOOT ORDER (critical for Railway health-check):
  1. setup_logging()        — configure log level/format
  2. start_health_server()  — bind :PORT so Railway probe gets 200
  3. import scanner         — triggers module-level DB pool initialization
  4. start_scanner_loop()   — enter the main loop

Previously health server was started inside start_scanner_loop() which
meant the port was dark during the DB initialization block, causing Railway to
mark the deployment as failed before the scanner even started.
"""

# ── 1. Logging must be configured FIRST, before any War Machine import ────────
from app.core.logging_config import setup_logging
setup_logging()

# ── 2. Health server UP before the DB pool initializes on scanner import ─────
#    (scanner.py triggers module-level DB pool initialization on import)
from app.core.health_server import start_health_server
start_health_server()

# ── 3. Now safe to import scanner (triggers module-level DB pool init) ────────
from app.core.scanner import start_scanner_loop

if __name__ == "__main__":
    start_scanner_loop()
