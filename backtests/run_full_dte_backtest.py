#!/usr/bin/env python3
"""
Complete DTE Backtest Workflow
Extract candles from DB -> Simulate trades -> Analyze DTE performance
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def run_command(cmd: list, description: str) -> bool:
    """Run command and return success status"""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}\n")
    
    result = subprocess.run(cmd, capture_output=False)
    success = result.returncode == 0
    
    if success:
        print(f"\n✅ {description} - SUCCESS")
    else:
        print(f"\n❌ {description} - FAILED")
    
    return success

def main():
    print("\n" + "="*60)
    print("WAR MACHINE - DTE STRATEGY BACKTEST")
    print("="*60)
    
    # Step 1: Extract candles from database
    print("\nStep 1: Extracting candle data from PostgreSQL cache...")
    
    extract_success = run_command(
        ['python', 'backtests/extract_candles_from_db.py', '--days', '90'],
        "Extract Candles from Database"
    )
    
    if not extract_success:
        print("\n⚠️ Candle extraction failed. Check database connection.")
        print("\nAlternatively, you can manually run:")
        print("  python backtests/extract_candles_from_db.py --list-symbols")
        return
    
    # Step 2: Run candle-based backtest
    candle_file = 'backtests/cached_candles.json'
    
    if not Path(candle_file).exists():
        print(f"\n⚠️ Candle file not found: {candle_file}")
        return
    
    sim_success = run_command(
        ['python', 'backtests/simulate_from_candles.py', candle_file, '--max-signals', '200'],
        "Simulate Trading Signals and Outcomes"
    )
    
    if not sim_success:
        print("\n⚠️ Simulation failed.")
        return
    
    # Step 3: Run historical advisor on simulated positions
    positions_file = 'backtests/simulated_positions.csv'
    
    if not Path(positions_file).exists():
        print(f"\n⚠️ Simulated positions file not found: {positions_file}")
        return
    
    print("\nStep 3: Analyzing DTE effectiveness...")
    
    # Copy simulated positions to position_history for advisor
    import shutil
    shutil.copy(positions_file, 'backtests/position_history.csv')
    
    advisor_success = run_command(
        ['python', 'backtests/historical_advisor.py'],
        "Historical DTE Advisor Analysis"
    )
    
    # Summary
    print("\n" + "="*60)
    print("BACKTEST WORKFLOW COMPLETE")
    print("="*60)
    
    if advisor_success:
        print("\n✅ All steps completed successfully!")
        print("\nGenerated files:")
        print("  - backtests/cached_candles.json (extracted data)")
        print("  - backtests/simulated_signals.csv (detected signals)")
        print("  - backtests/simulated_positions.csv (trade outcomes)")
        print("  - backtests/historical_advisor_results.csv (DTE analysis)")
        print("\nKey insights are shown above in the Historical DTE Advisor Report.")
    else:
        print("\n⚠️ Some steps failed. Check output above for details.")
    
    print("\n" + "="*60 + "\n")

if __name__ == '__main__':
    main()
