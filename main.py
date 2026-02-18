"""
War Machine - Main Entry Point
CFW6 Strategy + Options Signal Engine
INTEGRATED: AI Learning, Position Tracking, Win Rate Analysis
"""
import os
import sys
from datetime import datetime
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
    db_url = os.getenv("DATABASE_URL", "")

    print(f"\nEnvironment Variables:")
    print(f"  EODHD_API_KEY:       {'Set (' + api_key[:10] + '...)' if api_key else 'MISSING'}")
    print(f"  DISCORD_WEBHOOK_URL: {'Set' if webhook else 'MISSING'}")
    print(f"  DATABASE_URL:        {'PostgreSQL' if db_url else 'SQLite Fallback'}")

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
    """Initialize SQLite database via DataManager."""
    print("[INIT] Initializing database...")
    try:
        from data_manager import data_manager
        stats = data_manager.get_database_stats()
        print(f"Database ready: {stats['total_bars']} bars, {stats['unique_tickers']} tickers, {stats['size_mb']:.1f} MB")
        return data_manager
    except Exception as e:
        print(f"Database initialization error: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_ai_learning():
    """Load AI learning engine and display current state."""
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
    """Load position manager and display open positions."""
    print("[INIT] Loading position manager...")
    try:
        from position_manager import position_manager
        open_positions = position_manager.get_open_positions()
        print(f"Position Manager loaded")
        if open_positions:
            print(f"  {len(open_positions)} open positions from previous session:")
            for pos in open_positions:
                print(f"    {pos['ticker']} {pos['direction'].upper()} | Entry: ${pos['entry']:.2f}")
        else:
            print(f"  No open positions")
        return position_manager
    except Exception as e:
        print(f"Position Manager error: {e}")
        return None


def load_win_rate_tracker():
    """Load win rate stats from position manager."""
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
    """Send startup notification to Discord."""
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
        message = f"War Machine Started | {now.strftime('%I:%M:%S %p ET')} | {status} | CFW6 + Options Intelligence"
        send_simple_message(message)
        print("Startup notification sent to Discord")
    except Exception as e:
        print(f"Discord notification failed: {e}")


def main():
    """Main entry point with full initialization."""

    # Step 1: Check environment
    if not check_environment():
        print("\nStartup aborted due to missing configuration")
        sys.exit(1)

    # Step 2: Initialize database
    db = initialize_database()

    # Step 3: Load AI learning engine
    ai_engine = load_ai_learning()

    # Step 4: Load position manager
    pos_tracker = load_position_tracker()

    # Step 5: Load win rate data
    wr_tracker = load_win_rate_tracker()

    # Step 6: Send startup notification
    send_startup_notification()

    # Step 7: Display strategy summary
    print("\n" + "="*60)
    print("STRATEGY CONFIGURATION")
    print("="*60)
    print("Strategy:     CFW6 (Opening Range + FVG + Confirmation)")
    print("Grades:       A+, A, A-")
    print("Layers:       VWAP, Prev Day, Institutional Volume, Options Flow")
    print("MTF:          5m > 3m > 2m > 1m (highest timeframe priority)")
    print("Risk:         2% per trade | 1 contract max")
    print("Options:      7-45 DTE | 0.35-0.55 delta | High liquidity")
    print("="*60 + "\n")

    # Step 8: Start scanner loop
    print("Starting CFW6 scanner...\n")
    try:
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
