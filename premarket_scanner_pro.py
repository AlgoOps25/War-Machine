"""
COMPATIBILITY STUB - Deprecated

This module has been consolidated into premarket_scanner.py
Imports are redirected for backwards compatibility.

New code should import from premarket_scanner.py directly:
    from premarket_scanner import scan_ticker, scan_watchlist

This stub will be removed in a future release.
"""

# Redirect all imports to unified module
from premarket_scanner import (
    calculate_relative_volume,
    calculate_dollar_volume,
    score_volume_quality,
    fetch_fundamental_data,
    scan_ticker,
    scan_watchlist,
    get_cache_stats,
    clear_cache,
)

print("[DEPRECATED] premarket_scanner_pro.py is deprecated. Use premarket_scanner.py instead.")
