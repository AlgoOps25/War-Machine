#!/usr/bin/env python3
"""
Dynamic Stock Screener - War Machine  v3
3-Pass strategy to find stocks most likely to make major moves at market open.

EODHD Screener fields used:
  market_capitalization  - options liquidity gate (hard filter + score penalty)
  avgvol_1d              - yesterday's volume    (hard filter + RVOL numerator)
  avgvol_200d            - 200d avg volume        (RVOL denominator)
  refund_1d_p            - yesterday's % move     (momentum score driver)
  refund_5d_p            - 5-day return           (trend score + stale-decay check)
  adjusted_close         - price                  (options premium band + dollar-vol)
  200d_new_hi (signal)   - breakout continuation  (Pass 3 bonus)

Ignored intentionally:
  200d_new_lo, bookvalue_neg, wallstreet_hi, wallstreet_lo

NOTE: All EODHD screener data is End-of-Day (previous close).
      Real-time gap detection happens in premarket_scanner.py via live quotes.

PASS STRATEGY:
  Pass 1 - Liquid Universe  : Top 50 by volume. Always returns something.
  Pass 2 - Momentum Movers  : 2%+ movers yesterday. Gap continuation candidates.
  Pass 2b - Downside Movers : Activated only when Pass 2 is empty (bearish market day).
  Pass 3 - Breakout Trend   : 200d_new_hi signal. Institutional trend continuations.

POST-FETCH FILTERS (applied in Python, not at API level):
  1. Dollar-volume gate       - price * avgvol_1d >= MIN_DOLLAR_VOL
  2. "In-play" gate           - must have momentum OR elevated RVOL
  3. RVOL tier scoring        - A/B/C tiers, Tier D discarded
  4. Conflicting-signal check - heavy penalty if 5d trend opposes 1d move
  5. Sector cap               - max MAX_PER_SECTOR tickers per sector in top 20
  6. Stale-ticker decay       - penalty if flat RVOL and flat recent returns
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

# ── Project root on sys.path for direct CLI runs ────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils import config


# ─────────────────────────────────────────────
# Tuning Constants  —  adjust here, nowhere else
# ─────────────────────────────────────────────

# — Cache
_CACHE_TTL_MINUTES  = 30

# — RVOL tiers
RVOL_TIER_A         = 2.0    # 🔥 HOT
RVOL_TIER_B         = 1.5    # ⚡ WARM
RVOL_TIER_C         = 1.0    # 📊 MILD
# Tier D = anything below RVOL_TIER_C → discarded

# — "In-play" gate  (NEW v3)
# A ticker passes if ANY ONE of these is true:
#   abs(refund_1d) >= IN_PLAY_MIN_1D_PCT
#   abs(refund_5d) >= IN_PLAY_MIN_5D_PCT
#   rvol            >= IN_PLAY_MIN_RVOL
# If none are true → ticker is dropped (stale, nothing going on).
IN_PLAY_MIN_1D_PCT  = 1.0    # 1%+ yesterday
IN_PLAY_MIN_5D_PCT  = 3.0    # 3%+ over the week
IN_PLAY_MIN_RVOL    = 1.3    # 1.3x volume minimum

# — Dollar-volume gate  (NEW v3)
# price * avgvol_1d must exceed this for options to be tradable
# $10M = typical minimum for 0DTE spreads to have acceptable fill
# If market_cap < $5B, tighten to MIN_DOLLAR_VOL_SMALL_CAP
MIN_DOLLAR_VOL          = 10_000_000   # $10M  (>$5B cap stocks)
MIN_DOLLAR_VOL_SMALL_CAP= 20_000_000   # $20M  (<$5B cap stocks, need more liquidity proof)

# — Score caps / penalties
SCORE_BASE = {"A": 60, "B": 45, "C": 30}

# — Sector cap in top 20 output  (NEW v3)
# Prevents 12 tech names and 1 of everything else
MAX_PER_SECTOR      = 4
SECTOR_CAP_WINDOW   = 20    # Only enforce cap within top N final list

# — Conflicting-signal threshold  (NEW v3)
# If 5d trend direction OPPOSES 1d move, score penalty applied
CONFLICT_THRESHOLD_5D  = 3.0   # 5d% >= this in one direction
CONFLICT_THRESHOLD_1D  = 1.0   # 1d% >= this in opposite direction
CONFLICT_PENALTY        = -5

# — Stale-ticker decay  (NEW v3)
# If RVOL is only barely above floor AND very small 1d/5d moves, apply extra penalty
STALE_RVOL_MAX      = 1.15   # Barely above average
STALE_1D_MAX        = 0.5    # Near-flat day
STALE_5D_MAX        = 1.5    # Near-flat week
STALE_PENALTY       = -8


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────
_screener_cache: Dict = {}


# ─────────────────────────────────────────────
# Pass Filter Definitions
# ─────────────────────────────────────────────

# PASS 1: Liquid Universe
# Purpose : Always-on baseline. Returns the most actively traded US stocks.
# No price-change filter here — that gate is enforced post-fetch by the
# "in-play" check so Pass 1 never comes back empty on a quiet day.
PASS1_LIQUID_UNIVERSE = {
    "filters": [
        ["market_capitalization", ">", 5_000_000_000],  # $5B+ (tight spreads)
        ["avgvol_1d",             ">", 1_500_000],       # 1.5M+ shares traded
        ["adjusted_close",        ">", 20],              # $20+ (meaningful premium)
        ["adjusted_close",        "<", 500],             # <$500 (affordable contracts)
        ["exchange",              "=", "us"],
    ],
    "sort":  "avgvol_1d.desc",
    "limit": 50,
    "label": "LIQUID UNIVERSE",
}

# PASS 2: Momentum Movers
# Purpose : Stocks that moved 2%+ yesterday. Prime gap-and-go candidates.
# Raised from 1.5% → 2.0% to reduce noise and keep the list fresh day-to-day.
PASS2_MOMENTUM_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2_000_000_000],  # $2B+ (includes mid-caps)
        ["avgvol_1d",             ">", 500_000],         # 500K+ minimum
        ["adjusted_close",        ">", 10],
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           ">", 2.0],             # ⬆ Raised from 1.5 → 2.0
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.desc",
    "limit": 30,
    "label": "MOMENTUM MOVERS",
}

# PASS 2b: Downside Movers  (bearish day fallback)
# Activated automatically when Pass 2 returns 0 results.
# Catches hard-down names for put continuation or bounce plays.
PASS2B_DOWNSIDE_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2_000_000_000],
        ["avgvol_1d",             ">", 500_000],
        ["adjusted_close",        ">", 10],
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           "<", -2.0],            # Dropped 2%+ yesterday
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.asc",   # Biggest drops first
    "limit": 30,
    "label": "DOWNSIDE MOVERS",
}

# PASS 3: Breakout Trend  (200-day new high signal)
# Purpose : Stocks in confirmed institutional uptrends breaking to new highs.
# Only fires on days when the 200d_new_hi signal population is non-zero.
PASS3_BREAKOUT_TREND = {
    "filters": [
        ["market_capitalization", ">", 5_000_000_000],  # Large-cap only
        ["avgvol_1d",             ">", 1_000_000],       # Liquid options chain
        ["adjusted_close",        ">", 20],
        ["exchange",              "=", "us"],
    ],
    "signal": "200d_new_hi",
    "sort":   "avgvol_1d.desc",
    "limit":  20,
    "label":  "BREAKOUT TREND",
}


# ─────────────────────────────────────────────
# Emergency Fallback  —  ONLY used when ALL 3 API passes fail
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
# EODHD API Call
# ─────────────────────────────────────────────

def _run_pass(pass_config: Dict) -> List[Dict]:
    """
    Execute one screener pass. Returns raw EODHD ticker dicts.
    All post-fetch logic (scoring, gating, dedup) is done separately.
    """
    filters = pass_config.get("filters", [])
    sort_by = pass_config.get("sort", "avgvol_1d.desc")
    limit   = pass_config.get("limit", 50)
    signal  = pass_config.get("signal", None)
    label   = pass_config.get("label", "PASS")

    url = (
        f"https://eodhd.com/api/screener"
        f"?api_token={config.EODHD_API_KEY}"
        f"&filters={json.dumps(filters, separators=(',', ':'))}"
        f"&limit={limit}"
        f"&sort={sort_by}"
        f"&fmt=json"
    )
    if signal:
        url += f"&signals={signal}"

    try:
        print(f"[SCREENER] [{label}] → signal={signal or 'none'}  sort={sort_by}  limit={limit}")
        r = requests.get(url, timeout=15)
        print(f"[SCREENER] [{label}] HTTP {r.status_code}")

        if r.status_code == 422:
            print(f"[SCREENER] [{label}] ❌ 422 filter rejected: {r.text[:200]}")
            return []
        if r.status_code == 403:
            print(f"[SCREENER] [{label}] ❌ 403 not in EODHD plan")
            return []
        if r.status_code == 401:
            print(f"[SCREENER] [{label}] ❌ 401 invalid API key")
            return []

        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return []

        results = data.get("data", [])
        print(f"[SCREENER] [{label}] ✅ {len(results)} raw results")
        return results

    except requests.exceptions.Timeout:
        print(f"[SCREENER] [{label}] ⚠️  Timeout")
        return []
    except Exception as e:
        print(f"[SCREENER] [{label}] ⚠️  Error: {e}")
        return []


# ─────────────────────────────────────────────
# Post-Fetch Scoring & Gating
# ─────────────────────────────────────────────

def _parse_raw(raw: Dict) -> Optional[Dict]:
    """
    Parse raw EODHD row into clean floats. Returns None on bad data.
    Centralises all the `or 0` / float-cast noise.
    """
    code = raw.get("code", "")
    if not code:
        return None

    ticker = code.split(".")[0].upper()

    return {
        "ticker":      ticker,
        "name":        raw.get("name", ""),
        "sector":      raw.get("sector", "") or "Unknown",
        "avgvol_1d":   float(raw.get("avgvol_1d",             0) or 0),
        "avgvol_200d": float(raw.get("avgvol_200d",           0) or 0),
        "refund_1d":   float(raw.get("refund_1d_p",           0) or 0),
        "refund_5d":   float(raw.get("refund_5d_p",           0) or 0),
        "price":       float(raw.get("adjusted_close",        0) or 0),
        "mktcap":      float(raw.get("market_capitalization", 0) or 0),
    }


def _passes_dollar_vol_gate(p: Dict) -> bool:
    """
    NEW v3: Dollar-volume gate.
    price * avgvol_1d must exceed minimum for options to be tradable.
    Smaller-cap stocks need a higher dollar-vol threshold to confirm liquidity.
    """
    dollar_vol = p["price"] * p["avgvol_1d"]
    threshold  = MIN_DOLLAR_VOL_SMALL_CAP if p["mktcap"] < 5_000_000_000 else MIN_DOLLAR_VOL
    if dollar_vol < threshold:
        return False
    return True


def _passes_in_play_gate(p: Dict, rvol: float) -> bool:
    """
    NEW v3: "In-play" gate.
    A ticker MUST satisfy at least one criterion to be considered live/active.
    This is the primary fix for same-old-tickers appearing on flat days.
    """
    if abs(p["refund_1d"]) >= IN_PLAY_MIN_1D_PCT:
        return True
    if abs(p["refund_5d"]) >= IN_PLAY_MIN_5D_PCT:
        return True
    if rvol >= IN_PLAY_MIN_RVOL:
        return True
    return False


def _score_ticker(p: Dict, rvol: float, tier: str, source_pass: int) -> int:
    """
    Calculate composite score for a ticker that has already passed all gates.

    Base score from RVOL tier:
      A (>=2x)   = 60
      B (>=1.5x) = 45
      C (>=1x)   = 30

    Momentum adjustments (refund_1d):
      +15  if  >= +3%
      +8   if  >= +1.5%   (or raised Pass 2 threshold)
      +10  if  <= -3%     (strong down = bearish momentum play)
      +5   if  <= -1.5%
      -5   if  < 0 but mild (noise)

    Weekly trend bonus (abs refund_5d):
      +10  if abs >= 5%
      +5   if abs >= 2%

    Conflicting-signal penalty  (NEW v3):
      -5 if 5d strongly goes one way but 1d reverses it (mean-revert noise)

    Breakout pass bonus (Pass 3):
      +10 for 200d_new_hi origin

    Market-cap penalty:
      -5 if market cap < $10B (thinner options chain)

    Stale-ticker decay penalty  (NEW v3):
      -8 if RVOL barely above 1x, 1d near-flat, and 5d near-flat
         (consistent dead money just showing up because of raw size)
    """
    score = SCORE_BASE[tier]

    r1 = p["refund_1d"]
    r5 = p["refund_5d"]

    # Momentum from 1d move
    if r1 >= 3.0:
        score += 15
    elif r1 >= 1.5:
        score += 8
    elif r1 <= -3.0:
        score += 10
    elif r1 <= -1.5:
        score += 5
    elif r1 < 0:
        score -= 5

    # Weekly trend bonus
    if abs(r5) >= 5.0:
        score += 10
    elif abs(r5) >= 2.0:
        score += 5

    # NEW v3: conflicting-signal penalty
    # 5d strongly up but yesterday was hard down (or vice-versa) = noisy mean-revert
    if r5 >= CONFLICT_THRESHOLD_5D and r1 <= -CONFLICT_THRESHOLD_1D:
        score += CONFLICT_PENALTY
    elif r5 <= -CONFLICT_THRESHOLD_5D and r1 >= CONFLICT_THRESHOLD_1D:
        score += CONFLICT_PENALTY

    # Breakout bonus
    if source_pass == 3:
        score += 10

    # Small-cap penalty
    if p["mktcap"] < 10_000_000_000:
        score -= 5

    # NEW v3: stale-ticker decay
    if (rvol <= STALE_RVOL_MAX
            and abs(r1) <= STALE_1D_MAX
            and abs(r5) <= STALE_5D_MAX):
        score += STALE_PENALTY

    return score


def _process_raw(raw: Dict, source_pass: int) -> Optional[Dict]:
    """
    Full pipeline for one raw EODHD row:
      1. Parse fields
      2. Dollar-volume gate
      3. RVOL + tier
      4. In-play gate
      5. Score
    Returns scored dict or None if dropped.
    """
    p = _parse_raw(raw)
    if p is None:
        return None

    # Gate 1: dollar volume
    if not _passes_dollar_vol_gate(p):
        return None

    # RVOL calculation
    rvol = round(p["avgvol_1d"] / p["avgvol_200d"], 2) if p["avgvol_200d"] > 0 else 0.0

    # Tier
    if rvol >= RVOL_TIER_A:
        tier = "A"
    elif rvol >= RVOL_TIER_B:
        tier = "B"
    elif rvol >= RVOL_TIER_C:
        tier = "C"
    else:
        return None   # Tier D — discard

    # Gate 2: in-play
    if not _passes_in_play_gate(p, rvol):
        return None

    score = _score_ticker(p, rvol, tier, source_pass)

    return {
        "ticker":      p["ticker"],
        "name":        p["name"],
        "sector":      p["sector"],
        "score":       score,
        "rvol":        rvol,
        "rvol_tier":   tier,
        "refund_1d":   round(p["refund_1d"], 2),
        "refund_5d":   round(p["refund_5d"], 2),
        "price":       round(p["price"], 2),
        "mktcap_b":    round(p["mktcap"] / 1e9, 1),
        "avgvol_1d":   int(p["avgvol_1d"]),
        "avgvol_200d": int(p["avgvol_200d"]),
        "dollar_vol_m":round((p["price"] * p["avgvol_1d"]) / 1e6, 1),
        "source_pass": source_pass,
    }


# ─────────────────────────────────────────────
# Sector Cap  (NEW v3)
# ─────────────────────────────────────────────

def _apply_sector_cap(scored: List[Dict]) -> List[Dict]:
    """
    NEW v3: Sector diversification cap.
    Within the top SECTOR_CAP_WINDOW tickers, no single sector can appear
    more than MAX_PER_SECTOR times. Extra tickers beyond the cap are pushed
    below the window (not removed — they still appear in the full list).

    This prevents the output from being dominated by 15 tech names on a
    tech-heavy day while energy / healthcare names with equal scores get buried.
    """
    if not scored:
        return scored

    sector_count: Dict[str, int] = defaultdict(int)
    within_cap:   List[Dict]     = []
    overflow:     List[Dict]     = []

    for t in scored:
        sector = t.get("sector", "Unknown")
        if len(within_cap) < SECTOR_CAP_WINDOW:
            if sector_count[sector] < MAX_PER_SECTOR:
                within_cap.append(t)
                sector_count[sector] += 1
            else:
                overflow.append(t)
        else:
            overflow.append(t)

    result = within_cap + overflow

    # Log if any sector was capped
    capped = {s: c for s, c in sector_count.items() if c >= MAX_PER_SECTOR}
    if capped:
        print(f"[SCREENER] Sector cap applied: {capped}")

    return result


# ─────────────────────────────────────────────
# Main Screener
# ─────────────────────────────────────────────

def run_all_passes(force_refresh: bool = False) -> List[Dict]:
    """
    Run all 3 passes, apply all post-fetch gates, score, dedup, sector-cap.
    Returns a list of scored ticker dicts sorted by score descending.
    Results are cached for _CACHE_TTL_MINUTES.
    """
    global _screener_cache

    # Cache check
    if not force_refresh and _screener_cache:
        ts = _screener_cache.get("timestamp")
        if ts and (datetime.now() - ts) < timedelta(minutes=_CACHE_TTL_MINUTES):
            cached = _screener_cache.get("scored", [])
            age_m  = int((datetime.now() - ts).total_seconds() / 60)
            print(f"[SCREENER] ✅ Cache hit: {len(cached)} tickers (age: {age_m}m)")
            return cached

    print(f"\n{'='*65}")
    print(f"[SCREENER] v3 — 3-Pass Dynamic Screener — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*65}\n")

    seen: Dict[str, Dict] = {}   # ticker → best-scored dict
    any_pass_ok = False

    def _merge(raw_list: List[Dict], pass_num: int) -> None:
        nonlocal any_pass_ok
        if raw_list:
            any_pass_ok = True
        for raw in raw_list:
            s = _process_raw(raw, source_pass=pass_num)
            if s is None:
                continue
            t = s["ticker"]
            if t not in seen or s["score"] > seen[t]["score"]:
                seen[t] = s

    # ── Pass 1: Liquid Universe ────────────────────────────
    _merge(_run_pass(PASS1_LIQUID_UNIVERSE), pass_num=1)

    # ── Pass 2: Momentum Movers (2%+ up)────────────────────
    pass2_raw = _run_pass(PASS2_MOMENTUM_MOVERS)
    if pass2_raw:
        _merge(pass2_raw, pass_num=2)
    else:
        # Bearish day — fall back to downside movers
        print("[SCREENER] Pass 2 empty — activating downside movers (Pass 2b)")
        _merge(_run_pass(PASS2B_DOWNSIDE_MOVERS), pass_num=2)

    # ── Pass 3: Breakout Trend (200d new high) ─────────────
    _merge(_run_pass(PASS3_BREAKOUT_TREND), pass_num=3)

    # ── All passes failed — API / network error ──────────────
    if not any_pass_ok:
        print("[SCREENER] ⚠️  All passes failed — FALLBACK_WATCHLIST (last resort)")
        return [{
            "ticker": t, "name": "", "sector": "",
            "score": 20, "rvol": 1.0, "rvol_tier": "C",
            "refund_1d": 0.0, "refund_5d": 0.0, "price": 0.0,
            "mktcap_b": 0.0, "avgvol_1d": 0, "avgvol_200d": 0,
            "dollar_vol_m": 0.0, "source_pass": 0,
        } for t in FALLBACK_WATCHLIST]

    # Sort by score
    sorted_results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    # NEW v3: apply sector cap before caching
    sorted_results = _apply_sector_cap(sorted_results)

    _screener_cache = {"timestamp": datetime.now(), "scored": sorted_results}
    _print_screener_summary(sorted_results)
    return sorted_results


# ─────────────────────────────────────────────
# Summary Printer
# ─────────────────────────────────────────────

def _print_screener_summary(scored: List[Dict], top_n: int = 15) -> None:
    if not scored:
        return

    tc = {"A": 0, "B": 0, "C": 0}
    for t in scored:
        tier = t.get("rvol_tier", "C")
        if tier in tc:
            tc[tier] += 1

    print(f"\n{'='*90}")
    print(f"[SCREENER] v3  |  {len(scored)} tickers scored  |  "
          f"🔥 Tier A: {tc['A']}  ⚡ Tier B: {tc['B']}  📊 Tier C: {tc['C']}")
    print(f"\n{'#':<4} {'Ticker':<7} {'Score':<7} {'Tier':<6} {'RVOL':<7} "
          f"{'1d%':>7} {'5d%':>7} {'$Vol M':>8} {'Price':>8} {'MCap$B':>8}  Sector")
    print("-" * 90)

    icons = {"A": "🔥", "B": "⚡", "C": "📊"}
    for i, t in enumerate(scored[:top_n], 1):
        icon = icons.get(t["rvol_tier"], "")
        print(
            f"{i:<4} {t['ticker']:<7} {t['score']:<7} "
            f"{icon}{t['rvol_tier']:<5} "
            f"{t['rvol']:<7.2f} "
            f"{t['refund_1d']:>+6.2f}%  "
            f"{t['refund_5d']:>+6.2f}%  "
            f"${t.get('dollar_vol_m', 0):>6.0f}M  "
            f"${t['price']:>7.2f} "
            f"${t['mktcap_b']:>7.1f}  "
            f"{t['sector'][:18]}"
        )
    print(f"{'='*90}\n")


# ─────────────────────────────────────────────
# Public Interface  (unchanged API — drop-in compatible with watchlist_funnel.py)
# ─────────────────────────────────────────────

def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50,
    force_refresh: bool = False,
) -> List[str]:
    """Ordered ticker list sorted by composite score."""
    scored  = run_all_passes(force_refresh=force_refresh)
    tickers = [t["ticker"] for t in scored[:max_tickers]]
    print(f"[SCREENER] get_dynamic_watchlist → {len(tickers)} tickers")
    return tickers


def get_scored_tickers(
    max_tickers: int = 50,
    min_score: int = 0,
    force_refresh: bool = False,
) -> List[Dict]:
    """Full scored dicts with RVOL, tier, dollar-vol, momentum — for watchlist_funnel."""
    scored = run_all_passes(force_refresh=force_refresh)
    return [t for t in scored if t["score"] >= min_score][:max_tickers]


def get_gap_candidates(min_gap_pct: float = 1.5, limit: int = 30) -> List[str]:
    """Tickers that moved >= min_gap_pct yesterday — gap-and-go candidates."""
    scored = run_all_passes()
    result = [t["ticker"] for t in scored if t["refund_1d"] >= min_gap_pct]
    print(f"[SCREENER] get_gap_candidates(≥{min_gap_pct}%) → {len(result[:limit])} tickers")
    return result[:limit]


def get_tier_a_tickers() -> List[str]:
    """Tier A (RVOL ≥ 2x) tickers only — highest priority plays."""
    return [t["ticker"] for t in run_all_passes() if t["rvol_tier"] == "A"]


def get_rvol_summary() -> List[Dict]:
    """RVOL summary for Discord alerts and monitoring."""
    return [
        {"ticker":    t["ticker"],
         "rvol":      t["rvol"],
         "tier":      t["rvol_tier"],
         "score":     t["score"],
         "refund_1d": t["refund_1d"],
         "price":     t["price"],
         "dollar_vol_m": t.get("dollar_vol_m", 0)}
        for t in run_all_passes()
    ]


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    """High-volume day: Tier A tickers pushed to front."""
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
    """Cache metadata for monitoring."""
    if not _screener_cache:
        return {"cached": False, "valid_scans": 0}
    ts   = _screener_cache.get("timestamp")
    data = _screener_cache.get("scored", [])
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
# CLI Test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*65)
    print("War Machine v3 — Dynamic Screener CLI Test")
    print("="*65)

    scored = run_all_passes(force_refresh=True)

    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    tier_b = [t for t in scored if t["rvol_tier"] == "B"]
    tier_c = [t for t in scored if t["rvol_tier"] == "C"]

    print(f"\n📊 RVOL Tier Breakdown:")
    print(f"  🔥 Tier A (≥2x):   {len(tier_a):>3}  →  {[t['ticker'] for t in tier_a[:8]]}")
    print(f"  ⚡ Tier B (≥1.5x): {len(tier_b):>3}  →  {[t['ticker'] for t in tier_b[:8]]}")
    print(f"  📊 Tier C (≥1x):   {len(tier_c):>3}  →  {[t['ticker'] for t in tier_c[:8]]}")

    print(f"\n🎯 Top 10 Watchlist (sector-capped):")
    for i, t in enumerate(get_dynamic_watchlist(max_tickers=10), 1):
        print(f"  {i:>2}. {t}")

    print(f"\n⚡ Gap Candidates (≥1.5% yesterday):")
    print(f"  {get_gap_candidates(min_gap_pct=1.5, limit=10)}")

    print(f"\n🔥 Tier A Only:")
    print(f"  {get_tier_a_tickers()}")

    print(f"\n💵 Dollar-Vol Sample (top 5):")
    for t in scored[:5]:
        print(f"  {t['ticker']:<6}  ${t['dollar_vol_m']:.0f}M  ({t['rvol_tier']})")

    print(f"\n💾 Cache Stats:")
    for k, v in get_cache_stats().items():
        print(f"  {k}: {v}")
