#!/usr/bin/env python3
"""
Extract Candles from PostgreSQL candle_cache for DTE Backtesting
Connects to your War Machine database and exports cached candle data.
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.data.db_connection import get_conn, dict_cursor
    HAS_DB = True
except ImportError:
    HAS_DB = False
    print("Warning: Could not import database connection. Make sure app.data module is available.")

def extract_candles(
    db_path: str,
    symbols: List[str],
    timeframe: str = '1m',
    days: int = 90,
    output_file: str = 'backtests/cached_candles.json'
) -> Dict:
    """
    Extract candles from database and save to JSON
    
    Args:
        db_path: Database connection string
        symbols: List of symbols to extract
        timeframe: Candle timeframe ('1m', '5m', etc.)
        days: Number of days to extract
        output_file: Output JSON file path
    
    Returns:
        Dict with extraction statistics
    """
    if not HAS_DB:
        print("ERROR: Database connection module not available")
        return {}
    
    cutoff = datetime.now() - timedelta(days=days)
    
    print(f"\nExtracting {timeframe} candles for {len(symbols)} symbols")
    print(f"Date range: Last {days} days (since {cutoff.strftime('%Y-%m-%d')})")
    print(f"Output: {output_file}\n")
    
    all_data = {}
    stats = {
        'symbols_extracted': 0,
        'total_candles': 0,
        'date_range': {},
        'symbols': {}
    }
    
    try:
        conn = get_conn(db_path)
        cursor = dict_cursor(conn)
        
        for symbol in symbols:
            cursor.execute("""
                SELECT datetime, open, high, low, close, volume
                FROM candle_cache
                WHERE ticker = %s 
                  AND timeframe = %s
                  AND datetime >= %s
                ORDER BY datetime ASC
            """, (symbol, timeframe, cutoff))
            
            rows = cursor.fetchall()
            
            if not rows:
                print(f"  {symbol}: No data found")
                continue
            
            # Convert to list of dicts
            candles = []
            for row in rows:
                dt = row['datetime']
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                
                candles.append({
                    'timestamp': dt.isoformat(),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume'])
                })
            
            all_data[symbol] = candles
            
            # Update stats
            stats['symbols_extracted'] += 1
            stats['total_candles'] += len(candles)
            stats['symbols'][symbol] = {
                'candle_count': len(candles),
                'first_bar': candles[0]['timestamp'],
                'last_bar': candles[-1]['timestamp']
            }
            
            print(f"  {symbol}: {len(candles)} candles "
                  f"({candles[0]['timestamp'][:10]} to {candles[-1]['timestamp'][:10]})")
        
        conn.close()
        
        # Save to JSON
        if all_data:
            output_path = Path(output_file)
            output_path.parent.mkdir(exist_ok=True, parents=True)
            
            with open(output_path, 'w') as f:
                json.dump(all_data, f, indent=2)
            
            print(f"\n✅ Saved {stats['total_candles']} candles "
                  f"for {stats['symbols_extracted']} symbols to {output_file}")
        else:
            print("\n⚠️ No candle data found")
        
        return stats
        
    except Exception as e:
        print(f"\nERROR extracting candles: {e}")
        import traceback
        traceback.print_exc()
        return stats

def get_available_symbols(db_path: str, timeframe: str = '1m') -> List[str]:
    """
    Get list of symbols available in cache
    """
    if not HAS_DB:
        return []
    
    try:
        conn = get_conn(db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute("""
            SELECT DISTINCT ticker
            FROM candle_cache
            WHERE timeframe = %s
            ORDER BY ticker
        """, (timeframe,))
        
        symbols = [row['ticker'] for row in cursor.fetchall()]
        conn.close()
        
        return symbols
    except Exception as e:
        print(f"Error querying symbols: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(
        description='Extract candles from War Machine PostgreSQL cache for backtesting'
    )
    parser.add_argument('--db', default='market_memory.db',
                       help='Database path (default: market_memory.db)')
    parser.add_argument('--symbols', nargs='+',
                       help='Symbols to extract (space-separated). If omitted, extracts all available.')
    parser.add_argument('--timeframe', default='1m',
                       help='Timeframe to extract (default: 1m)')
    parser.add_argument('--days', type=int, default=90,
                       help='Number of days to extract (default: 90)')
    parser.add_argument('--output', default='backtests/cached_candles.json',
                       help='Output JSON file (default: backtests/cached_candles.json)')
    parser.add_argument('--list-symbols', action='store_true',
                       help='List available symbols and exit')
    
    args = parser.parse_args()
    
    # List symbols mode
    if args.list_symbols:
        print(f"\nQuerying available symbols with {args.timeframe} data...\n")
        symbols = get_available_symbols(args.db, args.timeframe)
        if symbols:
            print(f"Found {len(symbols)} symbols with {args.timeframe} candles:\n")
            for i, symbol in enumerate(symbols, 1):
                print(f"  {i:2d}. {symbol}")
        else:
            print("No symbols found in cache")
        return
    
    # Extract mode
    if args.symbols:
        symbols = args.symbols
    else:
        # Auto-detect symbols
        print("No symbols specified, detecting available symbols...")
        symbols = get_available_symbols(args.db, args.timeframe)
        if not symbols:
            print("\nERROR: No symbols found in cache. Use --list-symbols to check.")
            return
        print(f"Found {len(symbols)} symbols: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}\n")
    
    # Extract
    stats = extract_candles(
        db_path=args.db,
        symbols=symbols,
        timeframe=args.timeframe,
        days=args.days,
        output_file=args.output
    )
    
    if stats.get('total_candles', 0) > 0:
        print("\n" + "="*60)
        print("EXTRACTION COMPLETE")
        print("="*60)
        print(f"\nRun DTE backtest with:\n")
        print(f"  python backtests/simulate_from_candles.py {args.output}")
        print("\n" + "="*60)

if __name__ == '__main__':
    main()
