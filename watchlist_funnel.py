"""
Adaptive Watchlist Funnel
Orchestrates dynamic watchlist narrowing from pre-market through market open.

Timeline:
  8:00-9:15 AM: Wide scan (Top 50) - collect gap movers and volume leaders
  9:15-9:25 AM: Narrow to Top 10 - score momentum quality and technical setup
  9:25-9:30 AM: Final Top 3 - highest probability plays for opening bell

Integration:
  - Uses momentum_screener_optimized.py for scoring (80%+ API call reduction)
  - Uses volume_analyzer.py for real-time volume tracking
  - Feeds scanner.py with optimized watchlist based on time of day
"""
from datetime import datetime, time
from typing import List, Dict, Optional
import momentum_screener_optimized as momentum_screener
import volume_analyzer
import dynamic_screener
import config


class WatchlistFunnel:
    """Manages adaptive watchlist narrowing throughout pre-market and market hours."""
    
    def __init__(self):
        self.current_watchlist: List[str] = []
        self.scored_tickers: List[Dict] = []
        self.volume_analyzer = volume_analyzer.VolumeAnalyzer(config.DB_PATH)
        
        # Funnel stage tracking
        self.current_stage = "wide"  # 'wide', 'narrow', 'final', 'live'
        self.last_update_time: Optional[datetime] = None
        
        # Stage definitions
        self.stages = {
            "wide": {
                "time_start": time(8, 0),
                "time_end": time(9, 15),
                "max_tickers": 50,
                "min_score": 40.0,
                "description": "Wide scan - Gap movers & volume leaders"
            },
            "narrow": {
                "time_start": time(9, 15),
                "time_end": time(9, 25),
                "max_tickers": 10,
                "min_score": 60.0,
                "description": "Top 10 - Momentum quality focus"
            },
            "final": {
                "time_start": time(9, 25),
                "time_end": time(9, 30),
                "max_tickers": 3,
                "min_score": 75.0,
                "description": "Top 3 - Highest probability setups"
            },
            "live": {
                "time_start": time(9, 30),
                "time_end": time(16, 0),
                "max_tickers": 10,
                "min_score": 65.0,
                "description": "Live session - Active movers"
            }
        }
    
    def get_current_stage(self) -> str:
        """Determine current funnel stage based on time of day."""
        now = datetime.now().time()
        
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
        
        # Update intervals by stage
        intervals = {
            "wide": 5,      # Every 5 minutes during wide scan
            "narrow": 2,    # Every 2 minutes when narrowing
            "final": 1,     # Every 1 minute for final selection
            "live": 3       # Every 3 minutes during live session
        }
        
        return elapsed_minutes >= intervals.get(current_stage, 5)
    
    def build_watchlist(self, force_refresh: bool = False) -> List[str]:
        """Build watchlist based on current stage and market conditions."""
        if not self.should_update(force_refresh):
            print(f"[FUNNEL] Using cached watchlist ({len(self.current_watchlist)} tickers)")
            return self.current_watchlist
        
        # Update stage
        new_stage = self.get_current_stage()
        stage_changed = new_stage != self.current_stage
        self.current_stage = new_stage
        
        stage_config = self.stages[self.current_stage]
        
        print(f"\n{'='*80}")
        print(f"WATCHLIST FUNNEL - {datetime.now().strftime('%H:%M:%S')}")
        print(f"Stage: {self.current_stage.upper()} - {stage_config['description']}")
        print(f"{'='*80}\n")
        
        # Stage-specific logic
        if self.current_stage == "wide":
            watchlist = self._build_wide_scan()
        elif self.current_stage == "narrow":
            watchlist = self._build_narrow_scan()
        elif self.current_stage == "final":
            watchlist = self._build_final_selection()
        else:  # live
            watchlist = self._build_live_watchlist()
        
        self.current_watchlist = watchlist
        self.last_update_time = datetime.now()
        
        # Initialize volume tracking for new tickers
        for ticker in watchlist:
            if ticker not in self.volume_analyzer.tracked_tickers:
                self.volume_analyzer.track_ticker(ticker, lookback_bars=20)
                self.volume_analyzer.load_historical_bars(ticker, lookback_minutes=60)
        
        print(f"\n✅ Watchlist: {len(watchlist)} tickers")
        print(f"{', '.join(watchlist[:15])}{'...' if len(watchlist) > 15 else ''}\n")
        
        return watchlist
    
    def _build_wide_scan(self) -> List[str]:
        """Wide scan: Top 50 gap movers and volume leaders."""
        stage_config = self.stages["wide"]
        
        # Start with dynamic screener results
        candidates = dynamic_screener.get_dynamic_watchlist(
            include_core=True,
            max_tickers=100,  # Get more than we need for filtering
            force_refresh=True
        )
        
        # Add gap candidates
        gap_movers = dynamic_screener.get_gap_candidates(min_gap_pct=2.0, limit=30)
        for ticker in gap_movers:
            if ticker not in candidates:
                candidates.append(ticker)
        
        # Score all candidates (optimized with caching)
        self.scored_tickers = momentum_screener.run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True  # Enable caching
        )
        
        # Return top N by score
        watchlist = momentum_screener.get_top_n_movers(
            self.scored_tickers,
            n=stage_config["max_tickers"]
        )
        
        momentum_screener.print_momentum_summary(self.scored_tickers, top_n=15)
        
        return watchlist
    
    def _build_narrow_scan(self) -> List[str]:
        """Narrow scan: Top 10 highest quality momentum plays."""
        stage_config = self.stages["narrow"]
        
        # Re-score existing watchlist (uses cache for efficiency)
        if self.current_watchlist:
            self.scored_tickers = momentum_screener.run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            # Fallback if no watchlist yet
            candidates = dynamic_screener.get_dynamic_watchlist(
                include_core=True,
                max_tickers=50,
                force_refresh=True
            )
            self.scored_tickers = momentum_screener.run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        
        # Get volume signals to boost/demote tickers
        volume_signals = self.volume_analyzer.get_active_signals()
        
        # Apply volume adjustments to scores
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    # Boost for bullish signals, penalize for bearish
                    if 'bullish' in signal['type'] or 'bottom' in signal['type']:
                        scored_ticker['composite_score'] += 10
                    elif 'bearish' in signal['type'] or 'climax_top' in signal['type']:
                        scored_ticker['composite_score'] -= 15
        
        # Re-sort after adjustments
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        
        watchlist = momentum_screener.get_top_n_movers(
            self.scored_tickers,
            n=stage_config["max_tickers"]
        )
        
        momentum_screener.print_momentum_summary(self.scored_tickers, top_n=10)
        
        return watchlist
    
    def _build_final_selection(self) -> List[str]:
        """Final selection: Top 3 plays for market open."""
        stage_config = self.stages["final"]
        
        # Re-score narrow watchlist with highest threshold
        if self.current_watchlist:
            self.scored_tickers = momentum_screener.run_momentum_screener(
                self.current_watchlist,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        else:
            # Emergency fallback
            candidates = dynamic_screener.get_gap_candidates(min_gap_pct=3.0, limit=20)
            self.scored_tickers = momentum_screener.run_momentum_screener(
                candidates,
                min_composite_score=stage_config["min_score"],
                use_cache=True
            )
        
        # Apply final volume filter (must have pre-market activity)
        filtered_tickers = []
        for scored_ticker in self.scored_tickers:
            # Check for 'volume' key (optimized version) or 'premarket_volume' (original)
            ticker_volume = scored_ticker.get('volume', scored_ticker.get('premarket_volume', 0))
            if ticker_volume > 50000:  # Minimum 50K pre-market volume
                filtered_tickers.append(scored_ticker)
        
        if not filtered_tickers:
            print("[FUNNEL] ⚠️  No tickers passed final volume filter, using top scorers")
            filtered_tickers = self.scored_tickers
        
        watchlist = momentum_screener.get_top_n_movers(
            filtered_tickers,
            n=stage_config["max_tickers"]
        )
        
        print("\n" + "="*80)
        print("🎯 FINAL TOP 3 FOR MARKET OPEN")
        print("="*80)
        momentum_screener.print_momentum_summary(filtered_tickers, top_n=3)
        
        return watchlist
    
    def _build_live_watchlist(self) -> List[str]:
        """Live session: Top 10 active movers based on real-time momentum."""
        stage_config = self.stages["live"]
        
        # During live session, use dynamic screener + volume signals
        candidates = dynamic_screener.get_dynamic_watchlist(
            include_core=True,
            max_tickers=30,
            force_refresh=False  # Use cache during live session
        )
        
        # Score candidates (cache heavily used during live session)
        self.scored_tickers = momentum_screener.run_momentum_screener(
            candidates,
            min_composite_score=stage_config["min_score"],
            use_cache=True
        )
        
        # Boost tickers with active volume signals
        volume_signals = self.volume_analyzer.get_active_signals()
        for signal in volume_signals:
            ticker = signal['ticker']
            for scored_ticker in self.scored_tickers:
                if scored_ticker['ticker'] == ticker:
                    scored_ticker['composite_score'] += 5
        
        self.scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
        
        watchlist = momentum_screener.get_top_n_movers(
            self.scored_tickers,
            n=stage_config["max_tickers"]
        )
        
        return watchlist
    
    def get_watchlist_metadata(self) -> Dict:
        """Get metadata about current watchlist state."""
        # Get cache stats for monitoring
        cache_stats = momentum_screener.get_cache_stats()
        
        return {
            'stage': self.current_stage,
            'stage_description': self.stages[self.current_stage]['description'],
            'ticker_count': len(self.current_watchlist),
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'top_3_tickers': self.current_watchlist[:3],
            'scored_tickers_count': len(self.scored_tickers),
            'cache_hits': cache_stats.get('valid_entries', 0)
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
    # Test funnel
    print("Testing Watchlist Funnel...\n")
    
    funnel = WatchlistFunnel()
    
    # Force wide scan
    watchlist = funnel.build_watchlist(force_refresh=True)
    
    print(f"\n📦 Current Stage: {funnel.current_stage}")
    print(f"🎯 Watchlist: {len(watchlist)} tickers")
    print(f"📈 Top 5: {watchlist[:5]}")
    
    # Get metadata
    metadata = funnel.get_watchlist_metadata()
    print(f"\n📊 Metadata: {metadata}")
