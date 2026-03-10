#!/usr/bin/env python3
"""
Adaptive Watchlist Funnel
Orchestrates dynamic watchlist narrowing from pre-market through market open.

Timeline:
  8:00-9:15 AM: Wide scan (Top 50) - collect gap movers and volume leaders
  9:15-9:25 AM: Narrow to Top 10 - score momentum quality and technical setup
  9:25-9:30 AM: Final Top 3 - highest probability plays for opening bell

Integration:
  - Uses premarket_scanner.py (UNIFIED) for professional 3-tier scoring
  - Uses volume_analyzer.py for real-time volume tracking
  - Feeds scanner.py with optimized watchlist based on time of day

NEW in v3.1:
  - Switched from get_dynamic_watchlist() to get_scored_tickers()
  - Now receives full metadata: rvol, rvol_tier, dollar_vol_m, sector
  - Can apply downstream filters on dollar-vol, RVOL tier, sector diversity

NEW in v3.2:
  - Fixed live session max_tickers cap (10 → 20) to allow more discovery
  - Reduced live session min_score (55 → 25) to match actual usage
  - Added dynamic expansion when insufficient tickers pass scoring

FIX v3.3 (PostgreSQL + Ellipsis):
  - Fixed ellipsis iteration bug (line 162, 210, 235, 263)
  - Replaced ... with proper function calls to get_top_n_movers()
  - Now safely handles empty/invalid watchlist data

PHASE 1.17 (MAR 10, 2026) — DTE filter removed:
  - Removed options_dte_filter integration from all funnel stages
  - DTE is a CONTRACT SELECTION concern, not a trade qualification gate
  - A ticker with only Friday options is still valid for a same-day explosive
    move — you just buy the nearest expiry and close before EOD
  - The DTE filter was rejecting every non-SPY/QQQ ticker on Tues-Thurs
    because most stocks only have weekly expirations (nearest DTE = 4)
  - options_dte_filter.py is kept for optional contract selection logic
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

class WatchlistFunnel:
    """Manages adaptive watchlist narrowing throughout pre-market and market hours."""

    def __init__(self):
        self.current_watchlist: List[str] = []
        self.scored_tickers: List[Dict] = []
        self.volume_analyzer = volume_analyzer.VolumeAnalyzer()

        self.current_stage = "wide"
        self.last_update_time: Optional[datetime] = None

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

        # PHASE 1.17: DTE filter removed — it was rejecting all non-SPY/QQQ tickers
        # on days where the nearest weekly expiry is 4 DTE (Tue-Thu). Contract
        # selection (which expiry to buy) is handled at order-entry time, not here.

        self.current_watchlist = watchlist
        self.last_update_time  = datetime.now()

        for ticker in watchlist:
            if ticker not in self.volume_analyzer.tracked_tickers:
                self.volume_analyzer.track_ticker(ticker, lookback_bars=20)
                try:
                    self.volume_analyzer.load_historical_bars(ticker, lookback_minutes=60)
                except Exception:
                    pass

        print(f"\n\u2705 Watchlist: {len(watchlist)} tickers")
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
            print("[FUNNEL] \u26a0\ufe0f  No tickers passed final volume filter, using top scorers")
            filtered_tickers = self.scored_tickers
        watchlist = _get_momentum_screener().get_top_n_movers(
            filtered_tickers, stage_config["max_tickers"]
        )
        print("\n" + "="*80)
        print("\U0001f3af FINAL TOP 3 FOR MARKET OPEN")
        print("="*80)
        _get_momentum_screener().print_momentum_summary(filtered_tickers, top_n=3)
        return watchlist

    def _build_live_watchlist(self) -> List[str]:
        stage_config = self.stages["live"]
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=50, min_score=0, force_refresh=False
        )
        candidates = [t['ticker'] for t in screener_results[:50]]
        print(f"[FUNNEL] Live session: scanning {len(candidates)} candidates from screener")
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        print(f"[FUNNEL] {len(self.scored_tickers)} tickers passed scoring (min_score={stage_config['min_score']})")
        if len(self.scored_tickers) < 10:
            print(f"[FUNNEL] \u26a0\ufe0f  Only {len(self.scored_tickers)} tickers passed — expanding search...")
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
        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    scored_ticker['composite_score'] += 5
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, stage_config["max_tickers"]
        )
        return watchlist

    def get_watchlist_metadata(self) -> Dict:
        cache_stats = _get_momentum_screener().get_cache_stats()
        return {
            'stage':                    self.current_stage,
            'stage_description':        self.stages[self.current_stage]['description'],
            'ticker_count':             len(self.current_watchlist),
            'last_update':              self.last_update_time.isoformat() if self.last_update_time else None,
            'top_3_tickers':            self.current_watchlist[:3],
            'scored_tickers_count':     len(self.scored_tickers),
            'cache_hits':               cache_stats.get('valid_scans', 0),
            'all_tickers_with_scores':  self.scored_tickers
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
    print(f"\n\U0001f4e6 Current Stage: {funnel.current_stage}")
    print(f"\U0001f3af Watchlist: {len(watchlist)} tickers")
    print(f"\U0001f4c8 Top 5: {watchlist[:5]}")
    metadata = funnel.get_watchlist_metadata()
    print(f"\n\U0001f4ca Metadata: {metadata}")
