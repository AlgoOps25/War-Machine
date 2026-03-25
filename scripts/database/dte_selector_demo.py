#!/usr/bin/env python3
"""
DTE Selector Demo / Development Tool

Standalone demo of time-of-day based DTE (Days-To-Expiration) selection logic.
Useful for manually testing DTE rules before integrating with live options flow.

Usage:
    python scripts/database/dte_selector_demo.py

Note: Moved from tests/dte_selector.py — this is a dev/demo tool,
not a pytest test. The production DTE selector lives in:
    app/options/options_dte_selector.py

This file exists for standalone prototyping and manual verification.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DTEConfig:
    """Configuration for DTE selection logic."""
    default_dte: int = 0
    pre_1000_dte: int = 0
    post_1000_dte: int = 1
    post_1030_dte: int = 2
    avoid_wed_0dte: bool = True
    min_time_value: float = 0.05
    enable_smart_routing: bool = True


class DTESelector:
    """Selects optimal DTE based on time of day and market conditions."""

    def __init__(self, config: DTEConfig):
        self.config = config
        logger.info(f"DTE Selector initialized: {config}")

    def select_dte(self, reference_time: Optional[datetime] = None) -> int:
        """
        Select optimal DTE based on current time and rules.

        Returns:
            Selected DTE (0, 1, or 2+)
        """
        if reference_time is None:
            reference_time = datetime.now()

        current_hour   = reference_time.hour
        current_minute = reference_time.minute
        day_of_week    = reference_time.weekday()  # 0=Monday, 6=Sunday

        # Wednesday 0DTE avoidance
        if day_of_week == 2 and self.config.avoid_wed_0dte:
            logger.info("DTE Avoiding Wednesday 0DTE - using 1DTE minimum")
            return max(1, self.config.default_dte)

        # Pre-market / early morning (before 10:00 AM)
        if current_hour < 10:
            dte = self.config.pre_1000_dte
            logger.debug(f"DTE Pre-1000 selection: {dte}DTE at {current_hour:02d}:{current_minute:02d}")
            return dte

        # Early session (10:00–10:30 AM)
        elif current_hour == 10 and current_minute < 30:
            dte = self.config.post_1000_dte
            logger.debug(f"DTE Early session selection: {dte}DTE at {current_hour:02d}:{current_minute:02d}")
            return dte

        # Standard session (after 10:30 AM)
        else:
            dte = self.config.post_1030_dte
            logger.debug(f"DTE Standard session selection: {dte}DTE at {current_hour:02d}:{current_minute:02d}")
            return dte

    def get_expiration_for_dte(self, dte: int, reference_time: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate expiration datetime for a given DTE."""
        if reference_time is None:
            reference_time = datetime.now()
        expiration_date = reference_time.date() + timedelta(days=dte)
        # Skip weekends
        while expiration_date.weekday() >= 5:
            expiration_date += timedelta(days=1)
        return datetime.combine(expiration_date, time(16, 0, 0))

    def get_time_to_expiration(self, expiration: datetime, reference_time: Optional[datetime] = None) -> float:
        """Return hours remaining until expiration."""
        if reference_time is None:
            reference_time = datetime.now()
        return (expiration - reference_time).total_seconds() / 3600

    def should_avoid_dte(self, dte: int, reference_time: Optional[datetime] = None) -> tuple[bool, str]:
        """Check if a specific DTE should be avoided."""
        if reference_time is None:
            reference_time = datetime.now()
        if dte == 0 and reference_time.weekday() == 2 and self.config.avoid_wed_0dte:
            return (True, "Wednesday 0DTE avoided by config")
        expiration = self.get_expiration_for_dte(dte, reference_time)
        if expiration:
            hours_remaining = self.get_time_to_expiration(expiration, reference_time)
            if hours_remaining < 0.5:
                return (True, f"Only {hours_remaining:.1f} hours until expiration")
        return (False, "DTE acceptable")

    def get_recommendation_summary(self, reference_time: Optional[datetime] = None) -> dict:
        """Get current DTE recommendation with full context."""
        if reference_time is None:
            reference_time = datetime.now()
        recommended_dte      = self.select_dte(reference_time)
        expiration           = self.get_expiration_for_dte(recommended_dte, reference_time)
        should_avoid, reason = self.should_avoid_dte(recommended_dte, reference_time)
        return {
            'recommended_dte':      recommended_dte,
            'expiration_date':      expiration.date() if expiration else None,
            'expiration_time':      expiration if expiration else None,
            'hours_to_expiration':  self.get_time_to_expiration(expiration, reference_time) if expiration else None,
            'current_time':         reference_time.strftime('%Y-%m-%d %H:%M:%S'),
            'day_of_week':          reference_time.strftime('%A'),
            'should_avoid':         should_avoid,
            'avoid_reason':         reason if should_avoid else None,
            'alternative_dtes':     [0, 1, 2],
            'config':               self.config,
        }

    def log_recommendation(self, reference_time: Optional[datetime] = None) -> None:
        """Log current DTE recommendation."""
        s = self.get_recommendation_summary(reference_time)
        logger.info(
            f"DTE RECOMMENDATION: {s['recommended_dte']} DTE "
            f"(exp: {s['expiration_date']}, {s['hours_to_expiration']:.1f}h remaining) "
            f"at {s['current_time']}"
        )
        if s['should_avoid']:
            logger.warning(f"DTE WARNING: {s['avoid_reason']}")


def get_default_config() -> DTEConfig:
    """Return default production DTE configuration."""
    return DTEConfig(
        default_dte=0,
        pre_1000_dte=0,
        post_1000_dte=1,
        post_1030_dte=2,
        avoid_wed_0dte=True,
        min_time_value=0.05,
        enable_smart_routing=True,
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    config   = get_default_config()
    selector = DTESelector(config)

    print("\n=== Current Time Test ===")
    selector.log_recommendation()

    test_times = [
        datetime(2026, 3, 3, 9, 30),   # Monday 9:30 AM
        datetime(2026, 3, 3, 10, 15),  # Monday 10:15 AM
        datetime(2026, 3, 3, 10, 45),  # Monday 10:45 AM
        datetime(2026, 3, 3, 14, 30),  # Monday 2:30 PM
        datetime(2026, 3, 5, 9, 30),   # Wednesday 9:30 AM
        datetime(2026, 3, 5, 14, 30),  # Wednesday 2:30 PM
    ]

    print("\n=== Time-of-Day Tests ===")
    for t in test_times:
        s = selector.get_recommendation_summary(t)
        print(f"\n{t.strftime('%A %I:%M %p')}:")
        print(f"  Recommended: {s['recommended_dte']} DTE")
        print(f"  Expiration:  {s['expiration_date']}")
        if s['should_avoid']:
            print(f"  WARNING: {s['avoid_reason']}")
