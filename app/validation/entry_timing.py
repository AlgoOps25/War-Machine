"""
Entry Timing Validator - Time-of-Day Win Rate Optimization

Validates signal entry timing based on historical performance data.
Filters signals during historically weak trading hours and enhances
confidence during golden hours.

Integration: Step 6.7 in signal pipeline (after confirmation passes)

PHASE 4.C-10 (Mar 19, 2026):
  - FIX: HOURLY_WIN_RATES was fabricated placeholder data — all rates were
    invented (0.58, 0.68, 0.71, etc.) with no real journal backing.
    All rates neutralized to 0.50 / sample_size=0 so MIN_SAMPLE_SIZE check
    fires immediately for every hour, returning True with no gating.
    Win rate gating is now a no-op until real backtested data is wired in.
"""

from datetime import datetime, time
from typing import Tuple, Dict, Optional
from zoneinfo import ZoneInfo
import logging
logger = logging.getLogger(__name__)


class EntryTimingValidator:
    """
    Validates signal entry timing against historical win rate data.

    Uses actual trading journal data to identify:
    - Golden hours (high win rate periods)
    - Dead zones (low win rate periods)
    - Session quality (open vs. mid-day vs. close)
    """

    # 4.C-10 FIX: All rates set to 0.50 / sample_size=0 (fabricated data removed).
    # sample_size=0 < MIN_SAMPLE_SIZE=20 → every hour returns True immediately.
    # Replace with real backtested rates when available.
    HOURLY_WIN_RATES = {
        9:  (0.50, 0),  # 9:30-10:00  - no real data yet
        10: (0.50, 0),  # 10:00-11:00 - no real data yet
        11: (0.50, 0),  # 11:00-12:00 - no real data yet
        12: (0.50, 0),  # 12:00-13:00 - no real data yet
        13: (0.50, 0),  # 13:00-14:00 - no real data yet
        14: (0.50, 0),  # 14:00-15:00 - no real data yet
        15: (0.50, 0),  # 15:00-16:00 - no real data yet
    }

    # Minimum sample size for confidence
    MIN_SAMPLE_SIZE = 20

    # Win rate thresholds
    GOLDEN_HOUR_THRESHOLD = 0.65  # 65%+ = golden hour
    WEAK_HOUR_THRESHOLD = 0.50    # <50% = weak hour (consider filtering)

    # Session quality periods
    SESSION_PERIODS = {
        'market_open':  (time(9,  30), time(10, 30)),
        'golden_hours': (time(10,  0), time(11, 30)),
        'lunch_lull':   (time(12,  0), time(13, 30)),
        'afternoon':    (time(14,  0), time(15,  0)),
        'power_hour':   (time(15,  0), time(16,  0)),
    }

    def __init__(self, min_win_rate: float = 0.50):
        self.min_win_rate = min_win_rate
        logger.info("[ENTRY-TIMING] ✅ Validator initialized")
        logger.info(f"[ENTRY-TIMING] Min win rate threshold: {min_win_rate:.1%}")
        logger.info(f"[ENTRY-TIMING] Golden hour threshold: {self.GOLDEN_HOUR_THRESHOLD:.1%}")
        logger.info("[ENTRY-TIMING] ⚠️  Win rate gating DISABLED — no real data (4.C-10)")

    def validate_entry_time(
        self,
        current_time: datetime,
        signal_type: str = "CFW6_INTRADAY",
        grade: str = "A"
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Validate if current time is suitable for entry."""
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo("America/New_York"))
        elif current_time.tzinfo != ZoneInfo("America/New_York"):
            current_time = current_time.astimezone(ZoneInfo("America/New_York"))

        current_hour = current_time.hour
        current_minute = current_time.minute  # noqa: F841

        hour_data = self.HOURLY_WIN_RATES.get(current_hour)

        if hour_data is None:
            return (
                True,
                f"No historical data for hour {current_hour}:00 (allowing)",
                {'hour': current_hour, 'hour_win_rate': None, 'session_quality': 'unknown'}
            )

        hour_win_rate, sample_size = hour_data
        session_quality = self._get_session_quality(current_time.time())

        timing_data = {
            'hour': current_hour,
            'hour_win_rate': hour_win_rate,
            'sample_size': sample_size,
            'session_quality': session_quality,
            'is_golden_hour': hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD,
            'is_weak_hour': hour_win_rate < self.WEAK_HOUR_THRESHOLD
        }

        # sample_size=0 for all hours → always hits this branch (no gating)
        if sample_size < self.MIN_SAMPLE_SIZE:
            return (
                True,
                f"Hour {current_hour}:00 - insufficient sample size ({sample_size} < {self.MIN_SAMPLE_SIZE})",
                timing_data
            )

        if hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD:
            return (
                True,
                f"Golden hour detected ({current_hour}:00 | {hour_win_rate:.1%} WR | {session_quality})",
                timing_data
            )

        if hour_win_rate < self.min_win_rate:
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

        return (
            True,
            f"Acceptable timing ({current_hour}:00 | {hour_win_rate:.1%} WR | {session_quality})",
            timing_data
        )

    def _get_session_quality(self, current_time: time) -> str:
        for period_name, (start_time, end_time) in self.SESSION_PERIODS.items():
            if start_time <= current_time < end_time:
                return period_name
        return "unknown"

    def get_timing_boost(self, current_time: datetime) -> float:
        """Calculate confidence boost/penalty based on timing."""
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo("America/New_York"))

        current_hour = current_time.hour
        hour_data = self.HOURLY_WIN_RATES.get(current_hour)

        if hour_data is None:
            return 0.0

        hour_win_rate, sample_size = hour_data

        # sample_size=0 → no boost/penalty until real data available
        if sample_size < self.MIN_SAMPLE_SIZE:
            return 0.0

        if hour_win_rate >= self.GOLDEN_HOUR_THRESHOLD:
            boost = (hour_win_rate - self.GOLDEN_HOUR_THRESHOLD) * 0.5
            return min(boost, 0.05)

        if hour_win_rate < self.WEAK_HOUR_THRESHOLD:
            penalty = (self.WEAK_HOUR_THRESHOLD - hour_win_rate) * 0.5
            return -min(penalty, 0.05)

        return 0.0

    def print_timing_summary(self):
        """Print summary of hourly win rates."""
        logger.info("\n" + "=" * 80)
        logger.info("ENTRY TIMING - HOURLY WIN RATES")
        logger.info("=" * 80)

        for hour in sorted(self.HOURLY_WIN_RATES.keys()):
            win_rate, sample_size = self.HOURLY_WIN_RATES[hour]
            classification = "🟢 GOLDEN" if win_rate >= self.GOLDEN_HOUR_THRESHOLD else \
                             "🔴 WEAK"   if win_rate <  self.WEAK_HOUR_THRESHOLD   else \
                             "🟡 DECENT"
            logger.info(
                f"  {hour:02d}:00 - {hour+1:02d}:00 | "
                f"{win_rate:.1%} WR | "
                f"{sample_size} trades | "
                f"{classification}"
            )

        logger.info("=" * 80)
        logger.info(f"Golden hour threshold: {self.GOLDEN_HOUR_THRESHOLD:.1%}")
        logger.info(f"Weak hour threshold:   {self.WEAK_HOUR_THRESHOLD:.1%}")
        logger.info(f"Minimum sample size:   {self.MIN_SAMPLE_SIZE} trades")
        logger.info("=" * 80 + "\n")


# Singleton instance
_validator = None


def get_entry_timing_validator() -> EntryTimingValidator:
    """Get or create singleton validator instance."""
    global _validator
    if _validator is None:
        _validator = EntryTimingValidator()
    return _validator


if __name__ == "__main__":
    validator = get_entry_timing_validator()
    validator.print_timing_summary()

    test_times = [
        datetime(2026, 3, 10, 10, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 3, 10, 12, 15, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 3, 10, 15, 30, tzinfo=ZoneInfo("America/New_York")),
    ]

    for test_time in test_times:
        is_valid, reason, data = validator.validate_entry_time(test_time, grade="A")
        logger.info(f"{test_time.strftime('%H:%M')} | Valid: {is_valid} | {reason}")
