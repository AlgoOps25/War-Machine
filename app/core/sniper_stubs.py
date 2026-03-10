"""
app/core/sniper_stubs.py
========================
FALLBACK ONLY — used if sniper.py fails to import at startup.

Phase 1.16: scanner.py now imports process_ticker directly from
sniper.py. These stubs are only reached if that import fails
(e.g. during a broken deploy). They keep the container alive
so Railway doesn't crash-loop.

Do NOT add signal logic here. Fix sniper.py instead.

FIXED M3 (Mar 10 2026): Module-level CRITICAL log + one-shot Discord alert
fired on import so the broken-import condition is immediately visible at
startup, not silently deferred until the first ticker scan.
"""
import logging
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

_armed_signals: Dict = {}
_watching_fvgs: Dict = {}

# ── M3 FIX: Startup-level warning ────────────────────────────────────────────
# Fires exactly once when this module is imported (i.e. when sniper.py failed).
logger.critical(
    "[STUBS] ⚠️  sniper_stubs.py loaded — sniper.py import FAILED. "
    "All process_ticker calls will be no-ops. Check Railway logs for the "
    "ImportError that caused the fallback."
)

try:
    from app.discord_helpers import send_simple_message as _dsend
    _dsend(
        "🚨 **WAR MACHINE STARTUP WARNING**\n"
        "sniper.py failed to import — falling back to stubs.\n"
        "No signals will fire until the import error is resolved.\n"
        "Check Railway deployment logs immediately."
    )
except Exception as _discord_err:
    logger.warning(f"[STUBS] Discord startup alert failed (non-fatal): {_discord_err}")
# ─────────────────────────────────────────────────────────────────────────────


def process_ticker(ticker: str) -> Optional[Dict]:
    """
    Fallback stub — logs a warning and returns None.
    Real logic lives in app/core/sniper.py.
    """
    logger.warning(
        f"[STUB] process_ticker called for {ticker} — "
        "sniper.py failed to import. No signal generated."
    )
    return None


def clear_armed_signals():
    count = len(_armed_signals)
    _armed_signals.clear()
    logger.info(f"[STUB] Cleared {count} armed signals")


def clear_watching_signals():
    count = len(_watching_fvgs)
    _watching_fvgs.clear()
    logger.info(f"[STUB] Cleared {count} watching FVGs")


def get_armed_signals() -> Dict:
    return _armed_signals.copy()


def get_watching_signals() -> Dict:
    return _watching_fvgs.copy()
