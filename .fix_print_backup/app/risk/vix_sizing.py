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

Data Source: EODHD API (^VIX.INDX)

Fixes applied
-------------
H1 (Mar 10 2026):
    _fetch_vix_from_eodhd() now reads 'last' (live intraday) first,
    falling back to 'close' (prior session close) only when 'last' is
    absent or zero.  The original code used 'close' alone, so sizing ran
    on yesterday's VIX throughout the entire trading day.

H2 (Mar 11 2026):
    Stale-data warning now suppressed outside market hours (09:30-16:00
    ET, Mon-Fri).  After hours and on weekends, EODHD returns the prior
    session close as 'close' — that IS the correct value; firing a
    warning every evening was pure noise.  Warning still fires during
    RTH if the timestamp is >20 min old (tightened from 15 min).
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
    (12,  1.30, "ultra-calm"),
    (15,  1.15, "calm"),
    (20,  1.00, "normal"),
    (25,  0.85, "elevated"),
    (30,  0.70, "high"),
    (40,  0.50, "very high"),
    (999, 0.30, "crisis"),
]

VIX_CACHE_TTL        = 300   # seconds — re-fetch every 5 min
VIX_STALE_WARN_SECS  = 1200  # 20 min — warn during RTH only (H2 fix)
VIX_FALLBACK         = 20.0

_cache_lock       = threading.Lock()
_cached_vix:      Optional[float]    = None
_cached_timestamp: Optional[datetime] = None
_cached_regime:   Optional[Dict]     = None


# ── Market-hours helper ───────────────────────────────────────────────────────

def _is_market_hours_now() -> bool:
    """
    H2 FIX: Returns True only during regular trading hours in ET.
    Mon-Fri 09:30-16:00 ET.  Stale-data warning is suppressed outside
    this window because EODHD legitimately returns prior-session close
    after hours and on weekends.
    """
    now = datetime.now(tz=ET)
    if now.weekday() >= 5:           # Saturday=5, Sunday=6
        return False
    open_mins  = 9 * 60 + 30        # 09:30
    close_mins = 16 * 60            # 16:00
    bar_mins   = now.hour * 60 + now.minute
    return open_mins <= bar_mins < close_mins


# ── EODHD fetch ───────────────────────────────────────────────────────────────

def _fetch_vix_from_eodhd() -> Optional[float]:
    """
    Fetch current VIX from EODHD real-time API.

    Field priority (H1 fix):
      1. 'last'  — live intraday print (populated during RTH)
      2. 'close' — prior session close (correct value after hours)

    Stale warning (H2 fix):
      Only fires during market hours (09:30-16:00 ET, Mon-Fri).
    """
    try:
        url = (
            f"https://eodhd.com/api/real-time/VIX.INDX"
            f"?api_token={config.EODHD_API_KEY}&fmt=json"
        )
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        # H1: prefer 'last' (live) over 'close' (prior session)
        vix_level    = None
        source_field = None

        last_val = data.get('last')
        if last_val and float(last_val) > 0:
            vix_level    = float(last_val)
            source_field = 'last'
        else:
            close_val = data.get('close')
            if close_val and float(close_val) > 0:
                vix_level    = float(close_val)
                source_field = 'close'

        if vix_level is None:
            print(f"[VIX] No valid 'last' or 'close' in response: {data}")
            return None

        # H2: stale warning only during RTH
        raw_ts = data.get('timestamp')
        if raw_ts and _is_market_hours_now():
            try:
                data_dt  = datetime.fromtimestamp(int(raw_ts), tz=ET)
                age_secs = (datetime.now(tz=ET) - data_dt).total_seconds()
                if age_secs > VIX_STALE_WARN_SECS:
                    print(
                        f"[VIX] ⚠️  Stale data during RTH: EODHD VIX timestamp is "
                        f"{age_secs/60:.0f} min old (field='{source_field}', "
                        f"value={vix_level:.2f}). Sizing may lag real volatility."
                    )
            except Exception:
                pass

        # Only print after-hours fetches at debug level (not INFO)
        if _is_market_hours_now():
            print(f"[VIX] Fetched VIX={vix_level:.2f} (field='{source_field}')")
        else:
            import logging as _log
            _log.getLogger(__name__).debug(
                f"[VIX] After-hours fetch: VIX={vix_level:.2f} (field='{source_field}')"
            )

        return vix_level

    except requests.exceptions.RequestException as exc:
        print(f"[VIX] Fetch error: {exc}")
        return None
    except Exception as exc:
        print(f"[VIX] Parse error: {exc}")
        return None


# ── Cache layer ───────────────────────────────────────────────────────────────

def _get_vix_with_cache() -> float:
    """Get VIX with 5-minute cache."""
    global _cached_vix, _cached_timestamp

    now = datetime.now()
    with _cache_lock:
        if _cached_vix is not None and _cached_timestamp is not None:
            if (now - _cached_timestamp).total_seconds() < VIX_CACHE_TTL:
                return _cached_vix

    vix = _fetch_vix_from_eodhd()

    if vix is None:
        with _cache_lock:
            if _cached_vix is not None:
                return _cached_vix
            return VIX_FALLBACK

    with _cache_lock:
        _cached_vix       = vix
        _cached_timestamp = now

    return vix


# ── Public API ────────────────────────────────────────────────────────────────

def _calculate_vix_regime(vix: float) -> Tuple[float, str]:
    for threshold, multiplier, regime_name in VIX_REGIMES:
        if vix < threshold:
            return multiplier, regime_name
    return VIX_REGIMES[-1][1], VIX_REGIMES[-1][2]


def get_vix_multiplier() -> float:
    """Get current VIX-based position sizing multiplier (0.3 – 1.3)."""
    vix = _get_vix_with_cache()
    multiplier, _ = _calculate_vix_regime(vix)
    return multiplier


def get_adjusted_risk(base_risk: float, vix_multiplier: float = None) -> float:
    """Apply VIX multiplier to base risk percentage."""
    if vix_multiplier is None:
        vix_multiplier = get_vix_multiplier()
    return base_risk * vix_multiplier


def get_vix_regime() -> Dict:
    """Get current VIX level, regime name, and multiplier."""
    global _cached_timestamp
    vix = _get_vix_with_cache()
    multiplier, regime_name = _calculate_vix_regime(vix)
    with _cache_lock:
        if _cached_timestamp:
            cache_age = (datetime.now() - _cached_timestamp).total_seconds()
            cached    = cache_age < VIX_CACHE_TTL
        else:
            cache_age = 0
            cached    = False
    return {
        'vix':        vix,
        'regime':     regime_name,
        'multiplier': multiplier,
        'cached':     cached,
        'cache_age':  cache_age,
    }


def clear_cache():
    """Clear VIX cache (useful for testing)."""
    global _cached_vix, _cached_timestamp, _cached_regime
    with _cache_lock:
        _cached_vix       = None
        _cached_timestamp = None
        _cached_regime    = None


# ── Diagnostic ───────────────────────────────────────────────────────────────

def get_sizing_examples() -> str:
    regime = get_vix_regime()
    vix, mult, regime_name = regime['vix'], regime['multiplier'], regime['regime']
    risk_tiers = [
        ("A+", 0.030), ("A", 0.025), ("B+", 0.020),
        ("B",  0.016), ("C+", 0.014),
    ]
    output = [
        f"\n{'='*60}",
        f"VIX POSITION SIZING - Current Regime",
        f"{'='*60}",
        f"VIX Level: {vix:.2f} ({regime_name.upper()})",
        f"Multiplier: {mult:.2f}\u00d7 ({mult*100:.0f}% of base size)",
        f"\n{'Grade':<8} {'Base Risk':<12} {'VIX-Adjusted':<15} {'Change'}",
        "-" * 60,
    ]
    for grade, base_risk in risk_tiers:
        adjusted   = get_adjusted_risk(base_risk, mult)
        change_pct = (adjusted - base_risk) / base_risk * 100
        output.append(
            f"{grade:<8} {base_risk*100:>5.1f}%{'':<6} "
            f"{adjusted*100:>5.1f}%{'':<9} {change_pct:>+5.1f}%"
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
    print(f"Multiplier: {regime['multiplier']:.2f}\u00d7 ({regime['multiplier']*100:.0f}% of base)")
    print(f"Cache: {'Cached' if regime['cached'] else 'Fresh'} ({regime['cache_age']:.0f}s old)")
    print(f"Market Hours Now: {_is_market_hours_now()}")
    if regime['multiplier'] > 1.0:
        print(f"\n✅ LOW VOLATILITY - Increase sizes by {(regime['multiplier']-1)*100:.0f}%")
    elif regime['multiplier'] < 0.85:
        print(f"\n⚠️  HIGH VOLATILITY - Reduce sizes by {(1-regime['multiplier'])*100:.0f}%")
    else:
        print(f"\n➡️  NORMAL VOLATILITY - Use baseline sizes")
    print(get_sizing_examples())
