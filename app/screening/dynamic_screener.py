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

import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

# Ensure project root is on sys.path when running this file directly.
# e.g. python app/screening/dynamic_screener.py
# Has no effect when imported as a module from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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

# PASS 4 (Downside / bearish days only)
# Used when Pass 2 returns 0 upside movers - catches big down-day candidates.
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
# LAST RESORT only - used when ALL API passes fail (network down, API key issue).
# This is NOT a trading strategy list. It is an emergency fallback only.
# ─────────────────────────────────────────────
FALLBACK_WATCHLIST = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "TSLA", "GOOGL", "AMZN",
    "JPM", "BAC", "GS",
    "XOM", "CVX",
    "UNH", "JNJ",
    "HD", "WMT", "COST",
    "COIN", "PLTR", "UBER",
]


# ─────────────────────────────────────────────
# Core API Call
# ─────────────────────────────────────────────

def _run_pass(pass_config: Dict) -> List[Dict]:
    """
    Execute a single screener pass against the EODHD API.
    Returns raw ticker dicts with full metadata for RVOL scoring.

    Each returned dict contains:
      code, name, sector, industry, exchange,
      market_capitalization, adjusted_close,
      avgvol_1d, avgvol_200d,
      refund_1d_p, refund_5d_p,
      earnings_share, dividend_yield
    """
    filters = pass_config.get("filters", [])
    sort_by = pass_config.get("sort", "avgvol_1d.desc")
    limit   = pass_config.get("limit", 50)
    signal  = pass_config.get("signal", None)
    label   = pass_config.get("label", "PASS")

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
        print(f"[SCREENER] [{label}] Calling API... "
              f"signal={signal or 'none'} sort={sort_by} limit={limit}")
        response = requests.get(url, timeout=15)
        print(f"[SCREENER] [{label}] HTTP {response.status_code}")

        if response.status_code == 422:
            print(f"[SCREENER] [{label}] ❌ 422 – filter rejected: {response.text[:300]}")
            return []
        if response.status_code == 403:
            print(f"[SCREENER] [{label}] ❌ 403 – not in your EODHD plan")
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
        print(f"[SCREENER] [{label}] Unexpected error: {e}")
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
    """Return RVOL tier label."""
    if rvol >= RVOL_TIER_A:
        return "A"   # HOT  – 2x+ normal volume
    elif rvol >= RVOL_TIER_B:
        return "B"   # WARM – 1.5x normal volume
    elif rvol >= RVOL_TIER_C:
        return "C"   # MILD – 1x  normal volume
    else:
        return "D"   # COLD – discard


def _score_ticker(raw: Dict, source_pass: int) -> Optional[Dict]:
    """
    Build a scored ticker dict from a raw EODHD result row.
    Returns None if the ticker should be discarded (bad data or RVOL too low).

    Scoring:
      Base score (RVOL tier):        A=60  B=45  C=30  D=discard
      Momentum bonus (refund_1d_p):  +15 if >=3%   +8 if >=1.5%
      Down move bonus:               +10 if <=-3%  +5 if <=-1.5%  (bearish momentum)
      Mild down penalty:             -5  if < 0% but > -1.5%
      Weekly trend (refund_5d_p):    +10 if abs>=5%  +5 if abs>=2%
      Breakout pass bonus (pass 3):  +10
      Small cap penalty (<$10B):     -5
    """
    code = raw.get("code", "")
    if not code:
        return None

    ticker = code.split(".")[0].upper()

    avgvol_1d   = float(raw.get("avgvol_1d",             0) or 0)
    avgvol_200d = float(raw.get("avgvol_200d",           0) or 0)
    refund_1d   = float(raw.get("refund_1d_p",           0) or 0)
    refund_5d   = float(raw.get("refund_5d_p",           0) or 0)
    close       = float(raw.get("adjusted_close",        0) or 0)
    mktcap      = float(raw.get("market_capitalization", 0) or 0)

    rvol = _calculate_rvol(avgvol_1d, avgvol_200d)
    tier = _get_rvol_tier(rvol)

    if tier == "D":
        return None

    score = {"A": 60, "B": 45, "C": 30}[tier]

    # Momentum bonus
    if refund_1d >= 3.0:
        score += 15
    elif refund_1d >= 1.5:
        score += 8
    elif refund_1d <= -3.0:
        score += 10
    elif refund_1d <= -1.5:
        score += 5
    elif refund_1d < 0:
        score -= 5

    # Weekly trend bonus
    if abs(refund_5d) >= 5.0:
        score += 10
    elif abs(refund_5d) >= 2.0:
        score += 5

    # Breakout signal bonus
    if source_pass == 3:
        score += 10

    # Small cap penalty
    if mktcap < 10_000_000_000:
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
# Main Screener
# ─────────────────────────────────────────────

def run_all_passes(force_refresh: bool = False) -> List[Dict]:
    """
    Run all 3 passes, merge, RVOL-score, and cache results.
    Returns deduplicated list sorted by score descending.
    """
    global _screener_cache

    if not force_refresh and _screener_cache:
        cached_time = _screener_cache.get("timestamp")
        if cached_time and (datetime.now() - cached_time) < timedelta(minutes=_CACHE_TTL_MINUTES):
            cached = _screener_cache.get("scored", [])
            age_m  = int((datetime.now() - cached_time).total_seconds() / 60)
            print(f"[SCREENER] ✅ Cache hit: {len(cached)} tickers (age: {age_m}m)")
            return cached

    print(f"\n{'='*60}")
    print(f"[SCREENER] 3-Pass Dynamic Screener — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    seen: Dict[str, Dict] = {}
    any_pass_ok = False

    # Pass 1 — Liquid Universe (always runs, always returns data)
    for raw in _run_pass(PASS1_LIQUID_UNIVERSE):
        any_pass_ok = True
        s = _score_ticker(raw, source_pass=1)
        if s and (s["ticker"] not in seen or s["score"] > seen[s["ticker"]]["score"]):
            seen[s["ticker"]] = s

    # Pass 2 — Momentum Movers (yesterday's 1.5%+ movers)
    pass2 = _run_pass(PASS2_MOMENTUM_MOVERS)
    if pass2:
        any_pass_ok = True
        for raw in pass2:
            s = _score_ticker(raw, source_pass=2)
            if s and (s["ticker"] not in seen or s["score"] > seen[s["ticker"]]["score"]):
                seen[s["ticker"]] = s
    else:
        # If no upside movers, try downside movers (bearish market day)
        print("[SCREENER] Pass 2 empty — trying downside movers...")
        for raw in _run_pass(PASS4_DOWNSIDE_MOVERS):
            any_pass_ok = True
            s = _score_ticker(raw, source_pass=2)
            if s and (s["ticker"] not in seen or s["score"] > seen[s["ticker"]]["score"]):
                seen[s["ticker"]] = s

    # Pass 3 — Breakout Trend (200d new high signal)
    for raw in _run_pass(PASS3_BREAKOUT_TREND):
        any_pass_ok = True
        s = _score_ticker(raw, source_pass=3)
        if s and (s["ticker"] not in seen or s["score"] > seen[s["ticker"]]["score"]):
            seen[s["ticker"]] = s

    # All passes failed — network/API error — emergency fallback
    if not any_pass_ok:
        print("[SCREENER] ⚠️  All passes failed — using FALLBACK_WATCHLIST (last resort)")
        return [{
            "ticker": t, "score": 20, "rvol": 1.0, "rvol_tier": "C",
            "refund_1d": 0.0, "refund_5d": 0.0, "price": 0.0,
            "mktcap_b": 0.0, "avgvol_1d": 0, "avgvol_200d": 0,
            "sector": "", "source_pass": 0, "name": "",
        } for t in FALLBACK_WATCHLIST]

    sorted_results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    _screener_cache = {"timestamp": datetime.now(), "scored": sorted_results}
    _print_screener_summary(sorted_results)
    return sorted_results


def _print_screener_summary(scored: List[Dict], top_n: int = 15) -> None:
    """Print formatted screener results table."""
    if not scored:
        return

    tc = {"A": 0, "B": 0, "C": 0}
    for t in scored:
        tier = t.get("rvol_tier", "C")
        if tier in tc:
            tc[tier] += 1

    print(f"\n{'='*80}")
    print(f"[SCREENER] {len(scored)} tickers scored  |  "
          f"🔥 Tier A (RVOL≥2x): {tc['A']}  "
          f"⚡ Tier B (RVOL≥1.5x): {tc['B']}  "
          f"📊 Tier C (RVOL≥1x): {tc['C']}")
    print(f"\n{'#':<4} {'Ticker':<7} {'Score':<7} {'Tier':<6} "
          f"{'RVOL':<7} {'1d%':>7} {'5d%':>7} {'Price':>8} {'MCap$B':>8}  Sector")
    print("-" * 80)

    icons = {"A": "🔥", "B": "⚡", "C": "📊"}
    for i, t in enumerate(scored[:top_n], 1):
        icon = icons.get(t["rvol_tier"], "")
        print(
            f"{i:<4} {t['ticker']:<7} {t['score']:<7} "
            f"{icon}{t['rvol_tier']:<5} "
            f"{t['rvol']:<7.2f} "
            f"{t['refund_1d']:>+6.2f}%  "
            f"{t['refund_5d']:>+6.2f}%  "
            f"${t['price']:>7.2f} "
            f"${t['mktcap_b']:>7.1f}  "
            f"{t['sector'][:18]}"
        )
    print(f"{'='*80}\n")


# ─────────────────────────────────────────────
# Public Interface
# ─────────────────────────────────────────────

def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50,
    force_refresh: bool = False
) -> List[str]:
    """Return ordered ticker list sorted by RVOL score."""
    scored  = run_all_passes(force_refresh=force_refresh)
    tickers = [t["ticker"] for t in scored[:max_tickers]]
    print(f"[SCREENER] get_dynamic_watchlist → {len(tickers)} tickers")
    return tickers


def get_scored_tickers(
    max_tickers: int = 50,
    min_score: int = 0,
    force_refresh: bool = False
) -> List[Dict]:
    """Return full scored ticker dicts including RVOL, tier, momentum data."""
    scored = run_all_passes(force_refresh=force_refresh)
    return [t for t in scored if t["score"] >= min_score][:max_tickers]


def get_gap_candidates(min_gap_pct: float = 1.5, limit: int = 30) -> List[str]:
    """Return tickers that moved >= min_gap_pct yesterday (gap continuation candidates)."""
    scored = run_all_passes()
    result = [t["ticker"] for t in scored if t["refund_1d"] >= min_gap_pct]
    print(f"[SCREENER] get_gap_candidates(≥{min_gap_pct}%) → {len(result[:limit])} tickers")
    return result[:limit]


def get_tier_a_tickers() -> List[str]:
    """Return Tier A (RVOL ≥ 2x) tickers only — highest priority."""
    return [t["ticker"] for t in run_all_passes() if t["rvol_tier"] == "A"]


def get_rvol_summary() -> List[Dict]:
    """RVOL summary for all scored tickers — used by Discord alerts."""
    return [
        {"ticker": t["ticker"], "rvol": t["rvol"], "tier": t["rvol_tier"],
         "score": t["score"], "refund_1d": t["refund_1d"], "price": t["price"]}
        for t in run_all_passes()
    ]


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    """High-volume day variant — Tier A tickers pushed to front."""
    scored = run_all_passes(force_refresh=True)
    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    rest   = [t for t in scored if t["rvol_tier"] != "A"]
    return [t["ticker"] for t in (tier_a + rest)[:limit]]


def clear_screener_cache() -> None:
    """Clear cache. Call at market open and EOD."""
    global _screener_cache
    _screener_cache = {}
    print("[SCREENER] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache metadata."""
    if not _screener_cache:
        return {"cached": False, "valid_scans": 0}
    ts    = _screener_cache.get("timestamp")
    data  = _screener_cache.get("scored", [])
    age_m = int((datetime.now() - ts).total_seconds() / 60) if ts else 0
    return {
        "cached":       True,
        "timestamp":    ts.isoformat() if ts else None,
        "age_minutes":  age_m,
        "valid_scans":  len(data),
        "tier_a":       sum(1 for t in data if t.get("rvol_tier") == "A"),
        "tier_b":       sum(1 for t in data if t.get("rvol_tier") == "B"),
        "tier_c":       sum(1 for t in data if t.get("rvol_tier") == "C"),
        "expires_in_m": max(0, _CACHE_TTL_MINUTES - age_m),
    }


# ─────────────────────────────────────────────
# CLI Test Runner
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("War Machine — Dynamic Screener CLI Test")
    print("="*60)

    scored = run_all_passes(force_refresh=True)

    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    tier_b = [t for t in scored if t["rvol_tier"] == "B"]
    tier_c = [t for t in scored if t["rvol_tier"] == "C"]

    print(f"\n📊 RVOL Tier Breakdown:")
    print(f"  🔥 Tier A (≥2x):   {len(tier_a):>3} tickers  →  {[t['ticker'] for t in tier_a[:8]]}")
    print(f"  ⚡ Tier B (≥1.5x): {len(tier_b):>3} tickers  →  {[t['ticker'] for t in tier_b[:8]]}")
    print(f"  📊 Tier C (≥1x):   {len(tier_c):>3} tickers  →  {[t['ticker'] for t in tier_c[:8]]}")

    print(f"\n🎯 Top 10 Watchlist:")
    for i, t in enumerate(get_dynamic_watchlist(max_tickers=10), 1):
        print(f"  {i:>2}. {t}")

    print(f"\n⚡ Gap Candidates (≥1.5% yesterday):")
    print(f"  {get_gap_candidates(min_gap_pct=1.5, limit=10)}")

    print(f"\n🔥 Tier A Only (highest priority):")
    print(f"  {get_tier_a_tickers()}")

    print(f"\n💾 Cache Stats:")
    for k, v in get_cache_stats().items():
        print(f"  {k}: {v}")
