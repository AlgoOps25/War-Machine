#!/usr/bin/env python3
"""
Backtest Enhanced Detector V2

Tests the new market-structure-aware detector against old detector.

Key improvements tested:
1. Trend alignment (1min + 5min must agree)
2. Prior consolidation requirement
3. VWAP directional gate
4. No pre-market/after-hours
5. Signal grading system

Usage:
    python backtest_v2_detector.py
    python backtest_v2_detector.py --quick
"""

import sys
sys.path.append('.')

import json
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List
from collections import Counter
import argparse

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from app.signals.enhanced_bos_fvg_v2 import get_enhanced_detector_v2, EnhancedSignalV2

ET = ZoneInfo("America/New_York")


def get_bars_for_ticker(ticker: str, days_back: int, interval: str = '1min') -> List[Dict]:
    """Fetch bars from PostgreSQL"""
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    
    p = ph()
    conn = get_conn()
    
    try:
        cursor = dict_cursor(conn)
        
        # Get 1min bars
        cursor.execute(f"""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = {p}
              AND datetime >= {p}
              AND datetime <= {p}
            ORDER BY datetime ASC
        """, (ticker, start_date, end_date))
        
        rows = cursor.fetchall()
        
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
    
    finally:
        return_conn(conn)


def aggregate_to_5min(bars_1min: List[Dict]) -> List[Dict]:
    """Aggregate 1min bars to 5min"""
    if not bars_1min:
        return []
    
    bars_5min = []
    
    i = 0
    while i < len(bars_1min):
        # Start new 5min bar
        start_bar = bars_1min[i]
        start_time = start_bar['datetime']
        
        # Collect next 5 bars (or until new 5min period)
        period_bars = [start_bar]
        j = i + 1
        
        while j < len(bars_1min) and j < i + 5:
            next_bar = bars_1min[j]
            # Check if still in same 5min period
            if (next_bar['datetime'] - start_time).seconds < 300:
                period_bars.append(next_bar)
                j += 1
            else:
                break
        
        # Aggregate
        bar_5min = {
            'datetime': start_time,
            'open': period_bars[0]['open'],
            'high': max(b['high'] for b in period_bars),
            'low': min(b['low'] for b in period_bars),
            'close': period_bars[-1]['close'],
            'volume': sum(b['volume'] for b in period_bars)
        }
        
        bars_5min.append(bar_5min)
        i = j
    
    return bars_5min


def scan_v2_signals(ticker: str, days_back: int) -> List[EnhancedSignalV2]:
    """Scan using v2 detector"""
    print(f"[SCAN] Scanning {ticker} with V2 detector...")
    
    # Get 1min bars
    bars_1min = get_bars_for_ticker(ticker, days_back)
    
    if not bars_1min or len(bars_1min) < 500:
        print(f"[SCAN] Insufficient data for {ticker}")
        return []
    
    print(f"[SCAN] Loaded {len(bars_1min):,} 1min bars")
    
    # Aggregate to 5min
    bars_5min = aggregate_to_5min(bars_1min)
    print(f"[SCAN] Aggregated to {len(bars_5min):,} 5min bars")
    
    # Run detector
    detector = get_enhanced_detector_v2()
    signals = []
    
    for idx in range(100, len(bars_1min) - 10):
        signal = detector.detect_signals(bars_1min, bars_5min, idx)
        
        if signal:
            # Set ticker
            signal.ticker = ticker
            signals.append(signal)
    
    print(f"[SCAN] Found {len(signals)} V2 signals")
    
    # Show grade distribution
    if signals:
        grades = Counter([s.grade for s in signals])
        print(f"[SCAN] Grade distribution: {dict(grades)}")
    
    return signals


def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate ATR"""
    if len(bars) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i]['high']
        low = bars[i]['low']
        prev_close = bars[i-1]['close']
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return 0.0
    
    return np.mean(true_ranges[-period:])


def simulate_trade_v2(signal: EnhancedSignalV2, bars: List[Dict], atr_mult: float = 3.0) -> Dict:
    """Simulate trade for v2 signal"""
    # Find signal bar
    signal_idx = None
    for i, bar in enumerate(bars):
        if bar['datetime'] == signal.timestamp:
            signal_idx = i
            break
    
    if signal_idx is None or signal_idx >= len(bars) - 5:
        return {
            'signal': signal,
            'r_multiple': 0.0,
            'win': False,
            'exit_reason': 'NO_DATA'
        }
    
    entry_price = signal.entry_price
    
    # Calculate ATR
    atr_bars = bars[max(0, signal_idx-50):signal_idx+1]
    atr = calculate_atr(atr_bars)
    
    if atr == 0:
        atr = entry_price * 0.01
    
    # Set stops/targets
    if signal.direction == 'CALL':
        stop_price = entry_price - (atr * atr_mult)
        target_1r = entry_price + (atr * atr_mult * 1)
        target_2r = entry_price + (atr * atr_mult * 2)
        target_3r = entry_price + (atr * atr_mult * 3)
    else:
        stop_price = entry_price + (atr * atr_mult)
        target_1r = entry_price - (atr * atr_mult * 1)
        target_2r = entry_price - (atr * atr_mult * 2)
        target_3r = entry_price - (atr * atr_mult * 3)
    
    # Simulate
    exit_price = entry_price
    exit_reason = 'EOD'
    hold_time = 0
    
    future_bars = bars[signal_idx+1:min(signal_idx+391, len(bars))]
    
    for i, bar in enumerate(future_bars):
        hold_time = i + 1
        
        if signal.direction == 'CALL':
            if bar['low'] <= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                break
            if bar['high'] >= target_3r:
                exit_price = target_3r
                exit_reason = 'T3'
                break
            if bar['high'] >= target_2r:
                exit_price = target_2r
                exit_reason = 'T2'
                break
            if bar['high'] >= target_1r:
                exit_price = target_1r
                exit_reason = 'T1'
                break
        else:
            if bar['high'] >= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                break
            if bar['low'] <= target_3r:
                exit_price = target_3r
                exit_reason = 'T3'
                break
            if bar['low'] <= target_2r:
                exit_price = target_2r
                exit_reason = 'T2'
                break
            if bar['low'] <= target_1r:
                exit_price = target_1r
                exit_reason = 'T1'
                break
        
        if i == len(future_bars) - 1:
            exit_price = bar['close']
            exit_reason = 'EOD'
    
    # Calculate
    if signal.direction == 'CALL':
        r_mult = (exit_price - entry_price) / (atr * atr_mult)
    else:
        r_mult = (entry_price - exit_price) / (atr * atr_mult)
    
    return {
        'signal': signal,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'r_multiple': r_mult,
        'win': r_mult > 0,
        'hold_time': hold_time
    }


def calculate_metrics(results: List[Dict]) -> Dict:
    """Calculate performance metrics"""
    if not results:
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0.0,
            'avg_r': 0.0,
            'total_r': 0.0,
            'sharpe': 0.0,
            'max_dd': 0.0
        }
    
    wins = sum(1 for r in results if r['win'])
    losses = len(results) - wins
    win_rate = wins / len(results)
    
    r_multiples = [r['r_multiple'] for r in results]
    avg_r = np.mean(r_multiples)
    total_r = sum(r_multiples)
    
    if len(r_multiples) > 1 and np.std(r_multiples) > 0:
        sharpe = (np.mean(r_multiples) / np.std(r_multiples)) * np.sqrt(252)
    else:
        sharpe = 0.0
    
    # Max DD
    cumulative_r = []
    running = 0
    for r in r_multiples:
        running += r
        cumulative_r.append(running)
    
    max_dd = 0
    if cumulative_r:
        peak = cumulative_r[0]
        for val in cumulative_r:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
    
    return {
        'total_trades': len(results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'exit_breakdown': dict(Counter([r['exit_reason'] for r in results]))
    }


def run_backtest(tickers: List[str], days_back: int = 90) -> Dict:
    """Run V2 backtest"""
    print(f"\n{'='*80}")
    print("ENHANCED DETECTOR V2 BACKTEST")
    print(f"{'='*80}\n")
    
    all_signals = []
    ticker_bars = {}
    
    # Scan all tickers
    for ticker in tickers:
        signals = scan_v2_signals(ticker, days_back)
        all_signals.extend(signals)
        
        if signals:
            ticker_bars[ticker] = get_bars_for_ticker(ticker, days_back)
    
    print(f"\n✅ Total V2 signals: {len(all_signals)}\n")
    
    if not all_signals:
        return {'error': 'No signals found'}
    
    # Analyze by grade
    grade_counts = Counter([s.grade for s in all_signals])
    print(f"🎖️  Grade Distribution:")
    for grade in ['A+', 'A', 'B', 'C']:
        count = grade_counts.get(grade, 0)
        pct = count / len(all_signals) * 100
        print(f"   {grade}: {count} signals ({pct:.1f}%)")
    
    # Process all signals
    print(f"\n🔬 Simulating {len(all_signals)} trades...\n")
    
    all_results = []
    results_by_grade = {'A+': [], 'A': [], 'B': [], 'C': []}
    
    for signal in all_signals:
        bars = ticker_bars.get(signal.ticker, [])
        
        if not bars:
            continue
        
        result = simulate_trade_v2(signal, bars)
        all_results.append(result)
        
        # Track by grade
        if signal.grade in results_by_grade:
            results_by_grade[signal.grade].append(result)
    
    # Calculate metrics
    all_metrics = calculate_metrics(all_results)
    grade_metrics = {grade: calculate_metrics(results) for grade, results in results_by_grade.items()}
    
    return {
        'total_signals': len(all_signals),
        'grade_distribution': dict(grade_counts),
        'all_signals': all_metrics,
        'by_grade': grade_metrics
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='Quick test (3 tickers, 30 days)')
    parser.add_argument('--days', type=int, default=90, help='Days back')
    args = parser.parse_args()
    
    if args.quick:
        tickers = ['AAPL', 'NVDA', 'TSLA']
        days = 30
    else:
        tickers = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META', 'GOOGL', 'AMD']
        days = args.days
    
    print(f"\nTesting {len(tickers)} tickers: {', '.join(tickers)}")
    print(f"Date range: Past {days} days\n")
    
    result = run_backtest(tickers, days)
    
    # Display results
    print(f"\n{'='*80}")
    print("RESULTS SUMMARY")
    print(f"{'='*80}\n")
    
    all_m = result['all_signals']
    print(f"ALL SIGNALS:")
    print(f"  Trades: {all_m['total_trades']}")
    print(f"  Win Rate: {all_m['win_rate']:.1%}")
    print(f"  Avg R: {all_m['avg_r']:.2f}R")
    print(f"  Total R: {all_m['total_r']:.2f}R")
    print(f"  Sharpe: {all_m['sharpe']:.2f}")
    print(f"  Max DD: {all_m['max_dd']:.2f}R\n")
    
    print(f"PERFORMANCE BY GRADE:\n")
    
    for grade in ['A+', 'A', 'B', 'C']:
        m = result['by_grade'][grade]
        if m['total_trades'] == 0:
            continue
        
        print(f"{grade} Grade:")
        print(f"  Trades: {m['total_trades']}")
        print(f"  Win Rate: {m['win_rate']:.1%}")
        print(f"  Avg R: {m['avg_r']:.2f}R")
        print(f"  Total R: {m['total_r']:.2f}R")
        print()
    
    # Save
    with open('backtest_v2_detector.json', 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    print("✅ Results saved to: backtest_v2_detector.json\n")


if __name__ == "__main__":
    main()
