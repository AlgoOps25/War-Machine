#!/usr/bin/env python3
"""
Backtest Comprehensive Multi-Indicator Detector

Tests the comprehensive detector that uses:
- BOS/FVG from MTF engine with 3-tier confirmation
- Volume Profile (HVN/LVN zones)
- VWAP bands
- Opening Range classification
- Multi-timeframe trend alignment

Focuses on:
1. Opening Range (9:30-10:00) - First BOS opportunity
2. Intraday high-quality setups throughout day

Only signals A+ and A grades (75%+ confidence)

Usage:
    python backtest_comprehensive.py --quick
    python backtest_comprehensive.py --days 90
"""

import sys
sys.path.append('.')

import json
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List
from collections import Counter
from dataclasses import asdict

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from app.signals.comprehensive_detector import get_comprehensive_detector, ComprehensiveSignal

ET = ZoneInfo("America/New_York")


def get_bars(ticker: str, days_back: int) -> List[Dict]:
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


def aggregate_bars(bars_1min: List[Dict], period_mins: int) -> List[Dict]:
    if not bars_1min:
        return []
    
    bars_agg = []
    i = 0
    
    while i < len(bars_1min):
        start_bar = bars_1min[i]
        start_time = start_bar['datetime']
        
        period_bars = [start_bar]
        j = i + 1
        
        while j < len(bars_1min) and j < i + period_mins:
            next_bar = bars_1min[j]
            if (next_bar['datetime'] - start_time).seconds < period_mins * 60:
                period_bars.append(next_bar)
                j += 1
            else:
                break
        
        bar_agg = {
            'datetime': start_time,
            'open': period_bars[0]['open'],
            'high': max(b['high'] for b in period_bars),
            'low': min(b['low'] for b in period_bars),
            'close': period_bars[-1]['close'],
            'volume': sum(b['volume'] for b in period_bars)
        }
        
        bars_agg.append(bar_agg)
        i = j
    
    return bars_agg


def scan_ticker(ticker: str, days_back: int) -> List[ComprehensiveSignal]:
    print(f"\n[SCAN] {ticker}...")
    
    bars_1min = get_bars(ticker, days_back)
    
    if not bars_1min or len(bars_1min) < 500:
        print(f"[SCAN] Insufficient data")
        return []
    
    print(f"[SCAN] Loaded {len(bars_1min):,} 1min bars")
    
    bars_5min = aggregate_bars(bars_1min, 5)
    bars_15min = aggregate_bars(bars_1min, 15)
    
    detector = get_comprehensive_detector()
    signals = []
    
    # Scan every bar
    for idx in range(50, len(bars_1min) - 10):
        # Get bars up to current point
        current_bars_1min = bars_1min[:idx+1]
        
        # Find matching 5min/15min bars
        current_time = bars_1min[idx]['datetime']
        current_bars_5min = [b for b in bars_5min if b['datetime'] <= current_time]
        current_bars_15min = [b for b in bars_15min if b['datetime'] <= current_time]
        
        signal = detector.detect_signals(
            ticker, current_bars_1min, current_bars_5min, current_bars_15min
        )
        
        if signal:
            signals.append(signal)
    
    print(f"[SCAN] Found {len(signals)} signals")
    
    if signals:
        grades = Counter([s.grade for s in signals])
        or_signals = sum(1 for s in signals if s.is_opening_range)
        print(f"[SCAN] Grades: {dict(grades)}")
        print(f"[SCAN] Opening Range signals: {or_signals}")
    
    return signals


def simulate_trade(signal: ComprehensiveSignal, bars: List[Dict]) -> Dict:
    # Find signal bar
    signal_idx = None
    for i, bar in enumerate(bars):
        if bar['datetime'] == signal.timestamp:
            signal_idx = i
            break
    
    if signal_idx is None or signal_idx >= len(bars) - 5:
        return {'r_multiple': 0.0, 'win': False, 'exit_reason': 'NO_DATA'}
    
    entry_price = signal.entry_price
    stop_price = signal.stop_price
    target_1 = signal.target_1
    target_2 = signal.target_2
    
    exit_price = entry_price
    exit_reason = 'EOD'
    hold_time = 0
    
    # Scan forward bars
    future_bars = bars[signal_idx+1:min(signal_idx+391, len(bars))]
    
    for i, bar in enumerate(future_bars):
        hold_time = i + 1
        
        if signal.direction == 'CALL':
            # Check stop
            if bar['low'] <= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                break
            # Check T2
            if bar['high'] >= target_2:
                exit_price = target_2
                exit_reason = 'T2'
                break
            # Check T1
            if bar['high'] >= target_1:
                exit_price = target_1
                exit_reason = 'T1'
                break
        else:  # PUT
            # Check stop
            if bar['high'] >= stop_price:
                exit_price = stop_price
                exit_reason = 'STOP'
                break
            # Check T2
            if bar['low'] <= target_2:
                exit_price = target_2
                exit_reason = 'T2'
                break
            # Check T1
            if bar['low'] <= target_1:
                exit_price = target_1
                exit_reason = 'T1'
                break
        
        if i == len(future_bars) - 1:
            exit_price = bar['close']
            exit_reason = 'EOD'
    
    # Calculate R multiple
    risk = abs(entry_price - stop_price)
    
    if signal.direction == 'CALL':
        profit = exit_price - entry_price
    else:
        profit = entry_price - exit_price
    
    r_mult = profit / risk if risk > 0 else 0
    
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
            'trades': 0,
            'wins': 0,
            'win_rate': 0.0,
            'avg_r': 0.0,
            'total_r': 0.0
        }
    
    wins = sum(1 for r in results if r['win'])
    r_multiples = [r['r_multiple'] for r in results]
    
    return {
        'trades': len(results),
        'wins': wins,
        'win_rate': wins / len(results),
        'avg_r': sum(r_multiples) / len(r_multiples),
        'total_r': sum(r_multiples),
        'exit_breakdown': dict(Counter([r['exit_reason'] for r in results]))
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--days', type=int, default=90)
    args = parser.parse_args()
    
    if args.quick:
        tickers = ['AAPL', 'NVDA', 'TSLA']
        days = 30
    else:
        tickers = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META']
        days = args.days
    
    print(f"\n{'='*80}")
    print("COMPREHENSIVE MULTI-INDICATOR DETECTOR BACKTEST")
    print(f"{'='*80}")
    print(f"\nTickers: {', '.join(tickers)}")
    print(f"Period: {days} days\n")
    
    # Scan all tickers
    all_signals = []
    ticker_bars = {}
    
    for ticker in tickers:
        signals = scan_ticker(ticker, days)
        all_signals.extend(signals)
        
        if signals:
            ticker_bars[ticker] = get_bars(ticker, days)
    
    print(f"\n{'='*80}")
    print(f"TOTAL SIGNALS: {len(all_signals)}")
    print(f"{'='*80}\n")
    
    if not all_signals:
        print("No signals found!\n")
        return
    
    # Grade distribution
    grade_counts = Counter([s.grade for s in all_signals])
    print("🎖️  Grade Distribution:")
    for grade in ['A+', 'A', 'B', 'C']:
        count = grade_counts.get(grade, 0)
        pct = count / len(all_signals) * 100 if all_signals else 0
        print(f"   {grade}: {count} ({pct:.1f}%)")
    
    # Opening Range vs Intraday
    or_signals = [s for s in all_signals if s.is_opening_range]
    intraday_signals = [s for s in all_signals if not s.is_opening_range]
    print(f"\n⏰ Session Distribution:")
    print(f"   Opening Range (9:30-10:00): {len(or_signals)}")
    print(f"   Intraday (10:00-15:30): {len(intraday_signals)}")
    
    # Simulate trades
    print(f"\n🔬 Simulating {len(all_signals)} trades...\n")
    
    all_results = []
    results_by_grade = {'A+': [], 'A': [], 'B': [], 'C': []}
    results_by_session = {'OR': [], 'Intraday': []}
    
    # Store detailed signal data for analysis
    detailed_signals = []
    
    for signal in all_signals:
        bars = ticker_bars.get(signal.ticker, [])
        if not bars:
            continue
        
        result = simulate_trade(signal, bars)
        all_results.append(result)
        
        if signal.grade in results_by_grade:
            results_by_grade[signal.grade].append(result)
        
        session = 'OR' if signal.is_opening_range else 'Intraday'
        results_by_session[session].append(result)
        
        # Create detailed signal record
        signal_data = {
            'ticker': signal.ticker,
            'timestamp': signal.timestamp.isoformat(),
            'time': signal.timestamp.strftime('%H:%M'),
            'direction': signal.direction,
            'entry_price': signal.entry_price,
            'stop_price': signal.stop_price,
            'target_1': signal.target_1,
            'target_2': signal.target_2,
            'grade': signal.grade,
            'confidence': signal.confidence,
            'bos_price': signal.bos_price,
            'bos_strength': signal.bos_strength,
            'fvg_low': signal.fvg_low,
            'fvg_high': signal.fvg_high,
            'fvg_size_pct': signal.fvg_size_pct,
            'confirmation_grade': signal.confirmation_grade,
            'confirmation_score': signal.confirmation_score,
            'volume_ratio': signal.volume_ratio,
            'volume_profile_zone': signal.volume_profile_zone,
            'price_vs_vwap': signal.price_vs_vwap,
            'vwap_band': signal.vwap_band,
            'is_opening_range': signal.is_opening_range,
            'or_classification': signal.or_classification,
            'or_boost': signal.or_boost,
            'mtf_score': signal.mtf_score,
            'trend_1min': signal.trend_1min,
            'trend_5min': signal.trend_5min,
            'trend_15min': signal.trend_15min,
            'result_r': result['r_multiple'],
            'exit_reason': result['exit_reason'],
            'hold_time': result['hold_time']
        }
        
        detailed_signals.append(signal_data)
    
    # Calculate metrics
    all_metrics = calculate_metrics(all_results)
    grade_metrics = {g: calculate_metrics(r) for g, r in results_by_grade.items()}
    session_metrics = {s: calculate_metrics(r) for s, r in results_by_session.items()}
    
    # Display results
    print(f"{'='*80}")
    print("RESULTS")
    print(f"{'='*80}\n")
    
    print("ALL SIGNALS:")
    m = all_metrics
    print(f"  Trades: {m['trades']}")
    print(f"  Win Rate: {m['win_rate']:.1%}")
    print(f"  Avg R: {m['avg_r']:+.2f}R")
    print(f"  Total R: {m['total_r']:+.2f}R\n")
    
    print("BY GRADE:\n")
    for grade in ['A+', 'A', 'B', 'C']:
        m = grade_metrics[grade]
        if m['trades'] == 0:
            continue
        print(f"{grade}:")
        print(f"  Trades: {m['trades']}")
        print(f"  Win Rate: {m['win_rate']:.1%}")
        print(f"  Avg R: {m['avg_r']:+.2f}R")
        print()
    
    print("BY SESSION:\n")
    for session in ['OR', 'Intraday']:
        m = session_metrics[session]
        if m['trades'] == 0:
            continue
        print(f"{session}:")
        print(f"  Trades: {m['trades']}")
        print(f"  Win Rate: {m['win_rate']:.1%}")
        print(f"  Avg R: {m['avg_r']:+.2f}R")
        print()
    
    # Save results with detailed signal data
    output = {
        'total_signals': len(all_signals),
        'grade_distribution': dict(grade_counts),
        'all_metrics': all_metrics,
        'grade_metrics': grade_metrics,
        'session_metrics': session_metrics,
        'signals': detailed_signals  # NEW: Save all signal details
    }
    
    with open('backtest_comprehensive.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("✅ Results saved to: backtest_comprehensive.json\n")


if __name__ == "__main__":
    main()
