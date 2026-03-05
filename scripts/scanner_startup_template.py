#!/usr/bin/env python3
"""
Scanner Startup Template with Integrated Health Checks

This is a template showing how to integrate comprehensive health checks
into your War Machine scanner startup sequence.

Usage:
    1. Copy this pattern into your main scanner file (breakout_detector.py or scanner.py)
    2. Replace placeholder comments with your actual scanner logic
    3. Adjust require_database and require_discord based on your needs
    4. Set environment variables before running

Environment Variables:
    EODHD_API_KEY         - Required for data feed
    DATABASE_URL          - Required for analytics (if enabled)
    DISCORD_WEBHOOK_URL   - Optional for alerts

Author: War Machine Team
Phase: 1.10 - Action Item #5
Date: March 5, 2026
"""

import sys
import os
import time
from datetime import datetime
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.health_check import perform_health_check, print_session_info
    HEALTH_CHECK_AVAILABLE = True
except ImportError:
    print("⚠️  Warning: Health check module not found")
    print("   Install with: pip install -r requirements.txt")
    HEALTH_CHECK_AVAILABLE = False


def initialize_war_machine(require_db: bool = True, 
                          require_discord: bool = False) -> dict:
    """
    Initialize War Machine with comprehensive health checks.
    
    Args:
        require_db: Fail fast if database unavailable
        require_discord: Fail fast if Discord not configured
        
    Returns:
        Configuration dict with initialized subsystems
    """
    print("\n" + "="*70)
    print("WAR MACHINE BOS/FVG SCANNER")
    print("Initializing subsystems...")
    print("="*70 + "\n")
    
    if not HEALTH_CHECK_AVAILABLE:
        print("⚠️  Running without health checks - limited diagnostics available\n")
        return {
            'health_check_ok': False,
            'analytics_enabled': False,
            'discord_enabled': False,
            'data_feed_ok': bool(os.getenv('EODHD_API_KEY'))
        }
    
    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1: Run comprehensive health check
    # ──────────────────────────────────────────────────────────────────────────
    health_status = perform_health_check(
        require_database=require_db,
        require_discord=require_discord,
        verbose=True
    )
    
    # Exit if critical systems failed
    if not health_status['critical_systems_ok']:
        print("\n⚠️  CRITICAL SYSTEM FAILURE - Cannot proceed")
        print("\nRequired fixes:")
        
        if require_db and health_status['subsystems']['database']['status'] != 'online':
            print("  1. Set DATABASE_URL environment variable")
            print("     Example: postgresql://user:pass@host:5432/database")
            print("  2. Verify PostgreSQL is running")
            print("  3. Install psycopg2: pip install psycopg2-binary")
        
        if require_discord and health_status['subsystems']['discord']['status'] != 'online':
            print("  1. Set DISCORD_WEBHOOK_URL environment variable")
            print("     Get from: Discord Server Settings → Webhooks")
        
        sys.exit(1)
    
    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2: Initialize subsystems based on health check results
    # ──────────────────────────────────────────────────────────────────────────
    config = {
        'health_check_ok': True,
        'analytics_enabled': False,
        'discord_enabled': False,
        'data_feed_ok': False,
        'analytics_conn': None,
        'discord_webhook': None
    }
    
    # Database / Analytics
    if health_status['subsystems']['database']['status'] == 'online':
        try:
            import psycopg2
            config['analytics_conn'] = psycopg2.connect(os.getenv('DATABASE_URL'))
            config['analytics_enabled'] = True
            print("✓ Analytics tracking ENABLED")
        except Exception as e:
            print(f"⚠️  Analytics connection failed: {e}")
            config['analytics_enabled'] = False
    else:
        print("⚠️  Analytics tracking DISABLED (no DATABASE_URL)")
    
    # Discord Alerting
    if health_status['subsystems']['discord']['status'] == 'online':
        config['discord_webhook'] = os.getenv('DISCORD_WEBHOOK_URL')
        config['discord_enabled'] = True
        print("✓ Discord alerts ENABLED")
    else:
        print("⚠️  Discord alerts DISABLED (no webhook configured)")
    
    # Data Feed
    if health_status['subsystems']['data_feed']['status'] == 'online':
        config['data_feed_ok'] = True
        print("✓ Data feed READY (EODHD)")
    else:
        print("❌ Data feed FAILED - missing EODHD_API_KEY")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("Subsystem initialization complete")
    print("="*70 + "\n")
    
    return config


def main():
    """
    Main scanner entry point with health checks.
    """
    # ══════════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ══════════════════════════════════════════════════════════════════════════
    
    # Adjust these based on your requirements
    REQUIRE_DATABASE = False  # Set to True for production with analytics
    REQUIRE_DISCORD = False   # Set to True if alerts are critical
    
    # ══════════════════════════════════════════════════════════════════════════
    # STARTUP & HEALTH CHECKS
    # ══════════════════════════════════════════════════════════════════════════
    
    config = initialize_war_machine(
        require_db=REQUIRE_DATABASE,
        require_discord=REQUIRE_DISCORD
    )
    
    # Print session information
    if HEALTH_CHECK_AVAILABLE:
        print_session_info(
            session_start="09:30",
            session_end="16:00",
            is_premarket=False,
            watchlist_size=20  # Replace with actual watchlist size
        )
    
    print("🚀 War Machine operational - starting main loop...\n")
    
    # ══════════════════════════════════════════════════════════════════════════
    # MAIN SCANNER LOOP
    # ══════════════════════════════════════════════════════════════════════════
    
    try:
        cycle_count = 0
        
        while True:
            cycle_count += 1
            cycle_start = time.time()
            
            print(f"\n{'='*70}")
            print(f"SCANNER CYCLE {cycle_count} - {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'='*70}")
            
            # ──────────────────────────────────────────────────────────────────
            # YOUR SCANNER LOGIC HERE
            # ──────────────────────────────────────────────────────────────────
            
            # Example:
            # 1. Fetch watchlist
            # watchlist = get_current_watchlist()
            
            # 2. Scan each ticker for BOS/FVG signals
            # for ticker in watchlist:
            #     signal = detect_breakout(ticker)
            #     if signal:
            #         if config['discord_enabled']:
            #             send_discord_alert(ticker, signal, config['discord_webhook'])
            #         if config['analytics_enabled']:
            #             log_signal_to_db(ticker, signal, config['analytics_conn'])
            
            # Placeholder output
            print("Scanning watchlist...")
            print(f"Analytics: {'ENABLED' if config['analytics_enabled'] else 'DISABLED'}")
            print(f"Discord: {'ENABLED' if config['discord_enabled'] else 'DISABLED'}")
            print("No signals detected this cycle")
            
            # ──────────────────────────────────────────────────────────────────
            # CYCLE COMPLETION
            # ──────────────────────────────────────────────────────────────────
            
            cycle_time = time.time() - cycle_start
            print(f"\nCycle {cycle_count} complete in {cycle_time:.2f}s")
            
            # Adjust sleep time based on market conditions
            # Pre-market: 60s, Market hours: 5-30s, Midday chop: 180s
            sleep_time = 30  # Replace with dynamic logic
            print(f"Next scan in {sleep_time}s...")
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Scanner stopped by user")
        cleanup(config)
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Fatal error in main loop: {e}")
        cleanup(config)
        sys.exit(1)


def cleanup(config: dict):
    """
    Cleanup resources on shutdown.
    
    Args:
        config: Configuration dict from initialize_war_machine()
    """
    print("\nShutting down War Machine...")
    
    # Close database connection
    if config.get('analytics_conn'):
        try:
            config['analytics_conn'].close()
            print("✓ Database connection closed")
        except Exception as e:
            print(f"⚠️  Database cleanup error: {e}")
    
    print("✓ Shutdown complete")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
