#!/usr/bin/env python3
"""
Signal Failure Analysis - Find the Root Cause of Losses
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

print("\n" + "="*80)
print("SIGNAL FAILURE ANALYSIS - Diagnose Loss Patterns")
print("="*80)

# Load data
df = pd.read_csv('signal_outcomes.csv')

print(f"\n📊 Dataset: {len(df):,} signals")
print(f"  Win Rate: {(df['outcome'] == 'REVERSAL').mean()*100:.1f}%")
print(f"  Loss Rate: {(df['outcome'] == 'STOP_OUT').mean()*100:.1f}%")

# Separate winners and losers
winners = df[df['outcome'] == 'REVERSAL']
losers = df[df['outcome'] == 'STOP_OUT']

print("\n" + "="*80)
print("1. STOP LOSS ANALYSIS - Are Stops Too Tight?")
print("="*80)

print(f"\n📏 Risk Statistics:")
print(f"  Winners avg risk: ${winners['risk'].mean():.4f} ({winners['risk'].mean()/winners['entry'].mean()*100:.2f}%)")
print(f"  Losers avg risk:  ${losers['risk'].mean():.4f} ({losers['risk'].mean()/losers['entry'].mean()*100:.2f}%)")

print(f"\n📐 Risk/ATR Ratio:")
print(f"  Winners: {(winners['risk'] / winners['atr']).mean():.2f}x ATR")
print(f"  Losers:  {(losers['risk'] / losers['atr']).mean():.2f}x ATR")

print(f"\n💡 Analysis:")
if (losers['risk'] / losers['atr']).mean() < 1.5:
    print("  🚨 PROBLEM: Stop losses are TOO TIGHT!")
    print("     Losers are using <1.5x ATR stops - getting stopped by noise")
    print("     RECOMMENDATION: Use minimum 2.0x ATR for stops")
else:
    print("  ✅ Stop distances look reasonable")

print("\n" + "="*80)
print("2. TARGET ANALYSIS - Are Targets Too Aggressive?")
print("="*80)

print(f"\n🎯 Peak R Achievement:")
print(f"  Winners peak_r: {winners['peak_r'].mean():.2f}R")
print(f"  Losers peak_r:  {losers['peak_r'].mean():.2f}R")

# Check if losers had potential but reversed
losers_with_potential = losers[losers['peak_r'] > 0.5]
print(f"\n💔 Losers that HAD POTENTIAL:")
print(f"  {len(losers_with_potential)} signals ({len(losers_with_potential)/len(losers)*100:.1f}%) reached >0.5R")
print(f"  Avg peak: {losers_with_potential['peak_r'].mean():.2f}R")
print(f"  Avg bars to peak: {losers_with_potential['bars_to_peak'].mean():.1f}")

if len(losers_with_potential) > len(losers) * 0.3:
    print(f"\n  🚨 PROBLEM: {len(losers_with_potential)/len(losers)*100:.0f}% of losses HAD POTENTIAL!")
    print("     Signals are reversing after showing promise")
    print("     RECOMMENDATION: Consider taking partial profits at 0.5R")

print("\n" + "="*80)
print("3. TIMING ANALYSIS - When Do Signals Fail?")
print("="*80)

df['timestamp'] = pd.to_datetime(df['timestamp'])
df['hour'] = df['timestamp'].dt.hour

print(f"\n⏰ Win Rate by Time of Day:")
for time_bucket in sorted(df['time_bucket'].unique()):
    subset = df[df['time_bucket'] == time_bucket]
    wr = (subset['outcome'] == 'REVERSAL').mean() * 100
    print(f"  {time_bucket:25} {wr:5.1f}% WR ({len(subset):>4} signals)")

worst_time = df.groupby('time_bucket').apply(
    lambda x: (x['outcome'] == 'REVERSAL').mean()
).idxmin()
print(f"\n  🚨 WORST TIME: {worst_time}")

print("\n" + "="*80)
print("4. TICKER ANALYSIS - Which Tickers Are Problematic?")
print("="*80)

ticker_stats = df.groupby('ticker').agg({
    'outcome': lambda x: (x == 'REVERSAL').mean(),
    'ticker': 'count',
    'peak_r': 'mean'
}).rename(columns={'outcome': 'win_rate', 'ticker': 'count'})

ticker_stats = ticker_stats.sort_values('win_rate')

print(f"\n📉 WORST Performing Tickers:")
for ticker, row in ticker_stats.head(5).iterrows():
    print(f"  {ticker:6} {row['win_rate']*100:5.1f}% WR ({row['count']:>4} signals) avg peak: {row['peak_r']:.2f}R")

print(f"\n📈 BEST Performing Tickers:")
for ticker, row in ticker_stats.tail(5).iterrows():
    print(f"  {ticker:6} {row['win_rate']*100:5.1f}% WR ({row['count']:>4} signals) avg peak: {row['peak_r']:.2f}R")

print("\n" + "="*80)
print("5. VOLUME ANALYSIS - Is Volume Filter Working?")
print("="*80)

print(f"\n📊 Volume Ratio Impact:")
for threshold in [2, 3, 5, 10]:
    high_vol = df[df['volume_ratio'] >= threshold]
    if len(high_vol) > 0:
        wr = (high_vol['outcome'] == 'REVERSAL').mean() * 100
        print(f"  >={threshold:>2}x volume: {wr:5.1f}% WR ({len(high_vol):>4} signals)")

print("\n💡 Analysis:")
if (df[df['volume_ratio'] >= 5]['outcome'] == 'REVERSAL').mean() < df['outcome'].mean():
    print("  🚨 PROBLEM: High volume signals are WORSE!")
    print("     Volume spikes may indicate exhaustion moves")
else:
    print("  ✅ Volume filter is helping")

print("\n" + "="*80)
print("6. CONFIDENCE ANALYSIS - Is Your Grading System Accurate?")
print("="*80)

print(f"\n🎯 Win Rate by Confidence Level:")
for conf in sorted(df['confidence'].unique(), reverse=True):
    subset = df[df['confidence'] == conf]
    if len(subset) > 10:
        wr = (subset['outcome'] == 'REVERSAL').mean() * 100
        print(f"  Confidence {conf:>3}: {wr:5.1f}% WR ({len(subset):>4} signals)")

print("\n💡 Analysis:")
conf_corr = df['confidence'].corr(df['outcome'].map({'REVERSAL': 1, 'STOP_OUT': 0}))
print(f"  Correlation: {conf_corr:.4f}")

if conf_corr < 0.05:
    print("  🚨 PROBLEM: Confidence scores are NOT predictive!")
    print("     Your grading system needs recalibration")

print("\n" + "="*80)
print("7. SIGNAL TYPE ANALYSIS - BUY vs SELL Performance")
print("="*80)

print(f"\n📈 Performance by Direction:")
for sig_type in df['signal_type'].unique():
    subset = df[df['signal_type'] == sig_type]
    wr = (subset['outcome'] == 'REVERSAL').mean() * 100
    print(f"  {sig_type:4} signals: {wr:5.1f}% WR ({len(subset):>4} signals)")

print("\n" + "="*80)
print("SUMMARY & RECOMMENDATIONS")
print("="*80)

# Calculate key metrics
avg_risk_pct = (df['risk'] / df['entry'] * 100).mean()
avg_atr_ratio = (df['risk'] / df['atr']).mean()
losers_with_pot_pct = len(losers[losers['peak_r'] > 0.5]) / len(losers) * 100

recommendations = []

# Check stop loss tightness
if avg_atr_ratio < 1.8:
    recommendations.append("🚨 INCREASE STOP DISTANCES to 2.0-2.5x ATR (currently too tight)")

# Check if signals reverse after showing promise
if losers_with_pot_pct > 30:
    recommendations.append(f"🚨 TAKE PARTIAL PROFITS at 0.5-1.0R ({losers_with_pot_pct:.0f}% of losses had potential)")

# Check time of day
worst_time_wr = df[df['time_bucket'] == worst_time].apply(
    lambda x: (x['outcome'] == 'REVERSAL').mean() if x.name == 'outcome' else None, axis=0
).iloc[0] * 100
if worst_time_wr < 45:
    recommendations.append(f"🚨 AVOID {worst_time} (only {worst_time_wr:.0f}% win rate)")

# Check confidence calibration
if conf_corr < 0.05:
    recommendations.append("🚨 RECALIBRATE confidence scoring (not predictive)")

# Check volume filter
high_vol_wr = (df[df['volume_ratio'] >= 5]['outcome'] == 'REVERSAL').mean()
if high_vol_wr < 0.50:
    recommendations.append("🚨 AVOID extreme volume spikes (>5x may signal exhaustion)")

print(f"\n🎯 TOP PRIORITY FIXES:\n")
for i, rec in enumerate(recommendations[:5], 1):
    print(f"  {i}. {rec}")

if not recommendations:
    print("  ✅ Core parameters look reasonable")
    print("  📊 Focus on: More data, better entry timing, market regime filters")

print("\n" + "="*80 + "\n")

# Save detailed analysis
print("💾 Saving detailed CSV files...")
losers_with_potential.to_csv('losers_with_potential.csv', index=False)
ticker_stats.to_csv('ticker_performance.csv')
print("  ✅ losers_with_potential.csv")
print("  ✅ ticker_performance.csv")
print("\n")
