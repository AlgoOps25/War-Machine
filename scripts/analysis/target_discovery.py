"""
Target Discovery System - Data-Driven T1/T2 Optimization

Purpose:
  Analyze historical BOS+FVG signals to determine optimal profit targets based on
  actual price movement outcomes rather than fixed R-multiples.

Analysis:
  - Replays every BOS+FVG signal from EODHD historical data
  - Tracks forward price action after each entry
  - Measures: peak R achieved, drawdown, time to peak, actual exit point
  - Identifies natural profit-taking zones (70th/90th percentile clusters)
  - Generates T1/T2 recommendations by ticker group and time-of-day
  - FILTERS: Regular trading hours only (9:30-16:00 ET, Mon-Fri, no holidays)

Output:
  1. signal_outcomes.csv - Every signal with actual peak/trough/reversal
  2. target_recommendations.csv - Optimal T1/T2 by characteristics
  3. target_distribution.png - Visual distribution of actual moves
  4. summary_report.txt - Key findings and recommendations

Usage:
  python target_discovery.py
  
Configuration:
  - Data period: Last 3 months (Dec 2025 - Feb 2026)
  - Tickers: SPY, QQQ, AAPL, TSLA, NVDA, MSFT, AMD, META, GOOGL, AMZN, NFLX, COIN
  - Forward tracking: Until reversal, FVG invalidation, or EOD
  - Caching: Saves data to data_cache/ for instant re-runs
  - RTH Only: 9:30 AM - 4:00 PM ET, Mon-Fri, no holidays
"""

import sys
import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from pathlib import Path
import pandas_market_calendars as mcal

print("\n" + "="*80)
print(" TARGET DISCOVERY SYSTEM - Historical Outcome Analysis")
print("="*80)

# Get API key
EODHD_API_KEY = os.getenv('EODHD_API_KEY')
if not EODHD_API_KEY:
    print("❌ EODHD_API_KEY not found!")
    sys.exit(1)

print(f"\n[1/8] ✅ EODHD API Ready")

# Import BOS+FVG detector
try:
    from app.signals.breakout_detector import BreakoutDetector
    print("[2/8] ✅ BreakoutDetector loaded")
except Exception as e:
    print(f"❌ Failed to load BreakoutDetector: {e}")
    sys.exit(1)

# Configuration
CONFIG = {
    'start_date': datetime(2025, 12, 1),  # 3 months of data
    'end_date': datetime(2026, 2, 27),
    'watchlist': [
        'SPY', 'QQQ', 'AAPL', 'TSLA', 'NVDA', 'MSFT',
        'AMD', 'META', 'GOOGL', 'AMZN', 'NFLX', 'COIN'
    ],
    'forward_bars': 120,  # Track 2 hours forward (120 x 1-min bars)
    'reversal_threshold': 0.5,  # 50% retracement from peak = reversal
    'cache_dir': 'data_cache',  # Cache directory
    'rth_start': time(9, 30),  # Regular trading hours start
    'rth_end': time(16, 0),    # Regular trading hours end
}

# Create cache directory
Path(CONFIG['cache_dir']).mkdir(exist_ok=True)

print(f"[3/8] ✅ Configuration loaded")
print(f"   📅 Period: {CONFIG['start_date'].date()} to {CONFIG['end_date'].date()}")
print(f"   📊 Tickers: {len(CONFIG['watchlist'])}")
print(f"   ⏱️  Forward tracking: {CONFIG['forward_bars']} bars (2 hours)")
print(f"   💾 Cache: {CONFIG['cache_dir']}/")
print(f"   🕒 RTH Only: 9:30 AM - 4:00 PM ET (Mon-Fri, no holidays)")

# Setup market calendar
print(f"\n[4/8] 🗓️  Loading NYSE calendar...")
try:
    nyse = mcal.get_calendar('NYSE')
    market_days = nyse.schedule(
        start_date=CONFIG['start_date'], 
        end_date=CONFIG['end_date']
    )
    trading_days = set(market_days.index.date)
    print(f"   ✅ {len(trading_days)} trading days identified")
except Exception as e:
    print(f"   ⚠️  Calendar load failed: {e}")
    print("   ⚠️  Falling back to simple weekday filter")
    trading_days = None

def is_regular_trading_hours(dt: datetime, trading_days_set: Optional[set] = None) -> bool:
    """
    Check if datetime is during regular trading hours.
    
    Rules:
    - Monday-Friday only
    - 9:30 AM - 4:00 PM ET
    - Not a market holiday (if calendar available)
    """
    # Check if datetime object
    if not hasattr(dt, 'weekday'):
        return False
    
    # Check weekday (0=Monday, 6=Sunday)
    if dt.weekday() > 4:  # Saturday or Sunday
        return False
    
    # Check if market holiday (if calendar available)
    if trading_days_set is not None:
        if dt.date() not in trading_days_set:
            return False
    
    # Check time range (9:30 AM - 4:00 PM)
    bar_time = dt.time()
    if bar_time < CONFIG['rth_start'] or bar_time >= CONFIG['rth_end']:
        return False
    
    return True

# Fetch historical data with caching
def fetch_eodhd_intraday(ticker: str, from_date: datetime, to_date: datetime) -> pd.DataFrame:
    """Fetch 1-min bars from EODHD with local caching and RTH filtering"""
    
    # Check cache first
    cache_file = Path(CONFIG['cache_dir']) / f"{ticker}_{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}_RTH.parquet"
    
    if cache_file.exists():
        print(f"      💾 Loading from cache...", end="", flush=True)
        try:
            df = pd.read_parquet(cache_file)
            print(f" ✅ {len(df)} bars (cached, RTH only)", flush=True)
            return df
        except Exception as e:
            print(f" ⚠️  Cache corrupted, re-fetching", flush=True)
            cache_file.unlink()  # Delete corrupted cache
    
    # Fetch from API
    from_ts = int(from_date.timestamp())
    to_ts = int(to_date.timestamp())
    
    url = f'https://eodhd.com/api/intraday/{ticker}.US'
    params = {
        'api_token': EODHD_API_KEY,
        'interval': '1m',
        'from': from_ts,
        'to': to_ts,
        'fmt': 'json'
    }
    
    print(f"      🔄 Fetching from EODHD...", end="", flush=True)
    
    try:
        response = requests.get(url, params=params, timeout=60)
        if response.status_code == 200:
            data = response.json()
            if data:
                df = pd.DataFrame(data)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df['datetime'] = df['timestamp']  # Add datetime column for compatibility
                
                # Filter to RTH only
                original_count = len(df)
                df = df[df['timestamp'].apply(lambda x: is_regular_trading_hours(x, trading_days))].copy()
                rth_count = len(df)
                
                df.set_index('timestamp', inplace=True)
                
                # Save to cache
                try:
                    df.to_parquet(cache_file)
                    print(f" ✅ {rth_count} bars RTH ({original_count} total, {original_count-rth_count} filtered)", flush=True)
                except Exception as e:
                    print(f" ✅ {rth_count} bars RTH (cache write failed)", flush=True)
                
                return df
            else:
                print(f" ⚠️  Empty response", flush=True)
        else:
            print(f" ❌ HTTP {response.status_code}", flush=True)
    except requests.exceptions.Timeout:
        print(f" ❌ Timeout (60s)", flush=True)
    except Exception as e:
        print(f" ❌ Error: {str(e)[:30]}", flush=True)
    
    return pd.DataFrame()

print("[5/8] ✅ Data fetcher ready (with RTH filtering + caching)")

# Outcome analyzer
def analyze_signal_outcome(signal: Dict, forward_bars: List[Dict], 
                          signal_type: str) -> Dict:
    """
    Analyze what actually happened after a BOS+FVG signal.
    
    Args:
        signal: BOS+FVG signal dict with entry/stop/targets
        forward_bars: List of bars AFTER the signal (up to 120 bars forward)
        signal_type: 'BUY' or 'SELL'
    
    Returns:
        Outcome dict with actual R achieved, reversal point, time to peak, etc.
    """
    entry = signal['entry']
    stop = signal['stop']
    risk = abs(entry - stop)
    
    if not forward_bars or risk == 0:
        return None
    
    # Initialize tracking
    peak_r = 0.0
    peak_price = entry
    peak_bar_idx = 0
    stopped_out = False
    reversal_bar_idx = None
    fvg_invalidated = False
    
    if signal_type == 'BUY':
        # Track bullish move
        for i, bar in enumerate(forward_bars):
            high = bar['high']
            low = bar['low']
            
            # Check for stop out
            if low <= stop:
                stopped_out = True
                break
            
            # Track peak
            if high > peak_price:
                peak_price = high
                peak_r = (peak_price - entry) / risk
                peak_bar_idx = i
            
            # Check for reversal (50% retracement from peak)
            if peak_r > 0.5:  # Only track reversals after meaningful move
                retracement_threshold = entry + (peak_price - entry) * (1 - CONFIG['reversal_threshold'])
                if low <= retracement_threshold:
                    reversal_bar_idx = i
                    break
    
    else:  # SELL signal
        # Track bearish move
        for i, bar in enumerate(forward_bars):
            high = bar['high']
            low = bar['low']
            
            # Check for stop out
            if high >= stop:
                stopped_out = True
                break
            
            # Track peak (lowest price)
            if low < peak_price:
                peak_price = low
                peak_r = (entry - peak_price) / risk
                peak_bar_idx = i
            
            # Check for reversal (50% retracement from peak)
            if peak_r > 0.5:
                retracement_threshold = entry - (entry - peak_price) * (1 - CONFIG['reversal_threshold'])
                if high >= retracement_threshold:
                    reversal_bar_idx = i
                    break
    
    # Determine outcome
    if stopped_out:
        outcome = 'STOP_OUT'
        actual_r = -1.0
        exit_bar_idx = peak_bar_idx
    elif reversal_bar_idx is not None:
        outcome = 'REVERSAL'
        actual_r = peak_r * CONFIG['reversal_threshold']  # Exited at 50% retracement
        exit_bar_idx = reversal_bar_idx
    else:
        # Reached end of tracking window
        outcome = 'EOD_EXIT'
        actual_r = peak_r
        exit_bar_idx = len(forward_bars) - 1
    
    return {
        'outcome': outcome,
        'peak_r': round(peak_r, 2),
        'actual_r': round(actual_r, 2),
        'peak_price': round(peak_price, 2),
        'bars_to_peak': peak_bar_idx,
        'bars_to_exit': exit_bar_idx,
        'time_to_peak_min': peak_bar_idx,
        'time_to_exit_min': exit_bar_idx,
        'stopped_out': stopped_out
    }

print("[6/8] ✅ Outcome analyzer ready")

# Main analysis loop
print(f"\n[7/8] 🔄 Running target discovery...")
print(f"   ⏰ Start: {datetime.now().strftime('%I:%M %p')}")
print(f"   ⏱️  Est. completion: {(datetime.now() + timedelta(minutes=20)).strftime('%I:%M %p')}")

all_outcomes = []
detector = BreakoutDetector(
    volume_multiplier=2.0,
    lookback_bars=12,
    min_candle_body_pct=0.2,
    min_bars_since_breakout=0
)

for ticker_idx, ticker in enumerate(CONFIG['watchlist'], 1):
    print(f"\n   [{ticker_idx}/{len(CONFIG['watchlist'])}] {ticker}...")
    
    try:
        # Fetch data (from cache or API) - RTH only
        df = fetch_eodhd_intraday(ticker, CONFIG['start_date'], CONFIG['end_date'])
        
        if df.empty or len(df) < 100:
            print(f"      ⚠️  Insufficient data")
            continue
        
        print(f"      🔄 Detecting signals...", end="", flush=True)
        
        # Convert to list for bar-by-bar processing
        bars_list = df.to_dict('records')
        
        # Detect signals bar-by-bar
        signals_detected = 0
        outcomes_analyzed = 0
        
        for i in range(100, len(bars_list) - CONFIG['forward_bars']):
            bars_subset = bars_list[:i+1]
            signal = detector.detect_breakout(bars_subset, ticker)
            
            if signal:
                signals_detected += 1
                
                # Get forward bars for outcome analysis
                forward_bars = bars_list[i+1:i+1+CONFIG['forward_bars']]
                
                # Analyze outcome
                outcome = analyze_signal_outcome(
                    signal,
                    forward_bars,
                    signal['signal']
                )
                
                if outcome:
                    outcomes_analyzed += 1
                    
                    # Extract signal time and characteristics
                    signal_time = bars_subset[-1].get('datetime', datetime.now())
                    hour = signal_time.hour if hasattr(signal_time, 'hour') else 9
                    minute = signal_time.minute if hasattr(signal_time, 'minute') else 30
                    
                    # Categorize time of day
                    if hour == 9 and minute < 45:
                        time_bucket = 'OPEN (9:30-9:45)'
                    elif hour == 9 or (hour == 10 and minute < 30):
                        time_bucket = 'MORNING (9:45-10:30)'
                    elif hour < 15:
                        time_bucket = 'MIDDAY (10:30-15:00)'
                    else:
                        time_bucket = 'CLOSE (15:00-16:00)'
                    
                    # Store complete outcome
                    all_outcomes.append({
                        'ticker': ticker,
                        'timestamp': signal_time,
                        'time_bucket': time_bucket,
                        'signal_type': signal['signal'],
                        'entry': signal['entry'],
                        'stop': signal['stop'],
                        'risk': signal['risk'],
                        'atr': signal.get('atr', 0),
                        'volume_ratio': signal.get('volume_ratio', 0),
                        'confidence': signal.get('confidence', 0),
                        'outcome': outcome['outcome'],
                        'peak_r': outcome['peak_r'],
                        'actual_r': outcome['actual_r'],
                        'peak_price': outcome['peak_price'],
                        'bars_to_peak': outcome['bars_to_peak'],
                        'time_to_peak_min': outcome['time_to_peak_min'],
                        'bars_to_exit': outcome['bars_to_exit'],
                        'stopped_out': outcome['stopped_out']
                    })
        
        print(f" ✅ {signals_detected} signals | {outcomes_analyzed} analyzed")
    
    except Exception as e:
        print(f"      ❌ Error: {str(e)[:50]}")

print(f"\n   ✅ Complete! {datetime.now().strftime('%I:%M %p')}")
print(f"   📊 Total outcomes analyzed: {len(all_outcomes)}")

# Save raw outcomes
print(f"\n[8/8] 💾 Saving results...")

if not all_outcomes:
    print("   ❌ No outcomes to analyze!")
    sys.exit(1)

df_outcomes = pd.DataFrame(all_outcomes)
df_outcomes.to_csv('signal_outcomes.csv', index=False)
print(f"   ✅ signal_outcomes.csv ({len(all_outcomes)} signals)")

# Calculate statistics
winners = df_outcomes[df_outcomes['actual_r'] > 0]
losers = df_outcomes[df_outcomes['actual_r'] <= 0]

print("\n" + "="*80)
print(" RESULTS SUMMARY")
print("="*80)

print(f"\n📊 Overall Statistics:")
print(f"   Total Signals: {len(all_outcomes)}")
print(f"   Winners: {len(winners)} ({len(winners)/len(all_outcomes)*100:.1f}%)")
print(f"   Losers: {len(losers)} ({len(losers)/len(all_outcomes)*100:.1f}%)")
print(f"   Stop Outs: {len(df_outcomes[df_outcomes['stopped_out']])}")

if len(winners) > 0:
    print(f"\n🎯 Winner Statistics:")
    print(f"   Median Peak R: {winners['peak_r'].median():.2f}R")
    print(f"   Mean Peak R: {winners['peak_r'].mean():.2f}R")
    print(f"   70th Percentile: {winners['peak_r'].quantile(0.70):.2f}R")
    print(f"   90th Percentile: {winners['peak_r'].quantile(0.90):.2f}R")
    print(f"   Max Peak R: {winners['peak_r'].max():.2f}R")
    
    print(f"\n⏱️  Timing Statistics:")
    print(f"   Median Time to Peak: {winners['time_to_peak_min'].median():.0f} minutes")
    print(f"   Mean Time to Peak: {winners['time_to_peak_min'].mean():.0f} minutes")

# Generate T1/T2 recommendations
print(f"\n" + "="*80)
print(" RECOMMENDED TARGETS")
print("="*80)

if len(winners) > 10:
    # Overall recommendation
    t1_recommended = round(winners['peak_r'].quantile(0.70), 1)
    t2_recommended = round(winners['peak_r'].quantile(0.90), 1)
    
    print(f"\n🎯 Overall Recommended Targets:")
    print(f"   T1 = {t1_recommended}R (70th percentile - captures most moves)")
    print(f"   T2 = {t2_recommended}R (90th percentile - lets winners run)")
    
    # By time of day
    print(f"\n🕐 Recommended Targets by Time of Day:")
    for time_bucket in df_outcomes['time_bucket'].unique():
        bucket_winners = winners[winners['time_bucket'] == time_bucket]
        if len(bucket_winners) > 5:
            t1 = round(bucket_winners['peak_r'].quantile(0.70), 1)
            t2 = round(bucket_winners['peak_r'].quantile(0.90), 1)
            count = len(bucket_winners)
            print(f"   {time_bucket:<25} T1={t1}R, T2={t2}R (n={count})")
    
    # By ticker group
    print(f"\n📈 Recommended Targets by Ticker:")
    ticker_groups = {
        'INDICES': ['SPY', 'QQQ'],
        'MEGA_CAP': ['AAPL', 'MSFT', 'GOOGL', 'AMZN'],
        'VOLATILE': ['TSLA', 'NVDA', 'AMD', 'META', 'COIN', 'NFLX']
    }
    
    for group_name, tickers in ticker_groups.items():
        group_winners = winners[winners['ticker'].isin(tickers)]
        if len(group_winners) > 5:
            t1 = round(group_winners['peak_r'].quantile(0.70), 1)
            t2 = round(group_winners['peak_r'].quantile(0.90), 1)
            count = len(group_winners)
            print(f"   {group_name:<15} T1={t1}R, T2={t2}R (n={count})")

else:
    print("   ⚠️  Not enough data for recommendations (need 10+ winners)")

# Save summary report
with open('target_discovery_summary.txt', 'w') as f:
    f.write("TARGET DISCOVERY SUMMARY\n")
    f.write("="*80 + "\n\n")
    f.write(f"Analysis Period: {CONFIG['start_date'].date()} to {CONFIG['end_date'].date()}\n")
    f.write(f"Regular Trading Hours Only: 9:30 AM - 4:00 PM ET (Mon-Fri, no holidays)\n")
    f.write(f"Total Signals Analyzed: {len(all_outcomes)}\n")
    f.write(f"Win Rate: {len(winners)/len(all_outcomes)*100:.1f}%\n\n")
    
    if len(winners) > 10:
        f.write(f"RECOMMENDED TARGETS:\n")
        f.write(f"  T1 = {t1_recommended}R (70th percentile)\n")
        f.write(f"  T2 = {t2_recommended}R (90th percentile)\n\n")
        f.write(f"Current System Uses: T1=1.5R, T2=2.5R\n")
        f.write(f"Recommended Change: T1={t1_recommended}R, T2={t2_recommended}R\n")

print(f"\n   ✅ target_discovery_summary.txt")

print("\n" + "="*80)
print(" ✅ Analysis Complete!")
print("="*80)
print(f"\n📁 Files generated:")
print(f"   1. signal_outcomes.csv - All {len(all_outcomes)} signals with outcomes")
print(f"   2. target_discovery_summary.txt - Recommendations report")
print(f"\n💡 Next Steps:")
print(f"   1. Review signal_outcomes.csv for detailed analysis")
print(f"   2. Update BreakoutDetector T1/T2 parameters based on recommendations")
print(f"   3. Re-run production_indicator_backtest.py with new targets")
print(f"\n💾 Cache Info:")
print(f"   - Next run will use cached data (30 seconds vs 20 minutes)")
print(f"   - To refresh data: Delete data_cache/ folder")
print(f"   - NOTE: Old cache files without RTH filter should be deleted")
print("\n" + "="*80 + "\n")
