"""
Compatibility stubs for watchlist_funnel.py integration.
Adds legacy function names that map to the unified premarket_scanner.py API.

Add this to the END of premarket_scanner.py:
"""

def run_momentum_screener(
    tickers: list,
    min_composite_score: float = 60.0,
    use_cache: bool = True
) -> list:
    """
    Compatibility stub for watchlist_funnel.py.
    Maps to scan_watchlist() with renamed parameters.
    """
    from premarket_scanner import scan_watchlist
    return scan_watchlist(tickers, min_score=min_composite_score)


def get_top_n_movers(scored_tickers: list, n: int = 10) -> list:
    """
    Get top N tickers from scored results.
    Compatibility function for watchlist_funnel.py.
    """
    sorted_tickers = sorted(scored_tickers, key=lambda x: x.get('composite_score', 0), reverse=True)
    return [t['ticker'] for t in sorted_tickers[:n]]


def print_momentum_summary(scored_tickers: list, top_n: int = 10):
    """
    Print formatted summary of top N movers.
    Compatibility function for watchlist_funnel.py.
    """
    if not scored_tickers:
        print("[PREMARKET] No tickers to display")
        return
    
    print(f"\n{'='*80}")
    print(f"TOP {min(top_n, len(scored_tickers))} MOMENTUM MOVERS")
    print(f"{'='*80}")
    print(f"{'Rank':<6} {'Ticker':<8} {'Score':<8} {'RVOL':<8} {'Price':<10} {'Volume':>12}")
    print(f"{'-'*80}")
    
    for i, ticker_data in enumerate(scored_tickers[:top_n], 1):
        rank = f"#{i}"
        ticker = ticker_data.get('ticker', 'N/A')
        score = ticker_data.get('composite_score', 0)
        rvol = ticker_data.get('rvol', 0)
        price = ticker_data.get('price', 0)
        volume = ticker_data.get('volume', 0)
        
        print(f"{rank:<6} {ticker:<8} {score:<8.1f} {rvol:<8.2f} ${price:<9.2f} {volume:>12,}")
    
    print(f"{'='*80}\n")


def get_cache_stats() -> dict:
    """Return cache statistics for monitoring."""
    from premarket_scanner import _scanner_cache
    return _scanner_cache.get_stats()
