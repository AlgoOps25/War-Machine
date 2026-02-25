#!/usr/bin/env python3
"""
Candle Cache Management CLI
Tools for managing the candle cache system
"""

import sys
import argparse
from datetime import datetime
from candle_cache import candle_cache
from data_manager import data_manager
import config

def cmd_stats():
    """Show cache statistics."""
    print("=" * 60)
    print("CANDLE CACHE STATISTICS")
    print("=" * 60)
    
    stats = candle_cache.get_cache_stats()
    
    print(f"\n📊 Overview:")
    print(f"  Total bars: {stats['total_bars']:,}")
    print(f"  Unique tickers: {stats['unique_tickers']}")
    print(f"  Cache size: {stats['cache_size']}")
    
    if stats['date_range'][0]:
        print(f"\n📅 Date Range:")
        print(f"  First bar: {stats['date_range'][0]}")
        print(f"  Last bar: {stats['date_range'][1]}")
    
    if stats['timeframe_breakdown']:
        print(f"\n⏱️  Timeframe Breakdown:")
        for tf, count in stats['timeframe_breakdown'].items():
            print(f"  {tf}: {count:,} bars")

def cmd_warmup(tickers: str, days: int):
    """Warmup cache with historical data."""
    from data_manager_cache_integration import warmup_cache
    
    ticker_list = tickers.split(',') if tickers else config.SEED_TICKERS
    warmup_cache(data_manager, ticker_list, days)

def cmd_cleanup(days: int):
    """Clean up old cache data."""
    print(f"[CACHE] Cleaning up bars older than {days} days...")
    deleted = candle_cache.cleanup_old_cache(days)
    print(f"[CACHE] ✅ Deleted {deleted:,} bars")

def cmd_check(ticker: str):
    """Check cache status for a ticker."""
    print(f"[CACHE] Checking cache for {ticker}...")
    
    metadata = candle_cache.get_cache_metadata(ticker, '1m')
    
    if not metadata:
        print(f"[CACHE] ❌ No cache found for {ticker}")
        return
    
    print(f"[CACHE] ✅ Cache found:")
    print(f"  First bar: {metadata['first_bar_time']}")
    print(f"  Last bar: {metadata['last_bar_time']}")
    print(f"  Bar count: {metadata['bar_count']:,}")
    print(f"  Last cached: {metadata['last_cache_time']}")
    print(f"  Status: {metadata['cache_status']}")
    
    # Check freshness
    is_fresh = candle_cache.is_cache_fresh(ticker, '1m', max_age_minutes=60)
    print(f"  Fresh (< 1hr): {'✅ Yes' if is_fresh else '❌ No'}")

def cmd_aggregate(ticker: str, source_tf: str, target_tf: str):
    """Test aggregation from one timeframe to another."""
    print(f"[CACHE] Aggregating {ticker}: {source_tf} -> {target_tf}")
    
    agg_bars = candle_cache.aggregate_to_timeframe(ticker, source_tf, target_tf, days=7)
    
    if agg_bars:
        print(f"[CACHE] ✅ Generated {len(agg_bars)} {target_tf} bars")
        print(f"[CACHE] First: {agg_bars[0]['datetime']} - Last: {agg_bars[-1]['datetime']}")
    else:
        print(f"[CACHE] ❌ No aggregated bars generated")

def main():
    parser = argparse.ArgumentParser(description='Candle Cache Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Stats command
    subparsers.add_parser('stats', help='Show cache statistics')
    
    # Warmup command
    warmup_parser = subparsers.add_parser('warmup', help='Warmup cache with historical data')
    warmup_parser.add_argument('--tickers', type=str, help='Comma-separated ticker list')
    warmup_parser.add_argument('--days', type=int, default=60, help='Days of history')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old cache data')
    cleanup_parser.add_argument('--days', type=int, default=60, help='Keep bars newer than N days')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check cache status for ticker')
    check_parser.add_argument('ticker', type=str, help='Ticker symbol')
    
    # Aggregate command
    agg_parser = subparsers.add_parser('aggregate', help='Test timeframe aggregation')
    agg_parser.add_argument('ticker', type=str, help='Ticker symbol')
    agg_parser.add_argument('--from', dest='source_tf', type=str, default='1m', help='Source timeframe')
    agg_parser.add_argument('--to', dest='target_tf', type=str, default='5m', help='Target timeframe')
    
    args = parser.parse_args()
    
    if args.command == 'stats':
        cmd_stats()
    elif args.command == 'warmup':
        cmd_warmup(args.tickers, args.days)
    elif args.command == 'cleanup':
        cmd_cleanup(args.days)
    elif args.command == 'check':
        cmd_check(args.ticker)
    elif args.command == 'aggregate':
        cmd_aggregate(args.ticker, args.source_tf, args.target_tf)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
