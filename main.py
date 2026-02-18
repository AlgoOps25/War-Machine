"""
War Machine - Main Entry Point
CFW6 Strategy + Options Signal Engine
INTEGRATED: PostgreSQL, AI Learning, Position Tracking, Win Rate Analysis
"""

import os
import sys
from datetime import datetime


def check_environment():
    """Check and display environment configuration."""
    print("\n" + "="*60)
    print("WAR MACHINE - SYSTEM DIAGNOSTICS")
    print("="*60)
    
    # Python version
    print(f"Python: {sys.version.split()[0]}")
    print(f"Working Directory: {os.getcwd()}")
    
    # Check environment variables
    api_key = os.getenv("EODHD_API_KEY", "")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    db_url = os.getenv("DATABASE_URL", "")
    
    print(f"\nEnvironment Variables:")
    print(f"  EODHD_API_KEY: {'✅ Set (' + api_key[:10] + '...)' if api_key else '❌ MISSING'}")
    print(f"  DISCORD_WEBHOOK_URL: {'✅ Set' if webhook else '❌ MISSING'}")
    print(f"  DATABASE_URL: {'✅ PostgreSQL' if db_url else '⚠️ SQLite Fallback'}")
    
    # Current time and market status
    now = datetime.now()
    print(f"\nCurrent Time: {now.strftime('%I:%M:%S %p EST')}")
    print(f"Date: {now.strftime('%A, %B %d, %Y')}")
    
    from scanner import is_market_hours, is_premarket
    
    if is_premarket():
        status = "🟡 PRE-MARKET"
    elif is_market_hours():
        status = "🟢 MARKET OPEN"
    else:
        status = "🔴 MARKET CLOSED"
    
    print(f"Market Status: {status}")
    
    print("="*60 + "\n")
    
    # Validate critical requirements
    if not api_key:
        print("❌ FATAL ERROR: EODHD_API_KEY not set!")
        print("   Set environment variable: export EODHD_API_KEY='your_key_here'")
        return False
    
    if not webhook:
        print("⚠️ WARNING: DISCORD_WEBHOOK_URL not set. No alerts will be sent.")
    
    return True


def initialize_database():
    """Initialize PostgreSQL database and create tables."""
    print("[INIT] Initializing database...")
    
    try:
        from database_setup import setup_database
        db = setup_database()
        
        if db.use_postgres:
            print("✅ PostgreSQL initialized successfully")
        else:
            print("⚠️ Running with SQLite fallback")
        
        return db
    
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_ai_learning():
    """Load AI learning engine and display current state."""
    print("[INIT] Loading AI learning engine...")
    
    try:
        from ai_learning import learning_engine
        
        # Display current optimization parameters
        params = learning_engine.get_optimal_parameters()
        
        print("✅ AI Learning Engine loaded")
        print(f"   Optimal FVG size: {params['fvg_min_size_pct']:.4f}")
        print(f"   Confirmation weights: {params['confirmation_weights']}")
        
        # Display historical performance if available
        total_trades = len(learning_engine.data.get("trades", []))
        if total_trades > 0:
            print(f"   Historical trades: {total_trades}")
        
        return learning_engine
    
    except Exception as e:
        print(f"⚠️ AI Learning Engine error: {e}")
        return None


def load_position_tracker():
    """Load position tracker and display open positions."""
    print("[INIT] Loading position tracker...")
    
    try:
        from position_tracker import position_tracker
        
        open_positions = position_tracker.get_open_positions()
        
        print(f"✅ Position Tracker loaded")
        
        if open_positions:
            print(f"   ⚠️ {len(open_positions)} open positions from previous session:")
            for pos in open_positions:
                print(f"      {pos['ticker']} {pos['direction'].upper()} | "
                      f"Entry: ${pos['entry']:.2f} | P&L: ${pos['current_pnl']:+.2f}")
        else:
            print(f"   No open positions")
        
        return position_tracker
    
    except Exception as e:
        print(f"⚠️ Position Tracker error: {e}")
        return None


def load_win_rate_tracker():
    """Load win rate tracker and display stats."""
    print("[INIT] Loading win rate tracker...")
    
    try:
        from win_rate_tracker import win_rate_tracker
        
        overall = win_rate_tracker.get_overall_win_rate(30)
        
        print(f"✅ Win Rate Tracker loaded")
        
        if overall['total_trades'] > 0:
            print(f"   Last 30 days: {overall['win_rate']:.1f}% WR ({overall['total_trades']} trades)")
        else:
            print(f"   No historical data yet")
        
        return win_rate_tracker
    
    except Exception as e:
        print(f"⚠️ Win Rate Tracker error: {e}")
        return None


def send_startup_notification():
    """Send startup notification to Discord."""
    try:
        from discord_helpers import send_simple_message
        from scanner import is_market_hours, is_premarket
        
        now = datetime.now()
        
        if is_premarket():
            status = "PRE-MARKET MODE"
            emoji = "🟡"
        elif is_market_hours():
            status = "MARKET HOURS MODE"
            emoji = "🟢"
        else:
            status = "AFTER HOURS MODE"
            emoji = "🔴"
        
        message = f"{emoji} **War Machine Started**\n"
        message += f"Time: {now.strftime('%I:%M:%S %p EST')}\n"
        message += f"Status: {status}\n"
        message += f"Strategy: CFW6 + Options Intelligence\n"
        message += f"Ready to scan for signals!"
        
        send_simple_message(message)
        print("✅ Startup notification sent to Discord")
    
    except Exception as e:
        print(f"⚠️ Discord notification failed: {e}")


def main():
    """Main entry point with full initialization."""
    
    # Step 1: Check environment
    if not check_environment():
        print("\n❌ Startup aborted due to missing configuration")
        sys.exit(1)
    
    # Step 2: Initialize database
    db = initialize_database()
    
    # Step 3: Load AI learning engine
    ai_engine = load_ai_learning()
    
    # Step 4: Load position tracker
    pos_tracker = load_position_tracker()
    
    # Step 5: Load win rate tracker
    wr_tracker = load_win_rate_tracker()
    
    # Step 6: Send startup notification
    send_startup_notification()
    
    # Step 7: Display strategy summary
    print("\n" + "="*60)
    print("STRATEGY CONFIGURATION")
    print("="*60)
    print("Strategy: CFW6 (Opening Range + FVG + Confirmation)")
    print("Confirmation Tiers: A+, A, A-")
    print("Layers: VWAP, Prev Day, Institutional Volume, Options Flow")
    print("Position Size: 1 contract max")
    print("Risk: 2% per trade")
    print("Options Focus: High liquidity, 7-45 DTE, 0.35-0.55 delta")
    print("="*60 + "\n")
    
    # Step 8: Start scanner loop
    print("🚀 Starting CFW6 scanner...\n")
    
    try:
        from scanner import start_scanner_loop
        start_scanner_loop()
    
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("SHUTDOWN INITIATED")
        print("="*60)
        
        # Display final stats
        if pos_tracker:
            print("\nPosition Summary:")
            pos_tracker.print_summary()
        
        if wr_tracker:
            print("\nWin Rate Summary:")
            wr_tracker.print_report()
        
        if ai_engine:
            print("\nAI Learning Summary:")
            print(ai_engine.generate_performance_report())
        
        # Close database connection
        if db and db.use_postgres:
            db.close()
        
        print("\n✅ Shutdown complete. Goodbye!\n")
        sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        # Send error notification
        try:
            from discord_helpers import send_simple_message
            send_simple_message(f"🚨 **CRITICAL ERROR**\n```{str(e)}```\nSystem shutting down.")
        except:
            pass
        
        sys.exit(1)


if __name__ == "__main__":
    main()
