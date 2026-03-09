#!/usr/bin/env python3
"""
Backtest Realistic Detector

Tests the realistic detector with achievable thresholds:
- Volume: 1.3x (was 2.0x)
- Breakout: 0.5% (was 1.0%)
- Market hours: 9:30-16:00

Expected: 20-50 signals per 30 days

Usage:
    python backtest_realistic_detector.py --quick
    python backtest_realistic_detector.py
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
from app.signals.realistic_bos_fvg import get_realistic_detector, RealisticSignal

ET = ZoneInfo("America/New_York")


def get_bars_for_ticker(ticker: str, days_back: int) -> List[Dict]:
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    
    p = ph()
    conn = get_conn()
    
    try:
        cursor = dict_cursor(conn)
        
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
    if not bars_1min:
        return []
    
    bars_5min = []
    i = 0
    
    while i < len(bars_1min):
        start_bar = bars_1min[i]
        start_time = start_bar['datetime']
        
        period_bars = [start_bar]
        j = i + 1
        
        while j < len(bars_1min) and j < i + 5:
            next_bar = bars_1min[j]
            if (next_bar['datetime'] - start_time).seconds < 300:
                period_bars.append(next_bar)
                j += 1
            else:
                break
        
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


def scan_signals(ticker: str, days_back: int) -> List[RealisticSignal]:
    print(f"[SCAN] Scanning {ticker}...")
    
    bars_1min = get_bars_for_ticker(ticker, days_back)
    
    if not bars_1min or len(bars_1min) < 500:
        print(f"[SCAN] Insufficient data for {ticker}")
        return []
    
    print(f"[SCAN] Loaded {len(bars_1min):,} 1min bars")
    
    bars_5min = aggregate_to_5min(bars_1min)
    
    detector = get_realistic_detector()
    signals = []
    
    for idx in range(50, len(bars_1min) - 10):
        signal = detector.detect_signals(bars_1min, bars_5min, idx)
        
        if signal:
            signal.ticker = ticker
            signals.append(signal)
    
    print(f"[SCAN] Found {len(signals)} signals")
    
    if signals:
        grades = Counter([s.grade for s in signals])
        print(f"[SCAN] Grades: {dict(grades)}")
    
    return signals


def calculate_atr(bars: List[Dict], period: int = 14) -> float:
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


def simulate_trade(signal: RealisticSignal, bars: List[Dict], atr_mult: float = 3.0) -> Dict:
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
    
    atr_bars = bars[max(0, signal_idx-50):signal_idx+1]
    atr = calculate_atr(atr_bars)
    
    if atr == 0:
        atr = entry_price * 0.01
    
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
    if not results:
        return {
            'total_trades': 0,
            'wins': 0,
            'win_rate': 0.0,
            'avg_r': 0.0,
            'total_r': 0.0,
            'sharpe': 0.0,
            'max_dd': 0.0
        }
    
    wins = sum(1 for r in results if r['win'])
    win_rate = wins / len(results)
    
    r_multiples = [r['r_multiple'] for r in results]
    avg_r = np.mean(r_multiples)
    total_r = sum(r_multiples)
    
    if len(r_multiples) > 1 and np.std(r_multiples) > 0:
        sharpe = (np.mean(r_multiples) / np.std(r_multiples)) * np.sqrt(252)
    else:
        sharpe = 0.0
    
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
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'exit_breakdown': dict(Counter([r['exit_reason'] for r in results]))
    }


def run_backtest(tickers: List[str], days_back: int = 90) -> Dict:
    print(f"\n{'='*80}")
    print("REALISTIC DETECTOR BACKTEST")
    print(f"{'='*80}\n")
    
    all_signals = []
    ticker_bars = {}
    
    for ticker in tickers:
        signals = scan_signals(ticker, days_back)
        all_signals.extend(signals)
        
        if signals:
            ticker_bars[ticker] = get_bars_for_ticker(ticker, days_back)
    
    print(f"\n✅ Total signals: {len(all_signals)}\n")
    
    if not all_signals:
        return {'error': 'No signals found'}
    
    grade_counts = Counter([s.grade for s in all_signals])
    print(f"🎖️  Grade Distribution:")
    for grade in ['A+', 'A', 'B', 'C']:
        count = grade_counts.get(grade, 0)
        pct = count / len(all_signals) * 100 if all_signals else 0
        print(f"   {grade}: {count} ({pct:.1f}%)")
    
    print(f"\n🔬 Simulating {len(all_signals)} trades...\n")
    
    all_results = []
    results_by_grade = {'A+': [], 'A': [], 'B': [], 'C': []}
    
    for signal in all_signals:
        bars = ticker_bars.get(signal.ticker, [])
        
        if not bars:
            continue
        
        result = simulate_trade(signal, bars)
        all_results.append(result)
        
        if signal.grade in results_by_grade:
            results_by_grade[signal.grade].append(result)
    
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
    
    if 'error' in result:
        print(f"\n⚠️  {result['error']}\n")
        return
    
    print(f"\n{'='*80}")
    print("RESULTS")
    print(f"{'='*80}\n")
    
    all_m = result['all_signals']
    print(f"ALL SIGNALS:")
    print(f"  Trades: {all_m['total_trades']}")
    print(f"  Win Rate: {all_m['win_rate']:.1%}")
    print(f"  Avg R: {all_m['avg_r']:+.2f}R")
    print(f"  Total R: {all_m['total_r']:+.2f}R")
    print(f"  Sharpe: {all_m['sharpe']:.2f}")
    print(f"  Max DD: {all_m['max_dd']:.2f}R\n")
    
    print(f"BY GRADE:\n")
    
    for grade in ['A+', 'A', 'B', 'C']:
        m = result['by_grade'][grade]
        if m['total_trades'] == 0:
            continue
        
        print(f"{grade}:")
        print(f"  Trades: {m['total_trades']}")
        print(f"  Win Rate: {m['win_rate']:.1%}")
        print(f"  Avg R: {m['avg_r']:+.2f}R")
        print(f"  Total R: {m['total_r']:+.2f}R")
        print()
    
    with open('backtest_realistic.json', 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    print("✅ Results saved to: backtest_realistic.json\n")


if __name__ == "__main__":
    main()
