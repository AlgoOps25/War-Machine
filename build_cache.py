#!/usr/bin/env python3
"""
Simple data cache builder for backtesting.
Fetches 30 days of historical data for all tickers in scanner's emergency fallback list.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from data_manager import data_manager
import config

ET = ZoneInfo("America/New_York")

# Use scanner's emergency fallback list
# These are the core tickers War Machine always monitors
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
    "GOOGL", "AMZN", "NFLX", "DIS", "INTC", "BABA", "BA", "JPM",
    "V", "MA", "PYPL", "SQ", "COIN", "PLTR", "SOFI", "RBLX",
    "GME", "AMC", "SNAP", "UBER", "LYFT", "SHOP", "ZM", "ROKU",
    "DKNG", "PENN", "ABNB", "DASH", "HOOD", "RIVN", "LCID", "F",
    "GM", "NIO", "XPEV", "LI", "PLUG", "FCEL", "BLNK", "CHPT",
    "ENPH", "SEDG", "RUN", "SPWR", "CSIQ", "JKS", "NOVA", "SOL",
    "TAN", "ICLN", "PBW", "QCLN", "SMOG", "ACES", "FAN", "GRID"
]

print("="*60)
print("📦 BUILDING DATA CACHE FOR BACKTESTING")
print("="*60)

print(f"\nTickers: {len(TICKERS)}")
print(f"Period: 30 days")
print(f"Source: Scanner emergency fallback list + extended watchlist")

# Build cache
print("\nFetching historical data from EODHD...\n")
data_manager.startup_backfill_today(TICKERS)

# Show stats
stats = data_manager.get_database_stats()
print(f"\n✅ CACHE COMPLETE!")
print(f"Total bars: {stats['total_bars']:,}")
print(f"Tickers: {stats['unique_tickers']}")
print(f"Database size: {stats['size']}")
print(f"\nYou can now run: python comprehensive_backtest_fixed.py")
