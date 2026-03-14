"""
sniper_stubs.py  —  fallback stubs used by scanner.py when sniper.py fails to import.

scanner.py error-path:
    except ImportError:
        from app.core.sniper_stubs import process_ticker, clear_armed_signals,
                                          clear_watching_signals

All functions here are no-ops that log a warning so the scanner loop can
continue running (health endpoint stays alive) even if sniper is broken.
"""
import logging
log = logging.getLogger(__name__)

_ORB_CLASSIFICATIONS: dict = {}


def process_ticker(ticker: str, *args, **kwargs) -> None:
    log.warning("[STUB] process_ticker called for %s — sniper.py is unavailable", ticker)


def clear_armed_signals(*args, **kwargs) -> None:
    log.warning("[STUB] clear_armed_signals called — sniper.py is unavailable")


def clear_watching_signals(*args, **kwargs) -> None:
    log.warning("[STUB] clear_watching_signals called — sniper.py is unavailable")


# Some scanner versions also import _orb_classifications
_orb_classifications = _ORB_CLASSIFICATIONS
