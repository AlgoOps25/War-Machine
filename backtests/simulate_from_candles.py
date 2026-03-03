#!/usr/bin/env python3
"""
Simulate Signals and Position Outcomes from Candle Data
Generates realistic trading scenarios from your cached 90-day candle data.
"""

import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from dte_selector import DTESelector, DTEConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CandleBacktester:
    """Simulate trading signals and outcomes from candle data"""
    
    def __init__(self, config: DTEConfig):
        self.dte_selector = DTESelector(config)
        self.config = config
        self.signals: List[Dict[str, Any]] = []
        self.positions: List[Dict[str, Any]] = []
    
    def load_candle_data(self, data_path: str) -> Dict[str, pd.DataFrame]:
        """
        Load candle data from your cache
        Supports JSON or CSV format
        """
        path = Path(data_path)
        candle_data = {}
        
        if path.is_file():
            # Single file - assume JSON with multiple symbols
            logger.info(f"Loading candle data from {data_path}")
            
            if data_path.endswith('.json'):
                with open(data_path, 'r') as f:
                    data = json.load(f)
                
                # Assume structure: {"SPY": [{"timestamp": ..., "open": ..., }], ...}
                for symbol, candles in data.items():
                    df = pd.DataFrame(candles)
                    if 'timestamp' in df.columns:
                        df['timestamp'] = pd.to_datetime(df['timestamp'])
                        df.set_index('timestamp', inplace=True)
                    candle_data[symbol] = df
            
            elif data_path.endswith('.csv'):
                df = pd.read_csv(data_path)
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                if 'symbol' in df.columns:
                    # Multi-symbol CSV
                    for symbol in df['symbol'].unique():
                        symbol_df = df[df['symbol'] == symbol].copy()
                        symbol_df.set_index('timestamp', inplace=True)
                        candle_data[symbol] = symbol_df
                else:
                    # Single symbol - use filename
                    symbol = path.stem.upper()
                    df.set_index('timestamp', inplace=True)
                    candle_data[symbol] = df
        
        elif path.is_dir():
            # Directory of CSV files - one per symbol
            logger.info(f"Loading candle data from directory {data_path}")
            
            for csv_file in path.glob('*.csv'):
                symbol = csv_file.stem.upper()
                df = pd.read_csv(csv_file)
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df.set_index('timestamp', inplace=True)
                candle_data[symbol] = df
        
        logger.info(f"Loaded {len(candle_data)} symbols with candle data")
        return candle_data
    
    def detect_bos_signals(self, df: pd.DataFrame, symbol: str) -> List[Dict[str, Any]]:
        """
        Detect BOS (Break of Structure) signals from candle data
        Simple implementation: new high after pullback
        """
        signals = []
        
        # Need at least 20 candles for context
        if len(df) < 20:
            return signals
        
        # Calculate rolling highs/lows
        df['high_5'] = df['high'].rolling(5).max()
        df['low_5'] = df['low'].rolling(5).min()
        df['prev_high'] = df['high'].shift(1)
        
        # BOS: Price breaks above recent high after pullback
        for i in range(20, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i-1]
            
            # Bullish BOS: break above 5-candle high
            if current['high'] > prev['high_5'] and current['volume'] > df['volume'].iloc[i-5:i].mean():
                signals.append({
                    'timestamp': current.name,
                    'symbol': symbol,
                    'signal_type': 'BOS_BULL',
                    'entry_price': current['close'],
                    'high': current['high'],
                    'low': current['low'],
                    'volume': current['volume']
                })
        
        return signals
    
    def detect_fvg_signals(self, df: pd.DataFrame, symbol: str) -> List[Dict[str, Any]]:
        """
        Detect FVG (Fair Value Gap) signals
        Gap between candle 1 high and candle 3 low (or vice versa)
        """
        signals = []
        
        if len(df) < 10:
            return signals
        
        for i in range(3, len(df)):
            candle1 = df.iloc[i-2]
            candle2 = df.iloc[i-1]
            candle3 = df.iloc[i]
            
            # Bullish FVG: gap up (candle1 high < candle3 low)
            if candle1['high'] < candle3['low']:
                gap_size = candle3['low'] - candle1['high']
                gap_pct = (gap_size / candle1['high']) * 100
                
                # Only significant gaps (>0.5%)
                if gap_pct > 0.5:
                    signals.append({
                        'timestamp': candle3.name,
                        'symbol': symbol,
                        'signal_type': 'FVG_BULL',
                        'entry_price': candle3['close'],
                        'gap_size': gap_size,
                        'gap_pct': gap_pct,
                        'volume': candle3['volume']
                    })
        
        return signals
    
    def generate_signals(self, candle_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Generate all trading signals from candle data
        """
        all_signals = []
        
        for symbol, df in candle_data.items():
            logger.info(f"Analyzing {symbol} ({len(df)} candles)")
            
            bos_signals = self.detect_bos_signals(df, symbol)
            fvg_signals = self.detect_fvg_signals(df, symbol)
            
            all_signals.extend(bos_signals)
            all_signals.extend(fvg_signals)
        
        signals_df = pd.DataFrame(all_signals)
        
        if not signals_df.empty:
            signals_df = signals_df.sort_values('timestamp')
            
            # Filter to market hours (9:30 AM - 4:00 PM ET)
            signals_df = signals_df[
                (signals_df['timestamp'].dt.hour >= 9) & 
                (signals_df['timestamp'].dt.hour < 16)
            ]
        
        logger.info(f"Generated {len(signals_df)} total signals")
        return signals_df
    
    def simulate_option_trade(
        self, 
        signal: Dict[str, Any], 
        candles: pd.DataFrame,
        dte: int
    ) -> Optional[Dict[str, Any]]:
        """
        Simulate an option trade outcome
        Uses simple price movement model
        """
        entry_time = signal['timestamp']
        entry_price = signal['entry_price']
        symbol = signal['symbol']
        
        # Get candles after entry
        future_candles = candles[candles.index > entry_time]
        
        if len(future_candles) == 0:
            return None
        
        # Simulate option pricing based on underlying movement
        # Simplified: 1% underlying move ≈ 10% option move at 0DTE, less at higher DTE
        dte_multiplier = 10 if dte == 0 else (7 if dte == 1 else 5)
        
        # Track position for up to 2 hours or 20 candles
        max_candles = min(20, len(future_candles))
        
        option_entry = 2.50  # Assume $2.50 entry (normalized)
        best_price = option_entry
        worst_price = option_entry
        exit_price = option_entry
        exit_time = entry_time
        
        for i in range(max_candles):
            candle = future_candles.iloc[i]
            pct_move = ((candle['close'] - entry_price) / entry_price) * 100
            
            # Simulate option price
            option_price = option_entry * (1 + (pct_move * dte_multiplier / 100))
            option_price = max(0.05, option_price)  # Floor at $0.05
            
            best_price = max(best_price, option_price)
            worst_price = min(worst_price, option_price)
            
            # Exit conditions
            exit_triggered = False
            
            # Take profit at +50% (0DTE) or +30% (1-2 DTE)
            profit_target = 1.5 if dte == 0 else 1.3
            if option_price >= option_entry * profit_target:
                exit_price = option_price
                exit_time = candle.name
                exit_triggered = True
            
            # Stop loss at -50%
            elif option_price <= option_entry * 0.5:
                exit_price = option_price
                exit_time = candle.name
                exit_triggered = True
            
            # Time-based exit (hold for 5-30 min depending on DTE)
            elif i >= (5 if dte == 0 else 15):
                exit_price = option_price
                exit_time = candle.name
                exit_triggered = True
            
            if exit_triggered:
                break
        
        # Calculate P&L
        pnl = (exit_price - option_entry) * 100  # Per contract
        pnl_pct = ((exit_price - option_entry) / option_entry) * 100
        
        hold_duration = (exit_time - entry_time).total_seconds() / 60
        
        return {
            'entry_time': entry_time,
            'exit_time': exit_time,
            'symbol': symbol,
            'strike': round(entry_price, 0),
            'dte': dte,
            'entry_price': round(option_entry, 2),
            'exit_price': round(exit_price, 2),
            'best_price': round(best_price, 2),
            'worst_price': round(worst_price, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'hold_duration_min': round(hold_duration, 1),
            'signal_type': signal['signal_type']
        }
    
    def run_backtest(
        self, 
        candle_data: Dict[str, pd.DataFrame],
        max_signals: int = 100
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Run full backtest with DTE strategy
        """
        # Generate signals
        signals_df = self.generate_signals(candle_data)
        
        if signals_df.empty:
            logger.error("No signals generated")
            return pd.DataFrame(), pd.DataFrame()
        
        # Limit to max_signals for reasonable runtime
        if len(signals_df) > max_signals:
            signals_df = signals_df.head(max_signals)
        
        logger.info(f"Backtesting {len(signals_df)} signals")
        
        positions = []
        
        for idx, signal in signals_df.iterrows():
            symbol = signal['symbol']
            
            if symbol not in candle_data:
                continue
            
            candles = candle_data[symbol]
            
            # Get recommended DTE for this signal time
            recommended_dte = self.dte_selector.select_dte(signal['timestamp'])
            
            # Simulate trade with recommended DTE
            position = self.simulate_option_trade(signal, candles, recommended_dte)
            
            if position:
                position['recommended_dte'] = recommended_dte
                position['actual_dte'] = recommended_dte  # Same for this simulation
                positions.append(position)
        
        positions_df = pd.DataFrame(positions)
        
        logger.info(f"Simulated {len(positions_df)} position outcomes")
        
        return signals_df, positions_df
    
    def print_backtest_report(self, positions_df: pd.DataFrame) -> None:
        """
        Print comprehensive backtest report
        """
        if positions_df.empty:
            print("No positions to analyze")
            return
        
        total_trades = len(positions_df)
        winners = len(positions_df[positions_df['pnl'] > 0])
        losers = len(positions_df[positions_df['pnl'] <= 0])
        win_rate = (winners / total_trades) * 100
        
        total_pnl = positions_df['pnl'].sum()
        avg_pnl = positions_df['pnl'].mean()
        avg_win = positions_df[positions_df['pnl'] > 0]['pnl'].mean() if winners > 0 else 0
        avg_loss = positions_df[positions_df['pnl'] <= 0]['pnl'].mean() if losers > 0 else 0
        
        # By DTE
        by_dte = positions_df.groupby('dte').agg({
            'pnl': ['count', 'mean', 'sum'],
            'pnl_pct': 'mean',
            'hold_duration_min': 'mean'
        }).round(2)
        
        by_dte['win_rate'] = positions_df.groupby('dte').apply(
            lambda x: (x['pnl'] > 0).sum() / len(x) * 100
        ).round(1)
        
        print("\n" + "="*70)
        print("CANDLE-BASED BACKTEST REPORT")
        print("="*70)
        print(f"\nTotal Trades: {total_trades}")
        print(f"Winners: {winners} ({win_rate:.1f}%)")
        print(f"Losers: {losers}")
        print(f"\nTotal P&L: ${total_pnl:,.2f}")
        print(f"Average P&L: ${avg_pnl:.2f}")
        print(f"Average Winner: ${avg_win:.2f}")
        print(f"Average Loser: ${avg_loss:.2f}")
        print(f"Profit Factor: {abs(avg_win / avg_loss):.2f}" if avg_loss != 0 else "N/A")
        
        print("\n" + "="*70)
        print("PERFORMANCE BY DTE")
        print("="*70)
        print(by_dte.to_string())
        
        print("\n" + "="*70)
        print("TOP 5 WINNERS")
        print("="*70)
        top_winners = positions_df.nlargest(5, 'pnl')[[
            'symbol', 'entry_time', 'dte', 'pnl', 'pnl_pct', 'hold_duration_min'
        ]]
        print(top_winners.to_string())
        
        print("\n" + "="*70)
        print("TOP 5 LOSERS")
        print("="*70)
        top_losers = positions_df.nsmallest(5, 'pnl')[[
            'symbol', 'entry_time', 'dte', 'pnl', 'pnl_pct', 'hold_duration_min'
        ]]
        print(top_losers.to_string())
        print("\n" + "="*70 + "\n")

def main():
    """
    Run candle-based backtest
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Backtest DTE strategy from candle data')
    parser.add_argument('data_path', help='Path to candle data (JSON/CSV file or directory)')
    parser.add_argument('--max-signals', type=int, default=100,
                       help='Maximum signals to process (default: 100)')
    parser.add_argument('--output-dir', default='backtests',
                       help='Output directory for results')
    
    args = parser.parse_args()
    
    # Configure DTE selector (match your production config)
    config = DTEConfig(
        default_dte=0,
        pre_1000_dte=0,
        post_1000_dte=1,
        post_1030_dte=2,
        avoid_wed_0dte=True,
        min_time_value=0.05,
        enable_smart_routing=True
    )
    
    backtester = CandleBacktester(config)
    
    # Load candle data
    candle_data = backtester.load_candle_data(args.data_path)
    
    if not candle_data:
        logger.error("No candle data loaded")
        return
    
    # Run backtest
    signals_df, positions_df = backtester.run_backtest(candle_data, args.max_signals)
    
    # Save results
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    if not signals_df.empty:
        signals_path = output_dir / 'simulated_signals.csv'
        signals_df.to_csv(signals_path, index=False)
        logger.info(f"Saved signals to {signals_path}")
    
    if not positions_df.empty:
        positions_path = output_dir / 'simulated_positions.csv'
        positions_df.to_csv(positions_path, index=False)
        logger.info(f"Saved positions to {positions_path}")
        
        # Print report
        backtester.print_backtest_report(positions_df)
    else:
        logger.warning("No positions generated")

if __name__ == '__main__':
    main()
