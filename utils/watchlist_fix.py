"""
Watchlist Processing Fix - Eliminates Ellipsis Iteration Error

This module provides safe watchlist processing that prevents
the 'ellipsis object is not iterable' error.
"""
from typing import List, Dict, Optional, Union, Any
import logging

logger = logging.getLogger(__name__)


class SafeWatchlistProcessor:
    """
    Safe watchlist processor that handles edge cases and prevents ellipsis iteration errors
    """
    
    @staticmethod
    def ensure_iterable(value: Any, default: Optional[List] = None) -> List:
        """
        Ensure a value is iterable, converting ellipsis and other non-iterables to empty list
        
        Args:
            value: Value to check
            default: Default value to return if value is not iterable
        
        Returns:
            List: Iterable list
        """
        # Handle ellipsis explicitly
        if value is Ellipsis or value is ...:
            logger.warning("[WATCHLIST] Detected ellipsis placeholder, converting to empty list")
            return default if default is not None else []
        
        # Handle None
        if value is None:
            return default if default is not None else []
        
        # Handle already iterable types (but not strings)
        if isinstance(value, (list, tuple, set)):
            return list(value)
        
        # Handle strings (don't iterate over characters)
        if isinstance(value, str):
            return [value]
        
        # Try to convert to list
        try:
            return list(value)
        except TypeError:
            logger.warning(f"[WATCHLIST] Could not convert {type(value)} to list, using default")
            return default if default is not None else []
    
    @staticmethod
    def process_watchlist(watchlist: Any, min_score: float = 25.0) -> List[str]:
        """
        Safely process watchlist, handling ellipsis and invalid data
        
        Args:
            watchlist: Watchlist data (could be list, ellipsis, None, etc.)
            min_score: Minimum score threshold
        
        Returns:
            List[str]: List of ticker symbols
        """
        try:
            # Ensure watchlist is iterable
            watchlist = SafeWatchlistProcessor.ensure_iterable(watchlist)
            
            if not watchlist:
                logger.info("[WATCHLIST] Empty watchlist, no tickers to process")
                return []
            
            # Extract ticker symbols
            tickers = []
            for item in watchlist:
                if isinstance(item, str):
                    # Already a ticker string
                    tickers.append(item)
                elif isinstance(item, dict):
                    # Dict with 'ticker' or 'symbol' key
                    ticker = item.get('ticker') or item.get('symbol')
                    if ticker:
                        tickers.append(ticker)
                elif hasattr(item, 'ticker'):
                    # Object with ticker attribute
                    tickers.append(item.ticker)
                else:
                    logger.warning(f"[WATCHLIST] Unknown watchlist item type: {type(item)}")
            
            logger.info(f"[WATCHLIST] Processed {len(tickers)} tickers from watchlist")
            return tickers
        
        except Exception as e:
            logger.error(f"[WATCHLIST] Error processing watchlist: {e}")
            logger.error(f"[WATCHLIST] Watchlist type: {type(watchlist)}")
            logger.error(f"[WATCHLIST] Watchlist value: {watchlist}")
            return []
    
    @staticmethod
    def validate_ticker_list(tickers: Any) -> List[str]:
        """
        Validate and clean ticker list
        
        Args:
            tickers: Ticker list (may contain ellipsis or invalid data)
        
        Returns:
            List[str]: Validated list of ticker symbols
        """
        tickers = SafeWatchlistProcessor.ensure_iterable(tickers)
        
        validated = []
        for ticker in tickers:
            if isinstance(ticker, str) and ticker.strip():
                # Valid ticker string
                validated.append(ticker.strip().upper())
            elif isinstance(ticker, dict):
                # Extract from dict
                t = ticker.get('ticker') or ticker.get('symbol')
                if t and isinstance(t, str):
                    validated.append(t.strip().upper())
        
        return validated
