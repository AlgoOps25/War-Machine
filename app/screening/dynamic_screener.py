#!/usr/bin/env python3
"""
Dynamic Stock Screener - War Machine
3-Pass strategy to find stocks most likely to make major moves at market open.

EODHD Screener fields available:
  Number: market_capitalization, avgvol_1d, avgvol_200d, adjusted_close,
          refund_1d_p, refund_5d_p, earnings_share, dividend_yield
  String: exchange, sector, industry, code, name
  Signal: 200d_new_hi, 200d_new_lo, bookvalue_pos, bookvalue_neg,
          wallstreet_hi, wallstreet_lo

NOTE: All EODHD screener data is End-of-Day (previous close).
      - refund_1d_p = yesterday's % change (NOT live gap)
      - avgvol_1d   = yesterday's total volume
      - adjusted_close = yesterday's closing price
      Real-time gap detection happens in premarket_scanner.py via live quotes.

PASS STRATEGY:
  Pass 1 - Liquid Universe    : Top 50 by volume. Always returns results.
  Pass 2 - Momentum Movers    : Yesterday's 1.5%+ movers. Gap continuation candidates.
  Pass 3 - Breakout Trend     : 200d new high signal. Trending breakout candidates.
  Post-fetch RVOL Scoring     : avgvol_1d / avgvol_200d -> Tier A/B/C priority.
"""

import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from utils import config

# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────
_screener_cache: Dict = {}
_CACHE_TTL_MINUTES = 30  # Refresh every 30 min during pre-market


# ─────────────────────────────────────────────
# RVOL Tier Thresholds
# These define how "hot" a stock's volume is vs its 200-day average.
# Higher RVOL = more unusual activity = higher probability of a big open move.
# ─────────────────────────────────────────────
RVOL_TIER_A = 2.0    # 2x+ normal volume  → HOT, priority signals
RVOL_TIER_B = 1.5    # 1.5x normal volume → Above average, worth watching
RVOL_TIER_C = 1.0    # 1x  normal volume  → In play but not exceptional
RVOL_MIN    = 0.8    # Below 0.8x → Discard, dead volume day for this ticker


# ─────────────────────────────────────────────
# Pass Filter Definitions
# ─────────────────────────────────────────────

# PASS 1: Liquid Universe
# Goal: A wide net that ALWAYS returns 50+ results regardless of market conditions.
# Logic: Sort by raw volume only. No price change filter (avoids 0-ticker problem).
# Result: The most actively traded, liquid, options-friendly stocks.
PASS1_LIQUID_UNIVERSE = {
    "filters": [
        ["market_capitalization", ">", 5000000000],  # $5B+ market cap (tight option spreads)
        ["avgvol_1d",             ">", 1500000],      # 1.5M+ volume (active options chain)
        ["adjusted_close",        ">", 20],           # $20+ price (meaningful option premium)
        ["adjusted_close",        "<", 500],          # <$500 (affordable contracts)
        ["exchange",              "=", "us"],
    ],
    "sort":  "avgvol_1d.desc",
    "limit": 50,
    "label": "LIQUID UNIVERSE",
}

# PASS 2: Momentum Movers
# Goal: Stocks that moved hard yesterday and are likely to gap/continue at open.
# Logic: refund_1d_p >= 1.5% catches most pre-market gap candidates.
#        Lower cap requirement ($2B) catches smaller high-beta names.
#        Sort by % move to put biggest movers first.
PASS2_MOMENTUM_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2000000000],  # $2B+ (looser, catches mid-caps)
        ["avgvol_1d",             ">", 500000],       # 500K+ minimum liquidity
        ["adjusted_close",        ">", 10],           # $10+ (avoid micro-cap noise)
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           ">", 1.5],          # Moved 1.5%+ yesterday
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.desc",
    "limit": 30,
    "label": "MOMENTUM MOVERS",
}

# PASS 3: Breakout Trend (200-day new high signal)
# Goal: Stocks in strong uptrends near 52-week highs.
# Logic: 200d_new_hi signal = institutional momentum, tends to continue at open.
#        Volume filter ensures these are actually liquid, not low-float traps.
PASS3_BREAKOUT_TREND = {
    "filters": [
        ["market_capitalization", ">", 5000000000],  # Large caps only for breakouts
        ["avgvol_1d",             ">", 1000000],      # Must be liquid
        ["adjusted_close",        ">", 20],
        ["exchange",              "=", "us"],
    ],
    "signal": "200d_new_hi",
    "sort":   "avgvol_1d.desc",
    "limit":  20,
    "label":  "BREAKOUT TREND",
}

# PASS 4 (Fallback only): Negative movers
# Only used if market sold off hard and pass 2 returns 0 results.
# Catches stocks that gapped down and may bounce or continue falling.
PASS4_DOWNSIDE_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2000000000],
        ["avgvol_1d",             ">", 500000],
        ["adjusted_close",        ">", 10],
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           "<", -1.5],         # Dropped 1.5%+ yesterday
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.asc",  # Biggest drops first
    "limit": 20,
    "label": "DOWNSIDE MOVERS",
}


# ─────────────────────────────────────────────
# Fallback Watchlist
# LAST RESORT only - when all 3 API passes fail (network error, API down, etc.)
# Not used for filtering strategy - only for complete API failure.
# Chosen for broad market coverage and high options liquidity.
# ─────────────────────────────────────────────
FALLBACK_WATCHLIST = [
    "SPY", "QQQ", "IWM", "DIA",          # Broad market ETFs
    "AAPL", "TSLA", "GOOGL", "AMZN",     # Mega-cap tech
    "JPM", "BAC", "GS",                  # Financials
    "XOM", "CVX",                        # Energy
    "UNH", "JNJ",                        # Healthcare
    "HD", "WMT", "COST",                 # Consumer
    "COIN", "PLTR", "UBER",              # High-beta momentum
]


# ─────────────────────────────────────────────
# Core API Call
# ─────────────────────────────────────────────

def _run_pass(pass_config: Dict) -> List[Dict]:
    """
    Execute a single screener pass against EODHD API.
    Returns a list of raw ticker dicts with full metadata (for RVOL scoring).

    Each returned dict contains:
      code, name, sector, industry, exchange,
      market_capitalization, adjusted_close,
      avgvol_1d, avgvol_200d,
      refund_1d_p, refund_5d_p,
      earnings_share, dividend_yield
    """
    filters    = pass_config.get("filters", [])
    sort_by    = pass_config.get("sort", "avgvol_1d.desc")
    limit      = pass_config.get("limit", 50)
    signal     = pass_config.get("signal", None)
    label      = pass_config.get("label", "PASS")

    filter_json = json.dumps(filters, separators=(',', ':'))

    url = (
        f"https://eodhd.com/api/screener"
        f"?api_token={config.EODHD_API_KEY}"
        f"&filters={filter_json}"
        f"&limit={limit}"
        f"&sort={sort_by}"
        f"&fmt=json"
    )
    if signal:
        url += f"&signals={signal}"

    try:
        print(f"[SCREENER] [{label}] Calling API... signal={signal or 'none'} sort={sort_by} limit={limit}")
        response = requests.get(url, timeout=15)
        print(f"[SCREENER] [{label}] HTTP {response.status_code}")

        if response.status_code == 422:
            print(f"[SCREENER] [{label}] ❌ 422 – filter format rejected: {response.text[:300]}")
            return []
        if response.status_code == 403:
            print(f"[SCREENER] [{label}] ❌ 403 – endpoint not in your EODHD plan")
            return []
        if response.status_code == 401:
            print(f"[SCREENER] [{label}] ❌ 401 – invalid EODHD_API_KEY")
            return []

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            print(f"[SCREENER] [{label}] Unexpected response type: {type(data)}")
            return []

        results = data.get("data", [])
        total   = data.get("total", "?")
        print(f"[SCREENER] [{label}] ✅ {len(results)} results (API total: {total})")
        return results

    except requests.exceptions.Timeout:
        print(f"[SCREENER] [{label}] ⚠️  Timeout after 15s")
        return []
    except requests.exceptions.HTTPError as e:
        print(f"[SCREENER] [{label}] HTTP error: {e}")
        return []
    except Exception as e:
        print(f"[SCREENER] [{label}] Error: {e}")
        return []


# ─────────────────────────────────────────────
# RVOL Scoring
# ─────────────────────────────────────────────

def _calculate_rvol(avgvol_1d: float, avgvol_200d: float) -> float:
    """Calculate Relative Volume ratio. Returns 0.0 if data missing."""
    if not avgvol_200d or avgvol_200d <= 0:
        return 0.0
    if not avgvol_1d or avgvol_1d <= 0:
        return 0.0
    return round(avgvol_1d / avgvol_200d, 2)


def _get_rvol_tier(rvol: float) -> str:
    """Return RVOL tier label based on relative volume ratio."""
    if rvol >= RVOL_TIER_A:
        return "A"   # HOT  – 2x+ normal volume
    elif rvol >= RVOL_TIER_B:
        return "B"   # WARM – 1.5x normal volume
    elif rvol >= RVOL_TIER_C:
        return "C"   # MILD – 1x  normal volume
    else:
        return "D"   # COLD – below average, discard


def _score_ticker(raw: Dict, source_pass: int) -> Optional[Dict]:
    """
    Build a scored ticker dict from a raw EODHD result row.
    Returns None if the ticker should be discarded (bad data, RVOL too low).

    Scoring logic:
      Base score from RVOL tier:     A=60, B=45, C=30, D=discard
      Bonus: momentum (refund_1d_p): +15 if > 3%, +8 if > 1.5%
      Bonus: weekly trend (refund_5d_p): +10 if > 5%, +5 if > 2%
      Bonus: breakout signal (pass 3): +10
      Penalty: negative day: -5 if refund_1d_p < 0
      Penalty: low market cap: -5 if < $10B

    Final score determines rank in watchlist funnel.
    """
    code = raw.get("code", "")
    if not code:
        return None

    ticker = code.split(".")[0].upper()

    # Parse numeric fields safely
    avgvol_1d   = float(raw.get("avgvol_1d",   0) or 0)
    avgvol_200d = float(raw.get("avgvol_200d", 0) or 0)
    refund_1d   = float(raw.get("refund_1d_p", 0) or 0)
    refund_5d   = float(raw.get("refund_5d_p", 0) or 0)
    close       = float(raw.get("adjusted_close", 0) or 0)
    mktcap      = float(raw.get("market_capitalization", 0) or 0)

    # Calculate RVOL
    rvol = _calculate_rvol(avgvol_1d, avgvol_200d)
    tier = _get_rvol_tier(rvol)

    # Discard cold volume tickers
    if tier == "D":
        return None

    # Base score from tier
    base_scores = {"A": 60, "B": 45, "C": 30}
    score = base_scores[tier]

    # Momentum bonus (yesterday's move)
    if refund_1d >= 3.0:
        score += 15
    elif refund_1d >= 1.5:
        score += 8
    elif refund_1d <= -3.0:
        score += 10   # Strong down moves also create open momentum
    elif refund_1d <= -1.5:
        score += 5
    elif refund_1d < 0:
        score -= 5    # Mild down day penalty

    # Weekly trend bonus (5-day return)
    if abs(refund_5d) >= 5.0:
        score += 10   # Strong trend either direction
    elif abs(refund_5d) >= 2.0:
        score += 5

    # Breakout bonus (came from pass 3 = 200d_new_hi signal)
    if source_pass == 3:
        score += 10

    # Size penalty (smaller cap = thinner options)
    if mktcap < 10_000_000_000:  # Under $10B
        score -= 5

    return {
        "ticker":      ticker,
        "score":       score,
        "rvol":        rvol,
        "rvol_tier":   tier,
        "refund_1d":   round(refund_1d, 2),
        "refund_5d":   round(refund_5d, 2),
        "price":       round(close, 2),
        "mktcap_b":    round(mktcap / 1e9, 1),
        "avgvol_1d":   int(avgvol_1d),
        "avgvol_200d": int(avgvol_200d),
        "sector":      raw.get("sector", ""),
        "source_pass": source_pass,
        "name":        raw.get("name", ""),
    }


# ─────────────────────────────────────────────
# Main Screener Entry Points
# ─────────────────────────────────────────────

def run_all_passes(force_refresh: bool = False) -> List[Dict]:
    """
    Run all 3 screener passes, merge results, apply RVOL scoring.
    Returns a deduplicated, scored, sorted list of ticker dicts.

    Called by get_dynamic_watchlist() and get_scored_tickers().
    Results are cached for CACHE_TTL_MINUTES.
    """
    global _screener_cache

    # Return cache if still valid
    if not force_refresh and _screener_cache:
        cached_time = _screener_cache.get("timestamp")
        if cached_time and (datetime.now() - cached_time) < timedelta(minutes=_CACHE_TTL_MINUTES):
            cached = _screener_cache.get("scored", [])
            print(f"[SCREENER] ✅ Cache hit: {len(cached)} scored tickers "
                  f"(age: {int((datetime.now()-cached_time).total_seconds()/60)}m)")
            return cached

    print(f"\n{'='*60}")
    print(f"[SCREENER] Running 3-pass dynamic screener...")
    print(f"[SCREENER] Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    seen: Dict[str, Dict] = {}   # ticker -> best scored dict
    any_pass_succeeded = False

    # ── Pass 1: Liquid Universe ──────────────────
    pass1_raw = _run_pass(PASS1_LIQUID_UNIVERSE)
    if pass1_raw:
        any_pass_succeeded = True
        for raw in pass1_raw:
            scored = _score_ticker(raw, source_pass=1)
            if scored is None:
                continue
            t = scored["ticker"]
            if t not in seen or scored["score"] > seen[t]["score"]:
                seen[t] = scored

    # ── Pass 2: Momentum Movers ──────────────────
    pass2_raw = _run_pass(PASS2_MOMENTUM_MOVERS)
    if pass2_raw:
        any_pass_succeeded = True
        for raw in pass2_raw:
            scored = _score_ticker(raw, source_pass=2)
            if scored is None:
                continue
            t = scored["ticker"]
            # If already in seen from pass 1, keep highest score
            if t not in seen or scored["score"] > seen[t]["score"]:
                seen[t] = scored

    # ── Pass 3: Breakout Trend ───────────────────
    pass3_raw = _run_pass(PASS3_BREAKOUT_TREND)
    if pass3_raw:
        any_pass_succeeded = True
        for raw in pass3_raw:
            scored = _score_ticker(raw, source_pass=3)
            if scored is None:
                continue
            t = scored["ticker"]
            if t not in seen or scored["score"] > seen[t]["score"]:
                seen[t] = scored

    # ── Fallback if all passes failed ────────────
    if not any_pass_succeeded:
        print("[SCREENER] ⚠️  All 3 passes failed (API down or network error)")
        print("[SCREENER] ⚠️  Using FALLBACK_WATCHLIST – THIS IS A LAST RESORT")
        fallback_scored = [{
            "ticker":      t,
            "score":       20,
            "rvol":        1.0,
            "rvol_tier":   "C",
            "refund_1d":   0.0,
            "refund_5d":   0.0,
            "price":       0.0,
            "mktcap_b":    0.0,
            "avgvol_1d":   0,
            "avgvol_200d": 0,
            "sector":      "",
            "source_pass": 0,
            "name":        "",
        } for t in FALLBACK_WATCHLIST]
        return fallback_scored

    # Sort by score descending
    sorted_tickers = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    # Cache results
    _screener_cache = {
        "timestamp": datetime.now(),
        "scored":    sorted_tickers,
    }

    _print_screener_summary(sorted_tickers)
    return sorted_tickers


def _print_screener_summary(scored: List[Dict], top_n: int = 15) -> None:
    """Print a formatted summary of screener results."""
    if not scored:
        return

    tier_counts = {"A": 0, "B": 0, "C": 0}
    for t in scored:
        tier = t.get("rvol_tier", "C")
        if tier in tier_counts:
            tier_counts[tier] += 1

    print(f"\n{'='*60}")
    print(f"[SCREENER] RESULTS: {len(scored)} tickers scored")
    print(f"[SCREENER] Tier A (🔥 RVOL≥2x): {tier_counts['A']} | "
          f"Tier B (⚡ RVOL≥1.5x): {tier_counts['B']} | "
          f"Tier C (📊 RVOL≥1x): {tier_counts['C']}")
    print(f"\n{'Rank':<5} {'Ticker':<7} {'Score':<7} {'Tier':<6} "
          f"{'RVOL':<7} {'1d%':<8} {'5d%':<8} {'Price':<8} {'MCap $B':<9} {'Sector'}")
    print("-" * 80)

    for i, t in enumerate(scored[:top_n], 1):
        tier_icon = {"A": "🔥", "B": "⚡", "C": "📊"}.get(t["rvol_tier"], "")
        print(
            f"{i:<5} {t['ticker']:<7} {t['score']:<7} "
            f"{tier_icon}{t['rvol_tier']:<5} "
            f"{t['rvol']:<7.2f} "
            f"{t['refund_1d']:>+6.2f}%  "
            f"{t['refund_5d']:>+6.2f}%  "
            f"${t['price']:<7.2f} "
            f"${t['mktcap_b']:<8.1f} "
            f"{t['sector'][:20]}"
        )
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────
# Public Interface (called by watchlist_funnel.py)
# ─────────────────────────────────────────────

def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50,
    force_refresh: bool = False
) -> List[str]:
    """
    Return ordered list of ticker symbols for the watchlist funnel.
    Sorted by RVOL score (highest priority first).
    """
    scored = run_all_passes(force_refresh=force_refresh)
    tickers = [t["ticker"] for t in scored[:max_tickers]]
    print(f"[SCREENER] get_dynamic_watchlist → {len(tickers)} tickers")
    return tickers


def get_scored_tickers(
    max_tickers: int = 50,
    min_score: int = 0,
    force_refresh: bool = False
) -> List[Dict]:
    """
    Return full scored ticker dicts for the momentum scorer.
    Includes RVOL, tier, score, refund data for downstream ranking.
    """
    scored = run_all_passes(force_refresh=force_refresh)
    filtered = [t for t in scored if t["score"] >= min_score]
    return filtered[:max_tickers]


def get_gap_candidates(min_gap_pct: float = 1.5, limit: int = 30) -> List[str]:
    """
    Return tickers from the momentum pass that moved >= min_gap_pct yesterday.
    Used by watchlist_funnel._build_wide_scan() for gap list.
    """
    scored = run_all_passes()
    gap_tickers = [
        t["ticker"] for t in scored
        if t["refund_1d"] >= min_gap_pct
    ]
    print(f"[SCREENER] get_gap_candidates(≥{min_gap_pct}%) → {len(gap_tickers[:limit])} tickers")
    return gap_tickers[:limit]


def get_tier_a_tickers() -> List[str]:
    """Return only Tier A (RVOL ≥ 2x) tickers - highest priority plays."""
    scored = run_all_passes()
    return [t["ticker"] for t in scored if t["rvol_tier"] == "A"]


def get_rvol_summary() -> List[Dict]:
    """
    Return RVOL summary for all scored tickers.
    Used by Discord alerts and monitoring.
    """
    scored = run_all_passes()
    return [
        {
            "ticker":    t["ticker"],
            "rvol":      t["rvol"],
            "tier":      t["rvol_tier"],
            "score":     t["score"],
            "refund_1d": t["refund_1d"],
            "price":     t["price"],
        }
        for t in scored
    ]


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    """High volume day variant - forces Pass 2 momentum movers to front."""
    scored = run_all_passes(force_refresh=True)
    # On high volume days, prioritize Tier A tickers from momentum pass
    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    rest   = [t for t in scored if t["rvol_tier"] != "A"]
    ordered = tier_a + rest
    return [t["ticker"] for t in ordered[:limit]]


def clear_screener_cache() -> None:
    """Clear screener cache. Call at market open and EOD."""
    global _screener_cache
    _screener_cache = {}
    print("[SCREENER] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache metadata for monitoring."""
    if not _screener_cache:
        return {"cached": False, "valid_scans": 0}
    ts    = _screener_cache.get("timestamp")
    data  = _screener_cache.get("scored", [])
    age_m = int((datetime.now() - ts).total_seconds() / 60) if ts else 0
    tier_a = len([t for t in data if t.get("rvol_tier") == "A"])
    tier_b = len([t for t in data if t.get("rvol_tier") == "B"])
    tier_c = len([t for t in data if t.get("rvol_tier") == "C"])
    return {
        "cached":       True,
        "timestamp":    ts.isoformat() if ts else None,
        "age_minutes":  age_m,
        "valid_scans":  len(data),
        "tier_a":       tier_a,
        "tier_b":       tier_b,
        "tier_c":       tier_c,
        "expires_in_m": max(0, _CACHE_TTL_MINUTES - age_m),
    }


# ─────────────────────────────────────────────
# CLI Test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\nWar Machine - Dynamic Screener Test\n")

    # Run full 3-pass screener
    scored = run_all_passes(force_refresh=True)

    print(f"\n📊 RVOL TIER BREAKDOWN:")
    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    tier_b = [t for t in scored if t["rvol_tier"] == "B"]
    tier_c = [t for t in scored if t["rvol_tier"] == "C"]
    print(f"  🔥 Tier A (RVOL≥{RVOL_TIER_A}x): {len(tier_a)} tickers → {[t['ticker'] for t in tier_a[:10]]}")
    print(f"  ⚡ Tier B (RVOL≥{RVOL_TIER_B}x): {len(tier_b)} tickers → {[t['ticker'] for t in tier_b[:10]]}")
    print(f"  📊 Tier C (RVOL≥{RVOL_TIER_C}x): {len(tier_c)} tickers → {[t['ticker'] for t in tier_c[:10]]}")

    print(f"\n🎯 TOP 10 WATCHLIST PICKS:")
    watchlist = get_dynamic_watchlist(max_tickers=10)
    for i, t in enumerate(watchlist, 1):
        print(f"  {i}. {t}")

    print(f"\n⚡ TIER A GAP CANDIDATES:")
    gaps = get_gap_candidates(min_gap_pct=1.5, limit=10)
    print(f"  {gaps}")

    print(f"\n📈 CACHE STATS:")
    stats = get_cache_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
