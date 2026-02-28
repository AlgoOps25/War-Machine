"""
Integrated Indicator Combination Backtest
Uses your existing infrastructure with indicator filters
"""

import sys
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

print("\n" + "="*70)
print(" INTEGRATED INDICATOR BACKTEST")
print("="*70)

# Import your infrastructure
print("\n[1/7] Loading infrastructure...")
try:
    from signal_generator import SignalGenerator
    from breakout_detector import BreakoutDetector
    from data_manager import data_manager
    from validation import get_validation_config
    print(" Core modules loaded")
except Exception as e:
    print(f" Failed: {e}")
    sys.exit(1)

# Test combinations
COMBINATIONS = [
    {
        'id': 1,
        'name': 'Current Winner (90.9%)',
        'filters': ['price_range', 'bollinger_position'],
        'params': {
            'price_min': 1, 'price_max': 200,
            'bb_period': 10, 'bb_std': 1.5, 'bb_min': 0.2, 'bb_max': 1.0
        }
    },
    {
        'id': 2,
        'name': 'Triple Filter (94.4%)',
        'filters': ['price_range', 'rsi_threshold', 'bollinger_position'],
        'params': {
            'price_min': 1, 'price_max': 200,
            'rsi_min': 35, 'rsi_max': 65, 'rsi_period': 20,
            'bb_period': 10, 'bb_std': 1.5, 'bb_min': 0.2, 'bb_max': 1.0
        }
    },
    {
        'id': 3,
        'name': 'ATR Variant (90.9%)',
        'filters': ['price_range', 'atr_threshold', 'bollinger_position'],
        'params': {
            'price_min': 1, 'price_max': 200,
            'atr_min': 0.5, 'atr_max': 5.0,
            'bb_period': 10, 'bb_std': 1.5, 'bb_min': 0.2, 'bb_max': 1.0
        }
    },
    {
        'id': 4,
        'name': 'Trend + Price',
        'filters': ['price_range', 'trend_alignment'],
        'params': {
            'price_min': 1, 'price_max': 200,
            'ema_fast': 9, 'ema_slow': 21
        }
    },
    {
        'id': 5,
        'name': 'RSI + Bollinger',
        'filters': ['rsi_threshold', 'bollinger_position'],
        'params': {
            'rsi_min': 35, 'rsi_max': 65, 'rsi_period': 20,
            'bb_period': 10, 'bb_std': 1.5, 'bb_min': 0.2, 'bb_max': 1.0
        }
    },
    {
        'id': 6,
        'name': 'Volume + Trend + Price',
        'filters': ['price_range', 'volume_surge', 'trend_alignment'],
        'params': {
            'price_min': 1, 'price_max': 200,
            'vol_multiplier': 1.5,
            'ema_fast': 9, 'ema_slow': 21
        }
    }
]

# Backtest configuration
CONFIG = {
    'start_date': datetime(2025, 12, 1),
    'end_date': datetime(2026, 2, 26),
    'watchlist': [
        'SPY', 'QQQ', 'IWM',
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',
        'AMD', 'NFLX', 'DIS', 'BA', 'JPM', 'COIN', 'PLTR',
        'SOFI', 'RIVN', 'NIO', 'F', 'GM', 'NKE', 'SBUX'
    ]
}

print(f"\n[2/7] Configuration:")
print(f"   Period: {CONFIG['start_date'].date()} to {CONFIG['end_date'].date()}")
print(f"   Days: {(CONFIG['end_date'] - CONFIG['start_date']).days}")
print(f"   Watchlist: {len(CONFIG['watchlist'])} tickers")
print(f"   Combinations: {len(COMBINATIONS)}")

# Indicator calculation functions
def calculate_rsi(prices, period=20):
    """Calculate RSI indicator"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_bollinger_position(prices, period=10, std_dev=1.5):
    """Calculate position within Bollinger Bands (0=lower band, 1=upper band)"""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    band_width = upper - lower
    position = (prices - lower) / band_width
    return position.clip(0, 1)

def calculate_atr(high, low, close, period=14):
    """Calculate Average True Range"""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def check_trend_alignment(close, ema_fast=9, ema_slow=21):
    """Check if price is above both EMAs"""
    ema_f = close.ewm(span=ema_fast, adjust=False).mean()
    ema_s = close.ewm(span=ema_slow, adjust=False).mean()
    return (close > ema_f) & (close > ema_s)

def check_volume_surge(volume, multiplier=1.5):
    """Check if volume is above average"""
    avg_vol = volume.rolling(window=20).mean()
    return volume >= (avg_vol * multiplier)

print(f"\n[3/7] Indicator functions loaded")

# Filter application function
def apply_combo_filters(df, combo):
    """Apply indicator filters for a combination"""
    filtered = df.copy()
    params = combo['params']
    
    for filter_name in combo['filters']:
        if filter_name == 'price_range':
            filtered = filtered[
                (filtered['close'] >= params['price_min']) &
                (filtered['close'] <= params['price_max'])
            ]
        
        elif filter_name == 'rsi_threshold':
            rsi = calculate_rsi(filtered['close'], params['rsi_period'])
            filtered = filtered[
                (rsi >= params['rsi_min']) & 
                (rsi <= params['rsi_max'])
            ]
        
        elif filter_name == 'bollinger_position':
            bb_pos = calculate_bollinger_position(
                filtered['close'],
                params['bb_period'],
                params['bb_std']
            )
            filtered = filtered[
                (bb_pos >= params['bb_min']) &
                (bb_pos <= params['bb_max'])
            ]
        
        elif filter_name == 'atr_threshold':
            atr = calculate_atr(
                filtered['high'],
                filtered['low'],
                filtered['close']
            )
            filtered = filtered[
                (atr >= params['atr_min']) &
                (atr <= params['atr_max'])
            ]
        
        elif filter_name == 'trend_alignment':
            trend = check_trend_alignment(
                filtered['close'],
                params['ema_fast'],
                params['ema_slow']
            )
            filtered = filtered[trend]
        
        elif filter_name == 'volume_surge':
            vol_surge = check_volume_surge(
                filtered['volume'],
                params['vol_multiplier']
            )
            filtered = filtered[vol_surge]
    
    return filtered

print(f"[4/7] Filter application ready")

# Backtest execution
print(f"\n[5/7] Running backtests for each combination...")
print(f"   Estimated time: 30-45 minutes")
print(f"   Start time: {datetime.now().strftime('%I:%M %p')}")

all_results = []

for combo in COMBINATIONS:
    print(f"\n   ")
    print(f"   Testing: {combo['name']}")
    print(f"   Filters: {', '.join(combo['filters'])}")
    print(f"   ")
    
    combo_signals = 0
    combo_wins = 0
    combo_losses = 0
    combo_pnl = 0.0
    
    # Loop through each ticker
    for ticker in CONFIG['watchlist']:
        try:
            # Fetch data (you would use your data_manager here)
            print(f"      Processing {ticker}...", end=" ")
            
            # Placeholder - integrate with your actual data fetching
            # df = data_manager.get_intraday_bars(ticker, CONFIG['start_date'], CONFIG['end_date'])
            
            # For now, simulate
            # In production: apply filters, generate signals, track results
            
            print(f"")
            
        except Exception as e:
            print(f" ({str(e)[:30]})")
            continue
    
    # Store results
    result = {
        'id': combo['id'],
        'name': combo['name'],
        'filters': combo['filters'],
        'total_signals': combo_signals,
        'wins': combo_wins,
        'losses': combo_losses,
        'win_rate': combo_wins / combo_signals if combo_signals > 0 else 0,
        'profit_factor': 0,  # Calculate from actual P&L
        'total_pnl': combo_pnl
    }
    
    all_results.append(result)
    
    print(f"\n   Results: {combo_signals} signals | WR: {result['win_rate']*100:.1f}%")

print(f"\n[6/7] Backtest complete!")
print(f"   End time: {datetime.now().strftime('%I:%M %p')}")

# Save results
results_df = pd.DataFrame(all_results)
results_df.to_csv('indicator_combination_results.csv', index=False)

with open('indicator_combination_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)

print(f"\n[7/7] Results saved:")
print(f"    indicator_combination_results.csv")
print(f"    indicator_combination_results.json")

# Display summary
print("\n" + "="*70)
print(" INDICATOR COMBINATION RESULTS")
print("="*70)

print(f"\n{'Rank':<6} {'Name':<30} {'Signals':<10} {'WR%':<10} {'PF':<10}")
print("-" * 70)

sorted_results = sorted(all_results, key=lambda x: x['win_rate'], reverse=True)
for i, r in enumerate(sorted_results, 1):
    print(f"{i:<6} {r['name']:<30} {r['total_signals']:<10} {r['win_rate']*100:<10.1f} {r['profit_factor']:<10.2f}")

print("\n" + "="*70)
print("  INTEGRATION STATUS: FRAMEWORK READY")
print("="*70)

print(f"\n TO COMPLETE:")
print(f"   This script needs data fetching integration")
print(f"   Connect to your data_manager.get_intraday_bars()")
print(f"   Add your signal generation logic")
print(f"   Add your exit/target calculation")

print(f"\n NEXT STEP:")
print(f"   I can integrate with your existing:")
print(f"    validate_top_config.py (has full backtest logic)")
print(f"    Or build from scratch with data_manager")
print(f"\n   Which would you prefer?")

print("\n" + "="*70)
