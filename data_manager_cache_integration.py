"""
COMPATIBILITY STUB - Deprecated

Cache integration is now built into data_manager.py (Phase 2A merge).
This stub maintains backwards compatibility for any external code.

New code should use:
    data_manager.startup_backfill_with_cache(tickers, days=30)
    data_manager.store_bars_with_cache(ticker, bars)
    data_manager.background_cache_sync(tickers)
    data_manager.warmup_cache(tickers, days=60)

This file can be safely deleted after verifying no external dependencies.
"""

from data_manager import data_manager

def startup_backfill_with_cache(dm, tickers, days=30):
    """Deprecated: Use data_manager.startup_backfill_with_cache() instead."""
    print("[DEPRECATED] data_manager_cache_integration.startup_backfill_with_cache() "
          "is deprecated. Use data_manager.startup_backfill_with_cache() instead.")
    return dm.startup_backfill_with_cache(tickers, days)

def store_bars_with_cache(dm, ticker, bars, quiet=False):
    """Deprecated: Use data_manager.store_bars_with_cache() instead."""
    return dm.store_bars_with_cache(ticker, bars, quiet)

def background_cache_sync(dm, tickers):
    """Deprecated: Use data_manager.background_cache_sync() instead."""
    return dm.background_cache_sync(tickers)

def warmup_cache(dm, tickers, days=60):
    """Deprecated: Use data_manager.warmup_cache() instead."""
    return dm.warmup_cache(tickers, days)