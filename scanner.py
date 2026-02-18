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

def is_premarket():
    """Check if currently in pre-market (4 AM - 9:30 AM EST)."""
    from datetime import datetime, time
    now = datetime.now().time()
    return time(4, 0) <= now < time(9, 30)

def is_market_hours():
    """Check if market is open (9:30 AM - 4 PM EST)."""
    from datetime import datetime, time
    import config
    now = datetime.now()
    
    # Weekend check
    if now.weekday() >= 5:
        return False
    
    current_time = now.time()
    return config.MARKET_OPEN <= current_time <= config.MARKET_CLOSE

def start_scanner_loop():
    """Intelligent scanner with pre-market and market hours logic."""
    from sniper import process_ticker
    from discord_helpers import send_simple_message
    from premarket_scanner import build_premarket_watchlist
    
    send_simple_message("🚀 War Machine Online - Waiting for market hours")
    
    premarket_watchlist = []
    cycle_count = 0
    
    while True:
        try:
            current_time_str = time.strftime('%I:%M:%S %p EST')
            
            # PRE-MARKET MODE (4 AM - 9:30 AM)
            if is_premarket():
                if not premarket_watchlist:
                    print(f"[PRE-MARKET] {current_time_str} - Building watchlist...")
                    premarket_watchlist = build_premarket_watchlist()
                    
                    # Send to Discord
                    watchlist_msg = f"📋 **Pre-Market Watchlist ({len(premarket_watchlist)} tickers)**\n"
                    watchlist_msg += f"```{', '.join(premarket_watchlist)}```"
                    send_simple_message(watchlist_msg)
                else:
                    print(f"[PRE-MARKET] {current_time_str} - Watchlist ready, waiting for 9:30 AM...")
                
                time.sleep(300)  # Check every 5 minutes in pre-market
                continue
            
            # MARKET HOURS MODE (9:30 AM - 4 PM)
            elif is_market_hours():
                cycle_count += 1
                
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}\n")
                
                # Use pre-market watchlist if available, otherwise build fresh
                if premarket_watchlist:
                    watchlist = premarket_watchlist
                    print(f"[SCANNER] Using pre-market watchlist: {len(watchlist)} tickers")
                else:
                    watchlist = build_watchlist()
                    print(f"[SCANNER] Built fresh watchlist: {len(watchlist)} tickers")
                
                # Process tickers
                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        print(f"\n--- [{idx}/{len(watchlist)}] {ticker} ---")
                        process_ticker(ticker)
                    except Exception as e:
                        print(f"[SCANNER] Error on {ticker}: {e}")
                
                print(f"\n[SCANNER] Cycle complete, sleeping {config.SCAN_INTERVAL}s\n")
                time.sleep(config.SCAN_INTERVAL)
            
            # AFTER HOURS (4 PM - 4 AM)
            else:
                print(f"[AFTER-HOURS] {current_time_str} - Market closed")
                premarket_watchlist = []  # Reset for next day
                time.sleep(600)  # Check every 10 minutes after hours
        
        except KeyboardInterrupt:
            print("\n🛑 Scanner stopped")
            break
        except Exception as e:
            print(f"❌ Scanner error: {e}")
            time.sleep(30)

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
