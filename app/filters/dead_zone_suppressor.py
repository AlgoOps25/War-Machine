# app/filters/dead_zone_suppressor.py
# Sprint 1 — 47.P1-2: Dead-zone suppressor
#
# PURPOSE:
#   Suppresses signals when the market is in a "dead zone":
#   VIX > VIX_DEAD_ZONE_THRESHOLD (default 30) AND the SPY EMA regime
#   is directionally OPPOSED to the signal direction.
#
#   In this environment market makers are short gamma, hedging flows are
#   chaotic, and directional signals have historically low win rates.
#
# USAGE (sniper.py — call inside _run_signal_pipeline after regime is loaded):
#   from app.filters.dead_zone_suppressor import is_dead_zone
#   blocked, reason = is_dead_zone(direction, spy_regime)
#   if blocked:
#       logger.info(f"[{ticker}] 🚫 DEAD ZONE: {reason}")
#       return False
#
# RULES:
#   bull signal → blocked if regime in (BEAR, STRONG_BEAR, NEUTRAL_BEAR) + VIX > 30
#   bear signal → blocked if regime in (BULL, STRONG_BULL, NEUTRAL_BULL) + VIX > 30
#   Explosive movers (score >= EXPLOSIVE_SCORE_THRESHOLD) are NOT exempt —
#   high VIX opposing tape is dangerous regardless of RVOL.

import logging
logger = logging.getLogger(__name__)

VIX_DEAD_ZONE_THRESHOLD = 30.0   # VIX level above which opposing signals are blocked

_BEAR_LABELS = {"BEAR", "STRONG_BEAR", "NEUTRAL_BEAR"}
_BULL_LABELS = {"BULL", "STRONG_BULL", "NEUTRAL_BULL"}


def is_dead_zone(direction: str, spy_regime: dict) -> tuple:
    """
    Returns (blocked: bool, reason: str).

    Parameters:
        direction  : "bull" or "bear"
        spy_regime : dict from get_market_regime() — must have 'label' and
                     optionally 'spy' sub-dict containing VIX fallback.
                     VIX is read from validation.get_regime_filter().get_regime_state().vix
    """
    try:
        if not spy_regime:
            return False, "no regime data"

        # Read VIX from the live regime filter (already in memory, no new call)
        try:
            from app.validation.validation import get_regime_filter
            vix = get_regime_filter().get_regime_state().vix
        except Exception:
            vix = 0.0

        if vix < VIX_DEAD_ZONE_THRESHOLD:
            return False, f"VIX={vix:.1f} below dead-zone threshold {VIX_DEAD_ZONE_THRESHOLD}"

        label = spy_regime.get("label", "UNKNOWN")

        if direction == "bull" and label in _BEAR_LABELS:
            return True, f"DEAD ZONE: bull signal vs {label} regime (VIX={vix:.1f})"

        if direction == "bear" and label in _BULL_LABELS:
            return True, f"DEAD ZONE: bear signal vs {label} regime (VIX={vix:.1f})"

        return False, f"not dead zone (VIX={vix:.1f}, regime={label}, dir={direction})"

    except Exception as e:
        logger.info(f"[DEAD_ZONE] check error (non-fatal): {e}")
        return False, f"dead_zone check error: {e}"
