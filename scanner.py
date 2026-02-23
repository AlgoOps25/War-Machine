"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
"""
import os
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import config
from premarket_scanner import build_premarket_watchlist
from data_manager import data_manager, cleanup_old_bars
from position_manager import position_manager
from ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)
from earnings_filter import bulk_prefetch_earnings, clear_earnings_cache

from signal_generator import check_and_alert, monitor_signals, print_active_signals, signal_generator

# NEW: Adaptive watchlist funnel (replaces static fallback)
from watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel
)

API_KEY = os.getenv("EODHD_API_KEY", "")

# Minimal fallback (only used if funnel completely fails)
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]


def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def is_premarket():
    now = _now_et().time()
    return dtime(4, 0) <= now < dtime(9, 30)


def is_market_hours():
    now = _now_et()
    if now.weekday() >= 5:
        return False
    return config.MARKET_OPEN <= now.time() <= config.MARKET_CLOSE


def build_watchlist(force_refresh: bool = False) -> list:
    """
    Build adaptive watchlist using funnel system.
    Automatically adjusts size and quality based on time of day.
    """
    try:
        watchlist = get_current_watchlist(force_refresh=force_refresh)
        if watchlist:
            return watchlist
    except Exception as e:
        print(f"[WATCHLIST] Funnel error: {e}")
    
    # Emergency fallback
    print(f"[WATCHLIST] Using emergency fallback: {len(EMERGENCY_FALLBACK)} tickers")
    return list(EMERGENCY_FALLBACK)


def monitor_open_positions():
    from data_manager import data_manager
    from ws_feed import get_current_bar, is_connected
    open_positions = position_manager.get_open_positions()
    if not open_positions:
        return
    print(f"\n[MONITOR] Checking {len(open_positions)} open positions...")
    current_prices = {}
    for pos in open_positions:
        ticker = pos["ticker"]
        # Prefer live WS bar (sub-10s latency) over DB-stored bar
        bar = get_current_bar(ticker) if is_connected() else None
        if bar is None:
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            bar  = bars[-1] if bars else None
        if bar:
            current_prices[ticker] = bar["close"]
    position_manager.check_exits(current_prices)

def start_scanner_loop():
    from sniper import process_ticker, clear_armed_signals, clear_watching_signals
    from discord_helpers import send_simple_message
    from ai_learning import learning_engine
    from cfw6_confirmation import clear_prev_day_cache

    print(f"\n{'='*60}")
    print("WAR MACHINE - CFW6 SCANNER")
    print(f"{'='*60}")
    print(f"Market Hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
    print(f"Adaptive intervals + watchlist funnel active")
    print(f"{'='*60}\n")

    try:
        send_simple_message("🎯 WAR MACHINE ONLINE - CFW6 Scanner + Adaptive Funnel Started")
    except Exception as e:
        print(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist = []
    premarket_built     = False
    cycle_count         = 0
    last_report_day     = None
    loss_streak_alerted = False

    # ── STARTUP SEQUENCE ────────────────────────────────────────────────────────────────────────────
    # Start with emergency fallback for initial WS subscription
    startup_watchlist = list(EMERGENCY_FALLBACK)
    try:
        start_ws_feed(startup_watchlist)
        print(f"[WS] WebSocket feed started for {len(startup_watchlist)} tickers")
    except Exception as e:
        print(f"[WS] ERROR starting WebSocket feed: {e}")

    # Historical backfill
    data_manager.startup_backfill_today(startup_watchlist)
    data_manager.startup_intraday_backfill_today(startup_watchlist)
    set_backfill_complete()
    bulk_prefetch_earnings(startup_watchlist)
    # ────────────────────────────────────────────────

    while True:
        try:
            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            if is_premarket():
                if not premarket_built:
                    print(f"\n[PRE-MARKET] {current_time_str} - Building Watchlist\n")
                    try:
                        # Use funnel system for pre-market watchlist
                        watchlist_data = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata = watchlist_data['metadata']
                        volume_signals = watchlist_data['volume_signals']
                        
                        premarket_built = True
                        subscribe_tickers(premarket_watchlist)
                        
                        print(f"[WS] Subscribed premarket watchlist "
                              f"({len(premarket_watchlist)} tickers) to WS feed")
                        
                        # Enhanced Discord message with funnel metadata
                        stage_emoji = {
                            'wide': '📡',
                            'narrow': '🎯',
                            'final': '🔥',
                            'live': '⚡'
                        }
                        emoji = stage_emoji.get(metadata['stage'], '📊')
                        
                        msg = (
                            f"{emoji} **{metadata['stage_description']}**\n"
                            f"✅ Watchlist: {len(premarket_watchlist)} tickers\n"
                            f"{', '.join(premarket_watchlist[:20])}{'...' if len(premarket_watchlist) > 20 else ''}"
                        )
                        
                        if volume_signals:
                            msg += f"\n\n⚠️ {len(volume_signals)} volume signals active"
                        
                        send_simple_message(msg)
                        
                    except Exception as e:
                        print(f"[PRE-MARKET] Funnel error: {e}")
                        import traceback
                        traceback.print_exc()
                        premarket_watchlist = list(EMERGENCY_FALLBACK)
                        premarket_built     = True
                else:
                    # Refresh watchlist periodically during pre-market
                    funnel = get_funnel()
                    if funnel.should_update():
                        print(f"[PRE-MARKET] {current_time_str} - Refreshing Watchlist\n")
                        try:
                            watchlist_data = get_watchlist_with_metadata(force_refresh=True)
                            premarket_watchlist = watchlist_data['watchlist']
                            subscribe_tickers(premarket_watchlist)
                            
                            # Check for stage transition
                            metadata = watchlist_data['metadata']
                            print(f"[FUNNEL] Stage: {metadata['stage'].upper()} - {metadata['stage_description']}")
                            print(f"[FUNNEL] Top 3: {', '.join(metadata['top_3_tickers'])}\n")
                            
                        except Exception as e:
                            print(f"[PRE-MARKET] Refresh error: {e}")
                    else:
                        print(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")
                    
                    time.sleep(60)  # Check every minute during pre-market
                continue

            elif is_market_hours():
                if not should_scan_now():
                    print(f"[SCANNER] {current_time_str} - Opening Range forming, waiting...")
                    time.sleep(15)
                    continue

                if position_manager.has_loss_streak(max_consecutive_losses=3):
                    if not loss_streak_alerted:
                        msg = (
                            "🛑 **CIRCUIT BREAKER** — 3 consecutive losses today. "
                            "New scans halted for the rest of the session. "
                            "Open positions still monitored."
                        )
                        try:
                            send_simple_message(msg)
                        except Exception:
                            pass
                        loss_streak_alerted = True
                        print("[RISK] Daily loss streak reached — halting new scans.")
                    monitor_open_positions()
                    time.sleep(60)
                    continue

                cycle_count += 1
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}")

                # Build watchlist with fallbacks
                try:
                    watchlist = get_current_watchlist(force_refresh=False)
                    if not watchlist:
                        watchlist = premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK)
                except Exception as e:
                    print(f"[WATCHLIST] Error: {e}")
                    watchlist = premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK)
                
                optimal_size = calculate_optimal_watchlist_size()
                watchlist = watchlist[:optimal_size]
                
                print(f"[SCANNER] {len(watchlist)} tickers | {', '.join(watchlist[:10])}...\n")

                # Scan for breakout signals
                print(f"[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...")
                check_and_alert(watchlist)

                # Monitor active signals
                monitor_signals()

                # Show active signals summary
                if signal_generator.active_signals:
                    print_active_signals()

                # Monitor open positions
                monitor_open_positions()

                # Daily stats
                daily_stats = position_manager.get_daily_stats()
                print(
                    f"[TODAY] Trades: {daily_stats['trades']} "
                    f"W/L: {daily_stats['wins']}/{daily_stats['losses']} "
                    f"WR: {daily_stats['win_rate']:.1f}% "
                    f"P&L: ${daily_stats['total_pnl']:+.2f}\n"
                )

                # Process tickers with CFW6
                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        print(f"\n--- [{idx}/{len(watchlist)}] {ticker} ---")
                        process_ticker(ticker)
                    except Exception as e:
                        print(f"[SCANNER] Error on {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

                print(f"\n[SCANNER] Cycle #{cycle_count} complete")
                scan_interval = get_adaptive_scan_interval()
                print(f"[SCANNER] Sleeping {scan_interval}s...\n")
                time.sleep(scan_interval)
                

def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> list:
    """Legacy screener function - kept for backwards compatibility."""
    import requests
    import json
    url    = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume",               ">=", 1000000],
            ["exchange",             "=",  "US"]
        ]),
        "limit": limit,
        "sort":  "volume.desc"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data    = response.json()
        tickers = []
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                code = item.get("code")
                if code:
                    tickers.append(code.replace(".US", ""))
        print(f"[SCREENER] Fetched {len(tickers)} tickers")
        return tickers[:limit]
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []


# ── Entry point ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_scanner_loop()
