#!/usr/bin/env python3
"""
Dynamic Stock Screener - War Machine  v3.1
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
  0. ETF exclusion gate       - name keyword match + known-bad ticker blocklist
                                (SPY and QQQ are allowed for 0DTE trading)
  1. Dollar-volume gate       - price * avgvol_1d >= MIN_DOLLAR_VOL
  2. "In-play" gate           - must have momentum OR elevated RVOL
  3. RVOL tier scoring        - A/B/C tiers, Tier D discarded
  4. Conflicting-signal check - penalty if 5d trend opposes 1d move
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
import logging
logger = logging.getLogger(__name__)

# ── Project root on sys.path for direct CLI runs ────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils import config


# ─────────────────────────────────────────────
# Tuning Constants  —  adjust here, nowhere else
# ─────────────────────────────────────────────

# — Cache
_CACHE_TTL_MINUTES      = 30

# — RVOL tiers
RVOL_TIER_A             = 2.0
RVOL_TIER_B             = 1.5
RVOL_TIER_C             = 1.0

# — "In-play" gate
IN_PLAY_MIN_1D_PCT      = 1.0
IN_PLAY_MIN_5D_PCT      = 3.0
IN_PLAY_MIN_RVOL        = 1.3

# — Dollar-volume gate
MIN_DOLLAR_VOL          = 10_000_000
MIN_DOLLAR_VOL_SMALL_CAP= 20_000_000

# — Score base
SCORE_BASE              = {"A": 60, "B": 45, "C": 30}

# — Sector cap
MAX_PER_SECTOR          = 4
SECTOR_CAP_WINDOW       = 20

# — Conflicting-signal penalty
CONFLICT_THRESHOLD_5D   = 3.0
CONFLICT_THRESHOLD_1D   = 1.0
CONFLICT_PENALTY        = -5

# — Stale-ticker decay
STALE_RVOL_MAX          = 1.15
STALE_1D_MAX            = 0.5
STALE_5D_MAX            = 1.5
STALE_PENALTY           = -8

# — ETF exclusion  (v3.1)
# Gate 0: Drop most ETFs / funds / trusts / index products.
# Two-layer approach:
#   Layer 1 — name keyword match (catches iShares, SPDR, Vanguard, etc.)
#   Layer 2 — known-bad ticker blocklist (sector ETFs, commodity ETFs, etc.)
#
# EXCEPTION: SPY and QQQ are NOT blocked — they're the most liquid 0DTE products.
_ETF_NAME_KEYWORDS = {
    # Issuers
    "ishares", "spdr", "vanguard", "invesco", "proshares", "direxion",
    "wisdomtree", "vaneck", "first trust", "global x", "schwab etf",
    "fidelity etf", "jpmorgan etf", "dimensional etf", "pacer",
    "amplify", "harbor etf", "nuveen etf", "goldman sachs etf",
    # Product-type words
    "etf", " fund", "index fund", "trust", "etn", "etp",
    "commodity pool", "commodity fund",
}

# Tickers that slip through because EODHD doesn't flag them as ETFs,
# or their name doesn't contain the keywords above.
# Add to this list any time a new one shows up in the output.
#
# NOTE: SPY and QQQ are intentionally REMOVED from this list.
_ETF_TICKER_BLOCKLIST = {
    # SPDR Sector ETFs
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
    "XLRE", "XLU", "XLV", "XLY",
    # iShares broad-market
    "IVV", "IWM", "IWF", "IWD", "IJH", "IJR", "IEF",
    "EFA", "EEM", "AGG", "LQD", "TLT", "SHY", "HYG",
    # Invesco / others
    "QQQM", "RSP", "IGV", "IGE", "IBB",
    "GDX", "GDXJ", "SLV", "GLD", "IAU", "GLDM",
    "USO", "UNG", "PDBC", "PSLV",
    # Vanguard
    "VTI", "VOO", "VEA", "VWO", "VIG", "VYM", "VNQ",
    "VGT", "VHT", "VFH", "VIS", "VAW", "VCR", "VDC",
    "VPU", "VOX",
    # Broad index / leveraged (SPY and QQQ removed)
    "DIA", "MDY", "TQQQ", "SQQQ", "UPRO", "SPXU",
    "UVXY", "SVXY", "VXX",
    # International / thematic
    "IEMG", "ACWI", "MCHI", "EWJ", "EWZ", "EWG", "FXI",
    "USAR", "BMNR",
}


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────
_screener_cache: Dict = {}


# ─────────────────────────────────────────────
# Pass Filter Definitions
# ─────────────────────────────────────────────

PASS1_LIQUID_UNIVERSE = {
    "filters": [
        ["market_capitalization", ">", 5_000_000_000],
        ["avgvol_1d",             ">", 1_500_000],
        ["adjusted_close",        ">", 20],
        ["adjusted_close",        "<", 500],
        ["exchange",              "=", "us"],
    ],
    "sort":  "avgvol_1d.desc",
    "limit": 50,
    "label": "LIQUID UNIVERSE",
}

PASS2_MOMENTUM_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2_000_000_000],
        ["avgvol_1d",             ">", 500_000],
        ["adjusted_close",        ">", 10],
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           ">", 2.0],
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.desc",
    "limit": 30,
    "label": "MOMENTUM MOVERS",
}

PASS2B_DOWNSIDE_MOVERS = {
    "filters": [
        ["market_capitalization", ">", 2_000_000_000],
        ["avgvol_1d",             ">", 500_000],
        ["adjusted_close",        ">", 10],
        ["adjusted_close",        "<", 500],
        ["refund_1d_p",           "<", -2.0],
        ["exchange",              "=", "us"],
    ],
    "sort":  "refund_1d_p.asc",
    "limit": 30,
    "label": "DOWNSIDE MOVERS",
}

PASS3_BREAKOUT_TREND = {
    "filters": [
        ["market_capitalization", ">", 5_000_000_000],
        ["avgvol_1d",             ">", 1_000_000],
        ["adjusted_close",        ">", 20],
        ["exchange",              "=", "us"],
    ],
    "signal": "200d_new_hi",
    "sort":   "avgvol_1d.desc",
    "limit":  20,
    "label":  "BREAKOUT TREND",
}


# ─────────────────────────────────────────────
# Emergency Fallback
# ─────────────────────────────────────────────
FALLBACK_WATCHLIST = [
    "SPY", "QQQ",  # Always include for 0DTE
    "AAPL", "TSLA", "GOOGL", "AMZN", "MSFT", "META",
    "JPM", "BAC", "GS", "XOM", "CVX",
    "UNH", "JNJ", "HD", "WMT", "COST",
    "COIN", "PLTR", "UBER",
]


# ─────────────────────────────────────────────
# EODHD API Call
# ─────────────────────────────────────────────

def _run_pass(pass_config: Dict) -> List[Dict]:
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
        logger.info(f"[SCREENER] [{label}] → signal={signal or 'none'}  sort={sort_by}  limit={limit}")
        r = requests.get(url, timeout=15)
        logger.info(f"[SCREENER] [{label}] HTTP {r.status_code}")

        if r.status_code == 422:
            logger.info(f"[SCREENER] [{label}] ❌ 422 filter rejected: {r.text[:200]}")
            return []
        if r.status_code == 403:
            logger.info(f"[SCREENER] [{label}] ❌ 403 not in EODHD plan")
            return []
        if r.status_code == 401:
            logger.info(f"[SCREENER] [{label}] ❌ 401 invalid API key")
            return []

        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return []

        results = data.get("data", [])
        logger.info(f"[SCREENER] [{label}] ✅ {len(results)} raw results")
        return results

    except requests.exceptions.Timeout:
        logger.info(f"[SCREENER] [{label}] ⚠️  Timeout")
        return []
    except Exception as e:
        logger.info(f"[SCREENER] [{label}] ⚠️  Error: {e}")
        return []


# ─────────────────────────────────────────────
# Gate 0: ETF Exclusion  (v3.1)
# ─────────────────────────────────────────────

def _is_etf(ticker: str, name: str) -> bool:
    """
    v3.1: Returns True if this row should be excluded as an ETF/fund/trust.

    Layer 1 — ticker blocklist:
      Hard-coded set of known ETF tickers that EODHD either mislabels or
      whose name doesn't contain catchable keywords (e.g. sector-ETFs like
      XLI, XLP, commodity trusts like PSLV, broad index products).

    Layer 2 — name keyword scan:
      Catches any new ETF/fund/trust not in the blocklist by matching
      provider names (iShares, SPDR, Vanguard…) and product-type words
      (ETF, Fund, Trust, ETN…) in the full name string.

    Both checks are case-insensitive. Either one returning True = excluded.
    
    EXCEPTION: SPY and QQQ are NOT in the blocklist — they're allowed for 0DTE trading.
    """
    if ticker in _ETF_TICKER_BLOCKLIST:
        return True

    name_lower = name.lower()
    return any(kw in name_lower for kw in _ETF_NAME_KEYWORDS)


# ─────────────────────────────────────────────
# Post-Fetch Scoring & Gating
# ─────────────────────────────────────────────

def _parse_raw(raw: Dict) -> Optional[Dict]:
    """Parse raw EODHD row into clean floats. Returns None on bad data."""
    code = raw.get("code", "")
    if not code:
        return None
    return {
        "ticker":      code.split(".")[0].upper(),
        "name":        raw.get("name", "") or "",
        "sector":      raw.get("sector", "") or "Unknown",
        "avgvol_1d":   float(raw.get("avgvol_1d",             0) or 0),
        "avgvol_200d": float(raw.get("avgvol_200d",           0) or 0),
        "refund_1d":   float(raw.get("refund_1d_p",           0) or 0),
        "refund_5d":   float(raw.get("refund_5d_p",           0) or 0),
        "price":       float(raw.get("adjusted_close",        0) or 0),
        "mktcap":      float(raw.get("market_capitalization", 0) or 0),
    }


def _passes_dollar_vol_gate(p: Dict) -> bool:
    dollar_vol = p["price"] * p["avgvol_1d"]
    threshold  = MIN_DOLLAR_VOL_SMALL_CAP if p["mktcap"] < 5_000_000_000 else MIN_DOLLAR_VOL
    return dollar_vol >= threshold


def _passes_in_play_gate(p: Dict, rvol: float) -> bool:
    if abs(p["refund_1d"]) >= IN_PLAY_MIN_1D_PCT:
        return True
    if abs(p["refund_5d"]) >= IN_PLAY_MIN_5D_PCT:
        return True
    if rvol >= IN_PLAY_MIN_RVOL:
        return True
    return False


def _score_ticker(p: Dict, rvol: float, tier: str, source_pass: int) -> int:
    score = SCORE_BASE[tier]
    r1 = p["refund_1d"]
    r5 = p["refund_5d"]

    if r1 >= 3.0:        score += 15
    elif r1 >= 1.5:      score += 8
    elif r1 <= -3.0:     score += 10
    elif r1 <= -1.5:     score += 5
    elif r1 < 0:         score -= 5

    if abs(r5) >= 5.0:   score += 10
    elif abs(r5) >= 2.0: score += 5

    if r5 >= CONFLICT_THRESHOLD_5D and r1 <= -CONFLICT_THRESHOLD_1D:
        score += CONFLICT_PENALTY
    elif r5 <= -CONFLICT_THRESHOLD_5D and r1 >= CONFLICT_THRESHOLD_1D:
        score += CONFLICT_PENALTY

    if source_pass == 3:
        score += 10

    if p["mktcap"] < 10_000_000_000:
        score -= 5

    if (rvol <= STALE_RVOL_MAX
            and abs(r1) <= STALE_1D_MAX
            and abs(r5) <= STALE_5D_MAX):
        score += STALE_PENALTY

    return score


def _process_raw(raw: Dict, source_pass: int) -> Optional[Dict]:
    """
    Full pipeline for a single raw EODHD row:
      Gate 0: ETF exclusion (SPY/QQQ allowed)
      Gate 1: Dollar-volume
      Gate 2: RVOL tier (drop Tier D)
      Gate 3: In-play
      Score:  Composite score
    """
    p = _parse_raw(raw)
    if p is None:
        return None

    # Gate 0: ETF / fund / trust exclusion (SPY and QQQ pass through)
    if _is_etf(p["ticker"], p["name"]):
        return None

    # Gate 1: dollar volume
    if not _passes_dollar_vol_gate(p):
        return None

    # RVOL + tier
    rvol = round(p["avgvol_1d"] / p["avgvol_200d"], 2) if p["avgvol_200d"] > 0 else 0.0
    if rvol >= RVOL_TIER_A:        tier = "A"
    elif rvol >= RVOL_TIER_B:      tier = "B"
    elif rvol >= RVOL_TIER_C:      tier = "C"
    else:                          return None   # Tier D

    # Gate 3: in-play
    if not _passes_in_play_gate(p, rvol):
        return None

    score = _score_ticker(p, rvol, tier, source_pass)

    return {
        "ticker":       p["ticker"],
        "name":         p["name"],
        "sector":       p["sector"],
        "score":        score,
        "rvol":         rvol,
        "rvol_tier":    tier,
        "refund_1d":    round(p["refund_1d"], 2),
        "refund_5d":    round(p["refund_5d"], 2),
        "price":        round(p["price"], 2),
        "mktcap_b":     round(p["mktcap"] / 1e9, 1),
        "avgvol_1d":    int(p["avgvol_1d"]),
        "avgvol_200d":  int(p["avgvol_200d"]),
        "dollar_vol_m": round((p["price"] * p["avgvol_1d"]) / 1e6, 1),
        "source_pass":  source_pass,
    }


# ─────────────────────────────────────────────
# Sector Cap
# ─────────────────────────────────────────────

def _apply_sector_cap(scored: List[Dict]) -> List[Dict]:
    """
    Within the top SECTOR_CAP_WINDOW tickers, enforce MAX_PER_SECTOR per sector.
    Overflow tickers are pushed below the window, not removed entirely.
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

    capped = {s: c for s, c in sector_count.items() if c >= MAX_PER_SECTOR}
    if capped:
        logger.info(f"[SCREENER] Sector cap applied: {capped}")

    return within_cap + overflow


# ─────────────────────────────────────────────
# Main Screener
# ─────────────────────────────────────────────

def run_all_passes(force_refresh: bool = False) -> List[Dict]:
    """
    Run all passes, apply all gates, score, dedup, sector-cap.
    Returns list of scored ticker dicts sorted by score descending.
    Cached for _CACHE_TTL_MINUTES.
    """
    global _screener_cache

    if not force_refresh and _screener_cache:
        ts = _screener_cache.get("timestamp")
        if ts and (datetime.now() - ts) < timedelta(minutes=_CACHE_TTL_MINUTES):
            cached = _screener_cache.get("scored", [])
            age_m  = int((datetime.now() - ts).total_seconds() / 60)
            logger.info(f"[SCREENER] ✅ Cache hit: {len(cached)} tickers (age: {age_m}m)")
            return cached

    logger.info(f"\n{'='*65}")
    logger.info(f"[SCREENER] v3.1 — Dynamic Screener — {datetime.now().strftime('%H:%M:%S')}")
    logger.info(f"{'='*65}\n")

    seen: Dict[str, Dict] = {}
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

    _merge(_run_pass(PASS1_LIQUID_UNIVERSE),  pass_num=1)

    pass2_raw = _run_pass(PASS2_MOMENTUM_MOVERS)
    if pass2_raw:
        _merge(pass2_raw, pass_num=2)
    else:
        logger.info("[SCREENER] Pass 2 empty — activating downside movers (Pass 2b)")
        _merge(_run_pass(PASS2B_DOWNSIDE_MOVERS), pass_num=2)

    _merge(_run_pass(PASS3_BREAKOUT_TREND),   pass_num=3)

    if not any_pass_ok:
        logger.info("[SCREENER] ⚠️  All passes failed — FALLBACK_WATCHLIST")
        return [{
            "ticker": t, "name": "", "sector": "",
            "score": 20, "rvol": 1.0, "rvol_tier": "C",
            "refund_1d": 0.0, "refund_5d": 0.0, "price": 0.0,
            "mktcap_b": 0.0, "avgvol_1d": 0, "avgvol_200d": 0,
            "dollar_vol_m": 0.0, "source_pass": 0,
        } for t in FALLBACK_WATCHLIST]

    sorted_results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
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

    logger.info(f"\n{'='*90}")
    print(f"[SCREENER] v3.1  |  {len(scored)} tickers  |  "
          f"🔥 Tier A: {tc['A']}  ⚡ Tier B: {tc['B']}  📊 Tier C: {tc['C']}")
    print(f"\n{'#':<4} {'Ticker':<7} {'Score':<7} {'Tier':<6} {'RVOL':<7} "
          f"{'1d%':>7} {'5d%':>7} {'$Vol M':>8} {'Price':>8} {'MCap$B':>8}  Sector")
    logger.info("-" * 90)

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
    logger.info(f"{'='*90}\n")


# ─────────────────────────────────────────────
# Public Interface
# ─────────────────────────────────────────────

def get_dynamic_watchlist(
    include_core: bool = True,
    max_tickers: int = 50,
    force_refresh: bool = False,
) -> List[str]:
    scored  = run_all_passes(force_refresh=force_refresh)
    tickers = [t["ticker"] for t in scored[:max_tickers]]
    logger.info(f"[SCREENER] get_dynamic_watchlist → {len(tickers)} tickers")
    return tickers


def get_scored_tickers(
    max_tickers: int = 50,
    min_score: int = 0,
    force_refresh: bool = False,
) -> List[Dict]:
    """Full scored dicts — use this in watchlist_funnel.py for RVOL + dollar_vol metadata."""
    scored = run_all_passes(force_refresh=force_refresh)
    return [t for t in scored if t["score"] >= min_score][:max_tickers]


def get_gap_candidates(min_gap_pct: float = 1.5, limit: int = 30) -> List[str]:
    scored = run_all_passes()
    result = [t["ticker"] for t in scored if t["refund_1d"] >= min_gap_pct]
    logger.info(f"[SCREENER] get_gap_candidates(≥{min_gap_pct}%) → {len(result[:limit])} tickers")
    return result[:limit]


def get_tier_a_tickers() -> List[str]:
    return [t["ticker"] for t in run_all_passes() if t["rvol_tier"] == "A"]


def get_rvol_summary() -> List[Dict]:
    return [
        {"ticker":       t["ticker"],
         "rvol":         t["rvol"],
         "tier":         t["rvol_tier"],
         "score":        t["score"],
         "refund_1d":    t["refund_1d"],
         "price":        t["price"],
         "dollar_vol_m": t.get("dollar_vol_m", 0)}
        for t in run_all_passes()
    ]


def get_high_volume_day_watchlist(limit: int = 50) -> List[str]:
    scored = run_all_passes(force_refresh=True)
    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    rest   = [t for t in scored if t["rvol_tier"] != "A"]
    return [t["ticker"] for t in (tier_a + rest)[:limit]]


def clear_screener_cache() -> None:
    global _screener_cache
    _screener_cache = {}
    logger.info("[SCREENER] Cache cleared")


def get_cache_stats() -> Dict:
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


def add_etf_to_blocklist(ticker: str) -> None:
    """
    Runtime helper: add a ticker to the ETF blocklist without restarting.
    Call this from the CLI or Discord bot if a new ETF slips through.
    Example: add_etf_to_blocklist('XME')
    """
    _ETF_TICKER_BLOCKLIST.add(ticker.upper())
    clear_screener_cache()
    logger.info(f"[SCREENER] Added {ticker.upper()} to ETF blocklist — cache cleared")


# ─────────────────────────────────────────────
# CLI Test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("\n" + "="*65)
    logger.info("War Machine v3.1 — Dynamic Screener CLI Test")
    logger.info("="*65)

    scored = run_all_passes(force_refresh=True)

    tier_a = [t for t in scored if t["rvol_tier"] == "A"]
    tier_b = [t for t in scored if t["rvol_tier"] == "B"]
    tier_c = [t for t in scored if t["rvol_tier"] == "C"]

    logger.info(f"\n📊 RVOL Tier Breakdown:")
    logger.info(f"  🔥 Tier A (≥2x):   {len(tier_a):>3}  →  {[t['ticker'] for t in tier_a[:8]]}")
    logger.info(f"  ⚡ Tier B (≥1.5x): {len(tier_b):>3}  →  {[t['ticker'] for t in tier_b[:8]]}")
    logger.info(f"  📊 Tier C (≥1x):   {len(tier_c):>3}  →  {[t['ticker'] for t in tier_c[:8]]}")

    logger.info(f"\n🎯 Top 10 Watchlist (SPY/QQQ allowed, other ETFs excluded):")
    for i, t in enumerate(get_dynamic_watchlist(max_tickers=10), 1):
        logger.info(f"  {i:>2}. {t}")

    logger.info(f"\n⚡ Gap Candidates (≥1.5% yesterday):")
    logger.info(f"  {get_gap_candidates(min_gap_pct=1.5, limit=10)}")

    logger.info(f"\n🔥 Tier A Only:")
    logger.info(f"  {get_tier_a_tickers()}")

    logger.info(f"\n💵 Dollar-Vol Sample (top 5):")
    for t in scored[:5]:
        logger.info(f"  {t['ticker']:<6}  ${t['dollar_vol_m']:.0f}M  ({t['rvol_tier']})  {t['name'][:40]}")

    logger.info(f"\n💾 Cache Stats:")
    for k, v in get_cache_stats().items():
        logger.info(f"  {k}: {v}")
