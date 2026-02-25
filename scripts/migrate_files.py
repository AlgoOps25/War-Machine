# migrate_files.py
"""
File migration script for War Machine reorganization
Moves files from flat structure to organized src/ structure
"""
import shutil
import os
from pathlib import Path

# File mapping: old_path -> new_path
FILE_MOVES = {
    # Core strategy
    "sniper.py": "src/core/strategy.py",
    "signal_generator.py": "src/core/signal_generator.py",
    "signal_validator.py": "src/core/signal_validator.py",
    "position_manager.py": "src/core/position_manager.py",
    
    # Data management
    "data_manager.py": "src/data/manager.py",
    "ws_feed.py": "src/data/websocket.py",
    "db_connection.py": "src/data/database.py",
    
    # Detection
    "breakout_detector.py": "src/detection/breakout.py",
    "bos_fvg_engine.py": "src/detection/fvg.py",
    "cfw6_confirmation.py": "src/detection/confirmation.py",
    
    # Analysis
    "technical_indicators.py": "src/analysis/technical.py",
    "volume_analyzer.py": "src/analysis/volume.py",
    "gex_engine.py": "src/analysis/gex.py",
    "vpvr_calculator.py": "src/analysis/vpvr.py",
    
    # Options
    "options_data_manager.py": "src/options/data_manager.py",
    "options_filter.py": "src/options/filter.py",
    "iv_tracker.py": "src/options/iv_tracker.py",
    
    # Learning
    "ai_learning.py": "src/learning/engine.py",
    "learning_policy.py": "src/learning/policy.py",
    "parameter_optimizer.py": "src/learning/optimizer.py",
    
    # Monitoring (Phase 4)
    "signal_analytics.py": "src/monitoring/analytics.py",
    "performance_monitor.py": "src/monitoring/performance.py",
    "performance_alerts.py": "src/monitoring/alerts.py",
    
    # Screening
    "momentum_screener_optimized.py": "src/screening/momentum.py",
    "dynamic_screener.py": "src/screening/dynamic.py",
    "watchlist_funnel.py": "src/screening/watchlist.py",
    "scanner.py": "src/screening/scanner.py",
    "uoa_scanner.py": "src/screening/uoa_scanner.py",
    
    # Filters
    "fundamentals_filter.py": "src/filters/fundamentals.py",
    "news_filter.py": "src/filters/news.py",
    "insider_filter.py": "src/filters/insider.py",
    
    # Utils
    "config.py": "src/utils/config.py",
    "discord_helpers.py": "src/utils/discord.py",
    "exchange_hours.py": "src/utils/exchange_hours.py",
    "timeframe_manager.py": "src/utils/timeframe.py",
    "trade_calculator.py": "src/utils/calculator.py",
    "dynamic_thresholds.py": "src/utils/thresholds.py",
    
    # Reporting
    "eod_digest.py": "src/reporting/eod_digest.py",
    "pnl_digest.py": "src/reporting/pnl_digest.py",
    
    # Scripts (standalone tools)
    "db_diagnostic.py": "scripts/db_diagnostic.py",
    "adaptive_historical_tuner.py": "scripts/adaptive_historical_tuner.py",
    "remote_historical_tuner.py": "scripts/remote_historical_tuner.py",
    "historical_tuner.py": "scripts/historical_tuner.py",
    "scanner_optimizer.py": "scripts/scanner_optimizer.py",
}

def migrate_files(dry_run=True):
    """
    Move files to new structure
    
    Args:
        dry_run: If True, only prints what would be done (default: True)
    """
    print("🚀 Starting file migration...")
    print(f"📋 Mode: {'DRY RUN (no files moved)' if dry_run else 'LIVE (files will be moved)'}\n")
    
    moved = 0
    skipped = 0
    
    for old_path, new_path in FILE_MOVES.items():
        if os.path.exists(old_path):
            if dry_run:
                print(f"✅ Would move: {old_path} -> {new_path}")
            else:
                # Actually move the file
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(old_path, new_path)
                print(f"✅ Moved: {old_path} -> {new_path}")
            moved += 1
        else:
            print(f"⚠️  Skipped (not found): {old_path}")
            skipped += 1
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Files to move: {moved}")
    print(f"   ⚠️  Files skipped: {skipped}")
    
    if dry_run:
        print(f"\n💡 This was a DRY RUN. To actually move files, run:")
        print(f"   python migrate_files.py --live")

if __name__ == "__main__":
    import sys
    
    # Check if --live flag is passed
    live_mode = "--live" in sys.argv
    
    if live_mode:
        confirm = input("⚠️  This will MOVE files. Are you sure? (type 'yes' to confirm): ")
        if confirm.lower() != 'yes':
            print("❌ Migration cancelled.")
            sys.exit(0)
    
    migrate_files(dry_run=not live_mode)
    
    if not live_mode:
        print("\n✅ Dry run complete! Review the output above.")
    else:
        print("\n✅ Migration complete!")
        print("\n📝 Next steps:")
        print("   1. Update imports in all moved files")
        print("   2. Create main.py entry point")
        print("   3. Update railway.toml")
        print("   4. Test locally before deploying")
