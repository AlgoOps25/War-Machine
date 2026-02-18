"""
Scanner Module - Builds watchlist and runs scanner loop
"""

import os
import requests
from scanner_helpers import get_screener_tickers
import config
import time

# API key from environment variable
API_KEY = os.getenv("EODHD_API_KEY", "")


def build_watchlist() -> list:
    """
    Build watchlist from EODHD screener based on market cap and volume.
    Returns list of ticker symbols.
    """
    try:
        tickers = get_screener_tickers(
            min_market_cap=config.MARKET_CAP_MIN,
            limit=config.TOP_SCAN_COUNT
        )
        
        if tickers:
            print(f"[SCANNER] Built watchlist with {len(tickers)} tickers")
            return tickers
        else:
            print("[SCANNER] No tickers from screener, using fallback")
            return fallback_list()
            
    except Exception as e:
        print(f"[SCANNER] Error building watchlist: {e}")
        return fallback_list()


def fallback_list() -> list:
    """
    Fallback watchlist if screener fails.
    Returns list of high-volume, liquid tickers.
    """
    fallback = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "NVDA", "META", "NFLX", "AMD", "COST",
        "SPY", "QQQ", "IWM", "DIA"
    ]
    print(f"[SCANNER] Using fallback list: {len(fallback)} tickers")
    return fallback


def start_scanner_loop():
    """
    Main scanner loop - builds watchlist and processes tickers continuously.
    Called by main.py to start the scanning engine.
    """
    from sniper import process_ticker
    
    print(f"[SCANNER] Starting scanner loop with {config.SCAN_INTERVAL}s interval")
    print(f"[SCANNER] Scanning top {config.TOP_SCAN_COUNT} tickers")
    
    cycle_count = 0
    
    while True:
        try:
            cycle_count += 1
            print(f"\n{'='*60}")
            print(f"[SCANNER] CYCLE #{cycle_count} - {time.strftime('%I:%M:%S %p')}")
            print(f"{'='*60}\n")
            
            # Build fresh watchlist
            watchlist = build_watchlist()
            
            if not watchlist:
                print("[SCANNER] Empty watchlist, using fallback")
                watchlist = fallback_list()
            
            print(f"[SCANNER] Processing {len(watchlist)} tickers\n")
            
            # Process each ticker through the sniper
            for idx, ticker in enumerate(watchlist, 1):
                try:
                    print(f"\n--- [{idx}/{len(watchlist)}] Processing {ticker} ---")
                    process_ticker(ticker)
                except Exception as e:
                    print(f"[SCANNER] Error processing {ticker}: {e}")
                    continue
            
            print(f"\n[SCANNER] Cycle #{cycle_count} complete. Sleeping {config.SCAN_INTERVAL}s")
            time.sleep(config.SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n[SCANNER] Scanner stopped by user")
            break
        except Exception as e:
            print(f"[SCANNER] Scanner loop error: {e}")
            import traceback
            traceback.print_exc()
            print(f"[SCANNER] Waiting 30s before retry...")
            time.sleep(30)
