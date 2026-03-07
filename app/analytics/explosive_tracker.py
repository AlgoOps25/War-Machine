# Explosive Mover Tracker - Tracks regime filter bypass events
# Purpose: Monitor when high-score/high-RVOL tickers bypass regime filter
# Helps validate effectiveness of explosive mover override logic

from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

class ExplosiveMoverTracker:
    """
    Tracks instances where explosive movers (score≥80 + RVOL≥4.0x)
    bypass the regime filter due to extreme opportunity.
    """
    
    def __init__(self):
        self._overrides: List[Dict] = []  # List of override events
        self._stats = {
            'total_overrides': 0,
            'tier_breakdown': {},  # tier -> count
            'avg_score': 0.0,
            'avg_rvol': 0.0,
            'max_score': 0,
            'max_rvol': 0.0
        }
    
    def _now_et(self) -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))
    
    def record_override(
        self, 
        ticker: str, 
        score: int, 
        rvol: float, 
        tier: str = "N/A"
    ) -> None:
        """Record an explosive mover regime bypass event."""
        timestamp = self._now_et()
        
        override_event = {
            'ticker': ticker,
            'score': score,
            'rvol': rvol,
            'tier': tier,
            'timestamp': timestamp
        }
        
        self._overrides.append(override_event)
        
        # Update stats
        self._stats['total_overrides'] += 1
        self._stats['tier_breakdown'][tier] = self._stats['tier_breakdown'].get(tier, 0) + 1
        self._stats['max_score'] = max(self._stats['max_score'], score)
        self._stats['max_rvol'] = max(self._stats['max_rvol'], rvol)
        
        # Update running averages
        total = self._stats['total_overrides']
        self._stats['avg_score'] = (
            (self._stats['avg_score'] * (total - 1) + score) / total
        )
        self._stats['avg_rvol'] = (
            (self._stats['avg_rvol'] * (total - 1) + rvol) / total
        )
    
    def get_overrides_today(self) -> List[Dict]:
        """Get all override events for today."""
        return self._overrides.copy()
    
    def get_override_count(self) -> int:
        """Get total number of overrides today."""
        return self._stats['total_overrides']
    
    def get_tier_breakdown(self) -> Dict[str, int]:
        """Get override count breakdown by tier."""
        return self._stats['tier_breakdown'].copy()
    
    def print_eod_report(self) -> None:
        """Print end-of-day explosive mover override report."""
        stats = self._stats
        total = stats['total_overrides']
        
        print("\n" + "="*80)
        print("EXPLOSIVE MOVER OVERRIDE - END OF DAY REPORT")
        print("="*80)
        print(f"Total Regime Filter Bypasses: {total}")
        
        if total == 0:
            print("\n✅ No explosive mover overrides today")
            print("   (All signals processed under normal regime conditions)")
            print("="*80 + "\n")
            return
        
        print(f"\nAggregate Statistics:")
        print(f"  • Average Score: {stats['avg_score']:.1f}")
        print(f"  • Average RVOL: {stats['avg_rvol']:.2f}x")
        print(f"  • Max Score: {stats['max_score']}")
        print(f"  • Max RVOL: {stats['max_rvol']:.2f}x")
        
        # Tier breakdown
        if stats['tier_breakdown']:
            print(f"\nTier Breakdown:")
            for tier in sorted(stats['tier_breakdown'].keys()):
                count = stats['tier_breakdown'][tier]
                pct = (count / total) * 100
                print(f"  • Tier {tier}: {count} ({pct:.1f}%)")
        
        # List all override events
        if self._overrides:
            print(f"\nOverride Events (chronological):")
            for i, event in enumerate(self._overrides, 1):
                time_str = event['timestamp'].strftime('%I:%M %p')
                print(
                    f"  {i}. {event['ticker']} @ {time_str} | "
                    f"Score: {event['score']} | RVOL: {event['rvol']:.1f}x | "
                    f"Tier: {event['tier']}"
                )
        
        print("\n💡 Insight: These tickers had extreme volume/momentum characteristics")
        print("   warranting regime filter bypass for potential high-conviction trades.")
        print("="*80 + "\n")
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at market close)."""
        self._overrides.clear()
        self._stats = {
            'total_overrides': 0,
            'tier_breakdown': {},
            'avg_score': 0.0,
            'avg_rvol': 0.0,
            'max_score': 0,
            'max_rvol': 0.0
        }

# Global singleton instance
explosive_tracker = ExplosiveMoverTracker()
