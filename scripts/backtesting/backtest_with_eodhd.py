#!/usr/bin/env python3
"""
Simple EODHD Backtesting Script

Fetches historical data directly from EODHD and runs basic backtest.
No database required - works standalone.

Usage:
    python backtest_with_eodhd.py --ticker AAPL --days 30
    python backtest_with_eodhd.py --ticker SPY --start 2026-01-01 --end 2026-02-01
"""

import os
import sys
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json


def fetch_eodhd_data(ticker: str, start_date: datetime, end_date: datetime, interval: str = '5m') -> pd.DataFrame:
    """Fetch historical intraday data from EODHD"""
    api_key = os.getenv('EODHD_API_KEY')
    
    if not api_key:
        print("❌ ERROR: EODHD_API_KEY environment variable not set")
        print("")
        print("Set it with:")
        print("  $env:EODHD_API_KEY = 'your_api_key_here'  # PowerShell")
        print("  export EODHD_API_KEY='your_api_key_here'  # Linux/Mac")
        sys.exit(1)
    
    from_ts = int(start_date.timestamp())
    to_ts = int(end_date.timestamp())
    
    url = f'https://eodhd.com/api/intraday/{ticker}.US'
    params = {
        'api_token': api_key,
        'interval': interval,
        'from': from_ts,
        'to': to_ts,
        'fmt': 'json'
    }
    
    print(f"📡 Fetching {ticker} data from EODHD...")
    print(f"   Date range: {start_date.date()} to {end_date.date()}")
    print(f"   Interval: {interval}")
    
    try:
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if not data:
                print(f"❌ No data returned for {ticker}")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]
            df = df.sort_values('datetime').reset_index(drop=True)
            
            print(f"✅ Loaded {len(df):,} bars")
            print(f"   First bar: {df['datetime'].iloc[0]}")
            print(f"   Last bar: {df['datetime'].iloc[-1]}")
            print(f"   Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
            
            return df
        
        else:
            print(f"❌ EODHD API error: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return pd.DataFrame()
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return pd.DataFrame()


def detect_simple_breakout(df: pd.DataFrame, lookback: int = 20) -> List[Dict]:
    """Detect simple breakout signals"""
    signals = []
    
    print(f"\n🔍 Scanning for breakout signals...")
    
    for i in range(lookback, len(df) - 5):
        # Get recent high/low
        recent_bars = df.iloc[i-lookback:i]
        swing_high = recent_bars['high'].max()
        swing_low = recent_bars['low'].min()
        
        current_bar = df.iloc[i]
        
        # Bullish breakout
        if current_bar['close'] > swing_high:
            strength = (current_bar['close'] - swing_high) / swing_high
            
            if strength >= 0.005:  # 0.5% breakout
                signals.append({
                    'index': i,
                    'datetime': current_bar['datetime'],
                    'direction': 'LONG',
                    'entry_price': current_bar['close'],
                    'strength': strength,
                    'swing_high': swing_high,
                    'swing_low': swing_low
                })
        
        # Bearish breakdown
        elif current_bar['close'] < swing_low:
            strength = (swing_low - current_bar['close']) / swing_low
            
            if strength >= 0.005:  # 0.5% breakdown
                signals.append({
                    'index': i,
                    'datetime': current_bar['datetime'],
                    'direction': 'SHORT',
                    'entry_price': current_bar['close'],
                    'strength': strength,
                    'swing_high': swing_high,
                    'swing_low': swing_low
                })
    
    print(f"✅ Found {len(signals)} potential signals")
    return signals


def simulate_trade(signal: Dict, df: pd.DataFrame, atr_multiplier: float = 3.0) -> Dict:
    """Simulate a trade outcome"""
    entry_idx = signal['index']
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    # Calculate ATR for stop
    atr_bars = df.iloc[max(0, entry_idx-14):entry_idx+1]
    atr = calculate_atr(atr_bars)
    
    if atr == 0:
        atr = entry_price * 0.01  # Fallback
    
    # Set stop and targets
    if direction == 'LONG':
        stop_price = entry_price - (atr * atr_multiplier)
        t1_price = entry_price + (atr * atr_multiplier)
        t2_price = entry_price + (atr * atr_multiplier * 2)
    else:  # SHORT
        stop_price = entry_price + (atr * atr_multiplier)
        t1_price = entry_price - (atr * atr_multiplier)
        t2_price = entry_price - (atr * atr_multiplier * 2)
    
    # Simulate through future bars
    future_bars = df.iloc[entry_idx+1:min(entry_idx+79, len(df))]  # Max ~6.5 hours (79 x 5min)
    
    exit_price = entry_price
    exit_reason = 'EOD'
    exit_time = signal['datetime']
    
    for idx, row in future_bars.iterrows():
        if direction == 'LONG':
            # Check stop
            if row['low'] <= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                exit_time = row['datetime']
                break
            # Check T2
            if row['high'] >= t2_price:
                exit_price = t2_price
                exit_reason = 'T2'
                exit_time = row['datetime']
                break
            # Check T1
            if row['high'] >= t1_price:
                exit_price = t1_price
                exit_reason = 'T1'
                exit_time = row['datetime']
                break
        
        else:  # SHORT
            # Check stop
            if row['high'] >= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                exit_time = row['datetime']
                break
            # Check T2
            if row['low'] <= t2_price:
                exit_price = t2_price
                exit_reason = 'T2'
                exit_time = row['datetime']
                break
            # Check T1
            if row['low'] <= t1_price:
                exit_price = t1_price
                exit_reason = 'T1'
                exit_time = row['datetime']
                break
    
    # Calculate P&L
    if direction == 'LONG':
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100
    
    # R-multiple
    risk = abs(entry_price - stop_price)
    reward = abs(exit_price - entry_price)
    r_multiple = (reward / risk) if risk > 0 else 0
    if pnl_pct < 0:
        r_multiple = -r_multiple
    
    return {
        'entry_time': signal['datetime'],
        'exit_time': exit_time,
        'direction': direction,
        'entry_price': entry_price,
        'stop_price': stop_price,
        't1_price': t1_price,
        't2_price': t2_price,
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'pnl_pct': pnl_pct,
        'r_multiple': r_multiple,
        'win': pnl_pct > 0
    }


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range"""
    if len(df) < 2:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(df)):
        high = df.iloc[i]['high']
        low = df.iloc[i]['low']
        prev_close = df.iloc[i-1]['close']
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return np.mean(true_ranges) if true_ranges else 0.0
    
    return np.mean(true_ranges[-period:])


def print_results(trades: List[Dict], ticker: str):
    """Print formatted backtest results"""
    if not trades:
        print("\n❌ No trades executed")
        return
    
    total = len(trades)
    winners = sum(1 for t in trades if t['win'])
    losers = total - winners
    win_rate = (winners / total) * 100
    
    total_r = sum(t['r_multiple'] for t in trades)
    avg_r = total_r / total
    
    winning_trades = [t for t in trades if t['win']]
    losing_trades = [t for t in trades if not t['win']]
    
    avg_win_pct = np.mean([t['pnl_pct'] for t in winning_trades]) if winning_trades else 0
    avg_loss_pct = np.mean([t['pnl_pct'] for t in losing_trades]) if losing_trades else 0
    
    # Exit breakdown
    exit_counts = {}
    for t in trades:
        reason = t['exit_reason']
        exit_counts[reason] = exit_counts.get(reason, 0) + 1
    
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print(f"\n📊 PERFORMANCE METRICS")
    print(f"  Ticker: {ticker}")
    print(f"  Total Trades: {total}")
    print(f"  Win Rate: {win_rate:.1f}% ({winners}W / {losers}L)")
    print(f"  Avg R-Multiple: {avg_r:.2f}R")
    print(f"  Total R: {total_r:+.2f}R")
    print(f"  Avg Win: {avg_win_pct:+.2f}%")
    print(f"  Avg Loss: {avg_loss_pct:.2f}%")
    
    print(f"\n📈 EXIT BREAKDOWN")
    for reason, count in sorted(exit_counts.items()):
        pct = (count / total) * 100
        print(f"  {reason}: {count} ({pct:.1f}%)")
    
    print(f"\n🎯 BEST/WORST")
    best = max(trades, key=lambda x: x['r_multiple'])
    worst = min(trades, key=lambda x: x['r_multiple'])
    print(f"  Best Trade: {best['r_multiple']:+.2f}R on {best['entry_time']}")
    print(f"  Worst Trade: {worst['r_multiple']:+.2f}R on {worst['entry_time']}")
    
    print("\n" + "="*80 + "\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Simple EODHD backtesting')
    parser.add_argument('--ticker', default='AAPL', help='Ticker symbol')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=30, help='Days back (if no start/end)')
    parser.add_argument('--interval', default='5m', choices=['1m', '5m', '1h'], help='Bar interval')
    parser.add_argument('--save', action='store_true', help='Save results to JSON')
    
    args = parser.parse_args()
    
    # Parse dates
    if args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    
    print("\n" + "="*80)
    print(f"EODHD BACKTEST - {args.ticker}")
    print("="*80 + "\n")
    
    # Fetch data
    df = fetch_eodhd_data(args.ticker, start_date, end_date, args.interval)
    
    if df.empty:
        print("\n❌ Failed to fetch data. Exiting.")
        sys.exit(1)
    
    # Detect signals
    signals = detect_simple_breakout(df)
    
    if not signals:
        print("\n❌ No signals found. Try:")
        print("   - Increasing date range (--days 60)")
        print("   - Different ticker (--ticker TSLA)")
        print("   - Smaller interval (--interval 1m)")
        sys.exit(0)
    
    # Simulate trades
    print(f"\n💼 Simulating {len(signals)} trades...")
    trades = []
    
    for signal in signals:
        trade = simulate_trade(signal, df)
        trades.append(trade)
    
    # Print results
    print_results(trades, args.ticker)
    
    # Save if requested
    if args.save:
        output = {
            'ticker': args.ticker,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_trades': len(trades),
            'trades': trades
        }
        
        filename = f"backtest_{args.ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        
        print(f"💾 Results saved to: {filename}\n")


if __name__ == '__main__':
    main()
