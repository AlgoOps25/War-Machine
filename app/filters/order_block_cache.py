# app/filters/order_block_cache.py
# C2: Order Block Retest Cache
# Identifies order blocks (last up/down candle before a BOS) and caches them.
# When price retests the OB zone, applies a confidence boost.
# Cache is in-memory (per session) — resets on restart.
#
# FIX 50.A-2 (Mar 26 2026): print() in apply_ob_retest_boost() replaced with
#   logger.info(); added import logging + module-level logger.

from datetime import datetime, time
from zoneinfo import ZoneInfo
import logging
logger = logging.getLogger(__name__)

OB_CACHE: dict[str, list] = {}   # ticker -> list of order block dicts

OB_BODY_MIN_PCT     = 0.0010     # OB candle body must be >= 0.10% to qualify
OB_ZONE_BUFFER_PCT  = 0.0015     # extend OB zone ±0.15% for retest tolerance
try:
    from utils import config as _cfg
    OB_RETEST_BOOST = getattr(_cfg, 'OB_RETEST_BOOST', 0.03)
except Exception:
    OB_RETEST_BOOST = 0.03

OB_MAX_CACHE_PER_TICKER = 5      # keep only the 5 most recent OBs per ticker


def _candle_body(bar: dict) -> float:
    return abs(bar["close"] - bar["open"])

def _is_bullish(bar: dict) -> bool:
    return bar["close"] > bar["open"]

def _is_bearish(bar: dict) -> bool:
    return bar["close"] < bar["open"]


def identify_order_block(bars: list, bos_idx: int, direction: str) -> dict | None:
    """
    Finds the last opposing candle before the BOS as the order block.
    Bull BOS → last bearish candle before bos_idx
    Bear BOS → last bullish candle before bos_idx
    """
    if bos_idx < 2:
        return None

    for i in range(bos_idx - 1, max(0, bos_idx - 10) - 1, -1):
        bar = bars[i]
        body = _candle_body(bar)
        if body / bar["close"] < OB_BODY_MIN_PCT:
            continue
        if direction == "bull" and _is_bearish(bar):
            return {
                "direction": direction,
                "ob_high":   max(bar["open"], bar["close"]),
                "ob_low":    min(bar["open"], bar["close"]),
                "bar_idx":   i,
                "bar_dt":    bar.get("datetime"),
                "used":      False,
            }
        if direction == "bear" and _is_bullish(bar):
            return {
                "direction": direction,
                "ob_high":   max(bar["open"], bar["close"]),
                "ob_low":    min(bar["open"], bar["close"]),
                "bar_idx":   i,
                "bar_dt":    bar.get("datetime"),
                "used":      False,
            }
    return None


def cache_order_block(ticker: str, ob: dict):
    """Add an OB to the cache for a ticker, capping at OB_MAX_CACHE_PER_TICKER."""
    if ticker not in OB_CACHE:
        OB_CACHE[ticker] = []
    OB_CACHE[ticker].append(ob)
    # Keep only most recent N
    OB_CACHE[ticker] = OB_CACHE[ticker][-OB_MAX_CACHE_PER_TICKER:]


def check_ob_retest(ticker: str, entry_price: float, direction: str) -> dict | None:
    """
    Returns the first unused cached OB whose zone contains entry_price (with buffer).
    Marks it as used so it doesn't fire twice.
    """
    obs = OB_CACHE.get(ticker, [])
    for ob in obs:
        if ob["used"]:
            continue
        if ob["direction"] != direction:
            continue
        zone_low  = ob["ob_low"]  * (1 - OB_ZONE_BUFFER_PCT)
        zone_high = ob["ob_high"] * (1 + OB_ZONE_BUFFER_PCT)
        if zone_low <= entry_price <= zone_high:
            ob["used"] = True
            return ob
    return None


def apply_ob_retest_boost(
    ticker: str,
    entry_price: float,
    direction: str,
    confidence: float
) -> tuple[float, dict | None]:
    """
    Checks for OB retest and returns (adjusted_confidence, ob_result).
    """
    ob = check_ob_retest(ticker, entry_price, direction)
    if ob is None:
        return confidence, None

    boosted = min(confidence + OB_RETEST_BOOST, 0.95)
    # FIX 50.A-2: was print() — use logger.info for Railway log stream
    logger.info(
        f"[{ticker}] \u2705 ORDER BLOCK RETEST: zone ${ob['ob_low']:.2f}\u2013${ob['ob_high']:.2f} | "
        f"Conf boost: {confidence:.3f} \u2192 {boosted:.3f} (+{OB_RETEST_BOOST:.2f})"
    )
    return boosted, ob


def clear_ob_cache(ticker: str = None):
    """Clear cache for one ticker or all tickers."""
    if ticker:
        OB_CACHE.pop(ticker, None)
    else:
        OB_CACHE.clear()
