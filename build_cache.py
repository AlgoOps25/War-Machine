#!/usr/bin/env python3
"""
Simple data cache builder for backtesting.
Fetches 30 days of historical data for all tickers in WATCHLIST.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from data_manager import data_manager
import config

ET = ZoneInfo("America/New_York")

print("="*60)
print("📦 BUILDING DATA CACHE FOR BACKTESTING")
print("="*60)

# Get tickers from config
tickers = config.WATCHLIST

print(f"\nTickers: {len(tickers)}")
print(f"Period: 30 days")

# Build cache
data_manager.startup_backfill_today(tickers)

# Show stats
stats = data_manager.get_database_stats()
print(f"\n✅ CACHE COMPLETE!")
print(f"Total bars: {stats['total_bars']:,}")
print(f"Tickers: {stats['unique_tickers']}")
print(f"Database size: {stats['size']}")
