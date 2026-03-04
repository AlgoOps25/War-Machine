#!/usr/bin/env python3
"""
Deep Analysis of Losing Trades
Identifies patterns, filters that failed, and improvement opportunities
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

def load_data():
    """Load simulated signals and positions"""
    signals_file = 'backtests/simulated_signals.csv'
    positions_file = 'backtests/simulated_positions.csv'
    
    if not Path(signals_file).exists() or not Path(positions_file).exists():
        print("ERROR: Run simulate_from_candles.py first to generate data")
        return None, None
    
    signals_df = pd.read_csv(signals_file)
    positions_df = pd.read_csv(positions_file)
    
    # Convert timestamps
    signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])
    positions_df['entry_time'] = pd.to_datetime(positions_df['entry_time'])
    positions_df['exit_time'] = pd.to_datetime(positions_df['exit_time'])
    
    # Merge to get full context
    merged = positions_df.merge(
        signals_df,
        left_on=['symbol', 'entry_time'],
        right_on=['symbol', 'timestamp'],
        how='left',
        suffixes=('_pos', '_sig')
    )
    
    return signals_df, positions_df, merged

def analyze_by_symbol(df):
    """Analyze performance by symbol"""
    print("\n" + "="*70)
    print("PERFORMANCE BY SYMBOL")
    print("="*70)
    
    by_symbol = df.groupby('symbol').agg({
        'pnl': ['count', 'sum', 'mean'],
        'pnl_pct': 'mean'
    }).round(2)
    
    # Calculate win rate
    win_rates = df.groupby('symbol').apply(
        lambda x: (x['pnl'] > 0).sum() / len(x) * 100,
        include_groups=False
    ).round(1)
    
    by_symbol['win_rate'] = win_rates
    by_symbol.columns = ['trades', 'total_pnl', 'avg_pnl', 'avg_pnl_pct', 'win_rate']
    
    print(by_symbol.sort_values('win_rate', ascending=False))
    
    # Identify problem symbols
    losers = by_symbol[by_symbol['win_rate'] < 40].sort_values('total_pnl')
    if not losers.empty:
        print("\n⚠️  PROBLEM SYMBOLS (Win Rate < 40%):")
        for symbol, row in losers.iterrows():
            print(f"  {symbol}: {row['win_rate']:.1f}% win rate, ${row['total_pnl']:.2f} total loss")

def analyze_by_time(df):
    """Analyze performance by time of day"""
    print("\n" + "="*70)
    print("PERFORMANCE BY TIME OF DAY")
    print("="*70)
    
    # Extract hour and minute
    df['entry_hour'] = df['entry_time'].dt.hour
    df['entry_minute'] = df['entry_time'].dt.minute
    df['time_bucket'] = df['entry_hour'].astype(str).str.zfill(2) + ':' + \
                        (df['entry_minute'] // 15 * 15).astype(str).str.zfill(2)
    
    by_time = df.groupby('time_bucket').agg({
        'pnl': ['count', 'mean'],
        'pnl_pct': 'mean'
    }).round(2)
    
    win_rates = df.groupby('time_bucket').apply(
        lambda x: (x['pnl'] > 0).sum() / len(x) * 100,
        include_groups=False
    ).round(1)
    
    by_time['win_rate'] = win_rates
    by_time.columns = ['trades', 'avg_pnl', 'avg_pnl_pct', 'win_rate']
    
    print(by_time[by_time['trades'] >= 5])  # Only show buckets with 5+ trades
    
    # Identify worst time windows
    worst_times = by_time[by_time['win_rate'] < 35].sort_values('avg_pnl')
    if not worst_times.empty:
        print("\n⚠️  WORST TIME WINDOWS (Win Rate < 35%):")
        for time_bucket, row in worst_times.iterrows():
            if row['trades'] >= 3:
                print(f"  {time_bucket}: {row['win_rate']:.1f}% win rate, ${row['avg_pnl']:.2f} avg loss")

def analyze_signal_characteristics(merged_df):
    """Analyze which signal characteristics correlate with losses"""
    print("\n" + "="*70)
    print("SIGNAL CHARACTERISTICS ANALYSIS")
    print("="*70)
    
    losers = merged_df[merged_df['pnl'] < 0].copy()
    winners = merged_df[merged_df['pnl'] > 0].copy()
    
    print(f"\nAnalyzing {len(losers)} losers vs {len(winners)} winners\n")
    
    # Signal type distribution
    if 'signal_type' in losers.columns:
        print("Signal Type Distribution:")
        print("  Losers:")
        loser_signals = losers['signal_type'].value_counts()
        for sig_type, count in loser_signals.items():
            pct = count / len(losers) * 100
            print(f"    {sig_type}: {count} ({pct:.1f}%)")
        
        print("  Winners:")
        winner_signals = winners['signal_type'].value_counts()
        for sig_type, count in winner_signals.items():
            pct = count / len(winners) * 100
            print(f"    {sig_type}: {count} ({pct:.1f}%)")
    
    # Trend strength (if available)
    if 'trend_strength' in losers.columns:
        print("\nTrend Strength:")
        print(f"  Losers avg: {losers['trend_strength'].mean():.3f}")
        print(f"  Winners avg: {winners['trend_strength'].mean():.3f}")
    
    # Volume ratio (if available)
    if 'volume_ratio' in losers.columns:
        print("\nVolume Ratio:")
        print(f"  Losers avg: {losers['volume_ratio'].mean():.2f}x")
        print(f"  Winners avg: {winners['volume_ratio'].mean():.2f}x")
    
    # Gap size (if available)
    if 'gap_pct' in losers.columns:
        print("\nGap Size:")
        print(f"  Losers avg: {losers['gap_pct'].mean():.2f}%")
        print(f"  Winners avg: {winners['gap_pct'].mean():.2f}%")

def analyze_dte_patterns(df):
    """Deep dive into DTE performance patterns"""
    print("\n" + "="*70)
    print("DTE PERFORMANCE DEEP DIVE")
    print("="*70)
    
    for dte in sorted(df['dte'].unique()):
        dte_trades = df[df['dte'] == dte]
        losers = dte_trades[dte_trades['pnl'] < 0]
        winners = dte_trades[dte_trades['pnl'] > 0]
        
        print(f"\n{dte} DTE Analysis:")
        print(f"  Total trades: {len(dte_trades)}")
        print(f"  Winners: {len(winners)} ({len(winners)/len(dte_trades)*100:.1f}%)")
        print(f"  Losers: {len(losers)} ({len(losers)/len(dte_trades)*100:.1f}%)")
        print(f"  Avg winner: ${winners['pnl'].mean():.2f}" if len(winners) > 0 else "  No winners")
        print(f"  Avg loser: ${losers['pnl'].mean():.2f}" if len(losers) > 0 else "  No losers")
        print(f"  Hold time: {dte_trades['hold_duration_min'].mean():.1f} min")
        
        # Show worst performers
        if len(losers) > 0:
            worst = losers.nsmallest(3, 'pnl')[['symbol', 'entry_time', 'pnl', 'pnl_pct']]
            print(f"\n  Worst {dte} DTE trades:")
            for idx, row in worst.iterrows():
                print(f"    {row['symbol']} at {row['entry_time']}: ${row['pnl']:.2f} ({row['pnl_pct']:.1f}%)")

def analyze_consecutive_patterns(df):
    """Identify if losers cluster together (bad market conditions)"""
    print("\n" + "="*70)
    print("CONSECUTIVE LOSS PATTERNS")
    print("="*70)
    
    df = df.sort_values('entry_time')
    df['is_loser'] = df['pnl'] < 0
    
    # Find streaks
    df['streak_id'] = (df['is_loser'] != df['is_loser'].shift()).cumsum()
    streaks = df[df['is_loser']].groupby('streak_id').size()
    
    long_streaks = streaks[streaks >= 3]
    
    if len(long_streaks) > 0:
        print(f"\nFound {len(long_streaks)} losing streaks of 3+ trades:\n")
        
        for streak_id in long_streaks.index:
            streak_trades = df[df['streak_id'] == streak_id]
            print(f"Streak starting {streak_trades.iloc[0]['entry_time']}: {len(streak_trades)} consecutive losses")
            print(f"  Symbols: {', '.join(streak_trades['symbol'].unique())}")
            print(f"  Total loss: ${streak_trades['pnl'].sum():.2f}")
            print()
    else:
        print("\n✓ No significant losing streaks detected (losses are distributed)")

def identify_filter_failures(merged_df):
    """Check if volume/gap filters are actually working"""
    print("\n" + "="*70)
    print("FILTER EFFECTIVENESS ANALYSIS")
    print("="*70)
    
    losers = merged_df[merged_df['pnl'] < 0]
    winners = merged_df[merged_df['pnl'] > 0]
    
    # Check if filters exist
    has_volume = 'volume_ratio' in merged_df.columns
    has_gap = 'gap_pct' in merged_df.columns
    
    if not has_volume and not has_gap:
        print("\n⚠️  WARNING: No filter data found in signals!")
        print("Signal detection may not be using volume/gap filters.")
        print("\nExpected columns: 'volume_ratio', 'gap_pct'")
        print(f"Available columns: {', '.join(merged_df.columns)}")
        return
    
    if has_volume:
        print("\nVolume Filter Analysis:")
        
        # Check if high volume actually helps
        losers_high_vol = losers[losers['volume_ratio'] >= 2.0]
        losers_low_vol = losers[losers['volume_ratio'] < 2.0]
        winners_high_vol = winners[winners['volume_ratio'] >= 2.0]
        winners_low_vol = winners[winners['volume_ratio'] < 2.0]
        
        if len(losers_high_vol) > 0:
            print(f"  High volume (≥2x) losers: {len(losers_high_vol)}")
            print(f"  Low volume (<2x) losers: {len(losers_low_vol)}")
            print(f"  High volume win rate: {len(winners_high_vol)/(len(winners_high_vol)+len(losers_high_vol))*100:.1f}%")
            print(f"  Low volume win rate: {len(winners_low_vol)/(len(winners_low_vol)+len(losers_low_vol))*100:.1f}%")
            
            if len(winners_low_vol)/(len(winners_low_vol)+len(losers_low_vol)) > len(winners_high_vol)/(len(winners_high_vol)+len(losers_high_vol)):
                print("\n  ⚠️  Volume filter NOT helping - low volume has BETTER win rate!")
        else:
            print("  Insufficient data for volume analysis")
    
    if has_gap:
        print("\nGap Filter Analysis:")
        
        # Check gap size distribution
        print(f"  Losers avg gap: {losers['gap_pct'].mean():.2f}%")
        print(f"  Winners avg gap: {winners['gap_pct'].mean():.2f}%")
        
        # Large gaps vs small gaps
        losers_big_gap = losers[losers['gap_pct'].abs() >= 1.0]
        losers_small_gap = losers[losers['gap_pct'].abs() < 1.0]
        winners_big_gap = winners[winners['gap_pct'].abs() >= 1.0]
        winners_small_gap = winners[winners['gap_pct'].abs() < 1.0]
        
        if len(losers_big_gap) > 0:
            print(f"  Big gap (≥1%) losers: {len(losers_big_gap)}")
            print(f"  Small gap (<1%) losers: {len(losers_small_gap)}")
            print(f"  Big gap win rate: {len(winners_big_gap)/(len(winners_big_gap)+len(losers_big_gap))*100:.1f}%")
            print(f"  Small gap win rate: {len(winners_small_gap)/(len(winners_small_gap)+len(losers_small_gap))*100:.1f}%")

def generate_recommendations(merged_df):
    """Generate specific, actionable recommendations"""
    print("\n" + "="*70)
    print("ACTIONABLE RECOMMENDATIONS")
    print("="*70 + "\n")
    
    recommendations = []
    
    # Analyze by symbol
    by_symbol = merged_df.groupby('symbol').agg({
        'pnl': lambda x: (x > 0).sum() / len(x) * 100
    })
    bad_symbols = by_symbol[by_symbol['pnl'] < 35]
    
    if not bad_symbols.empty:
        recommendations.append(
            f"❌ REMOVE these symbols (win rate < 35%): {', '.join(bad_symbols.index.tolist())}"
        )
    
    # Analyze by time
    merged_df['entry_hour'] = merged_df['entry_time'].dt.hour
    by_hour = merged_df.groupby('entry_hour').agg({
        'pnl': lambda x: (x > 0).sum() / len(x) * 100
    })
    bad_hours = by_hour[by_hour['pnl'] < 35]
    
    if not bad_hours.empty:
        recommendations.append(
            f"🕐 STOP trading after {bad_hours.index.min()}:00 (win rate drops below 35%)"
        )
    
    # Check DTE effectiveness
    by_dte = merged_df.groupby('dte').agg({
        'pnl': lambda x: (x > 0).sum() / len(x) * 100
    })
    best_dte = by_dte.idxmax()['pnl']
    recommendations.append(
        f"✅ FOCUS on {best_dte} DTE (highest win rate: {by_dte.loc[best_dte, 'pnl']:.1f}%)"
    )
    
    # Check if we should tighten stops
    losers = merged_df[merged_df['pnl'] < 0]
    avg_loser = losers['pnl_pct'].mean()
    if avg_loser < -8:
        recommendations.append(
            f"🛑 TIGHTEN stop loss (avg loser is {avg_loser:.1f}%, consider -5% max)"
        )
    
    # Check if we should take profits earlier
    winners = merged_df[merged_df['pnl'] > 0]
    avg_winner = winners['pnl_pct'].mean()
    if avg_winner < 5:
        recommendations.append(
            f"💰 Consider EARLIER profit targets (avg winner only {avg_winner:.1f}%)"
        )
    
    # Print recommendations
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}")
    
    print()

def main():
    print("\n" + "="*70)
    print("WAR MACHINE - DEEP LOSER ANALYSIS")
    print("="*70)
    
    signals_df, positions_df, merged_df = load_data()
    
    if merged_df is None:
        return
    
    print(f"\nAnalyzing {len(positions_df)} total trades")
    print(f"Winners: {len(positions_df[positions_df['pnl'] > 0])}")
    print(f"Losers: {len(positions_df[positions_df['pnl'] < 0])}")
    
    # Run all analyses
    analyze_by_symbol(positions_df)
    analyze_by_time(positions_df)
    analyze_dte_patterns(positions_df)
    analyze_consecutive_patterns(positions_df)
    
    if merged_df is not None and len(merged_df) > 0:
        analyze_signal_characteristics(merged_df)
        identify_filter_failures(merged_df)
    
    generate_recommendations(merged_df if merged_df is not None else positions_df)
    
    print("="*70)
    print("ANALYSIS COMPLETE")
    print("="*70 + "\n")

if __name__ == '__main__':
    main()
