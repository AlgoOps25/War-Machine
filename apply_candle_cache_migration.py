#!/usr/bin/env python3
"""
Candle Cache Migration Script
Applies cache schema to existing database
"""

import sys
from candle_cache import candle_cache
from data_manager import data_manager

def main():
    print("=" * 60)
    print("CANDLE CACHE MIGRATION")
    print("=" * 60)
    
    try:
        # Tables are auto-created by candle_cache.__init__()
        print("\n[MIGRATION] ✅ Cache tables created")
        
        # Show stats
        stats = candle_cache.get_cache_stats()
        print(f"\n[MIGRATION] Cache Statistics:")
        print(f"  Total bars: {stats['total_bars']:,}")
        print(f"  Unique tickers: {stats['unique_tickers']}")
        print(f"  Cache size: {stats['cache_size']}")
        
        print("\n[MIGRATION] ✅ Migration complete!")
        print("\n[NEXT STEPS]:")
        print("  1. Deploy to Railway (tables will be created automatically)")
        print("  2. First startup will populate cache from API")
        print("  3. Subsequent startups will use cache (instant!)")
        
        return 0
    
    except Exception as e:
        print(f"\n[MIGRATION] ❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
