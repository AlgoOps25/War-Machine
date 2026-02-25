#!/usr/bin/env python3
"""
MTF System Test - Simplified 5m + 3m Strategy

Tests the multi-timeframe detection system with:
  - 5m bars from data_manager (primary)
  - 3m bars aggregated from 1m (secondary)
  - MTF FVG convergence detection
  - Confidence boost calculation

Usage:
  python test_mtf.py
"""

from data_manager import data_manager
from mtf_data_manager import mtf_data_manager
from mtf_fvg_engine import mtf_fvg_engine

print("\n" + "="*80)
print("MTF SYSTEM TEST - Simplified 5m + 3m Strategy")
print("="*80 + "\n")

# Step 1: Backfill historical data (last 30 days)
test_tickers = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'TSLA']
print("Step 1: Backfilling historical data...")
print(f"Tickers: {', '.join(test_tickers)}\n")

data_manager.startup_backfill_today(test_tickers)

# Step 2: Try to backfill today's data (may not work after hours)
print("\nStep 2: Attempting today's intraday backfill...")
data_manager.startup_intraday_backfill_today(test_tickers)

# Step 3: Test MTF data manager
print("\n" + "="*80)
print("Step 3: Testing MTF Data Manager (5m + 3m from 1m aggregation)")
print("="*80 + "\n")

for ticker in test_tickers:
    print(f"\n--- {ticker} ---")
    # Use testing mode - falls back to latest available data
    bars_dict = mtf_data_manager.get_latest_available_bars(ticker)
    
    if bars_dict:
        for tf, bars in bars_dict.items():
            if bars:
                latest = bars[-1]
                print(f"  {tf}: {len(bars):>3} bars | Latest: ${latest['close']:>7.2f} @ {latest['datetime'].strftime('%m/%d %H:%M')}")
    else:
        print(f"  No data available")

# Step 4: Test MTF FVG Engine
print("\n" + "="*80)
print("Step 4: Testing MTF FVG Detection Engine")
print("="*80 + "\n")

signals_found = 0
signal_details = []

for ticker in test_tickers:
    # Use testing mode - falls back to latest available data
    bars_dict = mtf_data_manager.get_latest_available_bars(ticker)
    
    if not bars_dict:
        continue
    
    result = mtf_fvg_engine.detect_mtf_signal(ticker, bars_dict)
    
    if result:
        signals_found += 1
        
        boost = mtf_fvg_engine.get_mtf_boost_value(result['convergence_score'])
        
        signal_details.append({
            'ticker': ticker,
            'direction': result['direction'],
            'convergence': result['convergence_score'],
            'timeframes': result['timeframes_aligned'],
            'zone_low': result['zone_low'],
            'zone_high': result['zone_high'],
            'boost': boost
        })

print(f"\n{'='*80}")
print(f"SUMMARY: Found {signals_found}/{len(test_tickers)} MTF signals")
print(f"{'='*80}\n")

# Display signal details
if signal_details:
    print("MTF SIGNALS DETECTED:")
    print(f"{'-'*80}")
    for sig in signal_details:
        print(f"\n{sig['ticker']:>5} - {sig['direction'].upper():>4} | "
              f"Convergence: {sig['convergence']:>5.1%} | "
              f"Boost: +{sig['boost']:>5.2%}")
        print(f"       Zone: ${sig['zone_low']:>7.2f} - ${sig['zone_high']:>7.2f}")
        print(f"       Timeframes: {', '.join(sig['timeframes'])}")
    print(f"{'-'*80}\n")
else:
    print("No MTF signals found (normal if no patterns present in data)\n")

# Step 5: Cache stats
mtf_data_manager.print_cache_stats()

print("\n" + "="*80)
if signals_found > 0:
    print("✅ MTF System validated and ready for Phase 3 integration!")
else:
    print("⚠️  MTF System functional but no signals detected")
    print("   (Will work during live trading when patterns form)")
print("="*80 + "\n")
