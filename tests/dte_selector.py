#!/usr/bin/env python3
"""
DTE Selector Module
Intelligent Days-To-Expiration selection based on time of day and market conditions.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class DTEConfig:
    """Configuration for DTE selection logic"""
    default_dte: int = 0
    pre_1000_dte: int = 0
    post_1000_dte: int = 1
    post_1030_dte: int = 2
    avoid_wed_0dte: bool = True
    min_time_value: float = 0.05
    enable_smart_routing: bool = True

class DTESelector:
    """Selects optimal DTE based on time of day and market conditions"""
    
    def __init__(self, config: DTEConfig):
        self.config = config
        logger.info(f"DTE Selector initialized: {config}")
    
    def select_dte(self, reference_time: Optional[datetime] = None) -> int:
        """
        Select optimal DTE based on current time and rules
        
        Args:
            reference_time: Optional time for backtesting (defaults to now)
        
        Returns:
            Selected DTE (0, 1, or 2+)
        """
        if reference_time is None:
            reference_time = datetime.now()
        
        current_hour = reference_time.hour
        current_minute = reference_time.minute
        day_of_week = reference_time.weekday()  # 0=Monday, 6=Sunday
        
        # Wednesday 0DTE avoidance (if enabled)
        if day_of_week == 2 and self.config.avoid_wed_0dte:
            logger.info("DTE Avoiding Wednesday 0DTE - using 1DTE minimum")
            return max(1, self.config.default_dte)
        
        # Pre-market and early morning (before 10:00 AM)
        if current_hour < 10:
            dte = self.config.pre_1000_dte
            logger.debug(f"DTE Pre-1000 selection: {dte}DTE at {current_hour:02d}:{current_minute:02d}")
            return dte
        
        # Early session (10:00-10:30 AM)
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
        """
        Calculate expiration date for given DTE
        
        Args:
            dte: Days to expiration (0, 1, 2, etc.)
            reference_time: Optional reference time for calculation
        
        Returns:
            Expiration datetime (4:00 PM on expiration day) or None if invalid
        """
        if reference_time is None:
            reference_time = datetime.now()
        
        # Start from today
        expiration_date = reference_time.date()
        
        # Add DTE days
        expiration_date += timedelta(days=dte)
        
        # Skip weekends - move to next Monday if needed
        while expiration_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            expiration_date += timedelta(days=1)
        
        # Set expiration time to 4:00 PM (market close)
        expiration = datetime.combine(expiration_date, time(16, 0, 0))
        
        return expiration
    
    def get_time_to_expiration(self, expiration: datetime, reference_time: Optional[datetime] = None) -> float:
        """
        Calculate hours remaining until expiration
        
        Args:
            expiration: Expiration datetime
            reference_time: Optional reference time
        
        Returns:
            Hours remaining (float)
        """
        if reference_time is None:
            reference_time = datetime.now()
        
        delta = expiration - reference_time
        return delta.total_seconds() / 3600
    
    def should_avoid_dte(self, dte: int, reference_time: Optional[datetime] = None) -> tuple[bool, str]:
        """
        Check if a specific DTE should be avoided
        
        Args:
            dte: DTE to check
            reference_time: Optional reference time
        
        Returns:
            Tuple of (should_avoid: bool, reason: str)
        """
        if reference_time is None:
            reference_time = datetime.now()
        
        # Check Wednesday 0DTE avoidance
        if dte == 0 and reference_time.weekday() == 2 and self.config.avoid_wed_0dte:
            return (True, "Wednesday 0DTE avoided by config")
        
        # Check if expiration is too close (< 30 minutes)
        expiration = self.get_expiration_for_dte(dte, reference_time)
        if expiration:
            hours_remaining = self.get_time_to_expiration(expiration, reference_time)
            if hours_remaining < 0.5:
                return (True, f"Only {hours_remaining:.1f} hours until expiration")
        
        return (False, "DTE acceptable")
    
    def get_recommendation_summary(self, reference_time: Optional[datetime] = None) -> dict:
        """
        Get current DTE recommendation with full context
        
        Args:
            reference_time: Optional reference time for analysis
        
        Returns:
            Dictionary with recommendation details
        """
        if reference_time is None:
            reference_time = datetime.now()
        
        recommended_dte = self.select_dte(reference_time)
        expiration = self.get_expiration_for_dte(recommended_dte, reference_time)
        should_avoid, avoid_reason = self.should_avoid_dte(recommended_dte, reference_time)
        
        summary = {
            'recommended_dte': recommended_dte,
            'expiration_date': expiration.date() if expiration else None,
            'expiration_time': expiration if expiration else None,
            'hours_to_expiration': self.get_time_to_expiration(expiration, reference_time) if expiration else None,
            'current_time': reference_time.strftime('%Y-%m-%d %H:%M:%S'),
            'day_of_week': reference_time.strftime('%A'),
            'should_avoid': should_avoid,
            'avoid_reason': avoid_reason if should_avoid else None,
            'alternative_dtes': [0, 1, 2],
            'config': self.config
        }
        
        return summary
    
    def log_recommendation(self, reference_time: Optional[datetime] = None) -> None:
        """
        Log current DTE recommendation to logger
        
        Args:
            reference_time: Optional reference time
        """
        summary = self.get_recommendation_summary(reference_time)
        
        logger.info(
            f"DTE RECOMMENDATION: {summary['recommended_dte']} DTE "
            f"(exp: {summary['expiration_date']}, "
            f"{summary['hours_to_expiration']:.1f}h remaining) "
            f"at {summary['current_time']}"
        )
        
        if summary['should_avoid']:
            logger.warning(f"DTE WARNING: {summary['avoid_reason']}")


def get_default_config() -> DTEConfig:
    """
    Get default production DTE configuration
    
    Returns:
        DTEConfig with production defaults
    """
    return DTEConfig(
        default_dte=0,
        pre_1000_dte=0,
        post_1000_dte=1,
        post_1030_dte=2,
        avoid_wed_0dte=True,
        min_time_value=0.05,
        enable_smart_routing=True
    )


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    config = get_default_config()
    selector = DTESelector(config)
    
    # Test current time
    print("\n=== Current Time Test ===")
    selector.log_recommendation()
    
    # Test different times of day
    test_times = [
        datetime(2026, 3, 3, 9, 30),   # Monday 9:30 AM
        datetime(2026, 3, 3, 10, 15),  # Monday 10:15 AM
        datetime(2026, 3, 3, 10, 45),  # Monday 10:45 AM
        datetime(2026, 3, 3, 14, 30),  # Monday 2:30 PM
        datetime(2026, 3, 5, 9, 30),   # Wednesday 9:30 AM
        datetime(2026, 3, 5, 14, 30),  # Wednesday 2:30 PM
    ]
    
    print("\n=== Time-of-Day Tests ===")
    for test_time in test_times:
        summary = selector.get_recommendation_summary(test_time)
        print(f"\n{test_time.strftime('%A %I:%M %p')}:")
        print(f"  Recommended: {summary['recommended_dte']} DTE")
        print(f"  Expiration: {summary['expiration_date']}")
        if summary['should_avoid']:
            print(f"  WARNING: {summary['avoid_reason']}")
