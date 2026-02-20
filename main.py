"""
War Machine - Main Entry Point
CFW6 Strategy + Options Signal Engine
INTEGRATED: AI Learning, Position Tracking, Win Rate Analysis,
            Daily P&L Digest, Weekly Session Heatmap
"""
import os
import sys
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from discord_helpers import test_webhook
test_webhook()

def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def check_environment():
    """Check and display environment configuration."""
    print("\n" + "="*60)
    print("WAR MACHINE - SYSTEM DIAGNOSTICS")
    print("="*60)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Working Directory: {os.getcwd()}")

    api_key = os.getenv("EODHD_API_KEY", "")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    db_url  = os.getenv("DATABASE_URL", "")

    print(f"\nEnvironment Variables:")
    print(f"  EODHD_API_KEY:       {'Set (' + api_key[:10] + '...)' if api_key else 'MISSING'}")
    print(f"  DISCORD_WEBHOOK_URL: {'Set' if webhook else 'MISSING'}")
    print(f"  DATABASE_URL:        {'Set (' + db_url[:12] + '...)' if db_url and 'postgresql' in db_url else 'SQLite Fallback'}")

    now = _now_et()
    print(f"\nCurrent Time (ET): {now.strftime('%I:%M:%S %p')}")
    print(f"Date: {now.strftime('%A, %B %d, %Y')}")

    from scanner import is_market_hours, is_premarket
    if is_premarket():
        status = "PRE-MARKET"
    elif is_market_hours():
        status = "MARKET OPEN"
    else:
        status = "MARKET CLOSED"
    print(f"Market Status: {status}")
    print("="*60 + "\n")

    if not api_key:
        print("FATAL ERROR: EODHD_API_KEY not set!")
        return False
    if not webhook:
        print("WARNING: DISCORD_WEBHOOK_URL not set. No alerts will be sent.")
    return True


def initialize_database():
    print("[INIT] Initializing database...")
    try:
        from data_manager import data_manager
        stats = data_manager.get_database_stats()
        print(f"Database ready: {stats['total_bars']} bars, {stats['unique_tickers']} tickers, {stats['size']}")
        return data_manager
    except Exception as e:
        print(f"Database initialization error: {e}")
        import traceback
        traceback.print_exc()
        return None


def start_websocket_feed():
    print("[INIT] Starting WebSocket feed...")
    try:
        try:
            from scanner import FALLBACK_WATCHLIST
            ws_tickers = list(FALLBACK_WATCHLIST)
        except (ImportError, AttributeError):
            ws_tickers = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                "AMD",  "NFLX", "ADBE",  "CRM",  "ORCL", "INTC", "CSCO",
                "JPM",  "BAC",  "GS",    "MS",   "WFC",  "UNH",  "JNJ",
                "PFE",  "ABBV", "MRK",   "WMT",  "HD",   "COST", "NKE",
                "MCD",  "SPY"
            ]
        from ws_feed import start_ws_feed
        start_ws_feed(ws_tickers)
        time.sleep(3)
        print(f"[INIT] WebSocket feed started ({len(ws_tickers)} tickers)")
        return True
    except Exception as e:
        print(f"[INIT] WebSocket feed error (non-fatal): {e}")
        import traceback
        traceback.print_exc()
        return False


def load_ai_learning():
    print("[INIT] Loading AI learning engine...")
    try:
        from ai_learning import learning_engine
        params = learning_engine.get_optimal_parameters()
        print(f"AI Learning Engine loaded")
        print(f"  Optimal FVG size: {params['fvg_min_size_pct']:.4f}")
        print(f"  Confirmation weights: {params['confirmation_weights']}")
        total_trades = len(learning_engine.data.get("trades", []))
        if total_trades > 0:
            print(f"  Historical trades: {total_trades}")
        return learning_engine
    except Exception as e:
        print(f"AI Learning Engine error: {e}")
        return None


def load_position_tracker():
    print("[INIT] Loading position manager...")
    try:
        from position_manager import position_manager
        open_positions = position_manager.get_open_positions()
        print(f"Position Manager loaded")
        if open_positions:
            print(f"  {len(open_positions)} open positions from previous session:")
            for pos in open_positions:
                print(f"    {pos['ticker']} {pos['direction'].upper()} | Entry: ${pos['entry_price']:.2f}")
        else:
            print(f"  No open positions")
        return position_manager
    except Exception as e:
        print(f"Position Manager error: {e}")
        return None


def load_win_rate_tracker():
    print("[INIT] Loading win rate data...")
    try:
        from position_manager import position_manager
        daily_stats = position_manager.get_daily_stats()
        print(f"Win Rate data loaded")
        if daily_stats['trades'] > 0:
            print(f"  Today: {daily_stats['win_rate']:.1f}% WR ({daily_stats['trades']} trades)")
        else:
            print(f"  No trades today yet")
        return position_manager
    except Exception as e:
        print(f"Win Rate load error: {e}")
        return None


def send_startup_notification():
    try:
        from discord_helpers import send_simple_message
        from scanner import is_market_hours, is_premarket
        now = _now_et()
        if is_premarket():
            status = "PRE-MARKET MODE"
        elif is_market_hours():
            status = "MARKET HOURS MODE"
        else:
            status = "AFTER HOURS MODE"
        send_simple_message(
            f"War Machine Started | {now.strftime('%I:%M:%S %p ET')} | "
            f"{status} | CFW6 + Options Intelligence"
        )
        print("Startup notification sent to Discord")
    except Exception as e:
        print(f"Discord notification failed: {e}")


def run_eod_digest():
    """
    EOD cleanup: P&L digest + session heatmap (Fridays) + state resets.
    Called at 4:00 PM ET (scheduled) and on KeyboardInterrupt.
    """
    print("[EOD] Running end-of-day sequence...")
    try:
        # 1. Daily P&L digest (every day)
        from pnl_digest import send_pnl_digest
        send_pnl_digest()
    except Exception as e:
        print(f"[EOD] P&L digest error: {e}")

    try:
        # 2. Session heatmap (Fridays only — the function checks internally)
        from session_heatmap import send_heatmap
        send_heatmap()
    except Exception as e:
        print(f"[EOD] Heatmap error: {e}")

    try:
        # 3. State resets
        from earnings_filter import clear_earnings_cache
        from sniper import clear_armed_signals, clear_watching_signals
        clear_earnings_cache()
        clear_armed_signals()
        clear_watching_signals()
        print("[EOD] State resets complete")
    except Exception as e:
        print(f"[EOD] State reset error: {e}")

    print("[EOD] Daily cleanup complete")


def main():
    """Main entry point with full initialization."""

    if not check_environment():
        print("\nStartup aborted due to missing configuration")
        sys.exit(1)

    db          = initialize_database()
    start_websocket_feed()
    ai_engine   = load_ai_learning()
    pos_tracker = load_position_tracker()
    wr_tracker  = load_win_rate_tracker()
    send_startup_notification()

    print("\n" + "="*60)
    print("STRATEGY CONFIGURATION")
    print("="*60)
    print("Strategy:     CFW6 (Opening Range + FVG + Confirmation)")
    print("Grades:       A+, A, A-")
    print("Layers:       VWAP, Prev Day, Institutional Volume, Options Flow")
    print("MTF:          5m > 3m > 2m > 1m (highest timeframe priority)")
    print("Risk:         2% per trade | 1 contract max")
    print("Options:      7-45 DTE | 0.35-0.55 delta | High liquidity")
    print("Intelligence: IVR + UOA + GEX | Earnings Guard | AI Win-Rate Learning")
    print("Reporting:    Daily P&L Digest | Weekly Session Heatmap (Fri)")
    print("Data Feed:    EODHD WebSocket (real-time 1m bars) + REST snapshots")
    print("="*60 + "\n")

    _digest_sent_today = False
    EOD_DIGEST_TIME    = dt_time(16, 0)

    print("Starting CFW6 scanner...\n")
    try:
        from scanner import start_scanner_loop_iter
        try:
            for _ in start_scanner_loop_iter():
                now_et = _now_et()
                if not _digest_sent_today and now_et.time() >= EOD_DIGEST_TIME:
                    run_eod_digest()
                    _digest_sent_today = True
                if now_et.hour == 0 and now_et.minute == 0:
                    _digest_sent_today = False
        except (TypeError, AttributeError):
            from scanner import start_scanner_loop
            start_scanner_loop()

    except ImportError as e:
        print(f"IMPORT ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("SHUTDOWN INITIATED")
        print("="*60)
        run_eod_digest()
        if pos_tracker:
            print("\nPosition Summary:")
            pos_tracker.print_summary()
        if ai_engine:
            print("\nAI Learning Summary:")
            print(ai_engine.generate_performance_report())
        print("\nShutdown complete. Goodbye!\n")
        sys.exit(0)

    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        try:
            from discord_helpers import send_simple_message
            send_simple_message(f"CRITICAL ERROR: {str(e)} - System shutting down.")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
