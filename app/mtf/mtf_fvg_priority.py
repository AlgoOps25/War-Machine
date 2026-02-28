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

from datetime import datetime, time
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from utils import config

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHASE 3E: Import consolidated timeframe compression + metadata
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
from .mtf_compression import (
    compress_to_3m,
    compress_to_2m,
    compress_to_1m,
    TIMEFRAME_PRIORITY,
    TIMEFRAME_WEIGHTS
)

ET = ZoneInfo("America/New_York")

# Stats tracking
_priority_stats = {
    'scans': 0,
    'conflicts_resolved': 0,
    'primary_tf_breakdown': {'5m': 0, '3m': 0, '2m': 0, '1m': 0},
    'confluence_found': 0
}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FVG DETECTION (across all timeframes)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def detect_fvg_on_timeframe(
    bars: List[dict],
    direction: str,
    tf_name: str,
    min_pct: float = 0.001
) -> Optional[Dict]:
    """
    Scan bars for the most recent FVG matching the given direction.
    
    Returns FVG dict or None.
    """
    if len(bars) < 10:
        return None
    
    # Scan last 30 bars for FVGs (don't need full history)
    recent = bars[-30:]
    
    for i in range(len(recent) - 1, 2, -1):  # Scan backwards (most recent first)
        c0 = recent[i - 2]
        c2 = recent[i]
        
        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= min_pct:
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
                    'priority_weight': TIMEFRAME_WEIGHTS[tf_name]
                }
        
        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= min_pct:
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
                    'priority_weight': TIMEFRAME_WEIGHTS[tf_name]
                }
    
    return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MTF FVG SCANNER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def scan_all_timeframes_for_fvgs(
    bars_5m: List[dict],
    direction: str,
    min_pct: float = 0.001
) -> List[Dict]:
    """
    Scan all timeframes (5m, 3m, 2m, 1m) for FVGs in the given direction.
    
    Returns list of FVG dicts, unsorted.
    """
    if len(bars_5m) < 30:
        return []
    
    fvgs = []
    
    # Scan 5m (primary timeframe)
    fvg_5m = detect_fvg_on_timeframe(bars_5m, direction, '5m', min_pct)
    if fvg_5m:
        fvgs.append(fvg_5m)
    
    # Derive lower timeframes using consolidated compression module
    bars_3m = compress_to_3m(bars_5m)
    bars_2m = compress_to_2m(bars_5m)
    bars_1m = compress_to_1m(bars_5m)
    
    # Scan 3m
    fvg_3m = detect_fvg_on_timeframe(bars_3m, direction, '3m', min_pct)
    if fvg_3m:
        fvgs.append(fvg_3m)
    
    # Scan 2m
    fvg_2m = detect_fvg_on_timeframe(bars_2m, direction, '2m', min_pct)
    if fvg_2m:
        fvgs.append(fvg_2m)
    
    # Scan 1m
    fvg_1m = detect_fvg_on_timeframe(bars_1m, direction, '1m', min_pct)
    if fvg_1m:
        fvgs.append(fvg_1m)
    
    return fvgs


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FVG OVERLAP DETECTION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PRIORITY RESOLVER (Core Logic)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def resolve_fvg_priority(
    ticker: str,
    direction: str,
    bars_5m: List[dict],
    min_pct: float = 0.001
) -> Dict:
    """
    Scan all timeframes for FVGs and resolve priority conflicts.
    
    **Nitro Trades Rule:**
    "Always take the highest timeframe FVG when conflicts exist."
    
    Returns:
    {
        'primary_fvg': Dict (the FVG you should trade),
        'secondary_fvgs': List[Dict] (lower-TF FVGs for confluence),
        'confluence_count': int (how many TFs have FVGs),
        'has_conflict': bool (were multiple FVGs found?),
        'resolution': str (explanation of what was chosen)
    }
    """
    _priority_stats['scans'] += 1
    
    # Scan all timeframes
    all_fvgs = scan_all_timeframes_for_fvgs(bars_5m, direction, min_pct)
    
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
    
    # Sort by priority (5m > 3m > 2m > 1m)
    priority_order = {tf: i for i, tf in enumerate(TIMEFRAME_PRIORITY)}
    sorted_fvgs = sorted(all_fvgs, key=lambda x: priority_order[x['timeframe']])
    
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PUBLIC API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def get_highest_priority_fvg(
    ticker: str,
    direction: str,
    bars_5m: List[dict],
    min_pct: float = 0.001
) -> Optional[Dict]:
    """
    Get the highest-priority FVG for trading.
    
    **Use this in sniper.py INSTEAD of bos_fvg_engine.find_fvg_after_bos()**
    when you want MTF priority enforcement.
    
    Returns:
        Primary FVG dict (with 'timeframe' field) or None if no FVGs exist.
    """
    result = resolve_fvg_priority(ticker, direction, bars_5m, min_pct)
    
    if result['primary_fvg'] is None:
        return None
    
    # Log priority resolution
    if result['has_conflict']:
        print(
            f"[MTF-PRIORITY] {ticker} {direction.upper()}: "
            f"{result['resolution']}"
        )
    
    return result['primary_fvg']


def get_full_mtf_analysis(
    ticker: str,
    direction: str,
    bars_5m: List[dict],
    min_pct: float = 0.001
) -> Dict:
    """
    Get complete MTF FVG analysis including all detected FVGs and priority logic.
    
    Use this for detailed logging or when you need to track secondary FVGs.
    """
    return resolve_fvg_priority(ticker, direction, bars_5m, min_pct)


def print_priority_stats():
    """Print EOD MTF priority statistics."""
    if _priority_stats['scans'] == 0:
        return
    
    conflict_rate = (_priority_stats['conflicts_resolved'] / _priority_stats['scans']) * 100
    confluence_rate = (_priority_stats['confluence_found'] / _priority_stats['scans']) * 100
    
    print("\n" + "="*80)
    print("MTF FVG PRIORITY RESOLVER - DAILY STATISTICS")
    print("="*80)
    print(f"Total Scans:          {_priority_stats['scans']}")
    print(f"Conflicts Resolved:   {_priority_stats['conflicts_resolved']} ({conflict_rate:.1f}%)")
    print(f"Confluence Found:     {_priority_stats['confluence_found']} ({confluence_rate:.1f}%)")
    print("\nPrimary FVG Timeframe Breakdown:")
    for tf in TIMEFRAME_PRIORITY:
        count = _priority_stats['primary_tf_breakdown'][tf]
        pct = (count / _priority_stats['scans'] * 100) if _priority_stats['scans'] > 0 else 0
        print(f"  {tf}: {count} ({pct:.1f}%)")
    print("\nPriority Rule: 5m > 3m > 2m > 1m")
    print("Confluence: Lower-TF FVGs overlapping primary FVG zone")
    print("="*80 + "\n")


print("[MTF-PRIORITY] âœ… Multi-timeframe FVG priority resolver loaded")
print("[MTF-PRIORITY] Rule: Always trade the highest-TF FVG when conflicts exist")
print("[MTF-PRIORITY] Priority order: 5m > 3m > 2m > 1m")


