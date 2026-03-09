"""
TEMPORARY STUB FUNCTIONS FOR SCANNER COMPATIBILITY

These functions are temporary placeholders that scanner.py expects to import.
They should be moved into sniper.py or properly implemented.

PHASE 1.14 (MAR 9, 2026):
- Added process_ticker stub
- Added clear_armed_signals stub  
- Added clear_watching_signals stub

TODO: Implement actual BOS/FVG signal detection logic
"""
import logging

logger = logging.getLogger(__name__)

def process_ticker(ticker: str) -> dict:
    """
    Stub function - placeholder for signal processing.
    Scanner expects this function to exist.
    
    Args:
        ticker: Stock symbol to process
        
    Returns:
        Signal dictionary if signal detected, None otherwise
        
    TODO: Implement BOS/FVG signal detection logic here.
    """
    logger.debug(f"[STUB] process_ticker called for {ticker} - not implemented yet")
    return None

def clear_armed_signals():
    """
    Stub function - placeholder for clearing armed signals state.
    
    TODO: Implement signal state management.
    """
    logger.debug("[STUB] clear_armed_signals called - not implemented yet")
    pass

def clear_watching_signals():
    """
    Stub function - placeholder for clearing watching signals state.
    
    TODO: Implement signal state management.
    """
    logger.debug("[STUB] clear_watching_signals called - not implemented yet")
    pass
