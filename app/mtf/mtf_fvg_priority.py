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
        '1h': 0,   # NEW
        '30m': 0,  # NEW
        '15m': 0,  # NEW
        '5m': 0,
        '3m': 0,
        '2m': 0,
        '1m': 0
    },
    'confluence_found': 0,
    'volume_filtered': 0  # NEW: Track how many FVGs rejected due to low volume
}


###########################################################################
# FVG DETECTION (across all timeframes)
###########################################################################

def detect_fvg_on_timeframe(
    bars: List[dict],
    direction: str,
    tf_name: str,
    min_pct: float = 0.001,
    require_volume: bool = True  # NEW parameter
) -> Optional[Dict]:
    """
    Scan bars for the most recent FVG matching the given direction.
    Enhanced with volume confirmation.
    
    Returns FVG dict or None.
    """
    if len(bars) < 10:
        return None
    
    # Scan last 30 bars for FVGs
    recent = bars[-30:]
    
    # Calculate average volume for comparison
    avg_volume = sum(b['volume'] for b in recent[-20:-1]) / 19 if len(recent) >= 20 else None
    
    # Volume thresholds by timeframe (higher TF = stricter requirement)
    volume_thresholds = {
        '1h': 2.0,   # Require 100% above average
        '30m': 1.8,  # Require 80% above average
        '15m': 1.6,  # Require 60% above average
        '5m': 1.5,   # Require 50% above average
        '3m': 1.3,
        '2m': 1.2,
        '1m': 1.0    # No volume filter on 1m (too noisy)
    }
    
    min_volume_ratio = volume_thresholds.get(tf_name, 1.5)
    
    for i in range(len(recent) - 1, 2, -1):
        c0 = recent[i - 2]
        c2 = recent[i]
        
        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= min_pct:
                
                # Volume confirmation check
                if require_volume and avg_volume:
                    volume_ratio = c2['volume'] / avg_volume if avg_volume > 0 else 0
                    if volume_ratio < min_volume_ratio:
                        continue  # Skip this FVG - insufficient volume
                else:
                    volume_ratio = None
                
                return {
                    'timeframe': tf_name,
                    'direction': direction,
                    'fvg_high': c2["low"],
                    'fvg_low': c0["high"],
                    'fvg_mid': (c2["low"] + c0["high"]) / 2,
                    'fvg_size': gap,
                    'fvg_size_pct': round(gap / c0["high"] * 100, 3),
                    'bar_idx': i,
                    'bar_time': recent[i]['datetime'],
                    'priority_weight': TIMEFRAME_WEIGHTS.get(tf_name, 1.0),
                    'volume_ratio': round(volume_ratio, 2) if volume_ratio else None,
                    'volume_confirmed': volume_ratio >= min_volume_ratio if volume_ratio else False,
                    'avg_volume': round(avg_volume) if avg_volume else None
                }
        
        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= min_pct:
                
                # Volume confirmation check
                if require_volume and avg_volume:
                    volume_ratio = c2['volume'] / avg_volume if avg_volume > 0 else 0
                    if volume_ratio < min_volume_ratio:
                        continue  # Skip this FVG - insufficient volume
                else:
                    volume_ratio = None
                
                return {
                    'timeframe': tf_name,
                    'direction': direction,
                    'fvg_high': c0["low"],
                    'fvg_low': c2["high"],
                    'fvg_mid': (c0["low"] + c2["high"]) / 2,
                    'fvg_size': gap,
                    'fvg_size_pct': round(gap / c0["low"] * 100, 3),
                    'bar_idx': i,
                    'bar_time': recent[i]['datetime'],
                    'priority_weight': TIMEFRAME_WEIGHTS.get(tf_name, 1.0),
                    'volume_ratio': round(volume_ratio, 2) if volume_ratio else None,
                    'volume_confirmed': volume_ratio >= min_volume_ratio if volume_ratio else False,
                    'avg_volume': round(avg_volume) if avg_volume else None
                }
    
    return None


###########################################################################
# MTF FVG SCANNER
###########################################################################

def scan_all_timeframes_for_fvgs(
    bars_mtf: Dict[str, List[dict]],  # CHANGED: now accepts dict instead of just bars_5m
    direction: str,
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> List[Dict]:
    """
    Scan all available timeframes for FVGs in the given direction.
    
    Args:
        bars_mtf: Dict mapping timeframe name to bar list
                  e.g., {'1h': [...], '30m': [...], '5m': [...]}
        direction: 'bull' or 'bear'
        min_pct: Minimum FVG size as % of price
        current_time: Current timestamp (for time-aware filtering)
    
    Returns:
        List of FVG dicts, unsorted
    """
    fvgs = []
    
    # Determine which timeframes are valid based on market time
    available_tfs = get_available_timeframes(current_time) if current_time else TIMEFRAME_PRIORITY
    
    # Scan each available timeframe
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
    
    Strategy:
    - 9:30-9:45 AM: Only 5m and lower available
    - 9:45-10:00 AM: Add 15m (may be partial)
    - 10:00+ AM: Add 30m
    - 10:30+ AM: Add 1h (first complete bar)
    
    Returns:
        List of timeframe names in priority order
    """
    market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_since_open = (current_time - market_open).total_seconds() / 60
    
    if minutes_since_open < 0:
        # Pre-market: no intraday signals
        return []
    elif minutes_since_open < 15:
        # 9:30-9:45: Fast TFs only
        return ['5m', '3m', '2m', '1m']
    elif minutes_since_open < 30:
        # 9:45-10:00: Add 15m
        return ['15m', '5m', '3m', '2m', '1m']
    elif minutes_since_open < 60:
        # 10:00-10:30: Add 30m
        return ['30m', '15m', '5m', '3m', '2m', '1m']
    else:
        # 10:30+: All timeframes
        return ['1h', '30m', '15m', '5m', '3m', '2m', '1m']


###########################################################################
# FVG OVERLAP DETECTION
###########################################################################

def check_fvg_overlap(fvg1: Dict, fvg2: Dict, min_overlap_pct: float = 0.30) -> bool:
    """
    Check if two FVGs overlap by at least min_overlap_pct of the smaller FVG.
    
    This identifies when FVGs on different timeframes are "the same zone".
    """
    # Get ranges
    low1, high1 = fvg1['fvg_low'], fvg1['fvg_high']
    low2, high2 = fvg2['fvg_low'], fvg2['fvg_high']
    
    # Calculate overlap
    overlap_low = max(low1, low2)
    overlap_high = min(high1, high2)
    
    if overlap_high <= overlap_low:
        return False  # No overlap
    
    overlap_size = overlap_high - overlap_low
    size1 = high1 - low1
    size2 = high2 - low2
    smaller_size = min(size1, size2)
    
    if smaller_size == 0:
        return False
    
    overlap_ratio = overlap_size / smaller_size
    
    return overlap_ratio >= min_overlap_pct


def resolve_fvg_priority(
    ticker: str,
    direction: str,
    bars_mtf: Dict[str, List[dict]],  # CHANGED: was bars_5m
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> Dict:
    """
    Scan all timeframes for FVGs and resolve priority conflicts.
    
    **Nitro Trades Rule:**
    "Always take the highest timeframe FVG when conflicts exist."
    
    Args:
        ticker: Symbol
        direction: 'bull' or 'bear'
        bars_mtf: Dict of bars by timeframe
        min_pct: Minimum FVG size threshold
        current_time: Current time (for time-aware priority)
    
    Returns:
        Dict with priority resolution
    """
    _priority_stats['scans'] += 1
    
    # Scan all available timeframes
    all_fvgs = scan_all_timeframes_for_fvgs(bars_mtf, direction, min_pct, current_time)
    
    if not all_fvgs:
        return {
            'primary_fvg': None,
            'secondary_fvgs': [],
            'confluence_count': 0,
            'has_conflict': False,
            'resolution': 'No FVGs found on any timeframe'
        }
    
    # Single FVG - no conflict
    if len(all_fvgs) == 1:
        fvg = all_fvgs[0]
        _priority_stats['primary_tf_breakdown'][fvg['timeframe']] += 1
        
        return {
            'primary_fvg': fvg,
            'secondary_fvgs': [],
            'confluence_count': 1,
            'has_conflict': False,
            'resolution': f"Single FVG on {fvg['timeframe']}"
        }
    
    # Multiple FVGs - apply priority resolution
    _priority_stats['conflicts_resolved'] += 1
    
    # Sort by priority (1h > 30m > 15m > 5m > 3m > 2m > 1m)
    priority_order = {tf: i for i, tf in enumerate(TIMEFRAME_PRIORITY)}
    sorted_fvgs = sorted(all_fvgs, key=lambda x: priority_order.get(x['timeframe'], 999))
    
    # Highest TF FVG is primary
    primary_fvg = sorted_fvgs[0]
    _priority_stats['primary_tf_breakdown'][primary_fvg['timeframe']] += 1
    
    # Check for confluence (overlapping FVGs on lower TFs)
    secondary_fvgs = []
    for fvg in sorted_fvgs[1:]:
        if check_fvg_overlap(primary_fvg, fvg, min_overlap_pct=0.30):
            secondary_fvgs.append(fvg)
    
    if secondary_fvgs:
        _priority_stats['confluence_found'] += 1
    
    confluence_count = 1 + len(secondary_fvgs)
    
    resolution = (
        f"Priority: {primary_fvg['timeframe']} FVG selected (highest TF). "
        f"Confluence: {confluence_count} timeframe(s) aligned."
    )
    
    return {
        'primary_fvg': primary_fvg,
        'secondary_fvgs': secondary_fvgs,
        'confluence_count': confluence_count,
        'has_conflict': True,
        'resolution': resolution
    }


def get_highest_priority_fvg(
    ticker: str,
    direction: str,
    bars_mtf: Dict[str, List[dict]],  # CHANGED: was bars_5m
    min_pct: float = 0.001,
    current_time: Optional[datetime] = None
) -> Optional[Dict]:
    """
    Get the highest-priority FVG for trading.
    
    Args:
        ticker: Symbol
        direction: 'bull' or 'bear'
        bars_mtf: Dict of bars by timeframe
        min_pct: Minimum FVG size
        current_time: Current time for time-aware filtering
    
    Returns:
        Primary FVG dict or None
    """
    result = resolve_fvg_priority(ticker, direction, bars_mtf, min_pct, current_time)
    
    if result['primary_fvg'] is None:
        return None
    
    # Log priority resolution
    if result['has_conflict']:
        print(
            f"[MTF-PRIORITY] {ticker} {direction.upper()}: "
            f"{result['resolution']}"
        )
    
    return result['primary_fvg']


# ── PHASE 3C: FIX 41.H-5 ────────────────────────────────────────────────────────────────────────────────
# get_full_mtf_analysis now resamples internally from bars_5m (or bars_1m if
# provided) instead of requiring the caller to build the MTF dict. This
# eliminates the 3 extra DB reads that occurred when sniper.py passed raw
# session bars directly to resolve_fvg_priority, which expected a dict.
# Backward-compatible: existing callers that pass only bars_5m continue to work.

def get_full_mtf_analysis(
    ticker: str,
    direction: str,
    bars_5m: List[dict],
    min_pct: float = 0.001,
    bars_1m: List[dict] = None,  # optional: pre-fetched 1m bars for sharper resampling
) -> Dict:
    """
    Get complete MTF FVG analysis including all detected FVGs and priority logic.

    Builds the full timeframe dict internally - no additional DB reads.
    Use this for detailed logging or when you need to track secondary FVGs.
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
        "5m": bars_5m,
        "3m": _resample(src, 3),
        "2m": _resample(src, 2),
        "1m": src,
    }
    return resolve_fvg_priority(ticker, direction, bars_mtf, min_pct)


def print_priority_stats():
    """Print EOD MTF priority statistics."""
    if _priority_stats['scans'] == 0:
        return
    
    conflict_rate = (_priority_stats['conflicts_resolved'] / _priority_stats['scans']) * 100
    confluence_rate = (_priority_stats['confluence_found'] / _priority_stats['scans']) * 100
    
    logger.info("\n" + "="*80)
    logger.info("MTF FVG PRIORITY RESOLVER - DAILY STATISTICS")
    logger.info("="*80)
    logger.info(f"Total Scans:          {_priority_stats['scans']}")
    logger.info(f"Conflicts Resolved:   {_priority_stats['conflicts_resolved']} ({conflict_rate:.1f}%)")
    logger.info(f"Confluence Found:     {_priority_stats['confluence_found']} ({confluence_rate:.1f}%)")
    logger.info("\nPrimary FVG Timeframe Breakdown:")
    for tf in TIMEFRAME_PRIORITY:
        count = _priority_stats['primary_tf_breakdown'][tf]
        pct = (count / _priority_stats['scans'] * 100) if _priority_stats['scans'] > 0 else 0
        logger.info(f"  {tf}: {count} ({pct:.1f}%)")
    logger.info("\nPriority Rule: 5m > 3m > 2m > 1m")
    logger.info("Confluence: Lower-TF FVGs overlapping primary FVG zone")
    logger.info("="*80 + "\n")
