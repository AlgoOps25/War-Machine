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
"""
import sys
from pathlib import Path
from datetime import datetime, time
from typing import List, Dict, Optional

# Add project root to path for CLI runs
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#from app.screening import premarket_scanner as momentum_screener

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
        
        # Funnel stage tracking
        self.current_stage = "wide"
        self.last_update_time: Optional[datetime] = None
        
        # Stage definitions
        self.stages = {
            "wide": {
                "time_start": time(8, 0),
                "time_end": time(9, 15),
                "max_tickers": 50,
                "min_score": 35.0,
                "description": "Wide scan - Gap movers & volume leaders"
            },
            "narrow": {
                "time_start": time(9, 15),
                "time_end": time(9, 25),
                "max_tickers": 10,
                "min_score": 50.0,
                "description": "Top 10 - Momentum quality focus"
            },
            "final": {
                "time_start": time(9, 25),
                "time_end": time(9, 30),
                "max_tickers": 3,
                "min_score": 65.0,
                "description": "Top 3 - Highest probability setups"
            },
            "live": {
                "time_start": time(9, 30),
                "time_end": time(16, 0),
                "max_tickers": 20,  # INCREASED from 10 to allow more discovery
                "min_score": 25.0,  # REDUCED from 55.0 to match actual usage
                "description": "Live session - Active movers"
            }
        }
    
    def get_current_stage(self) -> str:
        now = datetime.now(tz=ET).time()   # ← timezone-aware
        
        if now < self.stages["wide"]["time_end"]:
            return "wide"
        elif now < self.stages["narrow"]["time_end"]:
            return "narrow"
        elif now < self.stages["final"]["time_end"]:
            return "final"
        else:
            return "live"
    
    def should_update(self, force: bool = False) -> bool:
        """Check if watchlist needs updating based on time and stage."""
        if force:
            return True
        
        current_stage = self.get_current_stage()
        
        # Stage transition = immediate update
        if current_stage != self.current_stage:
            return True
        
        # Time-based update intervals by stage
        if self.last_update_time is None:
            return True
        
        elapsed_minutes = (datetime.now() - self.last_update_time).total_seconds() / 60
        
        intervals = {
            "wide": 5,
            "narrow": 2,
            "final": 1,
            "live": 3
        }
        
        return elapsed_minutes >= intervals.get(current_stage, 5)
    
    def build_watchlist(self, force_refresh: bool = False) -> List[str]:
        """Build watchlist based on current stage and market conditions."""
        if not self.should_update(force_refresh):
            print(f"[FUNNEL] Using cached watchlist ({len(self.current_watchlist)} tickers)")
            return self.current_watchlist
        
        new_stage = self.get_current_stage()
        stage_changed = new_stage != self.current_stage
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
        self.last_update_time = datetime.now()
        
        # Initialize volume tracking for new tickers
        for ticker in watchlist:
            if ticker not in self.volume_analyzer.tracked_tickers:
                self.volume_analyzer.track_ticker(ticker, lookback_bars=20)
                # FIX: Skip historical bar loading - it tries to use SQLite which doesn't exist
                # The volume analyzer will work fine with live data from WebSocket feed
                try:
                    self.volume_analyzer.load_historical_bars(ticker, lookback_minutes=60)
                except Exception as e:
                    # Silently skip - historical bars are just for warming up the tracker
                    # Live bars will start flowing immediately from WebSocket
                    pass
        
        print(f"\n✅ Watchlist: {len(watchlist)} tickers")
        print(f"{', '.join(watchlist[:15])}{'...' if len(watchlist) > 15 else ''}\n")
        
        return watchlist
    
    def _build_wide_scan(self) -> List[str]:
        """Wide scan: Top 50 gap movers and volume leaders.
        
        NEW v3.1: Uses get_scored_tickers() instead of get_dynamic_watchlist().
        Now receives full metadata from dynamic_screener: rvol, tier, dollar_vol_m, sector.
        
        FIX v3.3: Replaced ellipsis with proper function call.
        """
        stage_config = self.stages["wide"]
        
        # Get scored tickers with full metadata from dynamic_screener
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=100,
            min_score=0,  # Get all, we'll filter below
            force_refresh=True
        )
        
        print(f"[FUNNEL] Dynamic screener returned {len(screener_results)} tickers with full metadata")
        
        # Optional: apply additional filters on screener metadata
        # Example: enforce minimum dollar volume for options liquidity
        # filtered = [t for t in screener_results if t.get('dollar_vol_m', 0) >= 15]
        
        # For now, just use the top N by screener score
        # The screener already applied all gates (ETF filter, dollar-vol, in-play, etc.)
        candidates = [t['ticker'] for t in screener_results[:stage_config["max_tickers"]]]
        
        # Add gap candidates for extra coverage
        gap_movers = dynamic_screener.get_gap_candidates(min_gap_pct=2.0, limit=30)
        for ticker in gap_movers:
            if ticker not in candidates:
                candidates.append(ticker)
        
        # Score all candidates with professional 3-tier scanner
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        
        # Return top N by score (FIXED: was ... ellipsis)
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, 
            stage_config["max_tickers"]
        )
        
        _get_momentum_screener().print_momentum_summary(self.scored_tickers, top_n=15)
        
        return watchlist
    
    def _build_narrow_scan(self) -> List[str]:
        """Narrow scan: Top 10 highest quality momentum plays.
        
        FIX v3.3: Replaced ellipsis with proper function call.
        """
        stage_config = self.stages["narrow"]
        
        if self.current_watchlist:
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            # Fallback: get fresh from screener
            screener_results = dynamic_screener.get_scored_tickers(
                max_tickers=50,
                min_score=0,
                force_refresh=True
            )
            candidates = [t['ticker'] for t in screener_results[:50]]
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        
        # Apply volume adjustments
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
        
        # Return top N by score (FIXED: was ... ellipsis)
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, 
            stage_config["max_tickers"]
        )
        
        _get_momentum_screener().print_momentum_summary(self.scored_tickers, top_n=10)
        
        return watchlist
    
    def _build_final_selection(self) -> List[str]:
        """Final selection: Top 3 plays for market open.
        
        FIX v3.3: Replaced ellipsis with proper function call.
        """
        stage_config = self.stages["final"]
        
        if self.current_watchlist:
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            # Emergency fallback
            candidates = dynamic_screener.get_gap_candidates(min_gap_pct=3.0, limit=20)
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        
        # Apply final volume filter
        filtered_tickers = []
        for scored_ticker in self.scored_tickers:
            ticker_volume = scored_ticker.get('volume', 0)
            if ticker_volume > 50000:
                filtered_tickers.append(scored_ticker)
        
        if not filtered_tickers:
            print("[FUNNEL] ⚠️  No tickers passed final volume filter, using top scorers")
            filtered_tickers = self.scored_tickers
        
        # Return top N by score (FIXED: was ... ellipsis)
        watchlist = _get_momentum_screener().get_top_n_movers(
            filtered_tickers, 
            stage_config["max_tickers"]
        )
        
        print("\n" + "="*80)
        print("🎯 FINAL TOP 3 FOR MARKET OPEN")
        print("="*80)
        _get_momentum_screener().print_momentum_summary(filtered_tickers, top_n=3)
        
        return watchlist
    
    def _build_live_watchlist(self) -> List[str]:
        """Live session: Top 10-20 active movers based on real-time momentum.
        
        BUGFIX v3.2: 
        - Increased max_tickers to 20 (from 10) to allow more discovery
        - Lowered min_score to 25.0 (from 55.0) since live tickers don't have premarket data
        - Added dynamic expansion: if < 10 tickers pass, fetch more candidates
        
        FIX v3.3: Replaced ellipsis with proper function call.
        """
        stage_config = self.stages["live"]
        
        # Get fresh scored tickers from screener (uses cache if recent)
        screener_results = dynamic_screener.get_scored_tickers(
            max_tickers=50,  # INCREASED from 30 to get more candidates
            min_score=0,
            force_refresh=False
        )
        candidates = [t['ticker'] for t in screener_results[:50]]
        
        print(f"[FUNNEL] Live session: scanning {len(candidates)} candidates from screener")
        
        # Score candidates with professional scanner
        # Use lower threshold (25.0) for live discovery - these tickers don't have
        # premarket momentum data, so scores will be in 20-50 range initially
        self.scored_tickers = _get_momentum_screener().run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],  # Now 25.0 (matches config)
            use_cache=True
        )
        
        print(f"[FUNNEL] {len(self.scored_tickers)} tickers passed scoring (min_score={stage_config['min_score']})")
        
        # DYNAMIC EXPANSION: If we have fewer than 10 tickers, fetch more candidates
        if len(self.scored_tickers) < 10:
            print(f"[FUNNEL] ⚠️  Only {len(self.scored_tickers)} tickers passed scoring, expanding search...")
            
            # Try fetching more candidates with lower screener score threshold
            expanded_results = dynamic_screener.get_scored_tickers(
                max_tickers=100,
                min_score=0,
                force_refresh=True
            )
            expanded_candidates = [t['ticker'] for t in expanded_results[:100]]
            
            # Re-score with even lower threshold
            self.scored_tickers = _get_momentum_screener().run_momentum_screener(
                expanded_candidates,
                min_composite_score=15.0,  # Emergency low threshold
                use_cache=True
            )
            
            print(f"[FUNNEL] Expanded search returned {len(self.scored_tickers)} tickers (min_score=15.0)")
        
        # Boost tickers with active volume signals
        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    scored_ticker['composite_score'] += 5
        
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # Return top N (up to max_tickers, now 20) - FIXED: was ... ellipsis
        watchlist = _get_momentum_screener().get_top_n_movers(
            self.scored_tickers, 
            stage_config["max_tickers"]
        )
        
        return watchlist
    
    def get_watchlist_metadata(self) -> Dict:
        """Get metadata about current watchlist state."""
        cache_stats = _get_momentum_screener().get_cache_stats()
        
        return {
            'stage': self.current_stage,
            'stage_description': self.stages[self.current_stage]['description'],
            'ticker_count': len(self.current_watchlist),
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'top_3_tickers': self.current_watchlist[:3],
            'scored_tickers_count': len(self.scored_tickers),
            'cache_hits': cache_stats.get('valid_scans', 0),
            'all_tickers_with_scores': self.scored_tickers  # Added for explosive mover detection
        }
    
    def get_volume_summary(self) -> List[Dict]:
        """Get volume analysis summary for current watchlist."""
        return self.volume_analyzer.get_all_states()
    
    def get_active_volume_signals(self) -> List[Dict]:
        """Get active volume signals for current watchlist."""
        return self.volume_analyzer.get_active_signals()


# Global funnel instance
_funnel_instance: Optional[WatchlistFunnel] = None


def get_funnel() -> WatchlistFunnel:
    """Get or create global funnel instance."""
    global _funnel_instance
    if _funnel_instance is None:
        _funnel_instance = WatchlistFunnel()
    return _funnel_instance


def get_current_watchlist(force_refresh: bool = False) -> List[str]:
    """Get current watchlist from funnel (main entry point for scanner.py)."""
    funnel = get_funnel()
    return funnel.build_watchlist(force_refresh)


def get_watchlist_with_metadata(force_refresh: bool = False) -> Dict:
    """Get watchlist + metadata (for Discord/logging)."""
    funnel = get_funnel()
    watchlist = funnel.build_watchlist(force_refresh)
    metadata = funnel.get_watchlist_metadata()
    volume_signals = funnel.get_active_volume_signals()
    
    return {
        'watchlist': watchlist,
        'metadata': metadata,
        'volume_signals': volume_signals
    }


if __name__ == "__main__":
    print("Testing Watchlist Funnel...\n")
    
    funnel = WatchlistFunnel()
    watchlist = funnel.build_watchlist(force_refresh=True)
    
    print(f"\n📦 Current Stage: {funnel.current_stage}")
    print(f"🎯 Watchlist: {len(watchlist)} tickers")
    print(f"📈 Top 5: {watchlist[:5]}")
    
    metadata = funnel.get_watchlist_metadata()
    print(f"\n📊 Metadata: {metadata}")
