"""
vix_sizing.py — VIX-Based Dynamic Position Sizing

Adjusts position sizes based on current VIX (market volatility) levels.
Higher VIX = smaller positions (risk-off), Lower VIX = larger positions (risk-on).

VIX Regimes:
  < 12:  Ultra-calm (1.3× position size)
  12-15: Calm (1.15×)
  15-20: Normal (1.0× baseline)
  20-25: Elevated (0.85×)
  25-30: High (0.7×)
  30-40: Very High (0.5×)
  > 40:  Crisis (0.3×)

Data Source: EODHD API (^VIX.INDX) - included in EOD+Intraday plan

Usage:
    from app.risk.vix_sizing import get_vix_multiplier, get_adjusted_risk
    
    # Get current VIX multiplier
    vix_mult = get_vix_multiplier()
    
    # Apply to base risk
    base_risk = 0.03  # 3% for A+ signal
    adjusted_risk = get_adjusted_risk(base_risk, vix_mult)
    # VIX=15 -> 3.0% (baseline)
    # VIX=30 -> 2.1% (70% of base)
    # VIX=10 -> 3.9% (130% of base)
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import threading
import requests
from typing import Optional, Dict, Tuple

from utils import config

ET = ZoneInfo("America/New_York")

# VIX regime thresholds and multipliers
VIX_REGIMES = [
    (12,  1.30, "ultra-calm"),   # VIX < 12: ultra-calm market, increase size 30%
    (15,  1.15, "calm"),         # VIX 12-15: calm, increase size 15%
    (20,  1.00, "normal"),       # VIX 15-20: normal, baseline sizing
    (25,  0.85, "elevated"),     # VIX 20-25: elevated vol, reduce 15%
    (30,  0.70, "high"),         # VIX 25-30: high vol, reduce 30%
    (40,  0.50, "very high"),    # VIX 30-40: very high vol, reduce 50%
    (999, 0.30, "crisis"),       # VIX > 40: crisis mode, reduce 70%
]

# Cache settings
VIX_CACHE_TTL = 300  # 5 minutes (VIX updates frequently during market hours)
VIX_FALLBACK = 20.0  # Assume "normal" regime if fetch fails

# Thread-safe cache
_cache_lock = threading.Lock()
_cached_vix: Optional[float] = None
_cached_timestamp: Optional[datetime] = None
_cached_regime: Optional[Dict] = None


def _fetch_vix_from_eodhd() -> Optional[float]:
    """
    Fetch current VIX from EODHD API.
    Uses real-time endpoint for ^VIX.INDX (CBOE Volatility Index).
    
    Returns:
        float: Current VIX level (e.g., 18.42)
        None: If fetch fails
    """
    try:
        # EODHD real-time API for VIX
        # ^VIX.INDX = CBOE Volatility Index
        url = f"https://eodhd.com/api/real-time/VIX.INDX?api_token={config.EODHD_API_KEY}&fmt=json"
        
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        vix_level = data.get('close')  # Current VIX level
        
        if vix_level is None or vix_level <= 0:
            print(f"[VIX] Invalid VIX data: {data}")
            return None
        
        return float(vix_level)
    
    except requests.exceptions.RequestException as e:
        print(f"[VIX] Fetch error: {e}")
        return None
    except Exception as e:
        print(f"[VIX] Parse error: {e}")
        return None


def _get_vix_with_cache() -> float:
    """
    Get VIX with 5-minute caching.
    Returns cached value if fresh, otherwise fetches new data.
    
    Returns:
        float: Current VIX level (or fallback if unavailable)
    """
    global _cached_vix, _cached_timestamp
    
    now = datetime.now()
    
    # Check cache
    with _cache_lock:
        if _cached_vix is not None and _cached_timestamp is not None:
            age = (now - _cached_timestamp).total_seconds()
            if age < VIX_CACHE_TTL:
                return _cached_vix
    
    # Fetch fresh VIX
    vix = _fetch_vix_from_eodhd()
    
    if vix is None:
        # Fetch failed - use cached if available, otherwise fallback
        with _cache_lock:
            if _cached_vix is not None:
                print(f"[VIX] Fetch failed, using stale cache: {_cached_vix:.2f}")
                return _cached_vix
            else:
                print(f"[VIX] Fetch failed, using fallback: {VIX_FALLBACK}")
                return VIX_FALLBACK
    
    # Update cache
    with _cache_lock:
        _cached_vix = vix
        _cached_timestamp = now
    
    return vix


def _calculate_vix_regime(vix: float) -> Tuple[float, str]:
    """
    Calculate VIX multiplier and regime name based on VIX level.
    
    Args:
        vix: Current VIX level
    
    Returns:
        (multiplier, regime_name): e.g., (0.85, "elevated")
    """
    for threshold, multiplier, regime_name in VIX_REGIMES:
        if vix < threshold:
            return multiplier, regime_name
    
    # Shouldn't reach here (999 threshold catches all)
    return VIX_REGIMES[-1][1], VIX_REGIMES[-1][2]


def get_vix_multiplier() -> float:
    """
    Get current VIX-based position sizing multiplier.
    
    Returns:
        float: Multiplier to apply to base position size (0.3 to 1.3)
    
    Example:
        mult = get_vix_multiplier()
        # VIX=15 -> 1.0 (baseline)
        # VIX=30 -> 0.7 (reduce size 30%)
        # VIX=10 -> 1.3 (increase size 30%)
    """
    vix = _get_vix_with_cache()
    multiplier, _ = _calculate_vix_regime(vix)
    return multiplier


def get_adjusted_risk(base_risk: float, vix_multiplier: float = None) -> float:
    """
    Apply VIX multiplier to base risk percentage.
    
    Args:
        base_risk: Base risk per trade (e.g., 0.03 for 3%)
        vix_multiplier: Optional override (if None, fetches current VIX)
    
    Returns:
        float: Adjusted risk percentage
    
    Example:
        # A+ signal normally gets 3% risk
        base = 0.03
        
        # VIX=15 (normal) -> 3.0%
        adjusted = get_adjusted_risk(base)  # 0.03
        
        # VIX=30 (high) -> 2.1%
        adjusted = get_adjusted_risk(base)  # 0.021 (70% of base)
        
        # VIX=10 (calm) -> 3.9%
        adjusted = get_adjusted_risk(base)  # 0.039 (130% of base)
    """
    if vix_multiplier is None:
        vix_multiplier = get_vix_multiplier()
    
    return base_risk * vix_multiplier


def get_vix_regime() -> Dict:
    """
    Get current VIX level, regime, and multiplier.
    
    Returns:
        dict: {
            'vix': float,          # Current VIX level
            'regime': str,         # Regime name ("normal", "elevated", etc.)
            'multiplier': float,   # Position size multiplier
            'cached': bool,        # True if using cached data
            'cache_age': float,    # Seconds since cache update
        }
    
    Example:
        regime = get_vix_regime()
        print(f"VIX: {regime['vix']:.2f} ({regime['regime']})")
        print(f"Position sizing: {regime['multiplier']*100:.0f}% of base")
    """
    global _cached_timestamp
    
    vix = _get_vix_with_cache()
    multiplier, regime_name = _calculate_vix_regime(vix)
    
    with _cache_lock:
        if _cached_timestamp:
            cache_age = (datetime.now() - _cached_timestamp).total_seconds()
            cached = cache_age < VIX_CACHE_TTL
        else:
            cache_age = 0
            cached = False
    
    return {
        'vix': vix,
        'regime': regime_name,
        'multiplier': multiplier,
        'cached': cached,
        'cache_age': cache_age,
    }


def clear_cache():
    """
    Clear VIX cache (useful for testing).
    """
    global _cached_vix, _cached_timestamp, _cached_regime
    with _cache_lock:
        _cached_vix = None
        _cached_timestamp = None
        _cached_regime = None


# ── Diagnostic / Testing Functions ──────────────────────────────────────────

def get_sizing_examples() -> str:
    """
    Generate examples of position sizing across signal grades at current VIX.
    
    Returns:
        str: Formatted table of examples
    """
    regime = get_vix_regime()
    vix = regime['vix']
    mult = regime['multiplier']
    regime_name = regime['regime']
    
    # Your current risk tiers
    risk_tiers = [
        ("A+", 0.030),  # 3.0%
        ("A",  0.025),  # 2.5%
        ("B+", 0.020),  # 2.0%
        ("B",  0.016),  # 1.6%
        ("C+", 0.014),  # 1.4%
    ]
    
    output = []
    output.append(f"\n{'='*60}")
    output.append(f"VIX POSITION SIZING - Current Regime")
    output.append(f"{'='*60}")
    output.append(f"VIX Level: {vix:.2f} ({regime_name.upper()})")
    output.append(f"Multiplier: {mult:.2f}× ({mult*100:.0f}% of base size)")
    output.append(f"\n{'Grade':<8} {'Base Risk':<12} {'VIX-Adjusted':<15} {'Change'}")
    output.append("-" * 60)
    
    for grade, base_risk in risk_tiers:
        adjusted = get_adjusted_risk(base_risk, mult)
        change_pct = (adjusted - base_risk) / base_risk * 100
        sign = "+" if change_pct > 0 else ""
        
        output.append(
            f"{grade:<8} {base_risk*100:>5.1f}%{'':<6} "
            f"{adjusted*100:>5.1f}%{'':<9} "
            f"{sign}{change_pct:>+5.1f}%"
        )
    
    output.append("=" * 60 + "\n")
    return "\n".join(output)


if __name__ == "__main__":
    # Diagnostic output when run directly
    print("\n" + "="*60)
    print("VIX SIZING - Market Volatility Check")
    print("="*60)
    
    regime = get_vix_regime()
    
    print(f"\nVIX Level: {regime['vix']:.2f}")
    print(f"Regime: {regime['regime'].upper()}")
    print(f"Position Multiplier: {regime['multiplier']:.2f}× ({regime['multiplier']*100:.0f}% of base)")
    print(f"Cache Status: {'Cached' if regime['cached'] else 'Fresh'} ({regime['cache_age']:.0f}s old)")
    
    # Regime interpretation
    if regime['multiplier'] > 1.0:
        print(f"\n✅ LOW VOLATILITY - Increase position sizes by {(regime['multiplier']-1)*100:.0f}%")
    elif regime['multiplier'] < 0.85:
        print(f"\n⚠️  HIGH VOLATILITY - Reduce position sizes by {(1-regime['multiplier'])*100:.0f}%")
    else:
        print(f"\n➡️  NORMAL VOLATILITY - Use baseline position sizes")
    
    # Show examples
    print(get_sizing_examples())
