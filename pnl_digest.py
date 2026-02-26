"""
COMPATIBILITY STUB - Deprecated

Daily P&L digest functionality has been consolidated into reporting.py (Phase 2C).
This stub maintains backwards compatibility for any code that imports from pnl_digest.

New code should use:
    from reporting import send_pnl_digest
    # OR
    from reporting import DailyReporter

This file can be safely deleted after verifying no external dependencies.

PHASE 2C: Consolidated eod_digest.py + pnl_digest.py → reporting.py
Benefits:
  - 50% file reduction (2 → 1)
  - Eliminated duplicate P&L calculation and formatting logic
  - Single source of truth for Discord digests
  - Unified reporting interface
"""

from reporting import send_pnl_digest, DailyReporter

# Maintain original functions for backwards compatibility
def build_pnl_summary():
    """Deprecated: Use DailyReporter().build_pnl_summary() instead."""
    reporter = DailyReporter()
    return reporter.build_pnl_summary()

def format_discord_digest(summary: dict) -> str:
    """Deprecated: Use DailyReporter().format_discord_digest() instead."""
    reporter = DailyReporter()
    return reporter.format_discord_digest(summary)

__all__ = [
    'send_pnl_digest',
    'build_pnl_summary',
    'format_discord_digest',
    'DailyReporter'
]
