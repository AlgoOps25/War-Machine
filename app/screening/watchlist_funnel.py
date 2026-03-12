#!/usr/bin/env python3
"""
Adaptive Watchlist Funnel
Orchestrates dynamic watchlist narrowing from pre-market through market open.

Timeline:
  8:00-9:15 AM: Wide scan (Top 50) - collect gap movers and volume leaders
  9:15-9:25 AM: Narrow to Top 10 - score momentum quality and technical setup
  9:25-9:30 AM: Final Top 3 - highest probability plays for opening bell
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
    as a relative outlier — matching Nitro's core morning filter:
    "find the one ticker bucking its sector group"
  - Safe: purely additive score adjustment, no tickers removed, no new deps
  - Only fires when 2+ tickers share a sector; solo tickers unaffected
"""
import sys
from pathlib import Path
from datetime import datetime, time
from typing import List, Dict, Optional

# Add project root to path for CLI runs
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.screening import volume_analyzer
from app.screening import dynamic_screener
from utils import config

from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

def _get_momentum_screener():
    """Lazy import to avoid circular dependency."""
    from app.screening import premarket_scanner
    return premarket_scanner


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1.19: RELATIVE STRENGTH/WEAKNESS OUTLIER BOOST
# Nitro Trades core filter: within each sector group, boost the ticker that is
# moving OPPOSITE to its peers. That outlier has the most conviction.
# ══════════════════════════════════════════════════════════════════════════════

def _apply_relative_outlier_boost(scored_tickers: List[Dict]) -> List[Dict]:
    """
    Boost tickers that are relative outliers within their sector group.

    Logic:
      1. Group tickers by sector (from sector_data.sector or 'unknown')
      2. For each group with 2+ tickers, compute the group's average gap_pct
         (gap_data.size_pct) as a proxy for consensus direction:
           > 0  = sector trending UP
           < 0  = sector trending DOWN
      3. Any ticker whose gap_pct is opposite in sign to the group average
         is flagged as a relative outlier and receives +20 to composite_score
      4. Log a clear summary so it's visible in Railway logs at 9:30 AM

    Safe guarantees:
      - Never removes tickers, only adds score
      - Groups of 1 are skipped entirely (no false outlier flagging)
      - Missing gap_data / sector_data handled gracefully (defaults to 0 / 'unknown')
      - Does not import any new module
    """
    if not scored_tickers:
        return scored_tickers

    # Step 1: group by sector
    sector_groups: Dict[str, List[Dict]] = {}
    for t in scored_tickers:
        sector_data = t.get('sector_data') or {}
        sector = sector_data.get('sector', 'unknown') or 'unknown'
        sector_groups.setdefault(sector, []).append(t)

    outlier_count = 0

    for sector, group in sector_groups.items():
        if len(group) < 2:
            continue  # need peers to compare against

        # Step 2: compute group average gap direction
        gap_values = []
        for t in group:
            gd = t.get('gap_data') or {}
            gap_pct = gd.get('size_pct', 0.0) or 0.0
            gap_values.append(gap_pct)

        group_avg_gap = sum(gap_values) / len(gap_values)

        # Skip neutral groups (all flat, no direction)
        if abs(group_avg_gap) < 0.1:
            continue

        # Step 3: flag and boost outliers
        for t, gap_pct in zip(group, gap_values):
            is_outlier = (
                (group_avg_gap > 0 and gap_pct < -0.1) or  # sector up, ticker down
                (group_avg_gap < 0 and gap_pct > 0.1)       # sector down, ticker up
            )
            if is_outlier:
                t['composite_score'] += 20
                t['relative_outlier'] = True
                t['outlier_sector'] = sector
                t['outlier_group_avg_gap'] = round(group_avg_gap, 2)
                outlier_count += 1
                print(
                    f"[FUNNEL] 🎯 OUTLIER BOOST: {t['ticker']} "
                    f"gap={gap_pct:+.2f}% vs sector '{sector}' avg={group_avg_gap:+.2f}% "
                    f"→ +20 score (new={t['composite_score']:.1f})"
                )
            else:
                t['relative_outlier'] = False

    if outlier_count == 0:
        print("[FUNNEL] ℹ️  No relative outliers detected in sector groups (all moving together)")
    else:
        print(f"[FUNNEL] ✅ Relative outlier boost applied to {outlier_count} ticker(s)")

    return scored_tickers


class WatchlistFunnel:
    """Manages adaptive watchlist narrowing throughout pre-market and market hours."""

    def __init__(self):
        self.current_watchlist: List[str] = []
        self.scored_tickers: List[Dict] = []
        self.volume_analyzer = volume_analyzer.VolumeAnalyzer()

        self.current_stage = "wide"
        self.last_update_time: Optional[datetime] = None

        # PHASE 1.18: watchlist lock — set once at first live build, never re-scored
        self._locked_watchlist: Optional[List[str]] = None
        self._locked_at: Optional[datetime] = None

        self.stages = {
            "wide": {
                "time_start": time(8, 0),
                "time_end":   time(9, 15),
                "max_tickers": 50,
                "min_score":   35.0,
                "description": "Wide scan - Gap movers & volume leaders"
            },
            "narrow": {
                "time_start": time(9, 15),
                "time_end":   time(9, 25),
                "max_tickers": 10,
                "min_score":   50.0,
                "description": "Top 10 - Momentum quality focus"
            },
            "final": {
                "time_start": time(9, 25),
                "time_end":   time(9, 30),
                "max_tickers": 3,
                "min_score":   65.0,
                "description": "Top 3 - Highest probability setups"
            },
            "live": {
                "time_start": time(9, 30),
                "time_end":   time(16, 0),
                "max_tickers": 20,
                "min_score":   25.0,
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
        # PHASE 1.18: once locked, never re-evaluate during live session
        if self._locked_watchlist is not None and self.get_current_stage() == "live":
            return False
        if force:
            return True
        current_stage = self.get_current_stage()
        if current_stage != self.current_stage:
            return True
        if self.last_update_time is None:
            return True
        elapsed_minutes = (datetime.now() - self.last_update_time).total_seconds() / 60
        intervals = {"wide": 5, "narrow": 2, "final": 1, "live": 3}
        return elapsed_minutes >= intervals.get(current_stage, 5)

    def build_watchlist(self, force_refresh: bool = False) -> List[str]:
        """Build watchlist based on current stage and market conditions."""
        # PHASE 1.18: return frozen watchlist immediately if locked
        if self._locked_watchlist is not None and self.get_current_stage() == "live" and not force_refresh:
            print(f"[FUNNEL] Using locked watchlist ({len(self._locked_watchlist)} tickers, locked at {self._locked_at.strftime('%H:%M:%S') if self._locked_at else '?'})")
            return self._locked_watchlist

        if not self.should_update(force_refresh):
            print(f"[FUNNEL] Using cached watchlist ({len(self.current_watchlist)} tickers)")
            return self.current_watchlist

        new_stage    = self.get_current_stage()
        self.current_stage = new_stage
        stage_config = self.stages[self.current_stage]

        print(f"\n{'='*80}")
        print(f"WATCHLIST FUNNEL - {datetime.now().strftime('%H:%M:%S')}")
        print(f"Stage: {self.current_stage.upper()} - {stage_config['description']}")
        print(f"{'='*80}\n")

        if self.current_stage == "wide":
            watchlist = self._build_wide_scan()
        elif self.current_stage == "narrow":
            watchlist = self._build_narrow_scan()
        elif self.current_stage == "final":
            watchlist = self._build_final_selection()
        else:
            watchlist = self._build_live_watchlist()

        self.current_watchlist = watchlist
        self.last_update_time  = datetime.now()

        for ticker in watchlist:
            if ticker not in self.volume_analyzer.tracked_tickers:
                self.volume_analyzer.track_ticker(ticker, lookback_bars=20)
                try:
                    self.volume_analyzer.load_historical_bars(ticker, lookback_minutes=60)
                except Exception:
                    pass

        print(f"\n✅ Watchlist: {len(watchlist)} tickers")
        print(f"{', '.join(watchlist[:15])}{'...' if len(watchlist) > 15 else ''}\n")

        return watchlist

    def _build_wide_scan(self) -> List[str]:
        stage_config = self.stages["wide"]
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=100, min_score=0, force_refresh=True
        )
        print(f"[FUNNEL] Dynamic screener returned {len(screener_results)} tickers")
        candidates = [t['ticker'] for t in screener_results[:stage_config["max_tickers"]]]
        gap_movers = dynamic_screener.get_gap_candidates(min_gap_pct=2.0, limit=30)
        for ticker in gap_movers:
            if ticker not in candidates:
                candidates.append(ticker)
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )
        _get_momentum_screener().print_momentum_summary(self.scored_tickers, top_n=15)
        return watchlist

    def _build_narrow_scan(self) -> List[str]:
        stage_config = self.stages["narrow"]
        if self.current_watchlist:
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            screener_results = dynamic_screener.get_scored_tickers(
                max_tickers=50, min_score=0, force_refresh=True
            )
            candidates = [t['ticker'] for t in screener_results[:50]]
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    if 'bullish' in signal['type'] or 'bottom' in signal['type']:
                        scored_ticker['composite_score'] += 10
                    elif 'bearish' in signal['type'] or 'climax_top' in signal['type']:
                        scored_ticker['composite_score'] -= 15
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
        filtered_tickers = [
            t for t in self.scored_tickers if t.get('volume', 0) > 50000
        ]
        if not filtered_tickers:
            print("[FUNNEL] ⚠️  No tickers passed final volume filter, using top scorers")
            filtered_tickers = self.scored_tickers
        watchlist = _get_momentum_screener().get_top_n_movers(
            filtered_tickers, stage_config["max_tickers"]
        )
        print("\n" + "="*80)
        print("🎯 FINAL TOP 3 FOR MARKET OPEN")
        print("="*80)
        _get_momentum_screener().print_momentum_summary(filtered_tickers, top_n=3)
        return watchlist

    def _build_live_watchlist(self) -> List[str]:
        """
        PHASE 1.18: Only runs ONCE at 9:30 ET.
        Builds the live watchlist from the screener, then freezes it.
        All subsequent calls return the locked list without re-scoring.

        PHASE 1.19: After scoring and volume adjustments, applies relative
        strength/weakness outlier boost before final sort and lock.
        """
        stage_config = self.stages["live"]
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=50, min_score=0, force_refresh=False
        )
        candidates = [t['ticker'] for t in screener_results[:50]]
        print(f"[FUNNEL] Live session scanning {len(candidates)} candidates from screener")
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        print(f"[FUNNEL] {len(self.scored_tickers)} tickers passed scoring (min_score={stage_config['min_score']})")
        if len(self.scored_tickers) < 10:
            print(f"[FUNNEL] ⚠️  Only {len(self.scored_tickers)} tickers passed — expanding search...")
            expanded_results = dynamic_screener.get_scored_tickers(
                max_tickers=100, min_score=0, force_refresh=True
            )
            expanded_candidates = [t['ticker'] for t in expanded_results[:100]]
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                expanded_candidates,
                min_composite_score=15.0,
                use_cache=True
            )
            print(f"[FUNNEL] Expanded search: {len(self.scored_tickers)} tickers (min_score=15.0)")

        # Volume signal adjustments (existing logic — unchanged)
        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    scored_ticker['composite_score'] += 5

        # PHASE 1.19: Relative strength/weakness outlier boost (Nitro Trades alignment)
        # Boosts tickers moving OPPOSITE to their sector peers by +20 score.
        # Must run BEFORE the final sort so outliers surface to the top.
        self.scored_tickers = _apply_relative_outlier_boost(self.scored_tickers)

        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )

        # PHASE 1.18: freeze — lock the cache and this watchlist for the session
        _get_momentum_screener().lock_scanner_cache()
        self._locked_watchlist = watchlist
        self._locked_at = datetime.now()
        print(f"[FUNNEL] Watchlist LOCKED at {self._locked_at.strftime('%H:%M:%S')} ET — {len(watchlist)} tickers will not be re-scored until next session")

        return watchlist

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


def get_current_watchlist(force_refresh: bool = False) -> List[str]:
    """Get current watchlist from funnel (main entry point for scanner.py)."""
    funnel = get_funnel()
    return funnel.build_watchlist(force_refresh)


def get_watchlist_with_metadata(force_refresh: bool = False) -> Dict:
    funnel    = get_funnel()
    watchlist = funnel.build_watchlist(force_refresh)
    metadata  = funnel.get_watchlist_metadata()
    volume_signals = funnel.get_active_volume_signals()
    return {
        'watchlist':      watchlist,
        'metadata':       metadata,
        'volume_signals': volume_signals
    }


if __name__ == "__main__":
    print("Testing Watchlist Funnel...\n")
    funnel    = WatchlistFunnel()
    watchlist = funnel.build_watchlist(force_refresh=True)
    print(f"\n📦 Current Stage: {funnel.current_stage}")
    print(f"🎯 Watchlist: {len(watchlist)} tickers")
    print(f"📈 Top 5: {watchlist[:5]}")
    metadata = funnel.get_watchlist_metadata()
    print(f"\n📊 Metadata: {metadata}")
