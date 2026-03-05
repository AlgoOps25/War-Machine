"""
Correlation Checker - SPY Correlation Analysis

This module checks if a ticker's move is market-driven (high SPY correlation)
or ticker-specific (low SPY correlation).

High SPY Correlation (>0.7):
- Ticker is moving WITH the market
- Less likely to be a ticker-specific breakout
- Reduce confidence (market momentum trade)

Low SPY Correlation (<0.3):
- Ticker is moving INDEPENDENTLY
- More likely to be a genuine ticker catalyst
- Boost confidence (ticker-specific setup)

Divergence Detection:
- Ticker breaks out while SPY is flat/ranging
- Highest conviction signals
- Maximum confidence boost

Usage:
    from app.filters.correlation import check_spy_correlation
    
    result = check_spy_correlation("NVDA", lookback_bars=20)
    # Returns: {
    #     'correlation': 0.35,
    #     'ticker_strength': 'independent',
    #     'confidence_adjustment': +5,
    #     'reason': 'Low SPY correlation - ticker-specific move'
    # }
"""
import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)


def check_spy_correlation(
    ticker: str,
    lookback_bars: int = 20,
    timeframe: str = '5m'
) -> dict:
    """
    Calculate SPY correlation for a ticker over recent bars.
    
    Args:
        ticker: Stock symbol to analyze
        lookback_bars: Number of bars to calculate correlation (default 20)
        timeframe: Timeframe for bars (default 5m)
    
    Returns:
        dict: {
            'correlation': float (0-1),
            'ticker_strength': str ('market_driven', 'independent', 'divergent'),
            'confidence_adjustment': int (-10 to +10),
            'reason': str
        }
    """
    try:
        # Fetch price data for ticker and SPY
        ticker_returns = _get_returns(ticker, lookback_bars, timeframe)
        spy_returns = _get_returns('SPY', lookback_bars, timeframe)
        
        if ticker_returns is None or spy_returns is None:
            logger.warning(
                f"[CORRELATION] Failed to fetch data for {ticker} or SPY",
                extra={'component': 'correlation', 'symbol': ticker}
            )
            return {
                'correlation': 0.5,
                'ticker_strength': 'unknown',
                'confidence_adjustment': 0,
                'reason': 'Correlation data unavailable'
            }
        
        # Calculate correlation coefficient
        correlation = np.corrcoef(ticker_returns, spy_returns)[0, 1]
        
        # Handle NaN correlation (can happen with flat prices)
        if np.isnan(correlation):
            correlation = 0.0
        
        # Analyze correlation strength
        if abs(correlation) > 0.7:
            # High correlation - market-driven move
            return {
                'correlation': correlation,
                'ticker_strength': 'market_driven',
                'confidence_adjustment': -5,
                'reason': f'High SPY correlation ({correlation:.2f}) - market-driven move'
            }
        
        elif abs(correlation) < 0.3:
            # Low correlation - ticker-specific move
            # Check for divergence (ticker strong, SPY weak)
            ticker_momentum = sum(ticker_returns[-5:])  # Last 5 bars
            spy_momentum = sum(spy_returns[-5:])
            
            if ticker_momentum > 0.02 and abs(spy_momentum) < 0.01:
                # Divergence: Ticker breaking out, SPY flat
                return {
                    'correlation': correlation,
                    'ticker_strength': 'divergent',
                    'confidence_adjustment': +10,
                    'reason': f'DIVERGENCE: {ticker} breaking out, SPY flat (correlation={correlation:.2f})'
                }
            else:
                # Low correlation, no strong divergence
                return {
                    'correlation': correlation,
                    'ticker_strength': 'independent',
                    'confidence_adjustment': +5,
                    'reason': f'Low SPY correlation ({correlation:.2f}) - ticker-specific move'
                }
        
        else:
            # Moderate correlation (0.3 - 0.7)
            return {
                'correlation': correlation,
                'ticker_strength': 'moderate',
                'confidence_adjustment': 0,
                'reason': f'Moderate SPY correlation ({correlation:.2f}) - neutral'
            }
    
    except Exception as e:
        logger.error(
            f"[CORRELATION] Error calculating correlation for {ticker}: {e}",
            extra={'component': 'correlation', 'symbol': ticker}
        )
        return {
            'correlation': 0.5,
            'ticker_strength': 'unknown',
            'confidence_adjustment': 0,
            'reason': 'Correlation calculation failed'
        }


def _get_returns(ticker: str, lookback_bars: int, timeframe: str) -> Optional[np.ndarray]:
    """
    Fetch price returns for a ticker.
    
    Returns:
        np.ndarray: Array of percentage returns, or None if failed
    """
    try:
        from app.data.data_manager import data_manager
        
        # Fetch bars from data manager
        bars = data_manager.get_bars_from_memory(ticker, limit=lookback_bars + 1)
        
        if not bars or len(bars) < lookback_bars:
            logger.warning(
                f"[CORRELATION] Insufficient data for {ticker} (need {lookback_bars}, got {len(bars)})",
                extra={'component': 'correlation', 'symbol': ticker}
            )
            return None
        
        # Calculate returns (percent change from bar to bar)
        closes = np.array([bar['close'] for bar in bars])
        returns = np.diff(closes) / closes[:-1]
        
        return returns[-lookback_bars:]  # Return last N returns
    
    except Exception as e:
        logger.error(
            f"[CORRELATION] Failed to get returns for {ticker}: {e}",
            extra={'component': 'correlation', 'symbol': ticker}
        )
        return None


def get_divergence_score(ticker: str, spy_lookback: int = 20) -> float:
    """
    Calculate divergence score between ticker and SPY.
    
    Higher score = stronger divergence (ticker moving independently of market)
    
    Returns:
        float: Divergence score (0-100)
    """
    try:
        ticker_returns = _get_returns(ticker, spy_lookback, '5m')
        spy_returns = _get_returns('SPY', spy_lookback, '5m')
        
        if ticker_returns is None or spy_returns is None:
            return 50.0  # Neutral score
        
        # Calculate correlation
        correlation = np.corrcoef(ticker_returns, spy_returns)[0, 1]
        
        if np.isnan(correlation):
            return 50.0
        
        # Calculate ticker and SPY momentum
        ticker_momentum = np.mean(ticker_returns[-5:])
        spy_momentum = np.mean(spy_returns[-5:])
        
        # Divergence score components:
        # 1. Low correlation (0-50 points)
        correlation_score = (1 - abs(correlation)) * 50
        
        # 2. Ticker strength vs SPY (0-50 points)
        if ticker_momentum > 0 and spy_momentum < 0:
            # Ticker up, SPY down - maximum divergence
            strength_score = 50
        elif ticker_momentum > 0 and abs(spy_momentum) < 0.005:
            # Ticker up, SPY flat - strong divergence
            strength_score = 40
        elif ticker_momentum > 0.01:
            # Ticker showing strength
            strength_score = 30
        else:
            strength_score = 0
        
        divergence_score = correlation_score + strength_score
        
        return min(100, divergence_score)
    
    except Exception as e:
        logger.error(f"[CORRELATION] Divergence score calculation failed: {e}")
        return 50.0


def is_market_driven_move(ticker: str, correlation_threshold: float = 0.7) -> bool:
    """
    Simple check: Is this ticker's move primarily market-driven?
    
    Args:
        ticker: Stock symbol
        correlation_threshold: Correlation above this = market-driven
    
    Returns:
        bool: True if market-driven, False if ticker-specific
    """
    result = check_spy_correlation(ticker)
    return abs(result['correlation']) >= correlation_threshold
