#!/usr/bin/env python3
"""
Historical Signal Backtester & ML Training Data Generator
Generates synthetic signal outcomes from 60-90 days of cached candle data
to bootstrap ML model training without waiting for live signals.

This script:
1. Scans historical candles for BOS/FVG patterns
2. Simulates signal generation with validation
3. Tracks outcomes (win/loss) based on actual price movement
4. Stores outcomes in signal_analytics database
5. Triggers ML model training once 100+ outcomes collected
"""

import sys
import os
from pathlib import Path

# Add project root to Python path so we can import app modules
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
    
    Args:
        lookback_days: How many days back to analyze (60-90)
        min_signals_per_ticker: Minimum signals to generate per ticker
        target_total_signals: Target number of total signals to generate
    
    Returns:
        Number of signals generated and stored
    """
    logger.info("=" * 80)
    logger.info("ML TRAINING DATA GENERATOR - Using Historical Cache")
    logger.info("=" * 80)
    
    try:
        # Import War Machine components
        from app.db.database import Database
        from app.signals.signal_generator import SignalGenerator
        from app.validation.validation import SignalValidator
        
        logger.info(f"Analyzing last {lookback_days} days of cached data")
        logger.info(f"Target: {target_total_signals} signals across all tickers")
        logger.info("")
        
        # Initialize components
        db = Database()
        signal_gen = SignalGenerator()
        validator = SignalValidator(min_final_confidence=0.50)
        
        # Get list of tickers with cached data
        tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMD']
        
        total_generated = 0
        ticker_stats = {}
        
        for ticker in tickers:
            logger.info(f"[{ticker}] Processing historical data...")
            
            try:
                # Get cached candles for this ticker
                end_date = datetime.now()
                start_date = end_date - timedelta(days=lookback_days)
                
                # Fetch 5-minute candles from cache
                candles = db.fetch_candles_from_cache(
                    ticker=ticker,
                    interval='5m',
                    start_time=start_date,
                    end_time=end_date
                )
                
                if not candles or len(candles) < 100:
                    logger.warning(f"  ⚠️  Insufficient data for {ticker} ({len(candles) if candles else 0} bars)")
                    continue
                
                logger.info(f"  📊 Loaded {len(candles)} bars")
                
                # Simulate signal detection on historical data
                signals_found = backtest_signals_from_candles(
                    ticker=ticker,
                    candles=candles,
                    signal_gen=signal_gen,
                    validator=validator,
                    min_signals=min_signals_per_ticker
                )
                
                if signals_found:
                    # Store outcomes in database
                    stored_count = store_signal_outcomes(db, ticker, signals_found)
                    total_generated += stored_count
                    ticker_stats[ticker] = stored_count
                    
                    logger.info(f"  ✅ Generated {stored_count} signal outcomes")
                else:
                    logger.warning(f"  ⚠️  No valid signals found")
                    ticker_stats[ticker] = 0
                
            except Exception as e:
                logger.error(f"  ❌ Error processing {ticker}: {e}")
                ticker_stats[ticker] = 0
                continue
        
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
        
        # Check if we have enough to train
        if total_generated >= 100:
            logger.info("")
            logger.info("🎯 READY FOR ML TRAINING!")
            logger.info("Run: python app/ml/train_ml_booster.py")
            return total_generated
        else:
            logger.warning("")
            logger.warning(f"⚠️  Need {100 - total_generated} more signals for ML training")
            logger.warning("Recommendation: Lower lookback period or add more tickers")
            return total_generated
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 0


def backtest_signals_from_candles(
    ticker: str,
    candles: List[Dict],
    signal_gen,
    validator,
    min_signals: int = 15
) -> List[Dict]:
    """
    Scan historical candles for BOS/FVG patterns and simulate signals.
    
    Returns list of signal outcomes with metadata.
    """
    signals = []
    
    try:
        # Use a sliding window to detect patterns
        window_size = 20  # Look at 20 bars at a time (100 minutes on 5m chart)
        
        for i in range(window_size, len(candles) - 30):  # Leave 30 bars for outcome tracking
            window = candles[i-window_size:i]
            
            # Check for BOS pattern
            has_bos, direction = detect_bos_pattern(window)
            
            if not has_bos:
                continue
            
            # Check for FVG
            has_fvg, fvg_data = detect_fvg_pattern(window, direction)
            
            if not has_fvg:
                continue
            
            # We have a potential signal - calculate features
            signal_bar = candles[i]
            signal_time = signal_bar.get('timestamp', datetime.now())
            entry_price = signal_bar['close']
            
            # Calculate volume ratio
            avg_volume = sum(b['volume'] for b in window) / len(window)
            volume_ratio = signal_bar['volume'] / avg_volume if avg_volume > 0 else 1.0
            
            # Base confidence (simplified)
            base_confidence = 0.55 + (0.1 if volume_ratio > 2.0 else 0)
            
            # Validate signal (this would adjust confidence)
            try:
                should_pass, final_conf, metadata = validator.validate_signal(
                    ticker=ticker,
                    signal_direction="BUY" if direction == "BULLISH" else "SELL",
                    current_price=entry_price,
                    current_volume=signal_bar['volume'],
                    base_confidence=base_confidence
                )
            except:
                should_pass = base_confidence >= 0.50
                final_conf = base_confidence
                metadata = {}
            
            if not should_pass:
                continue  # Only track signals that would have passed validation
            
            # Track outcome over next 30 bars (2.5 hours on 5m chart)
            outcome = calculate_signal_outcome(
                candles[i:i+30],
                entry_price,
                direction,
                stop_loss_pct=0.015,  # 1.5% stop
                target_pct=0.03       # 3% target (2R)
            )
            
            # Store signal data
            signal_data = {
                'ticker': ticker,
                'timestamp': signal_time,
                'direction': direction,
                'entry_price': entry_price,
                'confidence': final_conf,
                'volume_ratio': volume_ratio,
                'pattern_type': 'BOS+FVG',
                'outcome': outcome['result'],  # 'WIN', 'LOSS', or 'BREAKEVEN'
                'pnl_pct': outcome['pnl_pct'],
                'exit_price': outcome['exit_price'],
                'bars_held': outcome['bars_held'],
                'metadata': metadata
            }
            
            signals.append(signal_data)
            
            # Stop if we have enough signals for this ticker
            if len(signals) >= min_signals * 2:  # Generate extra to ensure quality
                break
        
        # Filter to best signals
        signals.sort(key=lambda x: x['confidence'], reverse=True)
        return signals[:min_signals * 2]
        
    except Exception as e:
        logger.error(f"Error in backtest: {e}")
        return signals


def detect_bos_pattern(candles: List[Dict]) -> Tuple[bool, str]:
    """
    Detect Break of Structure pattern.
    Returns (has_pattern, direction).
    """
    if len(candles) < 10:
        return False, None
    
    # Find recent high/low
    recent_high = max(c['high'] for c in candles[-10:])
    recent_low = min(c['low'] for c in candles[-10:])
    
    # Prior high/low (before recent)
    prior_high = max(c['high'] for c in candles[-20:-10])
    prior_low = min(c['low'] for c in candles[-20:-10])
    
    latest = candles[-1]
    
    # Bullish BOS: Break above prior high
    if latest['close'] > prior_high and latest['close'] > recent_high * 1.002:
        return True, "BULLISH"
    
    # Bearish BOS: Break below prior low
    if latest['close'] < prior_low and latest['close'] < recent_low * 0.998:
        return True, "BEARISH"
    
    return False, None


def detect_fvg_pattern(candles: List[Dict], direction: str) -> Tuple[bool, Dict]:
    """
    Detect Fair Value Gap pattern.
    Returns (has_pattern, fvg_data).
    """
    if len(candles) < 3:
        return False, {}
    
    # Check last 3 candles for gap
    c1, c2, c3 = candles[-3:]
    
    if direction == "BULLISH":
        # Bullish FVG: c1 high < c3 low (gap up)
        gap = c3['low'] - c1['high']
        if gap > 0:
            return True, {'gap_size': gap, 'gap_pct': gap / c1['close']}
    
    elif direction == "BEARISH":
        # Bearish FVG: c1 low > c3 high (gap down)
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
    """
    Track signal outcome over future candles.
    Returns outcome data (WIN/LOSS/BREAKEVEN).
    """
    if direction == "BULLISH":
        stop_price = entry_price * (1 - stop_loss_pct)
        target_price = entry_price * (1 + target_pct)
    else:  # BEARISH
        stop_price = entry_price * (1 + stop_loss_pct)
        target_price = entry_price * (1 - target_pct)
    
    for i, candle in enumerate(future_candles):
        # Check if stopped out
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
        
        # Check if target hit
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
    
    # Didn't hit stop or target - exit at last candle
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


def store_signal_outcomes(db, ticker: str, signals: List[Dict]) -> int:
    """
    Store signal outcomes in signal_analytics table for ML training.
    """
    stored_count = 0
    
    try:
        # Check if signal_analytics table exists, create if not
        create_table_sql = """
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
        );
        """
        
        db.execute(create_table_sql)
        
        # Insert signals
        for signal in signals:
            insert_sql = """
            INSERT INTO signal_analytics 
            (ticker, timestamp, direction, entry_price, confidence, volume_ratio,
             pattern_type, outcome, pnl_pct, exit_price, bars_held)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            db.execute(insert_sql, (
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
        
        logger.info(f"  💾 Stored {stored_count} outcomes to database")
        return stored_count
        
    except Exception as e:
        logger.error(f"Error storing outcomes: {e}")
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
        logger.info("Next step: python app/ml/train_ml_booster.py")
    else:
        logger.info(f"⚠️  Generated {total}/100 minimum signals")
        logger.info("Try: python scripts/generate_ml_training_data.py --days 90")
    logger.info("=" * 80)
