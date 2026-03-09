"""Screener Integration Helper - Fixes explosive mover metadata fetching.

Provides safe accessor for screener metadata with proper error handling
and integration with explosive mover tracking.
"""
from typing import Dict, Optional
import traceback


def get_ticker_screener_metadata(ticker: str) -> Dict:
    """Get screener metadata for a ticker with proper error handling.
    
    This function safely retrieves metadata from the dynamic screener,
    handling cases where the screener might not be initialized or
    the ticker might not be in the current scan results.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        Dict with keys:
            - qualified: bool (True if score >= 80 AND rvol >= 4.0)
            - score: int (0-100)
            - rvol: float (relative volume multiplier)
            - tier: str (TIER_1, TIER_2, TIER_3, or None)
    """
    default_metadata = {
        'qualified': False,
        'score': 0,
        'rvol': 0.0,
        'tier': None
    }
    
    try:
        # Import here to avoid circular dependencies
        from app.screening.dynamic_screener import get_screener
        
        # Get the screener instance (singleton)
        screener = get_screener()
        
        if screener is None:
            print(f"[SCREENER-INTEGRATION] Warning: Screener not initialized for {ticker}")
            return default_metadata
        
        # Check if screener has get_top_n_movers method
        if not hasattr(screener, 'get_top_n_movers'):
            print(f"[SCREENER-INTEGRATION] Error: Screener missing get_top_n_movers method")
            return default_metadata
        
        # Get current top movers
        try:
            top_movers = screener.get_top_n_movers(n=100)  # Get enough to find our ticker
        except TypeError:
            # If get_top_n_movers doesn't accept 'n' parameter
            top_movers = screener.get_top_n_movers()
        
        if not top_movers:
            return default_metadata
        
        # Find ticker in movers list
        ticker_data = None
        for mover in top_movers:
            if isinstance(mover, dict) and mover.get('ticker') == ticker:
                ticker_data = mover
                break
            elif hasattr(mover, 'ticker') and mover.ticker == ticker:
                # Handle if movers are objects
                ticker_data = {
                    'ticker': ticker,
                    'score': getattr(mover, 'score', 0),
                    'rvol': getattr(mover, 'rvol', 0.0),
                    'tier': getattr(mover, 'tier', None)
                }
                break
        
        if not ticker_data:
            # Ticker not in current scan results
            return default_metadata
        
        # Extract metadata
        score = ticker_data.get('score', 0)
        rvol = ticker_data.get('rvol', 0.0)
        tier = ticker_data.get('tier', None)
        
        # Check if qualified for explosive override
        # Thresholds: score >= 80 AND rvol >= 4.0
        qualified = (score >= 80 and rvol >= 4.0)
        
        return {
            'qualified': qualified,
            'score': score,
            'rvol': rvol,
            'tier': tier
        }
    
    except Exception as e:
        print(f"[SCREENER-INTEGRATION] EXPLOSIVE Metadata fetch error for {ticker}: {e}")
        print(f"[SCREENER-INTEGRATION] Traceback: {traceback.format_exc()}")
        return default_metadata


def get_screener_instance():
    """Get the screener singleton instance.
    
    Returns:
        DynamicScreener instance or None if not initialized
    """
    try:
        from app.screening.dynamic_screener import get_screener
        return get_screener()
    except Exception as e:
        print(f"[SCREENER-INTEGRATION] Failed to get screener instance: {e}")
        return None


def is_explosive_mover(ticker: str, score_threshold: int = 80, rvol_threshold: float = 4.0) -> bool:
    """Check if ticker qualifies as explosive mover.
    
    Args:
        ticker: Stock ticker symbol
        score_threshold: Minimum score required (default: 80)
        rvol_threshold: Minimum relative volume required (default: 4.0)
    
    Returns:
        True if ticker meets both thresholds
    """
    metadata = get_ticker_screener_metadata(ticker)
    return (metadata['score'] >= score_threshold and 
            metadata['rvol'] >= rvol_threshold)
