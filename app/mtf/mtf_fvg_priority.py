"""
MTF FVG Priority Resolver
Enforces Nitro Trades rule: "Always take the highest timeframe FVG when conflicts exist."

From video transcript:
"If you have a 1-minute, 2-minute, 3-minute, and 5-minute [signal],
you will go for the 5-minute. The highest time frame is going to be
the most powerful one. So if you have a few opportunities, a few
different FVG gaps, you will play the one that's on the highest time frame."

Priority Order: 5m > 3m > 2m > 1m

Integration:
- Called BEFORE sniper.py runs confirmation layers
- Scans all available timeframes for FVGs
- Returns the highest-TF FVG as the primary trade zone
- Marks lower-TF FVGs as "secondary" for confluence tracking only

FIX (Mar 26 2026) — issue #29:
  - get_highest_priority_fvg(): print() → logger.info() for priority log line.

FIX BUG-MTF-2 (Mar 27, 2026):
  - detect_fvg_on_timeframe(): volume_ratio was computed on c2 (the 3rd candle
    of the FVG triplet — the post-gap recovery bar). The impulse that creates
    the FVG is c1 (the middle candle, index i-1). Changed volume check to c1.
    Valid high-volume FVGs were being discarded when c2 was low-volume;
    low-quality FVGs were passing when the actual impulse bar was thin.

FIX BUG-MTF-3 (Mar 27, 2026):
  - get_full_mtf_analysis() only built 5m/3m/2m/1m in bars_mtf. After 10 AM
    get_available_timeframes() returns 30m and 15m but those keys were always
    absent — higher-TF FVGs were never found and _priority_stats for
    1h/30m/15m were permanently 0. Added '15m' and '30m' via the existing
    floor-bucket _resample() helper already defined in the function. '1h' is
    intentionally excluded (12 bars per candle — rarely available intraday).
"""

import logging
from datetime import datetime, time
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from utils import config

###########################################################################
# PHASE 3E: Import consolidated timeframe compression + metadata
###########################################################################
from .mtf_compression import (
    compress_to_3m,
    compress_to_2m,
    compress_to_1m,
    TIMEFRAME_PRIORITY,
    TIMEFRAME_WEIGHTS
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Stats tracking
_priority_stats = {
    'scans': 0,
    'conflicts_resolved': 0,
    'primary_tf_breakdown': {
        '1h': 0,
        '30m': 0,
        '15m': 0,
        '5m': 0,
        '3m': 0,
        '2m': 0,
        '1m': 0
    },
    'confluence_found': 0,
    'volume_filtered': 0
}


###########################################################################
# FVG DETECTION (across all timeframes)
###########################################################################

def detect_fvg_on_timeframe(
    bars: List[dict],
    direction: str,
    tf_name: str,
    min_pct: float = 0.001,
    require_volume: bool = True
) -> Optional[Dict]:
    """
    Scan bars for the most recent FVG matching the given direction.
    Enhanced with volume confirmation on the IMPULSE candle (c1).

    FVG pattern: 3-candle sequence c0, c1 (impulse), c2.
    The gap is between c0 and c2. Volume check is on c1 — the candle
    whose move created the imbalance (BUG-MTF-2 fix).

    Returns FVG dict or None.
    """
    if len(bars) < 10:
        return None

    recent = bars[-30:]

    avg_volume = sum(b['volume'] for b in recent[-20:-1]) / 19 if len(recent) >= 20 else None

    # Volume thresholds by timeframe (higher TF = stricter requirement)
    volume_thresholds = {
        '1h':  2.0,
        '30m': 1.8,
        '15m': 1.6,
        '5m':  1.5,
        '3m':  1.3,
        '2m':  1.2,
        '1m':  1.0
    }
    min_volume_ratio = volume_thresholds.get(tf_name, 1.5)

    for i in range(len(recent) - 1, 2, -1):
        c0 = recent[i - 2]
        c1 = recent[i - 1]   # BUG-MTF-2 FIX: impulse candle — volume checked here
        c2 = recent[i]

        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= min_pct:
                if require_volume and avg_volume:
                    volume_ratio = c1['volume'] / avg_volume if avg_volume > 0 else 0
                    if volume_ratio < min_volume_ratio:
                        _priority_stats['volume_filtered'] += 1
                        continue
                else:
                    volume_ratio = None
                return {
                    'timeframe':        tf_name,
                    'direction':        direction,
                    'fvg_high':         c2["low"],
                    'fvg_low':          c0["high"],
                    'fvg_mid':          (c2["low"] + c0["high"]) / 2,
                    'fvg_size':         gap,
                    'fvg_size_pct':     round(gap / c0["high"] * 100, 3),
                    'bar_idx':          i,
                    'bar_time':         recent[i]['datetime'],
                    'priority_weight':  TIMEFRAME_WEIGHTS.get(tf_name, 1.0),
                    'volume_ratio':     round(volume_ratio, 2) if volume_ratio is not None else None,
                    'volume_confirmed': volume_ratio >= min_volume_ratio if volume_ratio is not None else False,
                    'avg_volume':       round(avg_volume) if avg_volume else None
                }

        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= min_pct:
                if require_volume and avg_volume:
                    volume_ratio = c1['volume'] / avg_volume if avg_volume > 0 else 0
                    if volume_ratio < min_volume_ratio:
                        _priority_stats['volume_filtered'] += 1
                        continue
                else:
                    volume_ratio = None
                return {
                    'timeframe':        tf_name,
                    'direction':        direction,
                    'fvg_high':         c0["low"],
                    'fvg_low':          c2["high"],
                    'fvg_mid':          (c0["low"] + c2["high"]) / 2,
                    'fvg_size':         gap,
                    'fvg_size_pct':     round(gap / c0["low"] * 100, 3),
                    'bar_idx':          i,
                    'bar_time':         recent[i]['datetime'],
                    'priority_weight':  TIMEFRAME_WEIGHTS.get(tf_name, 1.0),
                    'volume_ratio':     round(volume_ratio, 2) if volume_ratio is not None else None,
                    'volume_confirmed': volume_ratio >= min_volume_ratio if volume_ratio is not None else False,
                    'avg_volume':       round(avg_volume) if avg_volume else None
                }

    return None


###########################################################################
# MTF FVG SCANNER
###########################################################################

def scan_all_timeframes_for_fvgs(
    bars_mtf: Dict[str, List[dict]],
    direction: str,
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> List[Dict]:
    """
    Scan all available timeframes for FVGs in the given direction.

    Args:
        bars_mtf:     Dict mapping timeframe name to bar list.
        direction:    'bull' or 'bear'
        min_pct:      Minimum FVG size as % of price.
        current_time: Current timestamp (for time-aware filtering).

    Returns:
        List of FVG dicts, unsorted.
    """
    fvgs = []
    available_tfs = get_available_timeframes(current_time) if current_time else TIMEFRAME_PRIORITY
    for tf_name in available_tfs:
        if tf_name not in bars_mtf:
            continue
        bars = bars_mtf[tf_name]
        if not bars or len(bars) < 10:
            continue
        fvg = detect_fvg_on_timeframe(bars, direction, tf_name, min_pct)
        if fvg:
            fvgs.append(fvg)
    return fvgs


def get_available_timeframes(current_time: datetime) -> List[str]:
    """
    Determine which timeframes have complete bars based on current market time.

    - 9:30-9:45 AM: 5m and lower only
    - 9:45-10:00 AM: add 15m
    - 10:00-10:30 AM: add 30m
    - 10:30+ AM: all timeframes (1h through 1m)
    """
    market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_since_open = (current_time - market_open).total_seconds() / 60
    if minutes_since_open < 0:
        return []
    elif minutes_since_open < 15:
        return ['5m', '3m', '2m', '1m']
    elif minutes_since_open < 30:
        return ['15m', '5m', '3m', '2m', '1m']
    elif minutes_since_open < 60:
        return ['30m', '15m', '5m', '3m', '2m', '1m']
    else:
        return ['1h', '30m', '15m', '5m', '3m', '2m', '1m']


###########################################################################
# FVG OVERLAP DETECTION
###########################################################################

def check_fvg_overlap(fvg1: Dict, fvg2: Dict, min_overlap_pct: float = 0.30) -> bool:
    """
    Check if two FVGs overlap by at least min_overlap_pct of the smaller FVG.
    Identifies when FVGs on different timeframes represent the same zone.
    """
    low1, high1 = fvg1['fvg_low'], fvg1['fvg_high']
    low2, high2 = fvg2['fvg_low'], fvg2['fvg_high']
    overlap_low  = max(low1, low2)
    overlap_high = min(high1, high2)
    if overlap_high <= overlap_low:
        return False
    overlap_size = overlap_high - overlap_low
    smaller_size = min(high1 - low1, high2 - low2)
    if smaller_size == 0:
        return False
    return (overlap_size / smaller_size) >= min_overlap_pct


def resolve_fvg_priority(
    ticker: str,
    direction: str,
    bars_mtf: Dict[str, List[dict]],
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> Dict:
    """
    Scan all timeframes for FVGs and resolve priority conflicts.
    Nitro Trades rule: always take the highest-timeframe FVG.
    """
    _priority_stats['scans'] += 1
    all_fvgs = scan_all_timeframes_for_fvgs(bars_mtf, direction, min_pct, current_time)

    if not all_fvgs:
        return {
            'primary_fvg': None, 'secondary_fvgs': [], 'confluence_count': 0,
            'has_conflict': False, 'resolution': 'No FVGs found on any timeframe'
        }

    if len(all_fvgs) == 1:
        fvg = all_fvgs[0]
        tf  = fvg['timeframe']
        if tf in _priority_stats['primary_tf_breakdown']:
            _priority_stats['primary_tf_breakdown'][tf] += 1
        return {
            'primary_fvg': fvg, 'secondary_fvgs': [], 'confluence_count': 1,
            'has_conflict': False, 'resolution': f"Single FVG on {tf}"
        }

    _priority_stats['conflicts_resolved'] += 1
    priority_order = {tf: i for i, tf in enumerate(TIMEFRAME_PRIORITY)}
    sorted_fvgs = sorted(all_fvgs, key=lambda x: priority_order.get(x['timeframe'], 999))
    primary_fvg = sorted_fvgs[0]
    tf = primary_fvg['timeframe']
    if tf in _priority_stats['primary_tf_breakdown']:
        _priority_stats['primary_tf_breakdown'][tf] += 1

    secondary_fvgs = [
        fvg for fvg in sorted_fvgs[1:]
        if check_fvg_overlap(primary_fvg, fvg, min_overlap_pct=0.30)
    ]
    if secondary_fvgs:
        _priority_stats['confluence_found'] += 1

    confluence_count = 1 + len(secondary_fvgs)
    return {
        'primary_fvg':     primary_fvg,
        'secondary_fvgs':  secondary_fvgs,
        'confluence_count': confluence_count,
        'has_conflict':    True,
        'resolution': (
            f"Priority: {tf} FVG selected (highest TF). "
            f"Confluence: {confluence_count} timeframe(s) aligned."
        )
    }


def get_highest_priority_fvg(
    ticker: str,
    direction: str,
    bars_mtf: Dict[str, List[dict]],
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> Optional[Dict]:
    """
    Get the highest-priority FVG for trading.
    Returns primary FVG dict or None.
    FIX #29: print() → logger.info() for conflict log line.
    """
    result = resolve_fvg_priority(ticker, direction, bars_mtf, min_pct, current_time)
    if result['primary_fvg'] is None:
        return None
    if result['has_conflict']:
        logger.info("[MTF-PRIORITY] %s %s: %s", ticker, direction.upper(), result['resolution'])
    return result['primary_fvg']


###########################################################################
# PHASE 3C / FIX 41.H-5: get_full_mtf_analysis
# Resamples internally from bars_5m (or bars_1m) so callers need only
# pass raw session bars. BUG-MTF-3 FIX: now also builds 15m and 30m
# bars via the same floor-bucket _resample() helper so that
# get_available_timeframes() entries after 10 AM are actually populated.
###########################################################################

def get_full_mtf_analysis(
    ticker: str,
    direction: str,
    bars_5m: List[dict],
    min_pct: float = 0.001,
    bars_1m: List[dict] = None,
) -> Dict:
    """
    Get complete MTF FVG analysis including all detected FVGs and priority logic.
    Builds the full timeframe dict internally — no additional DB reads.

    BUG-MTF-3 FIX: bars_mtf now includes '15m' and '30m' resampled from
    bars_5m so that get_available_timeframes() entries after 9:45 AM and
    10:00 AM are present in the dict and higher-TF FVGs can be detected.
    '1h' intentionally excluded (requires 12 bars per candle; rarely
    available intraday before signal windows close).
    """
    from collections import defaultdict

    def _resample(bars: list, minutes: int) -> list:
        buckets = defaultdict(list)
        for b in bars:
            dt = b["datetime"]
            floored = dt.replace(
                minute=(dt.minute // minutes) * minutes,
                second=0, microsecond=0
            )
            buckets[floored].append(b)
        result = []
        for ts in sorted(buckets):
            bucket = buckets[ts]
            result.append({
                "datetime": ts,
                "open":   bucket[0]["open"],
                "high":   max(b["high"]  for b in bucket),
                "low":    min(b["low"]   for b in bucket),
                "close":  bucket[-1]["close"],
                "volume": sum(b["volume"] for b in bucket),
            })
        return result

    src = bars_1m if bars_1m else bars_5m
    bars_mtf = {
        "30m": _resample(bars_5m, 30),  # BUG-MTF-3 FIX: added
        "15m": _resample(bars_5m, 15),  # BUG-MTF-3 FIX: added
        "5m":  bars_5m,
        "3m":  _resample(src, 3),
        "2m":  _resample(src, 2),
        "1m":  src,
    }
    return resolve_fvg_priority(ticker, direction, bars_mtf, min_pct)


def print_priority_stats():
    """Print EOD MTF priority statistics."""
    if _priority_stats['scans'] == 0:
        return
    conflict_rate   = (_priority_stats['conflicts_resolved'] / _priority_stats['scans']) * 100
    confluence_rate = (_priority_stats['confluence_found']   / _priority_stats['scans']) * 100
    logger.info("\n" + "=" * 80)
    logger.info("MTF FVG PRIORITY RESOLVER - DAILY STATISTICS")
    logger.info("=" * 80)
    logger.info("Total Scans:          %d", _priority_stats['scans'])
    logger.info("Conflicts Resolved:   %d (%.1f%%)", _priority_stats['conflicts_resolved'], conflict_rate)
    logger.info("Confluence Found:     %d (%.1f%%)", _priority_stats['confluence_found'], confluence_rate)
    logger.info("Volume Filtered FVGs: %d", _priority_stats['volume_filtered'])
    logger.info("Primary FVG Timeframe Breakdown:")
    for tf in TIMEFRAME_PRIORITY:
        count = _priority_stats['primary_tf_breakdown'][tf]
        pct   = (count / _priority_stats['scans'] * 100) if _priority_stats['scans'] > 0 else 0
        logger.info("  %s: %d (%.1f%%)", tf, count, pct)
    logger.info("Priority Rule: highest TF FVG wins when conflicts exist")
    logger.info("Confluence:    lower-TF FVGs overlapping primary FVG zone")
    logger.info("=" * 80 + "\n")
