"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Pre-Market Scanner, Win Rate Tracker, Position Monitoring, Database Cleanup
"""

import os
import time
from datetime import datetime, time as dtime
import config
from premarket_scanner import build_premarket_watchlist

from data_manager import cleanup_old_bars
from position_manager import position_manager as position_tracker
from position_manager import position_manager as win_rate_tracker

# API key from environment variable
API_KEY = os.getenv("EODHD_API_KEY", "")


def is_premarket():
    """Check if currently in pre-market (4 AM - 9:30 AM EST)."""
    now = datetime.now().time()
    return dtime(4, 0) <= now < dtime(9, 30)


def is_market_hours():
    """Check if market is open (9:30 AM - 4 PM EST)."""
    now = datetime.now()
    
    # Weekend check
    if now.weekday() >= 5:
        return False
    
    current_time = now.time()
    return config.MARKET_OPEN <= current_time <= config.MARKET_CLOSE


def build_watchlist() -> list:
    """Build watchlist during market hours (fallback if pre-market list unavailable)."""
    return fallback_list()


def fallback_list() -> list:
    """High-quality, liquid tickers for CFW6 strategy."""
    fallback = [
        # Mega cap tech
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        
        # Large cap tech
        "AMD", "NFLX", "ADBE", "CRM", "ORCL", "INTC", "CSCO",
        
        # Finance
        "JPM", "BAC", "GS", "MS", "WFC",
        
        # Healthcare
        "UNH", "JNJ", "PFE", "ABBV", "MRK",
        
        # Consumer
        "WMT", "HD", "COST", "NKE", "MCD",
        
        # ETFs (very liquid)
        "SPY", "QQQ", "IWM", "DIA"
    ]
    
    print(f"[SCANNER] Using fallback watchlist: {len(fallback)} tickers")
    return fallback


def monitor_open_positions():
    """Monitor open positions and check for exits."""
    open_positions = position_tracker.get_open_positions()
    
    if not open_positions:
        return
    
    print(f"\n[MONITOR] Checking {len(open_positions)} open positions...")
    
    from scanner_helpers import get_recent_bars_from_memory
    
    current_prices = {}
    for pos in open_positions:
        ticker = pos["ticker"]
        bars = get_recent_bars_from_memory(ticker, limit=1)
        if bars:
            current_prices[ticker] = bars[-1]["close"]
    
    position_tracker.check_exits(current_prices)

def start_scanner_loop():
    """
    Main scanner loop with intelligent scheduling:
    - PRE-MARKET (4 AM - 9:30 AM): Build watchlist, monitor pre-market action
    - MARKET HOURS (9:30 AM - 4 PM): Scan for CFW6 signals, monitor positions
    - AFTER HOURS (4 PM - 4 AM): Rest, generate reports, cleanup database
    """
    from sniper import process_ticker
    from discord_helpers import send_simple_message
    from ai_learning import learning_engine
    
    print(f"\n{'='*60}")
    print("WAR MACHINE - CFW6 SCANNER")
    print(f"{'='*60}")
    print(f"Market Hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
    print(f"Scan Interval: {config.SCAN_INTERVAL}s")
    print(f"{'='*60}\n")
    
    # Startup message to Discord
    try:
        send_simple_message("🚀 **War Machine Online**\nCFW6 Scanner Started - Waiting for market hours")
    except Exception as e:
        print(f"[SCANNER] Discord unavailable: {e}")
    
    premarket_watchlist = []
    premarket_built = False
    cycle_count = 0
    last_report_day = None
    
    while True:
        try:
            current_time_str = time.strftime('%I:%M:%S %p EST')
            current_day = datetime.now().strftime('%Y-%m-%d')
            
            # ═══════════════════════════════════════════════════════
            # PRE-MARKET MODE (4 AM - 9:30 AM)
            # ═══════════════════════════════════════════════════════
            if is_premarket():
                if not premarket_built:
                    print(f"\n{'='*60}")
                    print(f"[PRE-MARKET] {current_time_str} - Building Watchlist")
                    print(f"{'='*60}\n")
                    
                    try:
                        premarket_watchlist = build_premarket_watchlist()
                        premarket_built = True
                        
                        watchlist_msg = f"📋 **Pre-Market Watchlist Ready**\n"
                        watchlist_msg += f"**{len(premarket_watchlist)} tickers** identified for today\n"
                        watchlist_msg += f"```\n{', '.join(premarket_watchlist[:20])}\n```"
                        send_simple_message(watchlist_msg)
                        
                    except Exception as e:
                        print(f"[PRE-MARKET] Error building watchlist: {e}")
                        premarket_watchlist = fallback_list()
                        premarket_built = True
                else:
                    print(f"[PRE-MARKET] {current_time_str} - Watchlist ready, waiting for 9:30 AM...")
                
                time.sleep(300)  # Check every 5 minutes in pre-market
                continue
            
            # ═══════════════════════════════════════════════════════
            # MARKET HOURS MODE (9:30 AM - 4 PM)
            # ═══════════════════════════════════════════════════════
            elif is_market_hours():
                cycle_count += 1
                
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}")
                
                # Use pre-market watchlist if available
                if premarket_watchlist:
                    watchlist = premarket_watchlist
                    print(f"[SCANNER] Using pre-market watchlist: {len(watchlist)} tickers")
                else:
                    watchlist = build_watchlist()
                    print(f"[SCANNER] Built fresh watchlist: {len(watchlist)} tickers")
                
                print(f"[SCANNER] Tickers: {', '.join(watchlist[:10])}...\n")
                
                # Monitor open positions first
                monitor_open_positions()
                
                # Display current stats
                daily_stats = position_tracker.get_daily_stats()
                print(f"\n[TODAY] Trades: {daily_stats['trades']} | "
                      f"W/L: {daily_stats['wins']}/{daily_stats['losses']} | "
                      f"WR: {daily_stats['win_rate']:.1f}% | "
                      f"P&L: ${daily_stats['total_pnl']:+.2f}\n")
                
                # Process each ticker through CFW6
                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        print(f"\n--- [{idx}/{len(watchlist)}] Processing {ticker} ---")
                        process_ticker(ticker)
                    except Exception as e:
                        print(f"[SCANNER] ❌ Error on {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                print(f"\n[SCANNER] ✅ Cycle #{cycle_count} complete")
                print(f"[SCANNER] 💤 Sleeping {config.SCAN_INTERVAL}s...\n")
                time.sleep(config.SCAN_INTERVAL)

            # ═══════════════════════════════════════════════════════
            # AFTER HOURS (4 PM - 4 AM)
            # ═══════════════════════════════════════════════════════
            else:
                # Generate end-of-day report (once per day)
                if last_report_day != current_day:
                    print(f"\n{'='*60}")
                    print(f"[EOD] Market Closed - Generating Reports")
                    print(f"{'='*60}\n")
                    
                    # Close any remaining positions at market close
                    open_positions = position_tracker.get_open_positions()
                    if open_positions:
                        print(f"[EOD] {len(open_positions)} positions still open - marking for review")
                    
                    # Generate daily performance report
                    daily_stats = position_tracker.get_daily_stats()
                    
                    eod_report = f"📊 **End of Day Report - {current_day}**\n\n"
                    eod_report += f"**Trades:** {daily_stats['trades']}\n"
                    eod_report += f"**Win Rate:** {daily_stats['win_rate']:.1f}%\n"
                    eod_report += f"**P&L:** ${daily_stats['total_pnl']:+.2f}\n\n"
                    
                    # Add win rate analysis
                    try:
                        win_rate_report = win_rate_tracker.generate_report()
                        eod_report += f"```{win_rate_report}```"
                    except Exception as e:
                        print(f"[EOD] Win rate report error: {e}")
                    
                    send_simple_message(eod_report)
                    
                    # Run AI learning optimization
                    print("[AI] Running optimization...")
                    try:
                        learning_engine.optimize_confirmation_weights()
                        learning_engine.optimize_fvg_threshold()
                        print(learning_engine.generate_performance_report())
                    except Exception as e:
                        print(f"[AI] Optimization error: {e}")
                    
                    # Clean up old bars (keep last 7 days)
                    print("[CLEANUP] Removing old bars...")
                    try:
                        from incremental_fetch import cleanup_old_bars
                        cleanup_old_bars(days_to_keep=7)
                    except Exception as e:
                        print(f"[CLEANUP] Error: {e}")
                    
                    last_report_day = current_day
                    
                    # Reset for next day
                    premarket_watchlist = []
                    premarket_built = False
                    cycle_count = 0
                
                print(f"[AFTER-HOURS] {current_time_str} - Market closed")
                time.sleep(600)  # Check every 10 minutes after hours
        
        except KeyboardInterrupt:
            print("\n🛑 Scanner stopped by user")
            
            # Print final summary
            print("\n" + "="*60)
            print("SHUTDOWN SUMMARY")
            print("="*60)
            position_tracker.print_summary()
            win_rate_tracker.print_report()
            
            break
        
        except Exception as e:
            print(f"❌ [SCANNER] Critical error: {e}")
            import traceback
            traceback.print_exc()
            
            # Send error alert to Discord
            try:
                send_simple_message(f"⚠️ **Scanner Error**\n```{str(e)}```")
            except:
                pass
            
            time.sleep(30)  # Wait 30s before retry


def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> list:
    """
    Fetch top tickers from EODHD screener based on market cap and volume.
    """
    import requests
    import json
    
    url = "https://eodhd.com/api/screener"
    
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume", ">=", 1000000],
            ["exchange", "=", "US"]
        ]),
        "limit": limit,
        "sort": "volume.desc"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        tickers = []
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                code = item.get("code")
                if code:
                    ticker = code.replace(".US", "")
                    tickers.append(ticker)
        
        print(f"[SCREENER] Fetched {len(tickers)} tickers")
        return tickers[:limit]
        
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []
