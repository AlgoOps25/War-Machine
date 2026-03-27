#!/usr/bin/env python3
"""
Adaptive Watchlist Funnel
Orchestrates dynamic watchlist narrowing from pre-market through market open.

Timeline:
  8:00-9:15 AM: Wide scan (Top 50) - collect gap movers and volume leaders
  9:15-9:25 AM: Narrow to Top 15 - score momentum quality and technical setup
  9:25-9:30 AM: Final Top 6  - highest probability plays for opening bell
  9:30 AM+:     LOCKED - watchlist frozen, no re-scoring until next session

Integration:
  - Uses premarket_scanner.py (UNIFIED) for professional 3-tier scoring
  - Uses volume_analyzer.py for real-time volume tracking
  - Feeds scanner.py with optimized watchlist based on time of day

NEW in v3.1:
  - Switched from get_dynamic_watchlist() to get_scored_tickers()
  - Now receives full metadata: rvol, rvol_tier, dollar_vol_m, sector
  - Can apply downstream filters on dollar-vol, RVOL tier, sector diversity

NEW in v3.2:
  - Fixed live session max_tickers cap (10 -> 20) to allow more discovery
  - Reduced live session min_score (55 -> 25) to match actual usage
  - Added dynamic expansion when insufficient tickers pass scoring

FIX v3.3 (PostgreSQL + Ellipsis):
  - Fixed ellipsis iteration bug (line 162, 210, 235, 263)
  - Replaced ... with proper function calls to get_top_n_movers()
  - Now safely handles empty/invalid watchlist data

PHASE 1.17 (MAR 10, 2026) - DTE filter removed:
  - Removed options_dte_filter integration from all funnel stages
  - DTE is a CONTRACT SELECTION concern, not a trade qualification gate

PHASE 1.18 (MAR 10, 2026) - Watchlist lock at market open:
  - _build_live_watchlist() now freezes the watchlist on its first run
  - Subsequent funnel ticks in live session return the locked list immediately
  - run_momentum_screener() is NOT called again after 9:30 ET
  - ScannerCache TTL extended to EOD after first live build (lock_until_eod)
  - Eliminates the 3-minute re-score / PREMARKET log flood during market hours

PHASE 1.19 (MAR 12, 2026) - Relative strength/weakness outlier boost:
  - _apply_relative_outlier_boost() added (Nitro Trades alignment)
  - Groups scored tickers by sector; within each group, the ticker moving
    OPPOSITE to its sector peers receives a +20 score boost and is flagged
    as a relative outlier.
  - Safe: purely additive score adjustment, no tickers removed, no new deps
  - Only fires when 2+ tickers share a sector; solo tickers unaffected

FIX v3.4 (MAR 12, 2026) - Final stage empty watchlist fix:
  - Lowered final stage min_score from 65 -> 50 (matches narrow stage)
  - Lowered final stage volume filter from 50,000 -> 10,000 (pre-open volume is thin)
  - Added fallback: if filtered_tickers still empty after volume filter, use all scored

FIX v3.5 (MAR 12, 2026) - Issue #3 + #4:
  - Issue #3: Raised live session min_score 25 -> 40
  - Issue #4: Symmetric volume signal adjustments in _build_narrow_scan() (+/-10)

PHASE 1.27 (MAR 14, 2026) - Market calendar guard:
  - build_watchlist() returns [] immediately on weekends and US holidays.

FIX v3.6 (MAR 14, 2026) - Force ticker uppercase at all funnel output points:
  - _normalise() applied at build_watchlist() exit point.

PHASE 1.29 (MAR 16, 2026) - Discord watchlist channel:
  - build_watchlist() calls send_premarket_watchlist() after every stage build.

TUNE v3.7 (MAR 16, 2026) - Stage threshold tuning + catalyst bypass:
  - wide.min_score:      35  -> 30  (catch catalyst plays with low RVOL)
  - narrow.max_tickers:  10  -> 15  (keep more candidates pre-open)
  - final.max_tickers:   3   -> 6   (options bench; professionals want 5-7 setups)
  - final volume filter: 10,000 -> 5,000  (pre-open volume is always thin)
  - live.max_tickers:    20  -> 12  (focused, less noise post-lock)
  - _apply_catalyst_bypass() added: tickers with catalyst_score > 0 skip the
    min_score gate at wide and narrow stages unconditionally. Earnings / mergers /
    FDA events are highest-probability options setups regardless of RVOL score.

FIX v3.8 (MAR 17, 2026) - WS coverage filter before lock:
  - _build_live_watchlist() now drops tickers with zero session bars before
    the watchlist is locked. Tickers subscribed to the EODHD WebSocket but
    receiving no data (e.g. CFLT) were firing ⚠️ No session bars every scan
    cycle for the entire session. The filter runs once at lock time (9:30 ET)
    so there is zero overhead during the live session.
  - Falls back to the full unfiltered list only if every ticker fails the
    check (safety net — should never happen in practice).

PHASE 1.34 (MAR 19, 2026) - Daily funnel reset:
  - reset_funnel() added: sets _funnel_instance = None so the EOD block in
    scanner.py can clear the prior session's locked watchlist.
  - Without this, the Railway process retains the WatchlistFunnel singleton
    across session boundaries, causing yesterday's locked watchlist to be
    returned all day on the following session.

FIX v3.9 (MAR 26, 2026) - Prevent empty watchlist lock on mid-session redeploy:
  - _filter_ws_covered(): if ALL tickers have zero session bars (WS not
    connected yet / intraday backfill not complete at startup), skip the
    filter entirely and return the full unfiltered list. Previously the
    safety-net fallback was unreachable because the covered list was empty
    AND watchlist was returned — but _build_live_watchlist() then received
    the full list, scored 0 tickers, and locked []. Now the guard fires
    early (before scoring) so startup redeployments during market hours
    never produce an empty locked watchlist.
  - _build_live_watchlist(): if the watchlist is empty after all
    scoring/filtering, do NOT commit the lock (_locked_at cleared). The
    next scanner tick retries the full live build instead of perpetually
    returning an empty locked list for the rest of the session.

FIX v4.0 (MAR 26, 2026) - Phase 1.30 premarket gate blocks mid-session redeploy:
  - ROOT CAUSE: premarket_scanner.scan_ticker() returns None for every ticker
    when called outside the 04:00-09:30 ET window (Phase 1.30 gate). On a
    cold mid-session container the premarket scanner cache is empty, so
    run_momentum_screener() → scan_watchlist() → scan_ticker() returns None
    for ALL candidates → scored_tickers=[] → watchlist=[] → v3.9 defers lock
    → scanner retry loop exhausts 3 attempts → emergency fallback fires.
    The 38 screener tickers visible in logs come from dynamic_screener
    (unaffected by the gate) but never reach scoring.
  - FIX: In _build_live_watchlist(), when run_momentum_screener() returns
    empty (or fewer than MIN_SCORED_THRESHOLD tickers) AND we are outside
    the premarket window, fall back to the raw dynamic_screener results
    already in screener_results. These dicts have score/rvol/price/sector
    fields computed by dynamic_screener._score_ticker() and are sufficient
    to produce a valid locked watchlist without any additional API calls.
  - _map_screener_result_to_scored() added: converts a dynamic_screener dict
    to the subset of fields expected downstream by get_top_n_movers() and
    _apply_relative_outlier_boost().
  - MIN_SCORED_THRESHOLD = 3: if fewer than 3 tickers survive momentum
    scoring, treat as effectively empty and trigger the fallback.

FIX v4.1 (MAR 26, 2026) - Skip expansion block after v4.0 fallback to prevent hang:
  - ROOT CAUSE: After the v4.0 fallback fires and maps 38 dynamic_screener
    results into scored_tickers, the expansion block ("if len < 10") runs
    immediately because the count check fires before min_score is applied.
    The expansion calls get_scored_tickers(force_refresh=True) which runs
    all 4 EODHD API passes (up to 60s of blocking HTTP on the main thread),
    causing the container to hang with no further log output visible in Railway.
  - FIX: Added _used_fallback flag. When the v4.0 fallback fires, set
    _used_fallback=True and skip the expansion block entirely. The fallback
    already provides a full screener-quality set — no expansion is needed.
  - SECONDARY: Changed expansion block force_refresh=True -> force_refresh=False.
    Expansion should never re-run live API passes since dynamic_screener cache
    was populated moments earlier in the same function call.

MAR 27, 2026 — Logging cleanup:
  - All print() calls replaced with logger.info() / logger.debug().
    Affected: build_watchlist() (market closed), _filter_ws_covered() (drop notice),
    _apply_catalyst_bypass() (per-ticker bypass), _apply_relative_outlier_boost()
    (per-ticker boost → debug), _build_live_watchlist() (LOCKED confirmation).
    No logic changes.
"""
import sys
from pathlib import Path
from datetime import datetime, time
from typing import List, Dict, Optional
import logging
logger = logging.getLogger(__name__)

# Add project root to path for CLI runs
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.screening import volume_analyzer
from app.screening import dynamic_screener
from app.screening.market_calendar import is_active_session, is_market_day, next_market_open
from utils import config

from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

# FIX v4.0: if momentum screener returns fewer than this many tickers,
# treat as effectively empty and trigger the dynamic_screener fallback.
MIN_SCORED_THRESHOLD = 3

def _get_momentum_screener():
    """Lazy import to avoid circular dependency."""
    from app.screening import premarket_scanner
    return premarket_scanner


def _get_discord_helpers():
    """Lazy import to avoid circular dependency."""
    from app.notifications import discord_helpers
    return discord_helpers


def _normalise(watchlist: List[str]) -> List[str]:
    """Force all ticker symbols to uppercase. Single canonical normalisation point."""
    return [t.upper() for t in watchlist if t]


# ════════════════════════════════════════════════════════════════════════════════
# FIX v4.0: DYNAMIC_SCREENER RESULT MAPPER
# Converts a dynamic_screener dict to the minimal scored-ticker shape expected
# by get_top_n_movers() and _apply_relative_outlier_boost().
# ════════════════════════════════════════════════════════════════════════════════

def _map_screener_result_to_scored(t: Dict) -> Dict:
    """
    FIX v4.0: Map a dynamic_screener result dict to a premarket_scanner-style
    scored ticker dict.

    dynamic_screener fields used:
      ticker, score, rvol, rvol_tier, price, avgvol_1d, sector,
      refund_1d, refund_5d, dollar_vol_m, mktcap_b

    The composite_score field is set to dynamic_screener's score so that
    get_top_n_movers() (which sorts on composite_score) works correctly.
    gap_data is populated with refund_1d so that _apply_relative_outlier_boost()
    can compute the sector outlier delta.
    """
    return {
        'ticker':           t['ticker'],
        'composite_score':  float(t.get('score', 50)),
        'rvol':             float(t.get('rvol', 1.0)),
        'rvol_tier':        t.get('rvol_tier', 'C'),
        'price':            float(t.get('price', 0)),
        'volume':           int(t.get('avgvol_1d', 0)),
        'volume_score':     float(t.get('score', 50)),
        'gap_score':        0.0,
        'catalyst_score':   0.0,
        'sector_bonus':     0.0,
        'dollar_volume':    float(t.get('dollar_vol_m', 0)) * 1_000_000,
        'atr':              0.0,
        'market_cap':       float(t.get('mktcap_b', 0)) * 1_000_000_000,
        'float':            0,
        'avg_daily_volume': int(t.get('avgvol_1d', 0)),
        'gap_data':         {'size_pct': float(t.get('refund_1d', 0))},
        'catalyst_data':    None,
        'sector_data':      {'sector': t.get('sector', 'Unknown'), 'is_hot': False},
        'timestamp':        datetime.now(),
    }


# ════════════════════════════════════════════════════════════════════════════════
# FIX v3.8: WS COVERAGE FILTER
# Drop tickers that have zero session bars at lock time. These are tickers
# subscribed to EODHD WebSocket but for which EODHD sends no data.
#
# FIX v3.9: Skip filter entirely when NO tickers have bars yet.
# On a mid-session redeploy the WS hasn't connected and intraday backfill
# hasn't run — every ticker has 0 bars. The old code hit the safety-net
# fallback correctly, but _build_live_watchlist() still scored 0 tickers
# and locked []. Now we skip the filter up-front so the full candidate
# list reaches scoring.
# ════════════════════════════════════════════════════════════════════════════════

def _filter_ws_covered(watchlist: List[str]) -> List[str]:
    """
    FIX v3.8: Remove tickers with zero today session bars before lock.
    FIX v3.9: Skip filter entirely if backfill/WS not ready (all zeros).

    Tickers can pass scoring but have no WS coverage from EODHD (e.g. CFLT).
    Locking them causes ⚠️ No session bars every scan cycle all session.
    This check runs once at 9:30 ET — zero runtime cost during live session.

    Falls back to the full list if every ticker fails (safety net).
    """
    try:
        from app.data.data_manager import data_manager
        covered = []
        dropped = []
        for ticker in watchlist:
            bars = data_manager.get_today_session_bars(ticker)
            if bars:
                covered.append(ticker)
            else:
                dropped.append(ticker)

        # FIX v3.9: if nobody has bars, WS/backfill isn't ready yet —
        # skip the filter so the full list reaches scoring/lock.
        if not covered:
            logger.info(
                "[FUNNEL] ⚠️  WS coverage filter: 0/%d tickers have session bars "
                "— backfill likely still running, skipping filter (safety net)",
                len(watchlist),
            )
            return watchlist

        if dropped:
            logger.info(
                "[FUNNEL] 🚫 WS coverage filter dropped %d ticker(s) with no session bars: %s",
                len(dropped), dropped,
            )

        logger.info(
            "[FUNNEL] ✅ WS coverage filter: %d/%d tickers verified",
            len(covered), len(watchlist),
        )
        return covered

    except Exception as e:
        logger.info(f"[FUNNEL] ⚠️  WS coverage filter error (non-blocking): {e}")
        return watchlist


# ════════════════════════════════════════════════════════════════════════════════
# TUNE v3.7: CATALYST BYPASS
# Tickers with a real catalyst (earnings, merger, FDA) skip the min_score gate
# at wide and narrow stages.  Catalyst quality > pre-market RVOL score for options.
# ════════════════════════════════════════════════════════════════════════════════

def _apply_catalyst_bypass(
    scored_tickers: List[Dict],
    all_candidates: List[Dict],
    stage: str,
    min_score: float,
) -> List[Dict]:
    """
    TUNE v3.7: Catalyst bypass gate.

    For wide and narrow stages only: any ticker in all_candidates whose
    catalyst_score > 0 is injected into scored_tickers even if it failed the
    min_score filter.  This covers earnings, mergers, FDA events, and any
    other event-driven catalysts that the momentum screener may underweight
    because pre-market RVOL hasn't built yet.

    Args:
        scored_tickers : tickers that already passed min_score (from screener)
        all_candidates : all scored tickers BEFORE the min_score gate was applied
        stage          : current funnel stage string
        min_score      : the gate threshold that was applied

    Returns:
        merged list with catalyst bypasses appended (deduplicated, order preserved)
    """
    if stage not in ("wide", "narrow"):
        return scored_tickers

    passed_tickers = {t["ticker"] for t in scored_tickers}
    bypassed = []

    for t in all_candidates:
        ticker = t.get("ticker", "")
        catalyst_score = (
            t.get("catalyst_score", 0)
            or t.get("catalyst", {}).get("score", 0)
            or 0
        )
        if catalyst_score > 0 and ticker not in passed_tickers:
            t["catalyst_bypass"] = True
            bypassed.append(t)
            passed_tickers.add(ticker)
            logger.info(
                "[FUNNEL] ⚡ CATALYST BYPASS: %s catalyst_score=%s "
                "(score=%.1f < min=%s) — added to %s watchlist unconditionally",
                ticker, catalyst_score, t.get('composite_score', 0), min_score, stage,
            )

    if not bypassed:
        return scored_tickers

    logger.info(f"[FUNNEL] ✅ Catalyst bypass injected {len(bypassed)} ticker(s) into {stage} stage")
    return scored_tickers + bypassed


# ════════════════════════════════════════════════════════════════════════════════
# PHASE 1.19: RELATIVE STRENGTH/WEAKNESS OUTLIER BOOST
# ════════════════════════════════════════════════════════════════════════════════

def _apply_relative_outlier_boost(scored_tickers: List[Dict]) -> List[Dict]:
    """
    Boost tickers that are relative outliers within their sector group.
    (Nitro Trades core morning filter)
    """
    if not scored_tickers:
        return scored_tickers

    sector_groups: Dict[str, List[Dict]] = {}
    for t in scored_tickers:
        sector_data = t.get('sector_data') or {}
        sector = sector_data.get('sector', 'unknown') or 'unknown'
        sector_groups.setdefault(sector, []).append(t)

    outlier_count = 0

    for sector, group in sector_groups.items():
        if len(group) < 2:
            continue

        gap_values = []
        for t in group:
            gd = t.get('gap_data') or {}
            gap_pct = gd.get('size_pct', 0.0) or 0.0
            gap_values.append(gap_pct)

        group_avg_gap = sum(gap_values) / len(gap_values)

        if abs(group_avg_gap) < 0.1:
            continue

        for t, gap_pct in zip(group, gap_values):
            is_outlier = (
                (group_avg_gap > 0 and gap_pct < -0.1) or
                (group_avg_gap < 0 and gap_pct > 0.1)
            )
            if is_outlier:
                t['composite_score'] += 20
                t['relative_outlier'] = True
                t['outlier_sector'] = sector
                t['outlier_group_avg_gap'] = round(group_avg_gap, 2)
                outlier_count += 1
                logger.debug(
                    "[FUNNEL] 🎯 OUTLIER BOOST: %s gap=%+.2f%% vs sector '%s' avg=%+.2f%% "
                    "→ +20 score (new=%.1f)",
                    t['ticker'], gap_pct, sector, group_avg_gap, t['composite_score'],
                )
            else:
                t['relative_outlier'] = False

    if outlier_count == 0:
        logger.info("[FUNNEL] ℹ️  No relative outliers detected in sector groups")
    else:
        logger.info(f"[FUNNEL] ✅ Relative outlier boost applied to {outlier_count} ticker(s)")

    return scored_tickers


class WatchlistFunnel:
    """Manages adaptive watchlist narrowing throughout pre-market and market hours."""

    def __init__(self):
        self.current_watchlist: List[str] = []
        self.scored_tickers: List[Dict] = []
        self.volume_analyzer = volume_analyzer.VolumeAnalyzer()

        self.current_stage = "wide"
        self.last_update_time: Optional[datetime] = None

        # PHASE 1.18: watchlist lock
        self._locked_watchlist: Optional[List[str]] = None
        self._locked_at: Optional[datetime] = None

        # TUNE v3.7: updated thresholds
        self.stages = {
            "wide": {
                "time_start":  time(8, 0),
                "time_end":    time(9, 15),
                "max_tickers": 50,
                "min_score":   30.0,   # v3.7: was 35 — catch catalyst plays with low RVOL
                "description": "Wide scan - Gap movers & volume leaders"
            },
            "narrow": {
                "time_start":  time(9, 15),
                "time_end":    time(9, 25),
                "max_tickers": 15,     # v3.7: was 10 — keep more candidates pre-open
                "min_score":   50.0,
                "description": "Top 15 - Momentum quality focus"
            },
            "final": {
                "time_start":  time(9, 25),
                "time_end":    time(9, 30),
                "max_tickers": 6,      # v3.7: was 3 — options bench (5-7 setups)
                "min_score":   50.0,
                "description": "Top 6 - Highest probability setups"
            },
            "live": {
                "time_start":  time(9, 30),
                "time_end":    time(16, 0),
                "max_tickers": 12,     # v3.7: was 20 — focused post-lock
                "min_score":   40.0,
                "description": "Live session - Active movers"
            }
        }

    def get_current_stage(self) -> str:
        now = datetime.now(tz=ET).time()
        if now < self.stages["wide"]["time_end"]:
            return "wide"
        elif now < self.stages["narrow"]["time_end"]:
            return "narrow"
        elif now < self.stages["final"]["time_end"]:
            return "final"
        else:
            return "live"

    def should_update(self, force: bool = False) -> bool:
        if self._locked_watchlist is not None and self.get_current_stage() == "live":
            return False
        if force:
            return True
        current_stage = self.get_current_stage()
        if current_stage != self.current_stage:
            return True
        if self.last_update_time is None:
            return True
        elapsed_minutes = (datetime.now(tz=ET) - self.last_update_time).total_seconds() / 60
        intervals = {"wide": 5, "narrow": 2, "final": 1, "live": 3}
        return elapsed_minutes >= intervals.get(current_stage, 5)

    def build_watchlist(self, force_refresh: bool = False) -> List[str]:
        """Build watchlist based on current stage and market conditions."""

        now_et = datetime.now(tz=ET)
        if not is_active_session(now_et):
            nxt = next_market_open(now_et)
            logger.info(
                "[FUNNEL] Market closed (weekend/holiday) — "
                "no scan. Next open: %s",
                nxt.strftime('%a %b %d %I:%M %p ET'),
            )
            return []

        if self._locked_watchlist is not None and self.get_current_stage() == "live" and not force_refresh:
            logger.info(
                "[FUNNEL] Using locked watchlist (%d tickers, locked at %s)",
                len(self._locked_watchlist),
                self._locked_at.strftime('%H:%M:%S') if self._locked_at else '?',
            )
            return self._locked_watchlist

        if not self.should_update(force_refresh):
            logger.info(f"[FUNNEL] Using cached watchlist ({len(self.current_watchlist)} tickers)")
            return self.current_watchlist

        new_stage          = self.get_current_stage()
        self.current_stage = new_stage
        stage_config       = self.stages[self.current_stage]

        logger.info(f"\n{'='*80}")
        logger.info(f"WATCHLIST FUNNEL - {datetime.now(tz=ET).strftime('%H:%M:%S')}")
        logger.info(f"Stage: {self.current_stage.upper()} - {stage_config['description']}")
        logger.info(f"{'='*80}\n")

        if self.current_stage == "wide":
            watchlist = self._build_wide_scan()
        elif self.current_stage == "narrow":
            watchlist = self._build_narrow_scan()
        elif self.current_stage == "final":
            watchlist = self._build_final_selection()
        else:
            watchlist = self._build_live_watchlist()

        watchlist = _normalise(watchlist)

        self.current_watchlist = watchlist
        self.last_update_time  = datetime.now(tz=ET)

        # persist locked list after normalise (PHASE 1.18)
        self._finalise_lock(watchlist)

        for ticker in watchlist:
            if ticker not in self.volume_analyzer.tracked_tickers:
                self.volume_analyzer.track_ticker(ticker, lookback_bars=20)
                try:
                    self.volume_analyzer.load_historical_bars(ticker, lookback_minutes=60)
                except Exception:
                    pass

        logger.info(f"\n✅ Watchlist: {len(watchlist)} tickers")
        logger.info(f"{', '.join(watchlist[:15])}{'...' if len(watchlist) > 15 else ''}\n")

        try:
            _get_discord_helpers().send_premarket_watchlist(
                tickers=watchlist,
                scored_tickers=self.scored_tickers,
                stage=self.current_stage,
            )
        except Exception as e:
            logger.info(f"[FUNNEL] ⚠️  Discord watchlist post failed (non-blocking): {e}")

        return watchlist

    def _build_wide_scan(self) -> List[str]:
        stage_config = self.stages["wide"]
        # Fetch all candidates (no min_score gate — we apply it below)
        all_scored = dynamic_screener.get_scored_tickers(
            max_tickers=100, min_score=0, force_refresh=True
        )
        logger.info(f"[FUNNEL] Dynamic screener returned {len(all_scored)} tickers")
        candidates = [t['ticker'] for t in all_scored[:stage_config["max_tickers"]]]
        gap_movers = dynamic_screener.get_gap_candidates(min_gap_pct=2.0, limit=30)
        for ticker in gap_movers:
            if ticker not in candidates:
                candidates.append(ticker)

        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )

        # TUNE v3.7: catalyst bypass — inject tickers with real catalysts
        # that may have low RVOL score at 8 AM but high event probability.
        # all_scored contains pre-gate metadata including catalyst_score.
        self.scored_tickers = _apply_catalyst_bypass(
            self.scored_tickers,
            all_scored,
            stage="wide",
            min_score=stage_config["min_score"],
        )

        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )
        _get_momentum_screener().print_momentum_summary(self.scored_tickers, top_n=15)
        return watchlist

    def _build_narrow_scan(self) -> List[str]:
        stage_config = self.stages["narrow"]
        if self.current_watchlist:
            # Re-score the current wide watchlist with tighter gate
            all_scored = _get_momentum_screener().run_momentum_screener(
                self.current_watchlist,
                min_composite_score=0,   # fetch all first for catalyst bypass
                use_cache=True
            )
            self.scored_tickers = [
                t for t in all_scored
                if t.get("composite_score", 0) >= stage_config["min_score"]
                or t.get("catalyst_bypass", False)
            ]
            # TUNE v3.7: catalyst bypass
            self.scored_tickers = _apply_catalyst_bypass(
                self.scored_tickers,
                all_scored,
                stage="narrow",
                min_score=stage_config["min_score"],
            )
        else:
            screener_results = dynamic_screener.get_scored_tickers(
                max_tickers=50, min_score=0, force_refresh=True
            )
            candidates = [t['ticker'] for t in screener_results[:50]]
            all_scored = _get_momentum_screener().run_momentum_screener(
                candidates,
                min_composite_score=0,
                use_cache=True
            )
            self.scored_tickers = [
                t for t in all_scored
                if t.get("composite_score", 0) >= stage_config["min_score"]
            ]
            self.scored_tickers = _apply_catalyst_bypass(
                self.scored_tickers,
                all_scored,
                stage="narrow",
                min_score=stage_config["min_score"],
            )

        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    if 'bullish' in signal['type'] or 'bottom' in signal['type']:
                        scored_ticker['composite_score'] += 10
                    elif 'bearish' in signal['type'] or 'climax_top' in signal['type']:
                        scored_ticker['composite_score'] -= 10
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )
        _get_momentum_screener().print_momentum_summary(self.scored_tickers, top_n=10)
        return watchlist

    def _build_final_selection(self) -> List[str]:
        stage_config = self.stages["final"]
        if self.current_watchlist:
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            candidates = dynamic_screener.get_gap_candidates(min_gap_pct=3.0, limit=20)
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        # TUNE v3.7: final volume filter lowered from 10,000 -> 5,000
        # (pre-open volume is always thin; 10k was filtering good setups)
        filtered_tickers = [
            t for t in self.scored_tickers if t.get('volume', 0) > 5000
        ]
        if not filtered_tickers:
            logger.info("[FUNNEL] ⚠️  No tickers passed final volume filter, using top scorers")
            filtered_tickers = self.scored_tickers
        watchlist = _get_momentum_screener().get_top_n_movers(
            filtered_tickers, stage_config["max_tickers"]
        )
        n = stage_config["max_tickers"]
        logger.info("\n" + "="*80)
        logger.info(f"🎯 FINAL TOP {n} FOR MARKET OPEN")
        logger.info("="*80)
        _get_momentum_screener().print_momentum_summary(filtered_tickers, top_n=n)
        return watchlist

    def _build_live_watchlist(self) -> List[str]:
        """
        PHASE 1.18: Only runs ONCE at 9:30 ET.
        PHASE 1.19: Applies relative strength/weakness outlier boost before lock.
        FIX v3.8:   WS coverage filter drops zero-bar tickers before lock.
        FIX v3.9:   Do NOT lock an empty watchlist — defer to next tick.
        FIX v4.0:   Fall back to dynamic_screener results when run_momentum_screener()
                    returns empty due to the Phase 1.30 premarket window gate
                    blocking all scan_ticker() calls after 9:30 AM ET on a cold
                    mid-session container.
        FIX v4.1:   Skip the expansion block when v4.0 fallback was used — the
                    fallback already provides a full screener-quality set and the
                    expansion's force_refresh=True would hang the container.
        """
        stage_config = self.stages["live"]
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=50, min_score=0, force_refresh=False
        )
        candidates = [t['ticker'] for t in screener_results[:50]]
        logger.info(f"[FUNNEL] Live session scanning {len(candidates)} candidates from screener")
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        logger.info(f"[FUNNEL] {len(self.scored_tickers)} tickers passed scoring (min_score={stage_config['min_score']})")

        # ── FIX v4.0: Phase 1.30 premarket gate bypass ───────────────────────
        _used_fallback = False
        if len(self.scored_tickers) < MIN_SCORED_THRESHOLD and screener_results:
            logger.warning(
                f"[FUNNEL] ⚠️  run_momentum_screener() returned only "
                f"{len(self.scored_tickers)} ticker(s) — likely Phase 1.30 premarket "
                f"gate blocked all scan_ticker() calls (cold container, outside 04:00-09:30 ET). "
                f"Falling back to {len(screener_results)} dynamic_screener results."
            )
            self.scored_tickers = [
                _map_screener_result_to_scored(t)
                for t in screener_results
                if t.get('score', 0) >= stage_config["min_score"]
            ]
            if len(self.scored_tickers) < MIN_SCORED_THRESHOLD:
                logger.warning(
                    f"[FUNNEL] ⚠️  dynamic_screener fallback also thin "
                    f"({len(self.scored_tickers)} tickers at min_score="
                    f"{stage_config['min_score']}). Lowering threshold to 30."
                )
                self.scored_tickers = [
                    _map_screener_result_to_scored(t)
                    for t in screener_results
                    if t.get('score', 0) >= 30
                ]
            logger.info(
                f"[FUNNEL] ✅ Phase 1.30 fallback: {len(self.scored_tickers)} tickers "
                f"mapped from dynamic_screener for live lock."
            )
            _used_fallback = True
        # ── end FIX v4.0 ─────────────────────────────────────────────────────

        if not _used_fallback and len(self.scored_tickers) < 10:
            logger.info(f"[FUNNEL] ⚠️  Only {len(self.scored_tickers)} tickers — expanding search...")
            expanded_results = dynamic_screener.get_scored_tickers(
                max_tickers=100, min_score=0, force_refresh=False
            )
            expanded_candidates = [t['ticker'] for t in expanded_results[:100]]
            extra = _get_momentum_screener().run_momentum_screener(
                expanded_candidates,
                min_composite_score=20.0,
                use_cache=True
            )
            if not extra and expanded_results:
                logger.warning(
                    "[FUNNEL] ⚠️  Expanded run_momentum_screener() also empty "
                    "— using expanded dynamic_screener fallback."
                )
                extra = [
                    _map_screener_result_to_scored(t)
                    for t in expanded_results
                    if t.get('score', 0) >= 20
                ]
            existing_tickers = {t['ticker'] for t in self.scored_tickers}
            for t in extra:
                if t['ticker'] not in existing_tickers:
                    self.scored_tickers.append(t)
                    existing_tickers.add(t['ticker'])
            logger.info(f"[FUNNEL] Expanded: {len(self.scored_tickers)} tickers (min_score=20.0)")

        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    scored_ticker['composite_score'] += 5

        self.scored_tickers = _apply_relative_outlier_boost(self.scored_tickers)
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)

        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )

        watchlist = _filter_ws_covered(watchlist)

        if not watchlist:
            logger.warning(
                "[FUNNEL] ⚠️  Live build produced empty watchlist "
                "(screener cold / WS not ready) — deferring lock to next tick"
            )
            self._locked_at = None
            return []

        _get_momentum_screener().lock_scanner_cache()
        self._locked_watchlist = None  # finalised after normalise in build_watchlist
        self._locked_at = datetime.now(tz=ET)
        logger.info(
            "[FUNNEL] Watchlist LOCKED at %s ET — %d tickers | next session for re-score",
            self._locked_at.strftime('%H:%M:%S'), len(watchlist),
        )
        return watchlist

    def _finalise_lock(self, watchlist: List[str]) -> None:
        """Persist the normalised locked list (called by build_watchlist after normalise)."""
        if self.current_stage == "live" and self._locked_at is not None and self._locked_watchlist is None:
            self._locked_watchlist = watchlist

    def get_watchlist_metadata(self) -> Dict:
        cache_stats = _get_momentum_screener().get_cache_stats()
        locked_info = {
            'watchlist_locked': self._locked_watchlist is not None,
            'locked_at': self._locked_at.isoformat() if self._locked_at else None
        }
        return {
            'stage':                    self.current_stage,
            'stage_description':        self.stages[self.current_stage]['description'],
            'ticker_count':             len(self.current_watchlist),
            'last_update':              self.last_update_time.isoformat() if self.last_update_time else None,
            'top_3_tickers':            self.current_watchlist[:3],
            'scored_tickers_count':     len(self.scored_tickers),
            'cache_hits':               cache_stats.get('valid_scans', 0),
            'all_tickers_with_scores':  self.scored_tickers,
            **locked_info
        }

    def get_volume_summary(self) -> List[Dict]:
        return self.volume_analyzer.get_all_states()

    def get_active_volume_signals(self) -> List[Dict]:
        return self.volume_analyzer.get_active_signals()


# Global funnel instance
_funnel_instance: Optional[WatchlistFunnel] = None


def get_funnel() -> WatchlistFunnel:
    global _funnel_instance
    if _funnel_instance is None:
        _funnel_instance = WatchlistFunnel()
    return _funnel_instance


def reset_funnel() -> None:
    """
    PHASE 1.34: Reset the global funnel singleton.

    Called by scanner.py at EOD so the next session starts with a fresh
    WatchlistFunnel() — no stale locked watchlist, no prior-day stage state.
    Without this, the Railway process retains the singleton across midnight
    and the locked watchlist from yesterday is returned all day.
    """
    global _funnel_instance
    _funnel_instance = None
    logger.info("[FUNNEL] 🔄 Funnel singleton reset — fresh build on next premarket scan")


def get_current_watchlist(force_refresh: bool = False) -> List[str]:
    """Get current watchlist from funnel (main entry point for scanner.py)."""
    funnel = get_funnel()
    return funnel.build_watchlist(force_refresh)


def get_watchlist_with_metadata(force_refresh: bool = False) -> Dict:
    funnel         = get_funnel()
    watchlist      = funnel.build_watchlist(force_refresh)
    metadata       = funnel.get_watchlist_metadata()
    volume_signals = funnel.get_active_volume_signals()
    return {
        'watchlist':      watchlist,
        'metadata':       metadata,
        'volume_signals': volume_signals
    }


if __name__ == "__main__":
    logger.info("Testing Watchlist Funnel...\n")
    funnel    = WatchlistFunnel()
    watchlist = funnel.build_watchlist(force_refresh=True)
    logger.info(f"\n📦 Current Stage: {funnel.current_stage}")
    logger.info(f"🎯 Watchlist: {len(watchlist)} tickers")
    logger.info(f"📈 Top 5: {watchlist[:5]}")
    metadata = funnel.get_watchlist_metadata()
    logger.info(f"\n📊 Metadata: {metadata}")
