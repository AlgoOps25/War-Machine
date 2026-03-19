"""
Regular Trading Hours (RTH) Filter

Gates signal generation to valid trading windows:
  - Blocks pre-market noise (before 9:30 ET)
  - Blocks after-hours trading (after 16:00 ET)
  - Blocks the chaotic first 5 minutes (9:30-9:35 ET) — optional
  - Blocks the last 5 minutes (15:55-16:00 ET) — optional
  - Blocks known low-quality windows (lunch 12:00-13:30) — optional

Design:
  - Single is_rth() function for quick gate checks in hot loops
  - RTHFilter class with configurable window policy
  - All times in US/Eastern timezone

Usage:
    from app.filters.rth_filter import is_rth, RTHFilter

    # Simple gate (used in scanner/sniper hot path)
    if not is_rth():
        return  # Skip signal generation outside market hours

    # Policy-driven (used in sniper for fine-grained control)
    rth = RTHFilter(block_open_chop=True, block_lunch=False, block_close_chop=True)
    if not rth.passes(signal_time):
        return

CREATED: app/filters/rth_filter.py
See docs/RTH_FILTER_INTEGRATION.md for integration details.
"""

from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

MARKET_OPEN  = dtime(9, 30)   # Regular session open
MARKET_CLOSE = dtime(16, 0)   # Regular session close
OPEN_CHOP_END  = dtime(9, 35)   # End of open chop window
CLOSE_CHOP_START = dtime(15, 55)  # Start of close chop window
LUNCH_START  = dtime(12, 0)   # Lunch drift start
LUNCH_END    = dtime(13, 30)  # Lunch drift end


# ═══════════════════════════════════════════════════════════════════════════
# SIMPLE FUNCTION GATE (hot-path friendly)
# ═══════════════════════════════════════════════════════════════════════════

def is_rth(dt: Optional[datetime] = None) -> bool:
    """
    Check if the given datetime (or now) falls within Regular Trading Hours.

    Does NOT block open/close chop or lunch — use RTHFilter for that.
    This is the fast gate used in scanner and sniper hot loops.

    Args:
        dt: Datetime to check (default: now in ET)

    Returns:
        True if within 9:30-16:00 ET, False otherwise
    """
    if dt is None:
        dt = datetime.now(ET)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)

    t = dt.time()
    return MARKET_OPEN <= t < MARKET_CLOSE


def is_pre_market(dt: Optional[datetime] = None) -> bool:
    """True if before 9:30 ET."""
    if dt is None:
        dt = datetime.now(ET)
    return dt.time() < MARKET_OPEN


def is_after_hours(dt: Optional[datetime] = None) -> bool:
    """True if at or after 16:00 ET."""
    if dt is None:
        dt = datetime.now(ET)
    return dt.time() >= MARKET_CLOSE


def minutes_since_open(dt: Optional[datetime] = None) -> int:
    """
    Minutes elapsed since 9:30 ET open.
    Returns 0 if before open, negative not possible (clamped to 0).
    """
    if dt is None:
        dt = datetime.now(ET)
    t = dt.time()
    if t < MARKET_OPEN:
        return 0
    elapsed = (t.hour * 60 + t.minute) - (9 * 60 + 30)
    return max(0, elapsed)


def minutes_to_close(dt: Optional[datetime] = None) -> int:
    """
    Minutes remaining until 16:00 ET close.
    Returns 0 if at or after close.
    """
    if dt is None:
        dt = datetime.now(ET)
    t = dt.time()
    if t >= MARKET_CLOSE:
        return 0
    remaining = (16 * 60) - (t.hour * 60 + t.minute)
    return max(0, remaining)


# ═══════════════════════════════════════════════════════════════════════════
# RTHFilter CLASS — configurable policy
# ═══════════════════════════════════════════════════════════════════════════

class RTHFilter:
    """
    Configurable Regular Trading Hours filter.

    Policies:
      block_open_chop:  Block 9:30-9:35 (chaotic open, default True)
      block_lunch:      Block 12:00-13:30 low-volume drift (default False)
      block_close_chop: Block 15:55-16:00 end-of-day noise (default True)

    Usage:
        rth = RTHFilter(block_open_chop=True, block_lunch=False, block_close_chop=True)
        if not rth.passes():
            return  # Skip signal
    """

    def __init__(
        self,
        block_open_chop: bool = True,
        block_lunch: bool = False,
        block_close_chop: bool = True
    ):
        self.block_open_chop  = block_open_chop
        self.block_lunch      = block_lunch
        self.block_close_chop = block_close_chop

    def passes(self, dt: Optional[datetime] = None) -> bool:
        """
        Returns True if signal should be allowed at the given time.

        Args:
            dt: Datetime to check (default: now in ET)

        Returns:
            True = allowed, False = blocked
        """
        if dt is None:
            dt = datetime.now(ET)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)

        t = dt.time()

        # Must be within core RTH first
        if not (MARKET_OPEN <= t < MARKET_CLOSE):
            return False

        # Open chop gate
        if self.block_open_chop and t < OPEN_CHOP_END:
            return False

        # Lunch drift gate
        if self.block_lunch and LUNCH_START <= t < LUNCH_END:
            return False

        # Close chop gate
        if self.block_close_chop and t >= CLOSE_CHOP_START:
            return False

        return True

    def get_window_label(self, dt: Optional[datetime] = None) -> str:
        """
        Return human-readable label for the current trading window.

        Returns:
            'pre_market' | 'open_chop' | 'morning' | 'lunch' |
            'afternoon' | 'close_chop' | 'after_hours'
        """
        if dt is None:
            dt = datetime.now(ET)
        t = dt.time()

        if t < MARKET_OPEN:
            return 'pre_market'
        if t < OPEN_CHOP_END:
            return 'open_chop'
        if LUNCH_START <= t < LUNCH_END:
            return 'lunch'
        if t >= CLOSE_CHOP_START:
            return 'close_chop'
        if t >= MARKET_CLOSE:
            return 'after_hours'
        return 'morning' if t < dtime(12, 0) else 'afternoon'

    def __repr__(self) -> str:
        return (
            f"RTHFilter(block_open_chop={self.block_open_chop}, "
            f"block_lunch={self.block_lunch}, "
            f"block_close_chop={self.block_close_chop})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON (default policy)
# ═══════════════════════════════════════════════════════════════════════════

# Default filter: block open chop + close chop, allow lunch
_default_rth_filter = RTHFilter(block_open_chop=True, block_lunch=False, block_close_chop=True)


def passes_rth_filter(dt: Optional[datetime] = None) -> bool:
    """
    Check default RTH filter policy (block open + close chop, allow lunch).
    Drop-in replacement for is_rth() when chop windows should be blocked.
    """
    return _default_rth_filter.passes(dt)


def get_window_label(dt: Optional[datetime] = None) -> str:
    """Get current trading window label using default filter."""
    return _default_rth_filter.get_window_label(dt)


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")

    test_times = [
        (8, 0,  'Pre-market'),
        (9, 29, 'Just before open'),
        (9, 32, 'Open chop'),
        (9, 36, 'Morning session'),
        (12, 15, 'Lunch'),
        (14, 0,  'Afternoon'),
        (15, 57, 'Close chop'),
        (16, 1,  'After hours'),
    ]

    rth = RTHFilter(block_open_chop=True, block_lunch=False, block_close_chop=True)

    logger.info("RTH Filter Tests")
    logger.info("-" * 50)
    for h, m, label in test_times:
        dt = datetime.now(ET).replace(hour=h, minute=m, second=0, microsecond=0)
        result  = rth.passes(dt)
        window  = rth.get_window_label(dt)
        is_rth_val = is_rth(dt)
        mins_open  = minutes_since_open(dt)
        mins_close = minutes_to_close(dt)
        status = '✅ PASS' if result else '❌ BLOCK'
        logger.info(f"{label:20s} {h:02d}:{m:02d} | RTH:{is_rth_val} | Filter:{status} | Window:{window} | +{mins_open}m open | -{mins_close}m close")
