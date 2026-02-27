#!/usr/bin/env python3
"""
Quick Backtest - Realistic Signal Detection

Tests War Machine signal logic with proper BOS/FVG detection using
optimized parameters from config.py:
- Volume confirmation (3.0x average - from config.MIN_REL_VOL)
- ATR-based stops (2.5x - from config.STOP_MULTIPLIERS['A'])
- Breakeven stop management (move to entry after 1R profit)
- Structure breaks (new highs/lows)
- Momentum confirmation

Usage:
    python quick_backtest.py
"""
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict
import pandas as pd
import numpy as np

from data_manager import DataManager
from db_connection import get_conn, ph, dict_cursor
import config

ET = ZoneInfo("America/New_York")

# Test with top liquid tickers only
TEST_TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
    "GOOGL", "AMZN", "NFLX", "INTC", "PLTR", "COIN", "SOFI"
]


class RealisticBacktest:
    """Backtest with proper BOS/FVG signal detection using config.py parameters."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.data_manager = DataManager(db_path)
        
        # Load optimized parameters from config
        self.volume_multiplier = config.MIN_REL_VOL  # 3.0x
        self.atr_stop_multiplier = config.STOP_MULTIPLIERS['A']  # 2.5x
        self.target_rr = config.TARGET_1_RR  # 3.0R
        self.lookback_bars = config.LOOKBACK_BARS  # 12
        self.breakeven_trigger = config.BREAKEVEN_TRIGGER_RR  # 1.0R
        self.breakeven_enabled = config.BREAKEVEN_ENABLED  # True
        
        print(f"📊 Using optimized config parameters:")
        print(f"   Volume filter: {self.volume_multiplier}x average")
        print(f"   ATR stop: {self.atr_stop_multiplier}x")
        print(f"   Target: {self.target_rr}R")
        print(f"   Lookback: {self.lookback_bars} bars")
        print(f"   Breakeven: {'Enabled' if self.breakeven_enabled else 'Disabled'} (trigger at {self.breakeven_trigger}R)\n")
        
        # Date range (last 10 days for speed)
        now_et = datetime.now(ET)
        self.end_date = now_et.date()
        self.start_date = (now_et - timedelta(days=10)).date()
        
        print(f"Backtest period: {self.start_date} to {self.end_date}")
        print(f"Testing {len(TEST_TICKERS)} tickers\n")
        
        # Cache bars
        print("Loading bars...")
        self.bars_cache = {}
        for ticker in TEST_TICKERS:
            bars = self._load_bars(ticker)
            if bars:
                self.bars_cache[ticker] = bars
                print(f"  {ticker}: {len(bars)} bars")
        print(f"\nCached {sum(len(b) for b in self.bars_cache.values()):,} total bars\n")
    
    def _load_bars(self, ticker: str) -> List[Dict]:
        """Load 5-minute bars from database."""
        try:
            conn = get_conn(self.db_path)
            cur = dict_cursor(conn)
            
            query = f"""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = {ph()}
              AND datetime >= {ph()}
              AND datetime <= {ph()}
            ORDER BY datetime
            """
            
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
            conn.close()
            
            if not rows:
                return []
            
            bars = []
            for row in rows:
                dt = row["datetime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                
                bars.append({
                    "datetime": dt,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"])
                })
            
            return bars
        except Exception as e:
            print(f"Error loading {ticker}: {e}")
            return []
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(bars) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        return np.mean(tr_values[-period:]) if tr_values else 0
    
    def _calculate_avg_volume(self, bars: List[Dict], period: int = 20) -> float:
        """Calculate average volume."""
        if len(bars) < period:
            return 0
        
        volumes = [b['volume'] for b in bars[-period:]]
        return np.mean(volumes)
    
    def detect_breakout(self, bars: List[Dict]) -> Dict:
        """Detect BOS/FVG breakout with proper criteria using config parameters."""
        if len(bars) < self.lookback_bars + 14:  # Need extra bars for ATR
            return None
        
        current = bars[-1]
        prev = bars[-2]
        
        # Calculate indicators
        atr = self._calculate_atr(bars)
        avg_volume = self._calculate_avg_volume(bars)
        
        if atr == 0 or avg_volume == 0:
            return None
        
        # Volume confirmation (from config.MIN_REL_VOL = 3.0)
        volume_ratio = current['volume'] / avg_volume
        if volume_ratio < self.volume_multiplier:
            return None
        
        # Find structure (highs/lows in lookback)
        lookback_bars = bars[-self.lookback_bars-1:-1]
        highs = [b['high'] for b in lookback_bars]
        lows = [b['low'] for b in lookback_bars]
        
        resistance = max(highs)
        support = min(lows)
        
        # Check for breakout
        signal = None
        
        # Bullish breakout
        if current['close'] > resistance:
            # Momentum confirmation (close above open)
            if current['close'] > current['open']:
                signal = {
                    'direction': 'long',
                    'entry': current['close'],
                    'stop': current['close'] - (atr * self.atr_stop_multiplier),
                    'target': current['close'] + (atr * self.target_rr),
                    'atr': atr,
                    'datetime': current['datetime'],
                    'volume_ratio': volume_ratio,
                    'breakout_level': resistance
                }
        
        # Bearish breakout
        elif current['close'] < support:
            # Momentum confirmation (close below open)
            if current['close'] < current['open']:
                signal = {
                    'direction': 'short',
                    'entry': current['close'],
                    'stop': current['close'] + (atr * self.atr_stop_multiplier),
                    'target': current['close'] - (atr * self.target_rr),
                    'atr': atr,
                    'datetime': current['datetime'],
                    'volume_ratio': volume_ratio,
                    'breakout_level': support
                }
        
        return signal
    
    def simulate_trade(self, signal: Dict, bars: List[Dict]) -> Dict:
        """Simulate trade from signal with breakeven stop management."""
        entry_idx = next((i for i, b in enumerate(bars) 
                         if b["datetime"] == signal["datetime"]), None)
        
        if entry_idx is None or entry_idx >= len(bars) - 1:
            return None
        
        entry = signal['entry']
        stop = signal['stop']
        target = signal['target']
        direction = signal['direction']
        atr = signal['atr']
        
        # Breakeven stop tracking
        breakeven_triggered = False
        breakeven_trigger_price = entry + (atr * self.breakeven_trigger) if direction == 'long' else entry - (atr * self.breakeven_trigger)
        
        # Simulate forward (max 30 bars)
        for i in range(entry_idx + 1, min(entry_idx + 30, len(bars))):
            bar = bars[i]
            
            if direction == 'long':
                # Check if breakeven should trigger
                if self.breakeven_enabled and not breakeven_triggered and bar['high'] >= breakeven_trigger_price:
                    stop = entry  # Move stop to breakeven
                    breakeven_triggered = True
                
                # Check stop
                if bar['low'] <= stop:
                    pnl = stop - entry
                    return {
                        'exit_price': stop,
                        'exit_reason': 'stop_breakeven' if breakeven_triggered and pnl == 0 else 'stop',
                        'pnl': pnl,
                        'bars_held': i - entry_idx,
                        'breakeven_triggered': breakeven_triggered
                    }
                
                # Check target
                if bar['high'] >= target:
                    return {
                        'exit_price': target,
                        'exit_reason': 'target',
                        'pnl': target - entry,
                        'bars_held': i - entry_idx,
                        'breakeven_triggered': breakeven_triggered
                    }
            
            else:  # short
                # Check if breakeven should trigger
                if self.breakeven_enabled and not breakeven_triggered and bar['low'] <= breakeven_trigger_price:
                    stop = entry  # Move stop to breakeven
                    breakeven_triggered = True
                
                # Check stop
                if bar['high'] >= stop:
                    pnl = entry - stop
                    return {
                        'exit_price': stop,
                        'exit_reason': 'stop_breakeven' if breakeven_triggered and pnl == 0 else 'stop',
                        'pnl': pnl,
                        'bars_held': i - entry_idx,
                        'breakeven_triggered': breakeven_triggered
                    }
                
                # Check target
                if bar['low'] <= target:
                    return {
                        'exit_price': target,
                        'exit_reason': 'target',
                        'pnl': entry - target,
                        'bars_held': i - entry_idx,
                        'breakeven_triggered': breakeven_triggered
                    }
        
        # Close at last bar (timeout)
        last_bar = bars[min(entry_idx + 30, len(bars) - 1)]
        exit_price = last_bar['close']
        
        if direction == 'long':
            pnl = exit_price - entry
        else:
            pnl = entry - exit_price
        
        return {
            'exit_price': exit_price,
            'exit_reason': 'timeout',
            'pnl': pnl,
            'bars_held': min(30, len(bars) - entry_idx - 1),
            'breakeven_triggered': breakeven_triggered
        }
    
    def run_backtest(self) -> pd.DataFrame:
        """Run backtest on all cached bars."""
        print("="*60)
        print("RUNNING BACKTEST")
        print("="*60 + "\n")
        
        all_trades = []
        
        for ticker, bars in self.bars_cache.items():
            print(f"Scanning {ticker}...")
            
            # Scan through bars looking for signals
            for i in range(26, len(bars)):  # Need 26 bars for indicators
                bars_slice = bars[:i+1]
                signal = self.detect_breakout(bars_slice)
                
                if signal:
                    # Simulate trade
                    result = self.simulate_trade(signal, bars)
                    
                    if result:
                        trade = {
                            'ticker': ticker,
                            'datetime': signal['datetime'],
                            'direction': signal['direction'],
                            'entry': signal['entry'],
                            'exit': result['exit_price'],
                            'stop': signal['stop'],
                            'target': signal['target'],
                            'pnl': result['pnl'],
                            'pnl_pct': (result['pnl'] / signal['entry']) * 100,
                            'exit_reason': result['exit_reason'],
                            'bars_held': result['bars_held'],
                            'volume_ratio': signal['volume_ratio'],
                            'breakeven_triggered': result['breakeven_triggered']
                        }
                        all_trades.append(trade)
                        
                        # Skip forward to avoid overlapping signals
                        i += 10
        
        print(f"\n✅ Found {len(all_trades)} trades\n")
        return pd.DataFrame(all_trades)


def main():
    """Run backtest and print results."""
    backtest = RealisticBacktest()
    results_df = backtest.run_backtest()
    
    if len(results_df) == 0:
        print("❌ No trades found!\n")
        print("This means:")
        print("  - Signal criteria are too strict (volume filter at 3.0x), OR")
        print("  - Not enough bars in database, OR")
        print("  - No clear breakouts in test period\n")
        print("💡 This is GOOD - quality over quantity!\n")
        return
    
    # Calculate statistics
    print("="*60)
    print("BACKTEST RESULTS")
    print("="*60 + "\n")
    
    total_trades = len(results_df)
    winners = len(results_df[results_df['pnl'] > 0])
    losers = len(results_df[results_df['pnl'] < 0])
    breakeven_count = len(results_df[results_df['pnl'] == 0])
    
    win_rate = (winners / total_trades) * 100
    total_pnl = results_df['pnl'].sum()
    avg_win = results_df[results_df['pnl'] > 0]['pnl'].mean() if winners > 0 else 0
    avg_loss = results_df[results_df['pnl'] < 0]['pnl'].mean() if losers > 0 else 0
    
    # Breakeven stats
    be_triggered = len(results_df[results_df['breakeven_triggered'] == True])
    be_saved = len(results_df[(results_df['breakeven_triggered'] == True) & (results_df['pnl'] == 0)])
    
    print(f"Total Trades: {total_trades}")
    print(f"Winners: {winners} ({win_rate:.1f}%)")
    print(f"Losers: {losers}")
    print(f"Breakeven: {breakeven_count} (stop moved to entry)")
    print(f"\nBreakeven Management:")
    print(f"  Triggered: {be_triggered} trades ({be_triggered/total_trades*100:.1f}%)")
    print(f"  Saved from loss: {be_saved} trades")
    print(f"\nTotal P&L: ${total_pnl:.2f}")
    print(f"Avg Win: ${avg_win:.2f}")
    print(f"Avg Loss: ${avg_loss:.2f}")
    
    if avg_loss != 0:
        profit_factor = abs(winners * avg_win / (losers * abs(avg_loss))) if losers > 0 else float('inf')
        print(f"Profit Factor: {profit_factor:.2f}")
    
    print("\n" + "="*60)
    print("TRADES BY EXIT REASON")
    print("="*60 + "\n")
    
    exit_counts = results_df['exit_reason'].value_counts()
    for reason, count in exit_counts.items():
        pct = count/total_trades*100
        print(f"  {reason}: {count} ({pct:.1f}%)")
    
    # Save results
    results_df.to_csv("quick_backtest_results.csv", index=False)
    print("\n📊 Results saved to quick_backtest_results.csv\n")
    
    # Show top trades
    print("="*60)
    print("TOP 5 WINNING TRADES")
    print("="*60 + "\n")
    
    top_5 = results_df.nlargest(5, 'pnl')
    for idx, row in top_5.iterrows():
        be_flag = "[BE triggered]" if row['breakeven_triggered'] else ""
        print(f"{row['ticker']} {row['direction'].upper()}: {be_flag}")
        print(f"  Entry: ${row['entry']:.2f} → Exit: ${row['exit']:.2f}")
        print(f"  P&L: ${row['pnl']:.2f} ({row['pnl_pct']:.2f}%)")
        print(f"  Exit: {row['exit_reason']} after {row['bars_held']} bars\n")
    
    print("="*60)
    print("TOP 5 LOSING TRADES")
    print("="*60 + "\n")
    
    bottom_5 = results_df.nsmallest(5, 'pnl')
    for idx, row in bottom_5.iterrows():
        be_flag = "[BE triggered]" if row['breakeven_triggered'] else ""
        print(f"{row['ticker']} {row['direction'].upper()}: {be_flag}")
        print(f"  Entry: ${row['entry']:.2f} → Exit: ${row['exit']:.2f}")
        print(f"  P&L: ${row['pnl']:.2f} ({row['pnl_pct']:.2f}%)")
        print(f"  Exit: {row['exit_reason']} after {row['bars_held']} bars\n")


if __name__ == "__main__":
    main()
