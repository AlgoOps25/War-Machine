# app/filters/sd_zone_confluence.py
# D2: Supply/Demand Zone Confluence (MVP)
# Identifies intraday S/D zones from swing highs/lows with strong momentum.
# Boosts confidence when entry price lands inside a zone.
#
# FIX 50.A-3 (Mar 26 2026): print() in apply_sd_confluence_boost() replaced
#   with logger.info(); added import logging + module-level logger.

import logging
logger = logging.getLogger(__name__)

SD_ZONE_BUFFER_PCT   = 0.0020   # zone ±0.20% buffer for entry tolerance
SD_MOMENTUM_MIN_PCT  = 0.0015   # impulse candle body >= 0.15% to qualify
SD_LOOKBACK_BARS     = 50       # how far back to scan for zones
SD_CONFLUENCE_BOOST  = 0.03     # +3% confidence on zone confluence

_SD_CACHE: dict[str, list] = {}  # ticker -> list of zone dicts


def _candle_body_pct(bar: dict) -> float:
    if bar["open"] == 0:
        return 0.0
    return abs(bar["close"] - bar["open"]) / bar["open"]


def identify_sd_zones(bars: list) -> list[dict]:
    """
    Scans bars for S/D zones defined as:
    - Demand zone: strong bullish candle preceded by a down move
      (zone = body of the bullish impulse candle)
    - Supply zone: strong bearish candle preceded by an up move
      (zone = body of the bearish impulse candle)
    """
    zones = []
    scan = bars[-SD_LOOKBACK_BARS:] if len(bars) > SD_LOOKBACK_BARS else bars

    for i in range(2, len(scan) - 1):
        bar  = scan[i]
        prev = scan[i - 1]
        body = _candle_body_pct(bar)
        if body < SD_MOMENTUM_MIN_PCT:
            continue

        # Demand zone: prior bar bearish, current bar bullish impulse
        if bar["close"] > bar["open"] and prev["close"] < prev["open"]:
            zones.append({
                "type":      "demand",
                "zone_low":  min(bar["open"], bar["close"]),
                "zone_high": max(bar["open"], bar["close"]),
                "bar_idx":   i,
                "strength":  body,
            })

        # Supply zone: prior bar bullish, current bar bearish impulse
        if bar["close"] < bar["open"] and prev["close"] > prev["open"]:
            zones.append({
                "type":      "supply",
                "zone_low":  min(bar["open"], bar["close"]),
                "zone_high": max(bar["open"], bar["close"]),
                "bar_idx":   i,
                "strength":  body,
            })

    # Keep strongest 5 zones only
    zones.sort(key=lambda z: z["strength"], reverse=True)
    return zones[:5]


def cache_sd_zones(ticker: str, bars: list):
    """Identify and cache S/D zones for a ticker."""
    _SD_CACHE[ticker] = identify_sd_zones(bars)


def check_sd_confluence(
    ticker: str,
    entry_price: float,
    direction: str
) -> dict | None:
    """
    Returns the first zone that:
    - Contains entry_price (with buffer)
    - Aligns with direction (demand→bull, supply→bear)
    """
    zones = _SD_CACHE.get(ticker, [])
    for zone in zones:
        if direction == "bull" and zone["type"] != "demand":
            continue
        if direction == "bear" and zone["type"] != "supply":
            continue
        z_low  = zone["zone_low"]  * (1 - SD_ZONE_BUFFER_PCT)
        z_high = zone["zone_high"] * (1 + SD_ZONE_BUFFER_PCT)
        if z_low <= entry_price <= z_high:
            return zone
    return None


def apply_sd_confluence_boost(
    ticker: str,
    entry_price: float,
    direction: str,
    confidence: float
) -> tuple[float, dict | None]:
    """
    Checks S/D confluence and returns (adjusted_confidence, zone_result).
    """
    zone = check_sd_confluence(ticker, entry_price, direction)
    if zone is None:
        return confidence, None

    boosted = min(confidence + SD_CONFLUENCE_BOOST, 0.95)
    # FIX 50.A-3: was print() — use logger.info for Railway log stream
    logger.info(
        f"[{ticker}] \u2705 S/D ZONE CONFLUENCE: {zone['type'].upper()} "
        f"${zone['zone_low']:.2f}\u2013${zone['zone_high']:.2f} | "
        f"Conf boost: {confidence:.3f} \u2192 {boosted:.3f} (+{SD_CONFLUENCE_BOOST:.2f})"
    )
    return boosted, zone


def clear_sd_cache(ticker: str = None):
    if ticker:
        _SD_CACHE.pop(ticker, None)
    else:
        _SD_CACHE.clear()
