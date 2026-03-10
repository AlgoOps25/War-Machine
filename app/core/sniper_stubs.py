"""
app/core/sniper_stubs.py
========================
FALLBACK ONLY — used if sniper.py fails to import at startup.

Phase 1.16: scanner.py now imports process_ticker directly from
sniper.py. These stubs are only reached if that import fails
(e.g. during a broken deploy). They keep the container alive
so Railway doesn't crash-loop.

Do NOT add signal logic here. Fix sniper.py instead.
"""
import logging
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

_armed_signals: Dict = {}
_watching_fvgs: Dict = {}


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
