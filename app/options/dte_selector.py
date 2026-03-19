"""
Dynamic DTE Selector — Sprint 2, Task P2-3

Provides get_ideal_dte(vix, current_time) which returns the ideal DTE
(0 or 1) to pass as `ideal_dte` into OptionsFilter.validate_signal_for_options().

Logic (in priority order):
  1. After 2:00 PM ET            → prefer 1-DTE
     0DTE theta decays hard after 2PM; the move needs to happen NOW.
  2. VIX > 25                    → prefer 1-DTE
     Volatile tape = wider spreads on 0DTE; an extra day absorbs the noise.
  3. VIX > 20 AND time < 10:30   → prefer 1-DTE
     Elevated VIX at open — wait for tape to confirm direction.
  4. Otherwise                   → prefer 0-DTE
     Normal tape during core session: tight spreads, max gamma leverage.

Integration:
    from app.options.dte_selector import get_ideal_dte

    ideal = get_ideal_dte(vix=regime_state.vix)
    is_valid, data, reason = options_filter.validate_signal_for_options(
        ticker, direction, entry_price, target_price,
        ideal_dte=ideal
    )

Log output example:
    [DTE-SELECTOR] AAPL: VIX=27.4 @ 10:15 ET → 1-DTE (elevated VIX + early session)
    [DTE-SELECTOR] NVDA: VIX=18.2 @ 11:30 ET → 0-DTE (normal tape, core session)
    [DTE-SELECTOR] TSLA: VIX=22.1 @ 14:05 ET → 1-DTE (post-2PM theta risk)
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Thresholds — mirror config values but kept local so this module has no
# circular dependency on config (config imports nothing from app/).
_VIX_HIGH      = 25.0   # above this → always 1-DTE
_VIX_ELEVATED  = 20.0   # above this + early session → 1-DTE
_CUTOFF_HOUR   = 14     # 2:00 PM ET — post-2PM always prefers 1-DTE
_CUTOFF_MINUTE = 0
_EARLY_HOUR    = 10
_EARLY_MINUTE  = 30     # "early session" = before 10:30 AM ET


def get_ideal_dte(
    vix: float,
    current_time: Optional[datetime] = None,
    ticker: str = "",
) -> int:
    """
    Return the ideal DTE (0 or 1) for the current market conditions.

    Args:
        vix:          Current VIX level (from RegimeState.vix).
        current_time: Aware or naive datetime in ET. Defaults to now(ET).
        ticker:       Optional ticker string for log context.

    Returns:
        0 or 1 — the recommended ideal DTE to pass to find_best_strike().
    """
    if current_time is None:
        current_time = datetime.now(ET)

    # Normalise to ET-naive for simple time comparisons
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(ET).replace(tzinfo=None)

    t = current_time.time()
    tag = f"[{ticker}] " if ticker else ""

    # Rule 1: post-2PM — 0DTE theta is punishing, prefer next-day contract
    cutoff = datetime.now().replace(
        hour=_CUTOFF_HOUR, minute=_CUTOFF_MINUTE, second=0, microsecond=0
    ).time()
    if t >= cutoff:
        logger.info(
            f"[DTE-SELECTOR] {tag}VIX={vix:.1f} @ {t.strftime('%H:%M')} ET "
            f"→ 1-DTE (post-2PM theta risk)"
        )
        return 1

    # Rule 2: high VIX — always prefer 1-DTE regardless of time
    if vix > _VIX_HIGH:
        logger.info(
            f"[DTE-SELECTOR] {tag}VIX={vix:.1f} @ {t.strftime('%H:%M')} ET "
            f"→ 1-DTE (elevated VIX > {_VIX_HIGH:.0f})"
        )
        return 1

    # Rule 3: moderately elevated VIX + early session
    early_cutoff = datetime.now().replace(
        hour=_EARLY_HOUR, minute=_EARLY_MINUTE, second=0, microsecond=0
    ).time()
    if vix > _VIX_ELEVATED and t < early_cutoff:
        logger.info(
            f"[DTE-SELECTOR] {tag}VIX={vix:.1f} @ {t.strftime('%H:%M')} ET "
            f"→ 1-DTE (elevated VIX + early session)"
        )
        return 1

    # Default: normal tape, core session — 0-DTE maximises gamma leverage
    logger.info(
        f"[DTE-SELECTOR] {tag}VIX={vix:.1f} @ {t.strftime('%H:%M')} ET "
        f"→ 0-DTE (normal tape, core session)"
    )
    return 0
