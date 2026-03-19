"""
app/validation/volume_profile.py  —  Entry-gate Volume Profile Validator

Purpose
-------
Per-signal entry validation called by sniper.py Step 6.6 via validate_entry().
Builds a fixed 20¢-bin volume profile, then checks whether the entry price
is near an HVN (high resistance) or LVN (low resistance zone).

Merge history
-------------
Phase 3 (Mar 19, 2026) — absorbs app/indicators/volume_profile.py:
  - Was: coarse 20-bin profile with numpy-based bin math.
  - Now: fixed 20¢-bin resolution (CME standard) — no bin-count config needed.
  - Value area expansion is now correct CME-style: at each step the two-bar
    group above OR below the current VA boundary is compared, and the pair
    with higher combined volume is absorbed.  The old code compared single
    bars, which broke the algorithm for wide sessions.
  - 5-minute TTL module-level cache (was per-class dict; reuse now works
    across different VolumeProfileAnalyzer instances).
  - numpy dependency removed — pure Python; no import overhead.
  - Two new output keys on validate_entry() vp_data:
      confidence_boost (float): signed confidence delta for SignalValidator
      options_bias     (str):   'CALL' | 'PUT' | 'NEUTRAL'
  - app/indicators/volume_profile.py has been deleted (dead code, unwired).
  - No breaking changes to sniper.py callers: validate_entry() signature
    and return shape are unchanged; new keys are additive.

API contract
------------
  validate_entry(ticker, direction, entry_price, bars)
      -> (is_valid: bool, reason: str, vp_data: dict | None)

  vp_data keys:
      poc                  float  - Point of Control
      vah                  float  - Value Area High
      val                  float  - Value Area Low
      distance_from_poc_pct float - abs distance entry / poc
      volume_rank          str    - % of max volume at entry bin
      confidence_boost     float  - e.g. +0.05 near POC/LVN, -0.05 near HVN
      options_bias         str    - 'CALL' | 'PUT' | 'NEUTRAL'
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_BIN_SIZE       = 0.20          # 20¢ fixed bins (CME standard)
_VALUE_AREA_PCT = 0.70          # Standard 70% value area
_CACHE_TTL      = timedelta(minutes=5)

# ---------------------------------------------------------------------------
# Module-level TTL cache  (shared across all VolumeProfileAnalyzer instances)
# ---------------------------------------------------------------------------
# key  -> (result_tuple, expiry_datetime)
_entry_cache: Dict[str, tuple] = {}


def _cache_key(ticker: str, direction: str, entry_price: float) -> str:
    return f"{ticker}:{direction}:{entry_price:.2f}"


# ---------------------------------------------------------------------------
# Helpers — pure Python, no numpy
# ---------------------------------------------------------------------------

def _build_fixed_bins(bars: List[Dict]) -> Tuple[List[float], List[float]]:
    """
    Build 20¢-aligned price bins for the session range.

    Returns:
        bin_centers : list of float  (mid-point of each 20¢ bin)
        bin_volumes : list of float  (accumulated volume per bin)
    """
    session_high = max(b["high"] for b in bars)
    session_low  = min(b["low"]  for b in bars)

    # Align edges to the nearest 20¢ boundary
    import math
    lo_edge = math.floor(session_low  / _BIN_SIZE) * _BIN_SIZE
    hi_edge = math.ceil (session_high / _BIN_SIZE) * _BIN_SIZE

    n_bins = max(1, round((hi_edge - lo_edge) / _BIN_SIZE))
    edges  = [round(lo_edge + i * _BIN_SIZE, 2) for i in range(n_bins + 1)]
    centers = [round((edges[i] + edges[i + 1]) / 2, 2) for i in range(n_bins)]
    volumes = [0.0] * n_bins

    for bar in bars:
        hi   = bar["high"]
        lo   = bar["low"]
        vol  = bar["volume"]
        # Distribute volume across bins that overlap the bar's range
        touched = []
        for i, (e_lo, e_hi) in enumerate(zip(edges[:-1], edges[1:])):
            if e_hi > lo and e_lo < hi:          # bin overlaps bar range
                overlap = min(e_hi, hi) - max(e_lo, lo)
                bar_range = hi - lo if hi > lo else _BIN_SIZE
                touched.append((i, overlap / bar_range))
        if not touched:
            # Fallback: put all volume in the bin containing close
            idx = min(range(n_bins),
                      key=lambda i: abs(centers[i] - bar["close"]))
            touched = [(idx, 1.0)]
        total_weight = sum(w for _, w in touched)
        for idx, w in touched:
            volumes[idx] += vol * (w / total_weight)

    return centers, volumes


def _find_poc(centers: List[float], volumes: List[float]) -> Tuple[float, int]:
    """Return (poc_price, poc_index)."""
    poc_idx = max(range(len(volumes)), key=lambda i: volumes[i])
    return centers[poc_idx], poc_idx


def _cme_value_area(
    centers: List[float],
    volumes: List[float],
    poc_idx: int,
) -> Tuple[float, float]:
    """
    CME-correct value area expansion.

    At each iteration compare the TWO-bar group above the current high boundary
    against the TWO-bar group below the current low boundary.  Absorb the side
    with the higher combined volume.  Stop when accumulated volume >= 70% of
    total.  (Comparing single bars — the old approach — produces incorrect VA
    boundaries for wide or skewed sessions.)

    Returns (val, vah).
    """
    n = len(volumes)
    total_vol  = sum(volumes)
    target_vol = total_vol * _VALUE_AREA_PCT

    va_lo = poc_idx
    va_hi = poc_idx
    accumulated = volumes[poc_idx]

    while accumulated < target_vol:
        # Two-bar groups (fall back to one bar if at boundary)
        hi_1 = volumes[va_hi + 1] if va_hi + 1 < n     else 0.0
        hi_2 = volumes[va_hi + 2] if va_hi + 2 < n     else 0.0
        lo_1 = volumes[va_lo - 1] if va_lo - 1 >= 0    else 0.0
        lo_2 = volumes[va_lo - 2] if va_lo - 2 >= 0    else 0.0

        up_sum   = hi_1 + hi_2
        down_sum = lo_1 + lo_2

        if up_sum == 0 and down_sum == 0:
            break

        if up_sum >= down_sum and va_hi + 1 < n:
            va_hi      += 1
            accumulated += hi_1
            if va_hi + 1 < n:
                va_hi      += 1
                accumulated += hi_2
        elif va_lo - 1 >= 0:
            va_lo      -= 1
            accumulated += lo_1
            if va_lo - 1 >= 0:
                va_lo      -= 1
                accumulated += lo_2
        elif va_hi + 1 < n:
            va_hi      += 1
            accumulated += hi_1
        else:
            break

    return centers[va_lo], centers[va_hi]   # val, vah


def _pct_rank(value: float, arr: List[float]) -> float:
    """What fraction of arr is <= value (0.0 – 1.0)."""
    if not arr:
        return 0.5
    return sum(1 for x in arr if x <= value) / len(arr)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VolumeProfileAnalyzer:
    """
    Volume profile validator for per-signal entry gating.

    Bin resolution is fixed at 20¢ (no num_bins parameter).  The value area
    is computed with the CME two-bar expansion algorithm.  Results are stored
    in the module-level cache so they are shared across instances.
    """

    # ------------------------------------------------------------------
    # Public API — called by sniper.py Step 6.6
    # ------------------------------------------------------------------

    def analyze_session_profile(self, bars: List[Dict]) -> Dict:
        """
        Build volume profile for session bars.

        Returns:
            poc, vah, val, hvn_levels, lvn_levels, profile, total_volume
        """
        if not bars or len(bars) < 10:
            return self._empty_profile()

        centers, volumes = _build_fixed_bins(bars)
        n = len(centers)
        total_vol = sum(volumes)

        poc, poc_idx = _find_poc(centers, volumes)
        val, vah = _cme_value_area(centers, volumes, poc_idx)

        # HVN / LVN via percentile thresholds
        p80 = sorted(volumes)[int(n * 0.80)] if n >= 5 else 0.0
        p20 = sorted(volumes)[int(n * 0.20)] if n >= 5 else 0.0

        hvn_levels = [centers[i] for i, v in enumerate(volumes) if v >= p80]
        lvn_levels = [centers[i] for i, v in enumerate(volumes) if 0 < v <= p20]

        profile = list(zip(centers, volumes))

        return {
            "poc":           poc,
            "vah":           vah,
            "val":           val,
            "hvn_levels":    hvn_levels,
            "lvn_levels":    lvn_levels,
            "profile":       profile,
            "total_volume":  total_vol,
        }

    def _empty_profile(self) -> Dict:
        return {
            "poc": 0, "vah": 0, "val": 0,
            "hvn_levels": [], "lvn_levels": [],
            "profile": [], "total_volume": 0,
        }

    # ------------------------------------------------------------------
    # Breakout validation helpers  (unchanged from previous version)
    # ------------------------------------------------------------------

    def validate_breakout(
        self,
        profile: Dict,
        breakout_price: float,
        direction: str,
    ) -> Tuple[bool, str]:
        """Validate if breakout occurs at a favorable volume level."""
        if not profile or profile["total_volume"] == 0:
            return True, "No volume profile data"

        poc = profile["poc"]
        vah = profile["vah"]
        val = profile["val"]
        hvn_levels = profile["hvn_levels"]
        lvn_levels = profile["lvn_levels"]

        for lvn in lvn_levels:
            if abs(breakout_price - lvn) / breakout_price < 0.01:
                return True, f"Breakout near LVN (${lvn:.2f}) — Low resistance"

        for hvn in hvn_levels:
            if abs(breakout_price - hvn) / breakout_price < 0.01:
                return False, f"Breakout near HVN (${hvn:.2f}) — High resistance"

        if direction == "bull":
            if breakout_price > vah:
                return True, f"Bullish breakout above VAH (${vah:.2f})"
            elif breakout_price < val:
                return False, f"Bullish breakout below VAL (${val:.2f}) — Weak"
        else:
            if breakout_price < val:
                return True, f"Bearish breakout below VAL (${val:.2f})"
            elif breakout_price > vah:
                return False, f"Bearish breakout above VAH (${vah:.2f}) — Weak"

        return True, "Neutral volume profile context"

    # ------------------------------------------------------------------
    # Main entry point — called by sniper.py Step 6.6
    # ------------------------------------------------------------------

    def validate_entry(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        bars: List[Dict],
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Build the volume profile and validate the entry price.

        Results are stored in the module-level TTL cache (5 min).

        Returns:
            (is_valid, reason, vp_data)

        vp_data keys
        ------------
        poc                   float  Point of Control
        vah                   float  Value Area High
        val                   float  Value Area Low
        distance_from_poc_pct float  abs(entry - poc) / poc
        volume_rank           str    % of max-volume bin at entry
        confidence_boost      float  signed delta for SignalValidator
                                       +0.05 near POC / in LVN zone
                                       -0.05 near HVN / outside VA
                                        0.00 neutral
        options_bias          str    'CALL' | 'PUT' | 'NEUTRAL'
                                       CALL  if entry > vah (break-up)
                                       PUT   if entry < val (break-down)
                                       NEUTRAL otherwise
        """
        key = _cache_key(ticker, direction, entry_price)
        now = datetime.utcnow()
        if key in _entry_cache:
            result, expiry = _entry_cache[key]
            if now < expiry:
                return result

        profile = self.analyze_session_profile(bars)

        if not profile or profile.get("total_volume", 0) == 0:
            result = (True, "Volume profile unavailable (insufficient bars)", None)
            _entry_cache[key] = (result, now + _CACHE_TTL)
            return result

        is_valid, reason = self.validate_breakout(profile, entry_price, direction)

        poc = profile.get("poc", 0.0)
        vah = profile.get("vah", 0.0)
        val = profile.get("val", 0.0)
        hvn_levels = profile.get("hvn_levels", [])
        lvn_levels = profile.get("lvn_levels", [])

        distance_pct = abs(entry_price - poc) / poc if poc > 0 else 0.0

        # --- volume_rank ---
        volume_rank = "N/A"
        profile_bins = profile.get("profile", [])
        if profile_bins:
            try:
                vols = [v for _, v in profile_bins]
                closest_vol = min(profile_bins, key=lambda x: abs(x[0] - entry_price))[1]
                max_vol = max(vols) or 1.0
                volume_rank = f"{closest_vol / max_vol:.0%}"
            except Exception:
                pass

        # --- confidence_boost ---
        boost = 0.0
        near_poc = distance_pct <= 0.005            # within 0.5% of POC
        in_lvn   = any(abs(entry_price - lv) / entry_price < 0.01 for lv in lvn_levels)
        in_hvn   = any(abs(entry_price - hv) / entry_price < 0.01 for hv in hvn_levels)
        in_va    = val <= entry_price <= vah

        if near_poc:
            boost = +0.05
        elif in_lvn:
            boost = +0.05
        elif in_hvn:
            boost = -0.05
        elif not in_va:
            boost = -0.03

        # --- options_bias ---
        if entry_price > vah:
            options_bias = "CALL"
        elif entry_price < val:
            options_bias = "PUT"
        else:
            options_bias = "NEUTRAL"

        vp_data = {
            "poc":                   round(poc, 2),
            "vah":                   round(vah, 2),
            "val":                   round(val, 2),
            "distance_from_poc_pct": round(distance_pct, 4),
            "volume_rank":           volume_rank,
            "confidence_boost":      round(boost, 3),
            "options_bias":          options_bias,
        }

        result = (is_valid, reason, vp_data)
        _entry_cache[key] = (result, now + _CACHE_TTL)
        return result


# ---------------------------------------------------------------------------
# Global instance + factory
# ---------------------------------------------------------------------------

_volume_analyzer: Optional[VolumeProfileAnalyzer] = None


def get_volume_analyzer() -> VolumeProfileAnalyzer:
    global _volume_analyzer
    if _volume_analyzer is None:
        _volume_analyzer = VolumeProfileAnalyzer()
    return _volume_analyzer
