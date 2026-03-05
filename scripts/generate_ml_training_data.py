#!/usr/bin/env python3
"""
Historical Signal Backtester & ML Training Data Generator
Generates synthetic signal outcomes from 60-90 days of cached candle data
to bootstrap ML model training without waiting for live signals.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def generate_training_data_from_cache(
    lookback_days: int = 60,
    min_signals_per_ticker: int = 15,
    target_total_signals: int = 120
):
    """
    Generate ML training data from cached historical candles.
    """
    logger.info("=" * 80)
    logger.info("ML TRAINING DATA GENERATOR - Using Historical Cache")
    logger.info("=" * 80)
    
    try:
        # Import components
        from app.data.candle_cache import CandleCache
        from app.data.database import get_db_connection
        
        logger.info(f"Analyzing last {lookback_days} days of cached data")
        logger.info(f"Target: {target_total_signals} signals across all tickers")
        logger.info("")
        
        # Initialize
        cache = CandleCache()
        
        # Tickers
        tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMD']
        
        total_generated = 0
        ticker_stats = {}
        
        for ticker in tickers:
            logger.info(f"[{ticker}] Processing historical data...")
            
            try:
                # Load cached candles
                candles = cache.load_cached_candles(
                    ticker=ticker,
                    timeframe='5m',
                    days=lookback_days
                )
                
                if not candles or len(candles) < 100:
                    logger.warning(f"  ⚠️  Insufficient data for {ticker} ({len(candles) if candles else 0} bars)")
                    ticker_stats[ticker] = 0
                    continue
                
                logger.info(f"  📊 Loaded {len(candles)} bars")
                
                # Backtest signals
                signals = backtest_signals_from_candles(
                    ticker=ticker,
                    candles=candles,
                    min_signals=min_signals_per_ticker
                )
                
                if signals:
                    # Store to database
                    stored = store_signal_outcomes(ticker, signals)
                    total_generated += stored
                    ticker_stats[ticker] = stored
                    logger.info(f"  ✅ Generated {stored} signal outcomes")
                else:
                    logger.warning(f"  ⚠️  No valid signals found")
                    ticker_stats[ticker] = 0
                
            except Exception as e:
                logger.error(f"  ❌ Error processing {ticker}: {e}")
                import traceback
                traceback.print_exc()
                ticker_stats[ticker] = 0
        
        # Summary
        logger.info("")
        logger.info("=" * 80)
        logger.info("GENERATION SUMMARY")
        logger.info("=" * 80)
        
        for ticker, count in ticker_stats.items():
            status = "✅" if count >= min_signals_per_ticker else "⚠️"
            logger.info(f"{status} {ticker}: {count} signals")
        
        logger.info("")
        logger.info(f"Total Signals Generated: {total_generated}")
        logger.info(f"Target: {target_total_signals}")
        
        if total_generated >= 100:
            logger.info("")
            logger.info("🎯 READY FOR ML TRAINING!")
            logger.info("Next step: python -m app.ml.ml_trainer")
            return total_generated
        else:
            logger.warning("")
            logger.warning(f"⚠️  Need {100 - total_generated} more signals")
            logger.warning("Try: python scripts/generate_ml_training_data.py --days 90")
            return total_generated
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 0


def backtest_signals_from_candles(
    ticker: str,
    candles: List[Dict],
    min_signals: int = 15
) -> List[Dict]:
    """
    Scan historical candles for BOS/FVG patterns and simulate signals.
    """
    signals = []
    
    try:
        window_size = 20
        
        for i in range(window_size, len(candles) - 30):
            window = candles[i-window_size:i]
            
            # Detect BOS pattern
            has_bos, direction = detect_bos_pattern(window)
            if not has_bos:
                continue
            
            # Detect FVG
            has_fvg, fvg_data = detect_fvg_pattern(window, direction)
            if not has_fvg:
                continue
            
            # Calculate features
            signal_bar = candles[i]
            signal_time = signal_bar['datetime']
            entry_price = signal_bar['close']
            
            # Volume ratio
            avg_volume = sum(b['volume'] for b in window) / len(window)
            volume_ratio = signal_bar['volume'] / avg_volume if avg_volume > 0 else 1.0
            
            # Base confidence
            base_confidence = 0.55 + (0.1 if volume_ratio > 2.0 else 0)
            
            if base_confidence < 0.50:
                continue
            
            # Track outcome
            outcome = calculate_signal_outcome(
                candles[i:i+30],
                entry_price,
                direction,
                stop_loss_pct=0.015,
                target_pct=0.03
            )
            
            # Store signal
            signals.append({
                'ticker': ticker,
                'timestamp': signal_time,
                'direction': direction,
                'entry_price': entry_price,
                'confidence': base_confidence,
                'volume_ratio': volume_ratio,
                'pattern_type': 'BOS+FVG',
                'outcome': outcome['result'],
                'pnl_pct': outcome['pnl_pct'],
                'exit_price': outcome['exit_price'],
                'bars_held': outcome['bars_held']
            })
            
            if len(signals) >= min_signals * 2:
                break
        
        # Return best signals
        signals.sort(key=lambda x: x['confidence'], reverse=True)
        return signals[:min_signals * 2]
        
    except Exception as e:
        logger.error(f"Error in backtest: {e}")
        return signals


def detect_bos_pattern(candles: List[Dict]) -> Tuple[bool, str]:
    """Detect Break of Structure pattern."""
    if len(candles) < 10:
        return False, None
    
    recent_high = max(c['high'] for c in candles[-10:])
    recent_low = min(c['low'] for c in candles[-10:])
    prior_high = max(c['high'] for c in candles[-20:-10])
    prior_low = min(c['low'] for c in candles[-20:-10])
    
    latest = candles[-1]
    
    # Bullish BOS
    if latest['close'] > prior_high and latest['close'] > recent_high * 1.002:
        return True, "BULLISH"
    
    # Bearish BOS
    if latest['close'] < prior_low and latest['close'] < recent_low * 0.998:
        return True, "BEARISH"
    
    return False, None


def detect_fvg_pattern(candles: List[Dict], direction: str) -> Tuple[bool, Dict]:
    """Detect Fair Value Gap pattern."""
    if len(candles) < 3:
        return False, {}
    
    c1, c2, c3 = candles[-3:]
    
    if direction == "BULLISH":
        gap = c3['low'] - c1['high']
        if gap > 0:
            return True, {'gap_size': gap, 'gap_pct': gap / c1['close']}
    
    elif direction == "BEARISH":
        gap = c1['low'] - c3['high']
        if gap > 0:
            return True, {'gap_size': gap, 'gap_pct': gap / c1['close']}
    
    return False, {}


def calculate_signal_outcome(
    future_candles: List[Dict],
    entry_price: float,
    direction: str,
    stop_loss_pct: float = 0.015,
    target_pct: float = 0.03
) -> Dict:
    """Track signal outcome over future candles."""
    if direction == "BULLISH":
        stop_price = entry_price * (1 - stop_loss_pct)
        target_price = entry_price * (1 + target_pct)
    else:
        stop_price = entry_price * (1 + stop_loss_pct)
        target_price = entry_price * (1 - target_pct)
    
    for i, candle in enumerate(future_candles):
        # Check stop
        if direction == "BULLISH" and candle['low'] <= stop_price:
            return {
                'result': 'LOSS',
                'exit_price': stop_price,
                'pnl_pct': -stop_loss_pct,
                'bars_held': i + 1
            }
        elif direction == "BEARISH" and candle['high'] >= stop_price:
            return {
                'result': 'LOSS',
                'exit_price': stop_price,
                'pnl_pct': -stop_loss_pct,
                'bars_held': i + 1
            }
        
        # Check target
        if direction == "BULLISH" and candle['high'] >= target_price:
            return {
                'result': 'WIN',
                'exit_price': target_price,
                'pnl_pct': target_pct,
                'bars_held': i + 1
            }
        elif direction == "BEARISH" and candle['low'] <= target_price:
            return {
                'result': 'WIN',
                'exit_price': target_price,
                'pnl_pct': target_pct,
                'bars_held': i + 1
            }
    
    # Exit at last candle
    exit_price = future_candles[-1]['close']
    
    if direction == "BULLISH":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price
    
    result = 'WIN' if pnl_pct > 0.005 else ('LOSS' if pnl_pct < -0.005 else 'BREAKEVEN')
    
    return {
        'result': result,
        'exit_price': exit_price,
        'pnl_pct': pnl_pct,
        'bars_held': len(future_candles)
    }


def store_signal_outcomes(ticker: str, signals: List[Dict]) -> int:
    """
    Store signal outcomes in signal_analytics table.
    """
    from app.data.database import get_db_connection
    
    stored_count = 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_analytics (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                direction VARCHAR(10) NOT NULL,
                entry_price DECIMAL(12, 4),
                confidence DECIMAL(5, 4),
                volume_ratio DECIMAL(8, 2),
                pattern_type VARCHAR(50),
                outcome VARCHAR(20),
                pnl_pct DECIMAL(8, 4),
                exit_price DECIMAL(12, 4),
                bars_held INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert signals
        for signal in signals:
            cursor.execute("""
                INSERT INTO signal_analytics 
                (ticker, timestamp, direction, entry_price, confidence, volume_ratio,
                 pattern_type, outcome, pnl_pct, exit_price, bars_held)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                signal['ticker'],
                signal['timestamp'],
                signal['direction'],
                signal['entry_price'],
                signal['confidence'],
                signal['volume_ratio'],
                signal['pattern_type'],
                signal['outcome'],
                signal['pnl_pct'],
                signal['exit_price'],
                signal['bars_held']
            ))
            stored_count += 1
        
        conn.commit()
        logger.info(f"  💾 Stored {stored_count} outcomes to database")
        
        cursor.close()
        conn.close()
        
        return stored_count
        
    except Exception as e:
        logger.error(f"Error storing outcomes: {e}")
        import traceback
        traceback.print_exc()
        return stored_count


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate ML training data from cached candles')
    parser.add_argument('--days', type=int, default=60, help='Lookback days (default: 60)')
    parser.add_argument('--per-ticker', type=int, default=15, help='Min signals per ticker (default: 15)')
    parser.add_argument('--target', type=int, default=120, help='Target total signals (default: 120)')
    
    args = parser.parse_args()
    
    total = generate_training_data_from_cache(
        lookback_days=args.days,
        min_signals_per_ticker=args.per_ticker,
        target_total_signals=args.target
    )
    
    logger.info("")
    logger.info("=" * 80)
    if total >= 100:
        logger.info("✅ SUCCESS - Ready for ML training!")
        logger.info("Next step: Check app/ml/ml_trainer.py for training")
    else:
        logger.info(f"⚠️  Generated {total}/100 minimum signals")
        logger.info("Try: python scripts/generate_ml_training_data.py --days 90")
    logger.info("=" * 80)
