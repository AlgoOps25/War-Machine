"""Early Session Disqualifier - Task 2

Blocks CFW6_OR signals before 9:40 AM ET if the Opening Range is less than 3%.
Prevents premature entries during choppy/narrow OR formation periods.

Logic:
- Before 9:40 AM: OR must be >= 3% for CFW6_OR signals (gate active)
- After 9:40 AM: All OR sizes valid (gate inactive, market has "spoken")

Integration Point: app/core/sniper.py process_ticker() after OR validation

Author: Michael Perez
Date: 2026-03-03
"""

from datetime import time, datetime
from zoneinfo import ZoneInfo
from utils import config


def should_skip_cfw6_or_early(or_range_pct: float, now_et: datetime) -> bool:
    """
    Determine if a CFW6_OR signal should be blocked based on time and OR range.
    
    Args:
        or_range_pct: Opening Range as percentage (e.g., 0.025 = 2.5%)
        now_et: Current time in Eastern Time (timezone-aware datetime)
    
    Returns:
        True if signal should be BLOCKED (skipped)
        False if signal should proceed
    
    Gate Logic:
    - Before 9:40 AM + OR < 3% -> BLOCK (return True)
    - Before 9:40 AM + OR >= 3% -> ALLOW (return False)
    - After 9:40 AM -> ALLOW regardless of OR size (return False)
    """
    
    # Extract time component for comparison
    current_time = now_et.time()
    
    # Gate only active before 9:40 AM ET
    gate_end_time = time(9, 40)
    
    if current_time >= gate_end_time:
        # After 9:40 AM - gate inactive, allow all OR sizes
        return False
    
    # Before 9:40 AM - check OR range threshold
    if or_range_pct < config.MIN_OR_RANGE_PCT:
        # OR too narrow during gate window - BLOCK
        return True
    
    # Before 9:40 AM but OR >= 3% - ALLOW
    return False


if __name__ == '__main__':
    # Quick test
    from zoneinfo import ZoneInfo
    
    ET = ZoneInfo('America/New_York')
    
    # Test 1: 9:35 AM with 2% OR (should BLOCK)
    test_time_1 = datetime(2026, 3, 3, 9, 35, tzinfo=ET)
    result_1 = should_skip_cfw6_or_early(0.02, test_time_1)
    print(f"Test 1 (9:35 AM, OR=2%): Block={result_1} (expected True) {'✅' if result_1 == True else '❌'}")
    
    # Test 2: 9:35 AM with 4% OR (should ALLOW)
    test_time_2 = datetime(2026, 3, 3, 9, 35, tzinfo=ET)
    result_2 = should_skip_cfw6_or_early(0.04, test_time_2)
    print(f"Test 2 (9:35 AM, OR=4%): Block={result_2} (expected False) {'✅' if result_2 == False else '❌'}")
    
    # Test 3: 9:45 AM with 2% OR (should ALLOW)
    test_time_3 = datetime(2026, 3, 3, 9, 45, tzinfo=ET)
    result_3 = should_skip_cfw6_or_early(0.02, test_time_3)
    print(f"Test 3 (9:45 AM, OR=2%): Block={result_3} (expected False) {'✅' if result_3 == False else '❌'}")
    
    # Test 4: 9:40 AM exactly with 2% OR (should ALLOW)
    test_time_4 = datetime(2026, 3, 3, 9, 40, tzinfo=ET)
    result_4 = should_skip_cfw6_or_early(0.02, test_time_4)
    print(f"Test 4 (9:40 AM, OR=2%): Block={result_4} (expected False) {'✅' if result_4 == False else '❌'}")
