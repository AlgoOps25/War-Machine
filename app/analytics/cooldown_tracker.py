# Cooldown Tracker - Prevents duplicate signals on same ticker
# Tracks ticker cooldown periods after signal generation
# Purpose: Avoid rapid-fire signals on same ticker (quality > quantity)

from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

class CooldownTracker:
    """
    Tracks signal cooldown periods to prevent duplicate signals.
    Default cooldown: 15 minutes after signal armed.
    """
    
    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown_minutes = cooldown_minutes
        self._cooldowns: Dict[str, datetime] = {}  # ticker -> cooldown_expires_at
        self._stats = {
            'total_cooldowns_set': 0,
            'signals_blocked': 0,
            'cooldowns_expired': 0
        }
    
    def _now_et(self) -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))
    
    def set_cooldown(self, ticker: str) -> None:
        """Set cooldown period for ticker after signal armed."""
        expires_at = self._now_et() + timedelta(minutes=self.cooldown_minutes)
        self._cooldowns[ticker] = expires_at
        self._stats['total_cooldowns_set'] += 1
    
    def is_in_cooldown(self, ticker: str) -> bool:
        """Check if ticker is currently in cooldown period."""
        if ticker not in self._cooldowns:
            return False
        
        expires_at = self._cooldowns[ticker]
        now = self._now_et()
        
        if now >= expires_at:
            # Cooldown expired
            del self._cooldowns[ticker]
            self._stats['cooldowns_expired'] += 1
            return False
        
        # Still in cooldown
        self._stats['signals_blocked'] += 1
        return True
    
    def get_cooldown_remaining(self, ticker: str) -> float:
        """Get remaining cooldown time in seconds."""
        if ticker not in self._cooldowns:
            return 0.0
        
        expires_at = self._cooldowns[ticker]
        now = self._now_et()
        remaining = (expires_at - now).total_seconds()
        return max(0.0, remaining)
    
    def clear_cooldown(self, ticker: str) -> None:
        """Manually clear cooldown for ticker (e.g., position closed)."""
        if ticker in self._cooldowns:
            del self._cooldowns[ticker]
    
    def clear_all_cooldowns(self) -> None:
        """Clear all cooldowns (EOD reset)."""
        self._cooldowns.clear()
    
    def get_active_cooldowns(self) -> Dict[str, float]:
        """Get all active cooldowns with remaining time in seconds."""
        now = self._now_et()
        active = {}
        expired = []
        
        for ticker, expires_at in self._cooldowns.items():
            remaining = (expires_at - now).total_seconds()
            if remaining > 0:
                active[ticker] = remaining
            else:
                expired.append(ticker)
        
        # Clean up expired
        for ticker in expired:
            del self._cooldowns[ticker]
            self._stats['cooldowns_expired'] += 1
        
        return active
    
    def print_eod_report(self) -> None:
        """Print end-of-day cooldown statistics."""
        stats = self._stats
        active = self.get_active_cooldowns()
        
        print("\n" + "="*80)
        print("COOLDOWN TRACKER - END OF DAY REPORT")
        print("="*80)
        print(f"Cooldown Period: {self.cooldown_minutes} minutes")
        print(f"Total Cooldowns Set: {stats['total_cooldowns_set']}")
        print(f"Signals Blocked: {stats['signals_blocked']}")
        print(f"Cooldowns Expired: {stats['cooldowns_expired']}")
        
        if active:
            print(f"\nActive Cooldowns at EOD: {len(active)}")
            for ticker, remaining in sorted(active.items()):
                minutes = remaining / 60
                print(f"  • {ticker}: {minutes:.1f} min remaining")
        else:
            print("\nNo active cooldowns at EOD")
        
        # Calculate effectiveness
        total_signals_attempted = stats['total_cooldowns_set'] + stats['signals_blocked']
        if total_signals_attempted > 0:
            block_rate = (stats['signals_blocked'] / total_signals_attempted) * 100
            print(f"\nBlock Rate: {block_rate:.1f}% ({stats['signals_blocked']}/{total_signals_attempted})")
        
        print("="*80 + "\n")

# Global singleton instance
cooldown_tracker = CooldownTracker(cooldown_minutes=15)
