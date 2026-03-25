# app/filters/gex_pin_gate.py
# Sprint 1 — 47.P1-3: GEX gamma-flip pin-zone gate
#
# PURPOSE:
#   Suppress signals when the entry price is within ±GEX_PIN_ZONE_PCT of
#   the gamma_flip level.  At this zone market makers flip from long-gamma
#   to short-gamma hedging.  Price becomes choppy and mean-reverting —
#   exactly the worst environment for directional options entries.
#
# USAGE (sniper.py — call in _run_signal_pipeline after entry_price is set,
#        options_rec is available from Step 6.5 pre-gate):
#   from app.filters.gex_pin_gate import is_in_gex_pin_zone
#   blocked, reason = is_in_gex_pin_zone(entry_price, options_rec)
#   if blocked:
#       logger.info(f"[{ticker}] 🚫 GEX PIN GATE: {reason}")
#       return False
#
# RULES:
#   - gamma_flip must be present in options_rec["gex_data"]
#   - |entry_price - gamma_flip| / gamma_flip < GEX_PIN_ZONE_PCT → blocked
#   - GEX_PIN_ZONE_PCT = 0.003 (0.3%) configurable
#   - Missing gex_data or gamma_flip → (False, "no GEX data") → pass-through

import logging
logger = logging.getLogger(__name__)

GEX_PIN_ZONE_PCT = 0.003   # 0.3% band around gamma_flip


def is_in_gex_pin_zone(entry_price: float, options_rec: dict) -> tuple:
    """
    Returns (blocked: bool, reason: str).

    Parameters:
        entry_price : confirmed entry price from sniper pipeline
        options_rec : dict from options pre-gate (Step 6.5), expected to
                      contain key "gex_data" with output of compute_gex_levels()
    """
    try:
        if not options_rec:
            return False, "no options_rec"

        gex_data = options_rec.get("gex_data")
        if not gex_data or not gex_data.get("has_data"):
            return False, "no GEX data"

        gamma_flip = gex_data.get("gamma_flip")
        if gamma_flip is None or gamma_flip == 0:
            return False, "no gamma_flip level"

        distance_pct = abs(entry_price - gamma_flip) / gamma_flip

        if distance_pct < GEX_PIN_ZONE_PCT:
            return True, (
                f"entry ${entry_price:.2f} within {distance_pct:.2%} of "
                f"gamma_flip ${gamma_flip:.2f} (threshold {GEX_PIN_ZONE_PCT:.1%})"
            )

        return False, (
            f"entry ${entry_price:.2f} is {distance_pct:.2%} from "
            f"gamma_flip ${gamma_flip:.2f} — clear of pin zone"
        )

    except Exception as e:
        logger.info(f"[GEX_PIN_GATE] check error (non-fatal): {e}")
        return False, f"gex_pin_gate error: {e}"
