# app/filters/liquidity_sweep.py
# C1: Liquidity Sweep Detector
# Detects when price has swept a key level (OR high/low, prior swing, VWAP)
# and reversed — confirming institutional accumulation/distribution.
# Returns a sweep result dict or None if no sweep detected.
#
# FIX 5.G-18 (Mar 19 2026): Bull sweep close_reclaim now requires close to be
#   at least 20% of the OR range above or_low, not just $0.01 above.
#   Previous check: (bar["close"] - level) / level >= -SWEEP_CLOSE_MAX_PCT
#   allowed close anywhere above OR low - 0.10%, letting a close of $0.01
#   above or_low pass as a valid reclaim. Fix: _candle_swept_level() now
#   accepts an optional min_reclaim kwarg (absolute $) computed in
#   detect_liquidity_sweep() as 20% of the OR range.

from datetime import time
from zoneinfo import ZoneInfo
from datetime import datetime

SWEEP_WICK_MIN_PCT   = 0.0015   # wick must extend at least 0.15% beyond level
SWEEP_CLOSE_MAX_PCT  = 0.0010   # close must retrace back within 0.10% of level
SWEEP_LOOKBACK_BARS  = 6        # how many bars back to look for the sweep candle
SWEEP_CONFIDENCE_BOOST = 0.04   # +4% confidence when sweep confirmed
SWEEP_RECLAIM_OR_PCT = 0.20     # close must be >= or_low + 20% of OR range (5.G-18)

def _candle_swept_level(
    bar: dict,
    level: float,
    direction: str,
    min_reclaim: float = 0.0,
) -> bool:
    """
    Bull sweep: wick below level (low < level) but close back above it.
    Bear sweep: wick above level (high > level) but close back below it.

    min_reclaim (5.G-18): for bull sweeps, close must be >= level + min_reclaim
    (computed as 20% of OR range by detect_liquidity_sweep). Prevents a $0.01
    close above or_low from counting as a valid reclaim.
    """
    if direction == "bull":
        wick_breach = (level - bar["low"]) / level >= SWEEP_WICK_MIN_PCT
        close_reclaim = bar["close"] >= level + min_reclaim
        return wick_breach and close_reclaim and bar["close"] > bar["low"]
    elif direction == "bear":
        wick_breach = (bar["high"] - level) / level >= SWEEP_WICK_MIN_PCT
        close_reclaim = (level - bar["close"]) / level >= -SWEEP_CLOSE_MAX_PCT
        return wick_breach and close_reclaim and bar["close"] < bar["high"]
    return False

def detect_liquidity_sweep(
    bars: list,
    direction: str,
    or_high: float,
    or_low: float,
    vwap: float = 0.0
) -> dict | None:
    """
    Scans the last SWEEP_LOOKBACK_BARS bars for a liquidity sweep of:
      - OR high (bear sweep) or OR low (bull sweep)
      - VWAP (if provided)

    5.G-18: computes min_reclaim = 20% of OR range and passes it to
    _candle_swept_level() so close must be meaningfully above or_low.

    Returns:
        dict with keys: swept_level, sweep_bar_idx, sweep_type, boost
        or None if no sweep found.
    """
    if not bars or len(bars) < 3:
        return None

    scan_bars = bars[-SWEEP_LOOKBACK_BARS:]
    offset = len(bars) - SWEEP_LOOKBACK_BARS

    # 5.G-18: require close >= or_low + 20% of OR range for bull reclaim
    or_range = (or_high - or_low) if (or_high and or_low and or_high > or_low) else 0.0
    bull_min_reclaim = or_range * SWEEP_RECLAIM_OR_PCT

    levels = []
    if direction == "bull" and or_low:
        levels.append((or_low, "OR_LOW", bull_min_reclaim))
    if direction == "bear" and or_high:
        levels.append((or_high, "OR_HIGH", 0.0))
    if vwap and vwap > 0:
        levels.append((vwap, "VWAP", 0.0))

    for i, bar in enumerate(scan_bars):
        for level, label, min_reclaim in levels:
            if _candle_swept_level(bar, level, direction, min_reclaim=min_reclaim):
                return {
                    "swept_level":    level,
                    "sweep_bar_idx":  offset + i,
                    "sweep_type":     label,
                    "boost":          SWEEP_CONFIDENCE_BOOST,
                    "bar":            bar,
                }
    return None

def apply_sweep_boost(
    ticker: str,
    bars: list,
    direction: str,
    or_high: float,
    or_low: float,
    confidence: float,
    vwap: float = 0.0
) -> tuple[float, dict | None]:
    """
    Runs sweep detection and returns (adjusted_confidence, sweep_result).
    If no sweep found, confidence is unchanged.
    """
    result = detect_liquidity_sweep(bars, direction, or_high, or_low, vwap)
    if result is None:
        return confidence, None

    boosted = min(confidence + result["boost"], 0.95)
    print(
        f"[{ticker}] ✅ LIQUIDITY SWEEP: {result['sweep_type']} @ "
        f"${result['swept_level']:.2f} | "
        f"Conf boost: {confidence:.3f} → {boosted:.3f} (+{result['boost']:.2f})"
    )
    return boosted, result
