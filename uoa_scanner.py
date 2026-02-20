"""
Unusual Options Activity (UOA) Scanner

Detects smart money positioning by analyzing volume-to-open-interest ratios
across the full options chain for a given ticker.

Core formula:
  UOA Score = volume / max(open_interest, 1)

Interpretation:
  UOA ≥ 0.50 : Elevated activity — more volume than normal relative to OI
  UOA ≥ 1.00 : Volume EXCEEDS existing OI — new positions being aggressively opened
  UOA ≥ 2.00 : Volume is 2× OI — institutional block or sweep-level activity

Directional alignment:
  Calls with high UOA on a BULL signal  → smart money agrees  → confidence boost
  Puts  with high UOA on a BULL signal  → smart money opposes → confidence decay
  (logic inverts for BEAR signals)

Multiplier table:
  Extreme aligned  (UOA ≥ 2.0) : ×1.20
  Strong  aligned  (UOA ≥ 1.0) : ×1.15
  Aligned          (UOA ≥ 0.5) : ×1.10
  Mixed — aligned stronger    : ×1.05
  Mixed — opposing stronger   : ×0.92
  Opposing only               : ×0.85
  No UOA detected             : ×1.00  (neutral)

Minimum liquidity filter:
  OI  ≥ MIN_OI_FILTER  (100)  — avoids noise from illiquid strikes
  Vol ≥ MIN_VOL_FILTER (10)   — avoids single-trade anomalies
"""
from typing import Dict, List, Optional

# ── Thresholds ────────────────────────────────────────────────────────────
UOA_THRESHOLD         = 0.5   # minimum vol/OI to flag as unusual
UOA_STRONG_THRESHOLD  = 1.0   # volume exceeds OI
UOA_EXTREME_THRESHOLD = 2.0   # volume is 2× OI
MIN_OI_FILTER         = 100   # ignore strikes with fewer OI contracts
MIN_VOL_FILTER        = 10    # ignore strikes with fewer volume contracts


def scan_chain_for_uoa(chain_data: dict, direction: str,
                       current_price: float) -> dict:
    """
    Scan a full EODHD options chain dict for unusual activity.

    Parameters:
      chain_data    : raw chain from OptionsFilter.get_options_chain()
      direction     : "bull" or "bear" (from BOS/ORB detection)
      current_price : current stock price (used for logging context only)

    Returns a dict with keys:
      uoa_detected  : bool   — any UOA found anywhere in chain
      aligned       : bool   — UOA in direction matching signal
      opposing      : bool   — UOA in direction opposing signal
      max_uoa_score : float  — highest aligned vol/OI score found
      top_aligned   : list   — up to 3 best aligned UOA strikes
      top_opposing  : list   — up to 3 best opposing UOA strikes
      multiplier    : float  — confidence multiplier to apply
      label         : str    — human-readable UOA status tag
    """
    aligned_hits  = []
    opposing_hits = []

    for expiration_date, options_data in chain_data.get("data", {}).items():

        # ── Calls ───────────────────────────────────────────────────────────
        for strike_str, option in options_data.get("calls", {}).items():
            volume = option.get("volume", 0) or 0
            oi     = option.get("openInterest", 0) or 0
            if oi < MIN_OI_FILTER or volume < MIN_VOL_FILTER:
                continue
            uoa_score = volume / oi
            if uoa_score < UOA_THRESHOLD:
                continue
            entry = {
                "strike":    float(strike_str),
                "expiry":    expiration_date,
                "type":      "call",
                "uoa_score": round(uoa_score, 2),
                "volume":    int(volume),
                "oi":        int(oi)
            }
            if direction == "bull":
                aligned_hits.append(entry)
            else:
                opposing_hits.append(entry)

        # ── Puts ────────────────────────────────────────────────────────────
        for strike_str, option in options_data.get("puts", {}).items():
            volume = option.get("volume", 0) or 0
            oi     = option.get("openInterest", 0) or 0
            if oi < MIN_OI_FILTER or volume < MIN_VOL_FILTER:
                continue
            uoa_score = volume / oi
            if uoa_score < UOA_THRESHOLD:
                continue
            entry = {
                "strike":    float(strike_str),
                "expiry":    expiration_date,
                "type":      "put",
                "uoa_score": round(uoa_score, 2),
                "volume":    int(volume),
                "oi":        int(oi)
            }
            if direction == "bear":
                aligned_hits.append(entry)
            else:
                opposing_hits.append(entry)

    # Sort by UOA score descending
    aligned_hits.sort(key=lambda x: x["uoa_score"],  reverse=True)
    opposing_hits.sort(key=lambda x: x["uoa_score"], reverse=True)

    max_aligned  = aligned_hits[0]["uoa_score"]  if aligned_hits  else 0.0
    max_opposing = opposing_hits[0]["uoa_score"] if opposing_hits else 0.0
    uoa_detected = bool(aligned_hits or opposing_hits)

    # ── Compute multiplier ───────────────────────────────────────────────
    if aligned_hits and not opposing_hits:
        if max_aligned >= UOA_EXTREME_THRESHOLD:
            multiplier = 1.20
            label      = f"UOA-EXTREME-ALIGNED({max_aligned:.1f}x)"
        elif max_aligned >= UOA_STRONG_THRESHOLD:
            multiplier = 1.15
            label      = f"UOA-STRONG-ALIGNED({max_aligned:.1f}x)"
        else:
            multiplier = 1.10
            label      = f"UOA-ALIGNED({max_aligned:.1f}x)"

    elif opposing_hits and not aligned_hits:
        multiplier = 0.85
        label      = f"UOA-OPPOSING({max_opposing:.1f}x)"

    elif aligned_hits and opposing_hits:
        if max_aligned >= max_opposing:
            multiplier = 1.05
            label      = (f"UOA-MIXED-BULL({max_aligned:.1f}x "
                          f"vs {max_opposing:.1f}x)")
        else:
            multiplier = 0.92
            label      = (f"UOA-MIXED-BEAR({max_aligned:.1f}x "
                          f"vs {max_opposing:.1f}x)")
    else:
        multiplier = 1.00
        label      = "UOA-NONE"

    return {
        "uoa_detected":  uoa_detected,
        "aligned":       bool(aligned_hits),
        "opposing":      bool(opposing_hits),
        "max_uoa_score": max_aligned,
        "top_aligned":   aligned_hits[:3],
        "top_opposing":  opposing_hits[:3],
        "multiplier":    multiplier,
        "label":         label
    }
