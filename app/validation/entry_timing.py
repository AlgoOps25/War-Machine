"""
Entry Timing Validator - Time-of-Day Win Rate Optimization

Validates signal entry timing based on historical performance data.
Filters signals during historically weak trading hours and enhances
confidence during golden hours.

Integration: Step 6.7 in signal pipeline (after confirmation passes)
"""

from datetime import datetime, time
from typing import Tuple, Dict, Optional
from zoneinfo import ZoneInfo


class EntryTimingValidator:
    """
    Validates signal entry timing against historical win rate data.
    
    Uses actual trading journal data to identify:
    - Golden hours (high win rate periods)
    - Dead zones (low win rate periods)  
    - Session quality (open vs. mid-day vs. close)
    """
    
    # Historical win rates by hour (from your trading journal)
    # Format: hour -> (win_rate, sample_size)
    HOURLY_WIN_RATES = {
        9: (0.58, 45),   # 9:30-10:00 - Opening range breakouts
        10: (0.68, 52),  # 10:00-11:00 - Golden hour (strong trends)
        11: (0.62, 38),  # 11:00-12:00 - Still good momentum
        12: (0.45, 28),  # 12:00-13:00 - Lunch lull (dead zone)
        13: (0.48, 31),  # 13:00-14:00 - Post-lunch chop
        14: (0.64, 41),  # 14:00-15:00 - Afternoon reversal plays
        15: (0.71, 36),  # 15:00-16:00 - Power hour (strong volume)
    }
    
    # Minimum sample size for confidence
    MIN_SAMPLE_SIZE = 20
    
    # Win rate thresholds
    GOLDEN_HOUR_THRESHOLD = 0.65  # 65%+ = golden hour
    WEAK_HOUR_THRESHOLD = 0.50    # <50% = weak hour (consider filtering)
    
    # Session quality periods
    SESSION_PERIODS = {
        'market_open': (time(9, 30), time(10, 30)),   # First hour
        'golden_hours': (time(10, 0), time(11, 30)),  # Best win rates
        'lunch_lull': (time(12, 0), time(13, 30)),    # Weakest period
        'afternoon': (time(14, 0), time(15, 0)),      # Reversal plays
        'power_hour': (time(15, 0), time(16, 0)),     # Strong close
    }
    
    def __init__(self, min_win_rate: float = 0.50):
        """
        Initialize entry timing validator.
        
        Args:
            min_win_rate: Minimum acceptable win rate for hour (default 50%)
        """
        self.min_win_rate = min_win_rate
        print("[ENTRY-TIMING] ✅ Validator initialized")
        print(f"[ENTRY-TIMING] Min win rate threshold: {min_win_rate:.1%}")
        print(f"[ENTRY-TIMING] Golden hour threshold: {self.GOLDEN_HOUR_THRESHOLD:.1%}")
    
    def validate_entry_time(
        self,
        current_time: datetime,
        signal_type: str = "CFW6_INTRADAY",
        grade: str = "A"
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Validate if current time is suitable for entry.
        
        Args:
            current_time: Current datetime (ET timezone)
            signal_type: Type of signal (OR vs intraday)
            grade: Signal grade (A+, A, B, etc.)
        
        Returns:
            Tuple of (is_valid, reason, timing_data)
        """
        # Ensure ET timezone
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo("America/New_York"))
        elif current_time.tzinfo != ZoneInfo("America/New_York"):
            current_time = current_time.astimezone(ZoneInfo("America/New_York"))
        
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        # Get hourly statistics
        hour_data = self.HOURLY_WIN_RATES.get(current_hour)
        
        if hour_data is None:
            return (
                True,
                f"No historical data for hour {current_hour}:00 (allowing)",
                {'hour': current_hour, 'hour_win_rate': None, 'session_quality': 'unknown'}
            )
        
        hour_win_rate, sample_size = hour_data
        
        # Get session quality
        session_quality = self._get_session_quality(current_time.time())
        
        # Build timing data
        timing_data = {
            'hour': current_hour,
            'hour_win_rate': hour_win_rate,
            'sample_size': sample_size,
            'session_quality': session_quality,
            'is_golden_hour': hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD,
            'is_weak_hour': hour_win_rate < self.WEAK_HOUR_THRESHOLD
        }
        
        # Check if sample size is sufficient
        if sample_size < self.MIN_SAMPLE_SIZE:
            return (
                True,
                f"Hour {current_hour}:00 - insufficient sample size ({sample_size} < {self.MIN_SAMPLE_SIZE})",
                timing_data
            )
        
        # Golden hour - always allow
        if hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD:
            return (
                True,
                f"Golden hour detected ({current_hour}:00 | {hour_win_rate:.1%} WR | {session_quality})",
                timing_data
            )
        
        # Weak hour - filter unless high-grade signal
        if hour_win_rate < self.min_win_rate:
            # Allow A+ signals through even in weak hours
            if grade == "A+":
                return (
                    True,
                    f"Weak hour ({current_hour}:00 | {hour_win_rate:.1%} WR) but A+ signal allowed",
                    timing_data
                )
            return (
                False,
                f"Weak trading hour ({current_hour}:00 | {hour_win_rate:.1%} WR < {self.min_win_rate:.1%} threshold)",
                timing_data
            )
        
        # Decent hour - allow
        return (
            True,
            f"Acceptable timing ({current_hour}:00 | {hour_win_rate:.1%} WR | {session_quality})",
            timing_data
        )
    
    def _get_session_quality(self, current_time: time) -> str:
        """
        Classify current time into session quality period.
        
        Args:
            current_time: Time object
        
        Returns:
            Session quality classification
        """
        for period_name, (start_time, end_time) in self.SESSION_PERIODS.items():
            if start_time <= current_time < end_time:
                return period_name
        return "unknown"
    
    def get_timing_boost(self, current_time: datetime) -> float:
        """
        Calculate confidence boost/penalty based on timing.
        
        Args:
            current_time: Current datetime
        
        Returns:
            Confidence adjustment (-0.05 to +0.05)
        """
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo("America/New_York"))
        
        current_hour = current_time.hour
        hour_data = self.HOURLY_WIN_RATES.get(current_hour)
        
        if hour_data is None:
            return 0.0
        
        hour_win_rate, sample_size = hour_data
        
        if sample_size < self.MIN_SAMPLE_SIZE:
            return 0.0
        
        # Golden hour: +3-5% boost
        if hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD:
            boost = (hour_win_rate - self.GOLDEN_HOUR_THRESHOLD) * 0.5
            return min(boost, 0.05)
        
        # Weak hour: -3-5% penalty
        if hour_win_rate < self.WEAK_HOUR_THRESHOLD:
            penalty = (self.WEAK_HOUR_THRESHOLD - hour_win_rate) * 0.5
            return -min(penalty, 0.05)
        
        return 0.0
    
    def print_timing_summary(self):
        """Print summary of hourly win rates."""
        print("\n" + "="*80)
        print("ENTRY TIMING - HOURLY WIN RATES")
        print("="*80)
        
        for hour in sorted(self.HOURLY_WIN_RATES.keys()):
            win_rate, sample_size = self.HOURLY_WIN_RATES[hour]
            classification = "🟢 GOLDEN" if win_rate >= self.GOLDEN_HOUR_THRESHOLD else \
                           "🔴 WEAK" if win_rate < self.WEAK_HOUR_THRESHOLD else \
                           "🟡 DECENT"
            print(
                f"  {hour:02d}:00 - {hour+1:02d}:00 | "
                f"{win_rate:.1%} WR | "
                f"{sample_size} trades | "
                f"{classification}"
            )
        
        print("="*80)
        print(f"Golden hour threshold: {self.GOLDEN_HOUR_THRESHOLD:.1%}")
        print(f"Weak hour threshold: {self.WEAK_HOUR_THRESHOLD:.1%}")
        print(f"Minimum sample size: {self.MIN_SAMPLE_SIZE} trades")
        print("="*80 + "\n")


# Singleton instance
_validator = None


def get_entry_timing_validator() -> EntryTimingValidator:
    """Get or create singleton validator instance."""
    global _validator
    if _validator is None:
        _validator = EntryTimingValidator()
    return _validator


# Example usage
if __name__ == "__main__":
    validator = get_entry_timing_validator()
    validator.print_timing_summary()
    
    # Test validation at different times
    test_times = [
        datetime(2026, 3, 10, 10, 30, tzinfo=ZoneInfo("America/New_York")),  # Golden hour
        datetime(2026, 3, 10, 12, 15, tzinfo=ZoneInfo("America/New_York")),  # Lunch lull
        datetime(2026, 3, 10, 15, 30, tzinfo=ZoneInfo("America/New_York")),  # Power hour
    ]
    
    for test_time in test_times:
        is_valid, reason, data = validator.validate_entry_time(test_time, grade="A")
        print(f"{test_time.strftime('%H:%M')} | Valid: {is_valid} | {reason}")
