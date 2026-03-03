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


def get_gate_status(or_range_pct: float, now_et: datetime) -> dict:
    """
    Get detailed gate status for debugging/logging.
    
    Args:
        or_range_pct: Opening Range as percentage
        now_et: Current time in Eastern Time
    
    Returns:
        dict with gate status details
    """
    current_time = now_et.time()
    gate_end_time = time(9, 40)
    is_before_940 = current_time < gate_end_time
    
    should_block = should_skip_cfw6_or_early(or_range_pct, now_et)
    
    return {
        'current_time': current_time.strftime('%H:%M:%S'),
        'gate_active': is_before_940,
        'or_range_pct': or_range_pct,
        'threshold_pct': config.MIN_OR_RANGE_PCT,
        'or_sufficient': or_range_pct >= config.MIN_OR_RANGE_PCT,
        'should_block': should_block,
        'reason': _get_block_reason(is_before_940, or_range_pct >= config.MIN_OR_RANGE_PCT, should_block)
    }


def _get_block_reason(is_before_940: bool, or_sufficient: bool, should_block: bool) -> str:
    """Generate human-readable reason for gate decision."""
    if not is_before_940:
        return "Gate inactive (after 9:40 AM) - all OR sizes allowed"
    
    if should_block:
        return f"Gate active (before 9:40 AM) - OR < {config.MIN_OR_RANGE_PCT:.1%} blocked"
    
    return f"Gate active (before 9:40 AM) - OR >= {config.MIN_OR_RANGE_PCT:.1%} allowed"


if __name__ == '__main__':
    # Test cases
    from zoneinfo import ZoneInfo
    
    ET = ZoneInfo('America/New_York')
    
    # Test 1: 9:35 AM with 2% OR (should BLOCK)
    test_time_1 = datetime(2026, 3, 3, 9, 35, tzinfo=ET)
    test_or_1 = 0.02
    result_1 = should_skip_cfw6_or_early(test_or_1, test_time_1)
    status_1 = get_gate_status(test_or_1, test_time_1)
    print(f"Test 1 (9:35 AM, OR=2%): Block={result_1} (expected True)")
    print(f"  Status: {status_1}")
    
    # Test 2: 9:35 AM with 4% OR (should ALLOW)
    test_time_2 = datetime(2026, 3, 3, 9, 35, tzinfo=ET)
    test_or_2 = 0.04
    result_2 = should_skip_cfw6_or_early(test_or_2, test_time_2)
    status_2 = get_gate_status(test_or_2, test_time_2)
    print(f"\nTest 2 (9:35 AM, OR=4%): Block={result_2} (expected False)")
    print(f"  Status: {status_2}")
    
    # Test 3: 9:45 AM with 2% OR (should ALLOW - gate inactive)
    test_time_3 = datetime(2026, 3, 3, 9, 45, tzinfo=ET)
    test_or_3 = 0.02
    result_3 = should_skip_cfw6_or_early(test_or_3, test_time_3)
    status_3 = get_gate_status(test_or_3, test_time_3)
    print(f"\nTest 3 (9:45 AM, OR=2%): Block={result_3} (expected False)")
    print(f"  Status: {status_3}")
    
    # Test 4: 9:40 AM exactly with 2% OR (should ALLOW - gate just ended)
    test_time_4 = datetime(2026, 3, 3, 9, 40, tzinfo=ET)
    test_or_4 = 0.02
    result_4 = should_skip_cfw6_or_early(test_or_4, test_time_4)
    status_4 = get_gate_status(test_or_4, test_time_4)
    print(f"\nTest 4 (9:40 AM, OR=2%): Block={result_4} (expected False)")
    print(f"  Status: {status_4}")
