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

FIXED H1 (Mar 10 2026):
    _fetch_vix_from_eodhd() previously read data['close'] from the EODHD
    real-time endpoint. For indices during RTH, 'close' is the PRIOR
    SESSION close, not the live intraday value. The live value is in 'last'.
    Fix: read 'last' first, fall back to 'close' only when 'last' is
    absent or zero. Added stale-data warning when the returned timestamp
    is > 15 minutes old.
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
VIX_CACHE_TTL = 300        # 5 minutes
VIX_STALE_WARN_SECS = 900  # 15 minutes — warn if EODHD timestamp is older than this
VIX_FALLBACK = 20.0        # Assume "normal" regime if fetch fails

# Thread-safe cache
_cache_lock = threading.Lock()
_cached_vix: Optional[float] = None
_cached_timestamp: Optional[datetime] = None
_cached_regime: Optional[Dict] = None


def _fetch_vix_from_eodhd() -> Optional[float]:
    """
    Fetch current VIX from EODHD real-time API.

    EODHD real-time endpoint field priority (H1 fix):
      1. 'last'  — live intraday print (populated during RTH)
      2. 'close' — prior session close (fallback when market closed)

    Using 'close' alone (the original code) meant sizing ran on
    yesterday's VIX throughout the entire trading day.

    Returns:
        float: Current VIX level (e.g., 18.42)
        None:  If fetch fails or value is invalid
    """
    try:
        url = (
            f"https://eodhd.com/api/real-time/VIX.INDX"
            f"?api_token={config.EODHD_API_KEY}&fmt=json"
        )

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        # ── H1 FIX: prefer 'last' (live intraday) over 'close' (prior session) ──
        vix_level = None
        source_field = None

        last_val = data.get('last')
        if last_val and float(last_val) > 0:
            vix_level = float(last_val)
            source_field = 'last'
        else:
            close_val = data.get('close')
            if close_val and float(close_val) > 0:
                vix_level = float(close_val)
                source_field = 'close'
        # ─────────────────────────────────────────────────────────────────────────

        if vix_level is None:
            print(f"[VIX] No valid 'last' or 'close' in response: {data}")
            return None

        # Warn if EODHD's own timestamp shows stale data
        raw_ts = data.get('timestamp')
        if raw_ts:
            try:
                data_dt = datetime.fromtimestamp(int(raw_ts), tz=ET)
                age_secs = (datetime.now(tz=ET) - data_dt).total_seconds()
                if age_secs > VIX_STALE_WARN_SECS:
                    print(
                        f"[VIX] ⚠️  Stale data warning: EODHD VIX timestamp is "
                        f"{age_secs/60:.0f} min old (field='{source_field}', "
                        f"value={vix_level:.2f}). Sizing may lag real volatility."
                    )
            except Exception:
                pass  # Non-fatal — timestamp parse errors should never kill sizing

        print(f"[VIX] Fetched VIX={vix_level:.2f} (field='{source_field}')")
        return vix_level

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

    with _cache_lock:
        if _cached_vix is not None and _cached_timestamp is not None:
            age = (now - _cached_timestamp).total_seconds()
            if age < VIX_CACHE_TTL:
                return _cached_vix

    vix = _fetch_vix_from_eodhd()

    if vix is None:
        with _cache_lock:
            if _cached_vix is not None:
                print(f"[VIX] Fetch failed, using stale cache: {_cached_vix:.2f}")
                return _cached_vix
            else:
                print(f"[VIX] Fetch failed, using fallback: {VIX_FALLBACK}")
                return VIX_FALLBACK

    with _cache_lock:
        _cached_vix = vix
        _cached_timestamp = now

    return vix


def _calculate_vix_regime(vix: float) -> Tuple[float, str]:
    """
    Calculate VIX multiplier and regime name based on VIX level.

    Returns:
        (multiplier, regime_name): e.g., (0.85, "elevated")
    """
    for threshold, multiplier, regime_name in VIX_REGIMES:
        if vix < threshold:
            return multiplier, regime_name
    return VIX_REGIMES[-1][1], VIX_REGIMES[-1][2]


def get_vix_multiplier() -> float:
    """
    Get current VIX-based position sizing multiplier.

    Returns:
        float: Multiplier to apply to base position size (0.3 to 1.3)
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
    """
    if vix_multiplier is None:
        vix_multiplier = get_vix_multiplier()
    return base_risk * vix_multiplier


def get_vix_regime() -> Dict:
    """
    Get current VIX level, regime, and multiplier.

    Returns:
        dict: {
            'vix': float,
            'regime': str,
            'multiplier': float,
            'cached': bool,
            'cache_age': float,
        }
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
    """Clear VIX cache (useful for testing)."""
    global _cached_vix, _cached_timestamp, _cached_regime
    with _cache_lock:
        _cached_vix = None
        _cached_timestamp = None
        _cached_regime = None


# ── Diagnostic / Testing Functions ────────────────────────────────────────────────

def get_sizing_examples() -> str:
    """
    Generate examples of position sizing across signal grades at current VIX.
    """
    regime = get_vix_regime()
    vix = regime['vix']
    mult = regime['multiplier']
    regime_name = regime['regime']

    risk_tiers = [
        ("A+", 0.030),
        ("A",  0.025),
        ("B+", 0.020),
        ("B",  0.016),
        ("C+", 0.014),
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
    print("\n" + "="*60)
    print("VIX SIZING - Market Volatility Check")
    print("="*60)

    regime = get_vix_regime()

    print(f"\nVIX Level: {regime['vix']:.2f}")
    print(f"Regime: {regime['regime'].upper()}")
    print(f"Position Multiplier: {regime['multiplier']:.2f}× ({regime['multiplier']*100:.0f}% of base)")
    print(f"Cache Status: {'Cached' if regime['cached'] else 'Fresh'} ({regime['cache_age']:.0f}s old)")

    if regime['multiplier'] > 1.0:
        print(f"\n✅ LOW VOLATILITY - Increase position sizes by {(regime['multiplier']-1)*100:.0f}%")
    elif regime['multiplier'] < 0.85:
        print(f"\n⚠️  HIGH VOLATILITY - Reduce position sizes by {(1-regime['multiplier'])*100:.0f}%")
    else:
        print(f"\n➡️  NORMAL VOLATILITY - Use baseline position sizes")

    print(get_sizing_examples())
