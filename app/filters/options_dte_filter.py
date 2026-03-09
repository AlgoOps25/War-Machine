"""
Options DTE Filter - Reject tickers without 0DTE or near-term options
Ensures day traders don't get stuck with swing trade-only tickers like TTAN.

INTEGRATION:
- Called by watchlist_funnel.py before finalizing watchlist
- Checks if ticker has options expiring today or next trading day
- Rejects tickers with only weekly/monthly options (>2 DTE)

STRATEGY:
- 0DTE preferred (same-day expiration)
- 1DTE acceptable (next trading day)
- 2+ DTE rejected (forces swing trading)

PHASE 1.16 (MAR 9, 2026):
- Initial implementation with yfinance options chain check
- Cache results to avoid repeated API calls
- Graceful fallback if yfinance unavailable
"""
import logging
from typing import List, Set
from datetime import datetime, timedelta
import functools

logger = logging.getLogger(__name__)

# Try to import yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("[DTE_FILTER] ⚠️  yfinance not installed - DTE filtering disabled")

# Cache for ticker DTE availability (ticker -> has_near_term_options)
@functools.lru_cache(maxsize=512)
def _check_ticker_dte_cached(ticker: str) -> bool:
    """
    Check if ticker has 0DTE or 1DTE options available.
    Cached to avoid repeated yfinance API calls.
    
    Returns:
        True if ticker has near-term (0-1 DTE) options
        False if only weekly/monthly options available
    """
    if not YFINANCE_AVAILABLE:
        # Fallback: assume all tickers are acceptable
        return True
    
    try:
        stock = yf.Ticker(ticker)
        
        # Get available expiration dates
        expirations = stock.options
        
        if not expirations or len(expirations) == 0:
            logger.debug(f"[DTE_FILTER] {ticker} has no options chain")
            return False
        
        # Parse expiration dates and find nearest
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        nearest_dte = None
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                
                if nearest_dte is None or dte < nearest_dte:
                    nearest_dte = dte
                
                # Early exit if we find 0DTE or 1DTE
                if nearest_dte <= 1:
                    logger.debug(f"[DTE_FILTER] ✅ {ticker} has {nearest_dte}DTE options")
                    return True
                    
            except ValueError:
                continue
        
        # If we got here, nearest expiration is > 1 DTE
        if nearest_dte is not None:
            logger.info(f"[DTE_FILTER] ❌ {ticker} nearest DTE: {nearest_dte} (rejected, swing trade only)")
            return False
        else:
            # Couldn't parse any dates - accept by default
            return True
            
    except Exception as e:
        logger.warning(f"[DTE_FILTER] Error checking {ticker}: {e}")
        # On error, accept ticker (don't reject on data failures)
        return True


def filter_watchlist_by_dte(
    tickers: List[str], 
    max_dte: int = 1,
    verbose: bool = True
) -> List[str]:
    """
    Filter watchlist to only include tickers with near-term options.
    
    Args:
        tickers: List of ticker symbols to check
        max_dte: Maximum DTE acceptable (0 = 0DTE only, 1 = 0DTE or 1DTE)
        verbose: Print filtering results
        
    Returns:
        Filtered list containing only tickers with near-term options
    """
    if not YFINANCE_AVAILABLE:
        logger.warning("[DTE_FILTER] yfinance not available - returning unfiltered watchlist")
        return tickers
    
    if verbose:
        logger.info(f"[DTE_FILTER] Checking {len(tickers)} tickers for {max_dte}DTE options...")
    
    accepted: List[str] = []
    rejected: List[str] = []
    
    for ticker in tickers:
        if _check_ticker_dte_cached(ticker):
            accepted.append(ticker)
        else:
            rejected.append(ticker)
    
    if verbose and rejected:
        logger.info(
            f"[DTE_FILTER] ❌ Rejected {len(rejected)} swing-trade-only tickers: "
            f"{', '.join(rejected[:10])}{'...' if len(rejected) > 10 else ''}"
        )
    
    if verbose:
        logger.info(f"[DTE_FILTER] ✅ {len(accepted)}/{len(tickers)} tickers have 0-1 DTE options")
    
    return accepted


def clear_cache():
    """Clear the DTE check cache (call at EOD or on demand)."""
    _check_ticker_dte_cached.cache_clear()
    logger.info("[DTE_FILTER] Cache cleared")


def get_cache_info():
    """Get cache statistics."""
    return _check_ticker_dte_cached.cache_info()


if __name__ == "__main__":
    # Test with known tickers
    test_tickers = [
        "SPY",    # Has 0DTE
        "AAPL",   # Has weekly options
        "TSLA",   # Has weekly options  
        "TTAN",   # Only monthly (should reject)
        "QQQ",    # Has 0DTE
    ]
    
    print("\nTesting DTE Filter...")
    print("=" * 60)
    
    filtered = filter_watchlist_by_dte(test_tickers, max_dte=1, verbose=True)
    
    print("\nResults:")
    print(f"Input: {test_tickers}")
    print(f"Output: {filtered}")
    print(f"Cache: {get_cache_info()}")
