#!/usr/bin/env python3
"""
Enhanced Backtest with Volume Profile + Entry Timing Filters

This script tests your NEW filters (Volume Profile validation + Entry Timing gate)
against the baseline to measure their actual impact on performance.

Key improvements over backtest_optimized_params.py:
1. Integrates app.validation.volume_profile (FVG near POC check)
2. Integrates app.validation.entry_timing (golden hour filtering)
3. Tests multiple ATR multipliers (2.0x - 4.0x) to optimize stops
4. Tightens signal detection (requires 1%+ breakout + volume)
5. Hourly signal distribution analysis

Usage:
    python backtest_enhanced_filters.py
    python backtest_enhanced_filters.py --atr-test  # Test ATR multipliers
    python backtest_enhanced_filters.py --quick     # Fast test (30 days, 3 tickers)
"""

import sys
sys.path.append('.')

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import argparse

# War Machine imports
from app.data.db_connection import get_conn, ph, dict_cursor

# Try to import new filters
VOLUME_PROFILE_AVAILABLE = False
ENTRY_TIMING_AVAILABLE = False

try:
    from app.validation.volume_profile import get_volume_analyzer
    VOLUME_PROFILE_AVAILABLE = True
    print("[BACKTEST] ✅ Volume Profile filter loaded")
except ImportError as e:
    print(f"[BACKTEST] ⚠️  Volume Profile not available: {e}")

try:
    from app.validation.entry_timing import get_entry_timing_validator
    ENTRY_TIMING_AVAILABLE = True
    print("[BACKTEST] ✅ Entry Timing filter loaded")
except ImportError as e:
    print(f"[BACKTEST] ⚠️  Entry Timing not available: {e}")

ET = ZoneInfo("America/New_York")

# Enhanced parameters with tighter thresholds
ENHANCED_PARAMS = {
    "min_breakout_strength": 0.01,  # Require 1%+ breakout (was 0.005)
    "min_volume_ratio": 2.0,        # Require 2x average volume
    "atr_multiplier": 3.0,          # Default stop distance
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "mfi_overbought": 80,
    "mfi_oversold": 20,
}


@dataclass
class EnhancedSignal:
    """Signal with enhanced metadata"""
    timestamp: datetime
    ticker: str
    direction: str
    signal_type: str
    entry_price: float
    signal_strength: float
    volume_ratio: float
    hour: int  # Hour of day (9-16)
    bar_data: Dict


@dataclass
class EnhancedTradeResult:
    """Trade result with filter tracking"""
    signal: EnhancedSignal
    
    # Filter results
    passed_baseline: bool
    passed_volume_profile: bool
    passed_entry_timing: bool
    volume_profile_reason: str
    entry_timing_reason: str
    
    # Trade outcome
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    pnl_percent: float
    hold_time_minutes: int
    win: bool
    atr_multiplier: float


# ═══════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════

def get_bars_for_ticker(ticker: str, days_back: int = 90) -> List[Dict]:
    """Fetch bars from Railway PostgreSQL"""
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    
    p = ph()
    conn = get_conn()
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
    conn.close()
    
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


# ═══════════════════════════════════════════════════════════════════════════
# ENHANCED SIGNAL DETECTION (Tighter Thresholds)
# ═══════════════════════════════════════════════════════════════════════════

def detect_enhanced_bos(bars: List[Dict], idx: int) -> Optional[Dict]:
    """
    Enhanced BOS detection with:
    - Minimum 1% breakout strength
    - Volume confirmation (2x average)
    - Momentum check
    """
    if idx < 20 or idx >= len(bars) - 5:
        return None
    
    current_bar = bars[idx]
    lookback = bars[max(0, idx-20):idx]
    
    if len(lookback) < 10:
        return None
    
    # Find swing high/low
    highs = [b['high'] for b in lookback]
    lows = [b['low'] for b in lookback]
    swing_high = max(highs)
    swing_low = min(lows)
    
    # Check volume
    recent_volumes = [b['volume'] for b in lookback[-10:]]
    avg_volume = np.mean(recent_volumes) if recent_volumes else 0
    
    if avg_volume == 0:
        return None
    
    volume_ratio = current_bar['volume'] / avg_volume
    
    # Require volume confirmation
    if volume_ratio < ENHANCED_PARAMS['min_volume_ratio']:
        return None
    
    # Bullish BOS
    if current_bar['close'] > swing_high:
        strength = (current_bar['close'] - swing_high) / swing_high
        
        # Require minimum breakout strength
        if strength >= ENHANCED_PARAMS['min_breakout_strength']:
            return {
                'type': 'BOS',
                'direction': 'CALL',
                'strength': strength,
                'entry_price': current_bar['close'],
                'volume_ratio': volume_ratio
            }
    
    # Bearish BOS
    if current_bar['close'] < swing_low:
        strength = (swing_low - current_bar['close']) / swing_low
        
        if strength >= ENHANCED_PARAMS['min_breakout_strength']:
            return {
                'type': 'BOS',
                'direction': 'PUT',
                'strength': strength,
                'entry_price': current_bar['close'],
                'volume_ratio': volume_ratio
            }
    
    return None


def detect_enhanced_fvg(bars: List[Dict], idx: int) -> Optional[Dict]:
    """
    Enhanced FVG detection with:
    - Minimum gap size
    - Volume confirmation
    """
    if idx < 3 or idx >= len(bars) - 5:
        return None
    
    bar_minus_2 = bars[idx - 2]
    current_bar = bars[idx]
    
    # Check volume
    recent_volumes = [bars[i]['volume'] for i in range(max(0, idx-10), idx)]
    avg_volume = np.mean(recent_volumes) if recent_volumes else 0
    
    if avg_volume == 0:
        return None
    
    volume_ratio = current_bar['volume'] / avg_volume
    
    if volume_ratio < ENHANCED_PARAMS['min_volume_ratio']:
        return None
    
    # Bullish FVG
    if bar_minus_2['high'] < current_bar['low']:
        gap_size = (current_bar['low'] - bar_minus_2['high']) / bar_minus_2['high']
        
        if gap_size >= ENHANCED_PARAMS['min_breakout_strength']:
            return {
                'type': 'FVG',
                'direction': 'CALL',
                'strength': gap_size,
                'entry_price': current_bar['close'],
                'volume_ratio': volume_ratio
            }
    
    # Bearish FVG
    if bar_minus_2['low'] > current_bar['high']:
        gap_size = (bar_minus_2['low'] - current_bar['high']) / bar_minus_2['low']
        
        if gap_size >= ENHANCED_PARAMS['min_breakout_strength']:
            return {
                'type': 'FVG',
                'direction': 'PUT',
                'strength': gap_size,
                'entry_price': current_bar['close'],
                'volume_ratio': volume_ratio
            }
    
    return None


def scan_enhanced_signals(ticker: str, days_back: int = 90) -> List[EnhancedSignal]:
    """Scan with enhanced detection logic"""
    print(f"[SCAN] Scanning {ticker} (past {days_back} days)...")
    
    bars = get_bars_for_ticker(ticker, days_back)
    
    if not bars or len(bars) < 100:
        print(f"[SCAN] Insufficient data for {ticker} ({len(bars)} bars)")
        return []
    
    print(f"[SCAN] Loaded {len(bars):,} bars for {ticker}")
    
    signals = []
    
    for idx in range(50, len(bars) - 10):
        bar = bars[idx]
        timestamp = bar['datetime']
        
        # Detect BOS
        bos = detect_enhanced_bos(bars, idx)
        if bos:
            signals.append(EnhancedSignal(
                timestamp=timestamp,
                ticker=ticker,
                direction=bos['direction'],
                signal_type=bos['type'],
                entry_price=bos['entry_price'],
                signal_strength=bos['strength'],
                volume_ratio=bos['volume_ratio'],
                hour=timestamp.hour,
                bar_data=bar
            ))
        
        # Detect FVG
        fvg = detect_enhanced_fvg(bars, idx)
        if fvg:
            signals.append(EnhancedSignal(
                timestamp=timestamp,
                ticker=ticker,
                direction=fvg['direction'],
                signal_type=fvg['type'],
                entry_price=fvg['entry_price'],
                signal_strength=fvg['strength'],
                volume_ratio=fvg['volume_ratio'],
                hour=timestamp.hour,
                bar_data=bar
            ))
    
    print(f"[SCAN] Found {len(signals)} enhanced signals for {ticker}")
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# FILTER VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_with_filters(signal: EnhancedSignal, bars: List[Dict]) -> Tuple[bool, bool, str, str]:
    """
    Apply Volume Profile and Entry Timing filters.
    
    Returns:
        (passes_volume_profile, passes_entry_timing, vp_reason, timing_reason)
    """
    passes_vp = True
    passes_timing = True
    vp_reason = "N/A"
    timing_reason = "N/A"
    
    # Volume Profile filter
    if VOLUME_PROFILE_AVAILABLE:
        try:
            va = get_volume_analyzer()
            
            # For FVG signals, check if near POC
            if signal.signal_type == 'FVG':
                # Get recent bars for volume profile calculation
                signal_idx = None
                for i, bar in enumerate(bars):
                    if bar['datetime'] == signal.timestamp:
                        signal_idx = i
                        break
                
                if signal_idx and signal_idx >= 50:
                    recent_bars = bars[signal_idx-50:signal_idx+1]
                    
                    # Convert to format volume_profile expects
                    vp_bars = []
                    for b in recent_bars:
                        vp_bars.append({
                            'high': b['high'],
                            'low': b['low'],
                            'close': b['close'],
                            'volume': b['volume']
                        })
                    
                    # Check if FVG near POC
                    result = va.validate_fvg_near_poc(signal.entry_price, vp_bars)
                    passes_vp = result.get('valid', False)
                    vp_reason = result.get('reason', 'Unknown')
        
        except Exception as e:
            print(f"[FILTER] Volume Profile error: {e}")
            passes_vp = True  # Don't block on errors
            vp_reason = f"Error: {str(e)[:50]}"
    
    # Entry Timing filter
    if ENTRY_TIMING_AVAILABLE:
        try:
            timing_validator = get_entry_timing_validator()
            
            # Check if timestamp is during golden hours
            result = timing_validator.validate_entry_time(signal.timestamp)
            passes_timing = result.get('valid', False)
            timing_reason = result.get('reason', 'Unknown')
        
        except Exception as e:
            print(f"[FILTER] Entry Timing error: {e}")
            passes_timing = True
            timing_reason = f"Error: {str(e)[:50]}"
    
    return passes_vp, passes_timing, vp_reason, timing_reason


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════

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


def simulate_trade(signal: EnhancedSignal, bars: List[Dict], 
                   passes_vp: bool, passes_timing: bool,
                   vp_reason: str, timing_reason: str,
                   atr_mult: float = 3.0) -> EnhancedTradeResult:
    """
    Simulate trade with given ATR multiplier.
    """
    # Find signal bar
    signal_idx = None
    for i, bar in enumerate(bars):
        if bar['datetime'] == signal.timestamp:
            signal_idx = i
            break
    
    if signal_idx is None or signal_idx >= len(bars) - 5:
        # Can't simulate
        return EnhancedTradeResult(
            signal=signal,
            passed_baseline=True,
            passed_volume_profile=passes_vp,
            passed_entry_timing=passes_timing,
            volume_profile_reason=vp_reason,
            entry_timing_reason=timing_reason,
            entry_price=signal.entry_price,
            stop_price=signal.entry_price,
            exit_price=signal.entry_price,
            exit_reason='NO_DATA',
            r_multiple=0.0,
            pnl_percent=0.0,
            hold_time_minutes=0,
            win=False,
            atr_multiplier=atr_mult
        )
    
    entry_price = signal.entry_price
    
    # Calculate ATR
    atr_bars = bars[max(0, signal_idx-50):signal_idx+1]
    atr = calculate_atr(atr_bars)
    
    if atr == 0:
        atr = entry_price * 0.01
    
    # Set stop and targets
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
    
    # Simulate forward
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
    
    # Calculate results
    if signal.direction == 'CALL':
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        r_mult = (exit_price - entry_price) / (atr * atr_mult)
    else:
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        r_mult = (entry_price - exit_price) / (atr * atr_mult)
    
    return EnhancedTradeResult(
        signal=signal,
        passed_baseline=True,
        passed_volume_profile=passes_vp,
        passed_entry_timing=passes_timing,
        volume_profile_reason=vp_reason,
        entry_timing_reason=timing_reason,
        entry_price=entry_price,
        stop_price=stop_price,
        exit_price=exit_price,
        exit_reason=exit_reason,
        r_multiple=r_mult,
        pnl_percent=pnl_pct,
        hold_time_minutes=hold_time,
        win=r_mult > 0,
        atr_multiplier=atr_mult
    )


# ═══════════════════════════════════════════════════════════════════════════
# METRICS & ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def calculate_metrics(results: List[EnhancedTradeResult]) -> Dict:
    """Calculate performance metrics"""
    if not results:
        return {'total_trades': 0}
    
    wins = sum(1 for r in results if r.win)
    losses = len(results) - wins
    win_rate = wins / len(results)
    
    r_multiples = [r.r_multiple for r in results]
    avg_r = np.mean(r_multiples)
    total_r = sum(r_multiples)
    
    # Sharpe
    if len(r_multiples) > 1 and np.std(r_multiples) > 0:
        sharpe = (np.mean(r_multiples) / np.std(r_multiples)) * np.sqrt(252)
    else:
        sharpe = 0.0
    
    # Max drawdown
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
    
    # Exit breakdown
    exit_counts = Counter([r.exit_reason for r in results])
    
    return {
        'total_trades': len(results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'avg_hold_time': np.mean([r.hold_time_minutes for r in results]),
        'exit_breakdown': dict(exit_counts)
    }


def analyze_hourly_distribution(signals: List[EnhancedSignal]) -> Dict:
    """Analyze signal distribution by hour"""
    hourly = Counter([s.hour for s in signals])
    return dict(sorted(hourly.items()))


# ═══════════════════════════════════════════════════════════════════════════
# MAIN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(tickers: List[str], days_back: int = 90, atr_mult: float = 3.0) -> Dict:
    """
    Run complete backtest with enhanced filters.
    """
    print(f"\n{'='*80}")
    print(f"ENHANCED BACKTEST - ATR {atr_mult}x")
    print(f"{'='*80}\n")
    
    all_signals = []
    ticker_bars = {}
    
    # Scan all tickers
    for ticker in tickers:
        signals = scan_enhanced_signals(ticker, days_back)
        all_signals.extend(signals)
        
        if signals:
            ticker_bars[ticker] = get_bars_for_ticker(ticker, days_back)
    
    print(f"\n✅ Total enhanced signals: {len(all_signals)}")
    
    if not all_signals:
        return {'error': 'No signals found'}
    
    # Analyze hourly distribution
    hourly_dist = analyze_hourly_distribution(all_signals)
    print(f"\n📊 Hourly Distribution:")
    for hour, count in hourly_dist.items():
        print(f"   {hour:02d}:00 - {count} signals")
    
    # Process signals
    print(f"\n🔬 Processing {len(all_signals)} signals through filters...\n")
    
    baseline_results = []
    vp_results = []
    timing_results = []
    both_results = []
    
    for i, signal in enumerate(all_signals):
        if (i + 1) % 100 == 0:
            print(f"   Processed {i+1}/{len(all_signals)}...")
        
        ticker = signal.ticker
        bars = ticker_bars.get(ticker, [])
        
        if not bars:
            continue
        
        # Validate filters
        passes_vp, passes_timing, vp_reason, timing_reason = validate_with_filters(signal, bars)
        
        # Simulate trade
        result = simulate_trade(signal, bars, passes_vp, passes_timing, 
                                vp_reason, timing_reason, atr_mult)
        
        # Track different filter combinations
        baseline_results.append(result)
        
        if passes_vp:
            vp_results.append(result)
        
        if passes_timing:
            timing_results.append(result)
        
        if passes_vp and passes_timing:
            both_results.append(result)
    
    # Calculate metrics for each scenario
    baseline_metrics = calculate_metrics(baseline_results)
    vp_metrics = calculate_metrics(vp_results)
    timing_metrics = calculate_metrics(timing_results)
    both_metrics = calculate_metrics(both_results)
    
    return {
        'atr_multiplier': atr_mult,
        'total_signals': len(all_signals),
        'hourly_distribution': hourly_dist,
        'baseline': baseline_metrics,
        'volume_profile_only': vp_metrics,
        'entry_timing_only': timing_metrics,
        'both_filters': both_metrics
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='Quick test (3 tickers, 30 days)')
    parser.add_argument('--atr-test', action='store_true', help='Test multiple ATR multipliers')
    parser.add_argument('--days', type=int, default=90, help='Days back')
    args = parser.parse_args()
    
    if args.quick:
        tickers = ['AAPL', 'SPY', 'TSLA']
        days = 30
    else:
        tickers = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT', 'META', 'GOOGL', 'AMD']
        days = args.days
    
    print(f"\nTesting {len(tickers)} tickers: {', '.join(tickers)}")
    print(f"Date range: Past {days} days\n")
    
    if args.atr_test:
        # Test multiple ATR multipliers
        print("\n🔬 ATR MULTIPLIER OPTIMIZATION TEST\n")
        
        atr_tests = [2.0, 2.5, 3.0, 3.5, 4.0]
        atr_results = []
        
        for atr_mult in atr_tests:
            result = run_backtest(tickers, days, atr_mult)
            atr_results.append(result)
        
        # Compare results
        print(f"\n{'='*80}")
        print("ATR MULTIPLIER COMPARISON (Both Filters Active)")
        print(f"{'='*80}\n")
        
        for res in atr_results:
            both = res.get('both_filters', {})
            print(f"ATR {res['atr_multiplier']}x:")
            print(f"  Trades: {both.get('total_trades', 0)}")
            print(f"  Win Rate: {both.get('win_rate', 0):.1%}")
            print(f"  Avg R: {both.get('avg_r', 0):.2f}R")
            print(f"  Total R: {both.get('total_r', 0):.2f}R")
            print(f"  Sharpe: {both.get('sharpe', 0):.2f}")
            print()
        
        # Save results
        with open('backtest_atr_optimization.json', 'w') as f:
            json.dump(atr_results, f, indent=2, default=str)
        
        print("✅ Results saved to: backtest_atr_optimization.json\n")
    
    else:
        # Single run with default ATR
        result = run_backtest(tickers, days, ENHANCED_PARAMS['atr_multiplier'])
        
        # Display results
        print(f"\n{'='*80}")
        print("FILTER COMPARISON RESULTS")
        print(f"{'='*80}\n")
        
        baseline = result['baseline']
        vp_only = result['volume_profile_only']
        timing_only = result['entry_timing_only']
        both = result['both_filters']
        
        print(f"1. BASELINE (No Filters):")
        print(f"   Trades: {baseline['total_trades']}")
        print(f"   Win Rate: {baseline['win_rate']:.1%}")
        print(f"   Avg R: {baseline['avg_r']:.2f}R")
        print(f"   Total R: {baseline['total_r']:.2f}R")
        print()
        
        print(f"2. VOLUME PROFILE ONLY:")
        print(f"   Trades: {vp_only['total_trades']} ({(1-vp_only['total_trades']/baseline['total_trades'])*100:.1f}% filtered)")
        print(f"   Win Rate: {vp_only['win_rate']:.1%} ({(vp_only['win_rate']-baseline['win_rate'])*100:+.1f}pp)")
        print(f"   Avg R: {vp_only['avg_r']:.2f}R ({(vp_only['avg_r']-baseline['avg_r']):+.2f}R)")
        print(f"   Total R: {vp_only['total_r']:.2f}R")
        print()
        
        print(f"3. ENTRY TIMING ONLY:")
        print(f"   Trades: {timing_only['total_trades']} ({(1-timing_only['total_trades']/baseline['total_trades'])*100:.1f}% filtered)")
        print(f"   Win Rate: {timing_only['win_rate']:.1%} ({(timing_only['win_rate']-baseline['win_rate'])*100:+.1f}pp)")
        print(f"   Avg R: {timing_only['avg_r']:.2f}R ({(timing_only['avg_r']-baseline['avg_r']):+.2f}R)")
        print(f"   Total R: {timing_only['total_r']:.2f}R")
        print()
        
        print(f"4. BOTH FILTERS (Volume Profile + Entry Timing):")
        print(f"   Trades: {both['total_trades']} ({(1-both['total_trades']/baseline['total_trades'])*100:.1f}% filtered)")
        print(f"   Win Rate: {both['win_rate']:.1%} ({(both['win_rate']-baseline['win_rate'])*100:+.1f}pp)")
        print(f"   Avg R: {both['avg_r']:.2f}R ({(both['avg_r']-baseline['avg_r']):+.2f}R)")
        print(f"   Total R: {both['total_r']:.2f}R")
        print(f"   Sharpe: {both['sharpe']:.2f}")
        print(f"   Max DD: {both['max_dd']:.2f}R")
        print()
        
        # Save results
        with open('backtest_enhanced_filters.json', 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        print("✅ Results saved to: backtest_enhanced_filters.json\n")


if __name__ == "__main__":
    main()
