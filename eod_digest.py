"""
COMPATIBILITY STUB - Deprecated

EOD digest functionality has been consolidated into reporting.py (Phase 2C).
This stub maintains backwards compatibility for any code that imports from eod_digest.

New code should use:
    from reporting import digest_manager, send_pnl_digest
    # OR
    from reporting import EODDigestManager

This file can be safely deleted after verifying no external dependencies.

PHASE 2C: Consolidated eod_digest.py + pnl_digest.py → reporting.py
Benefits:
  - 50% file reduction (2 → 1)
  - Eliminated ~50 lines of duplicate P&L calculation logic
  - Single source of truth for all reporting
  - Unified import path
"""

from reporting import EODDigestManager, send_pnl_digest

# Maintain original API
digest_manager = EODDigestManager()

__all__ = [
    'EODDigestManager',
    'digest_manager',
    'send_pnl_digest'
]
