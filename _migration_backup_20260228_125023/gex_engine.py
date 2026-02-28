"""
Gamma Exposure (GEX) Engine

Computes Gamma Exposure by strike from EODHD options chain data.

Formula:
  GEX_strike = (Call_OI × Call_Gamma - Put_OI × Put_Gamma) × 100 × Stock_Price

  Positive GEX at a strike:
    Market makers are net LONG gamma at that level.
    They hedge by BUYING dips and SELLING rallies near that strike.
    Effect: price is ATTRACTED / PINNED to this strike (especially near expiration).

  Negative GEX at a strike:
    Market makers are net SHORT gamma at that level.
    They hedge by SELLING dips and BUYING rallies (pro-cyclical).
    Effect: moves are AMPLIFIED / TRENDING through this strike.

Key levels computed:
  gamma_pin   : Strike with the highest positive GEX value
                → Price gravitates here near expiration (ideal T1 target)
  gamma_flip  : Strike where cumulative GEX profile crosses zero (pos → neg)
                → Below flip = trending/momentum environment
                → Above flip = pinning/mean-reverting environment
  neg_gex_zone: True if current price < gamma_flip

Signal multiplier logic:
  Negative GEX zone               : ×1.08  (MMs amplify moves — trending day)
  Positive GEX + pin aligns T1    : ×1.05  (price magnetized to target)
  Positive GEX + pin is headwind  : ×0.92  (price pulled AWAY from target)
  Positive GEX + neutral          : ×0.97  (suppressed vol / pinning environment)
  No gamma data in chain          : ×1.00  (neutral, no penalty)
"""
from typing import Dict, List, Optional, Tuple

CONTRACT_SIZE = 100   # standard US equity options contract multiplier


# ─────────────────────────────────────────────────────────────
def compute_gex_levels(chain_data: dict, current_price: float) -> dict:
    """
    Compute Gamma Exposure at every strike in the options chain.

    Parameters:
      chain_data    : raw EODHD chain dict (chain_data["data"][expiry][calls/puts][strike])
      current_price : current stock price (used for GEX formula and zone detection)

    Returns a dict with keys:
      has_data      : bool  — False if no options had a valid gamma field
      gex_by_strike : {float_strike: float_gex}  — net GEX per strike (all expirations summed)
      total_gex     : float — sum of all per-strike GEX values
      gamma_pin     : float|None — strike with highest positive GEX (magnetic target)
      gamma_flip    : float|None — zero-crossing strike in sorted cumulative GEX profile
      neg_gex_zone  : bool  — True if current_price is below gamma_flip
      top_positive  : list of (strike, gex) tuples, sorted desc, up to 5
      top_negative  : list of (strike, gex) tuples, sorted asc (most negative first), up to 5
    """
    gex_by_strike: Dict[float, float] = {}
    gamma_field_found = False

    for expiration_date, options_data in chain_data.get("data", {}).items():

        # ── Calls ───────────────────────────────────────────────────────────
        for strike_str, option in options_data.get("calls", {}).items():
            gamma = option.get("gamma")
            oi    = option.get("openInterest", 0) or 0
            if gamma is None or gamma == 0 or oi == 0:
                continue
            gamma_field_found = True
            strike = float(strike_str)
            contribution = float(gamma) * oi * CONTRACT_SIZE * current_price
            gex_by_strike[strike] = gex_by_strike.get(strike, 0.0) + contribution

        # ── Puts ───────────────────────────────────────────────────────────
        for strike_str, option in options_data.get("puts", {}).items():
            gamma = option.get("gamma")
            oi    = option.get("openInterest", 0) or 0
            if gamma is None or gamma == 0 or oi == 0:
                continue
            gamma_field_found = True
            strike = float(strike_str)
            # Puts subtract from GEX (dealer is long put = short gamma exposure to market)
            contribution = float(gamma) * oi * CONTRACT_SIZE * current_price
            gex_by_strike[strike] = gex_by_strike.get(strike, 0.0) - contribution

    if not gamma_field_found or not gex_by_strike:
        return {
            "has_data": False, "gex_by_strike": {}, "total_gex": 0.0,
            "gamma_pin": None, "gamma_flip": None, "neg_gex_zone": False,
            "top_positive": [], "top_negative": []
        }

    # ── Gamma pin ─────────────────────────────────────────────────────────
    positive_strikes = {s: g for s, g in gex_by_strike.items() if g > 0}
    gamma_pin = max(positive_strikes, key=positive_strikes.get) if positive_strikes else None

    # ── Gamma flip (zero-crossing in cumulative GEX sorted by strike) ────────────
    sorted_strikes = sorted(gex_by_strike.keys())
    cumulative     = 0.0
    gamma_flip     = None
    prev_strike    = None
    prev_cum       = 0.0

    for strike in sorted_strikes:
        cumulative += gex_by_strike[strike]
        if prev_strike is not None and prev_cum * cumulative < 0:
            # Linear interpolation of zero-crossing between prev_strike and strike
            gamma_flip = prev_strike + (strike - prev_strike) * (
                abs(prev_cum) / (abs(prev_cum) + abs(cumulative))
            )
            gamma_flip = round(gamma_flip, 2)
            break
        prev_strike = strike
        prev_cum    = cumulative

    # If no zero-crossing found, use the strike closest to zero GEX
    if gamma_flip is None:
        gamma_flip = min(gex_by_strike.keys(),
                         key=lambda s: abs(gex_by_strike[s]))

    neg_gex_zone = (gamma_flip is not None) and (current_price < gamma_flip)
    total_gex    = sum(gex_by_strike.values())

    # ── Top levels ───────────────────────────────────────────────────────────
    sorted_by_gex = sorted(gex_by_strike.items(), key=lambda x: x[1], reverse=True)
    top_positive  = [(s, round(g, 0)) for s, g in sorted_by_gex if g > 0][:5]
    top_negative  = [(s, round(g, 0)) for s, g in sorted_by_gex if g < 0][-5:][::-1]

    return {
        "has_data":      True,
        "gex_by_strike": gex_by_strike,
        "total_gex":     round(total_gex, 0),
        "gamma_pin":     gamma_pin,
        "gamma_flip":    gamma_flip,
        "neg_gex_zone":  neg_gex_zone,
        "top_positive":  top_positive,
        "top_negative":  top_negative
    }


# ─────────────────────────────────────────────────────────────
def get_gex_signal_context(gex_data: dict, direction: str,
                           entry_price: float,
                           stop_price: float,
                           target_price: float) -> Tuple[float, str, dict]:
    """
    Translate GEX levels into a confidence multiplier for the current signal.

    Parameters:
      gex_data     : output of compute_gex_levels()
      direction    : "bull" or "bear"
      entry_price  : confirmed entry
      stop_price   : stop loss level
      target_price : T1 target

    Returns:
      (multiplier: float, label: str, context: dict)
    """
    if not gex_data.get("has_data"):
        return 1.0, "GEX-NO-DATA", {}

    gamma_pin    = gex_data["gamma_pin"]
    gamma_flip   = gex_data["gamma_flip"]
    neg_gex_zone = gex_data["neg_gex_zone"]

    multiplier = 1.0
    tags       = []

    # ── Rule 1: Neg vs Pos GEX environment ───────────────────────────────
    # Negative GEX = MM short gamma = they amplify moves (trending day)
    # Positive GEX = MM long gamma  = they suppress moves (pinning day)
    if neg_gex_zone:
        multiplier *= 1.08
        flip_str = f"${gamma_flip:.2f}" if gamma_flip else "?"
        tags.append(f"NEG-GEX(flip@{flip_str})")
    else:
        multiplier *= 0.97
        tags.append("POS-GEX-ENV")

    # ── Rule 2: Gamma pin alignment with target ──────────────────────────
    if gamma_pin is not None:
        pin_str = f"${gamma_pin:.2f}"
        if direction == "bull":
            if entry_price < gamma_pin <= target_price * 1.02:
                # Pin is at or just past T1 — price magnetized to target
                multiplier *= 1.05
                tags.append(f"PIN-TARGET({pin_str})")
            elif stop_price < gamma_pin < entry_price:
                # Pin is between stop and entry — downward magnetic pull
                multiplier *= 0.92
                tags.append(f"PIN-HEADWIND({pin_str})")
            else:
                tags.append(f"PIN-NEUTRAL({pin_str})")
        else:  # bear
            if entry_price > gamma_pin >= target_price * 0.98:
                # Pin is at or just below T1 — price magnetized downward to target
                multiplier *= 1.05
                tags.append(f"PIN-TARGET({pin_str})")
            elif stop_price > gamma_pin > entry_price:
                # Pin is between entry and stop — upward magnetic pull
                multiplier *= 0.92
                tags.append(f"PIN-HEADWIND({pin_str})")
            else:
                tags.append(f"PIN-NEUTRAL({pin_str})")

    multiplier = round(max(0.70, min(1.30, multiplier)), 3)
    label      = "GEX[" + "+".join(tags) + "]"

    return multiplier, label, {
        "gamma_pin":    gamma_pin,
        "gamma_flip":   gamma_flip,
        "neg_gex_zone": neg_gex_zone
    }
