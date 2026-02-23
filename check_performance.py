#!/usr/bin/env python3
"""
Check Performance - CLI tool for viewing signal analytics

Usage:
    python check_performance.py              # Show last 30 days
    python check_performance.py 7            # Show last 7 days
    python check_performance.py --recent 20  # Show 20 most recent signals
"""

import sys
from signal_analytics import analytics


def main():
    # Parse arguments
    days = 30
    show_recent = None
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--recent':
            show_recent = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        else:
            try:
                days = int(sys.argv[1])
            except ValueError:
                print("Usage: python check_performance.py [days] or --recent [count]")
                sys.exit(1)
    
    if show_recent:
        # Show recent signals
        print(f"\n{'='*90}")
        print(f"RECENT SIGNALS - Last {show_recent}")
        print(f"{'='*90}")
        
        signals = analytics.get_recent_signals(show_recent)
        
        if not signals:
            print("\nNo signals found\n")
            return
        
        print(f"\n{'ID':<6} {'Ticker':<8} {'Dir':<6} {'Time':<17} {'Entry':<8} "
              f"{'Target':<8} {'Outcome':<10} {'P&L':<10} {'R':<8}")
        print("-" * 90)
        
        for s in signals:
            sig_time = s['signal_time']
            if isinstance(sig_time, str):
                sig_time = sig_time[:16]  # Truncate to HH:MM
            else:
                sig_time = sig_time.strftime('%m/%d %H:%M')
            
            outcome = s['outcome'] or 'ACTIVE'
            pnl_str = f"${s['pnl']:+.2f}" if s['pnl'] else '-'
            pnl_r_str = f"{s['pnl_r']:+.2f}R" if s['pnl_r'] else '-'
            
            # Color code outcomes (if terminal supports it)
            if outcome == 'WIN':
                outcome = f"\033[92m{outcome}\033[0m"  # Green
            elif outcome == 'LOSS':
                outcome = f"\033[91m{outcome}\033[0m"  # Red
            elif outcome == 'EXPIRED':
                outcome = f"\033[93m{outcome}\033[0m"  # Yellow
            
            print(f"{s['id']:<6} {s['ticker']:<8} {s['direction']:<6} {sig_time:<17} "
                  f"${s['entry_price']:<7.2f} ${s['target_price']:<7.2f} "
                  f"{outcome:<20} {pnl_str:<10} {pnl_r_str:<8}")
        
        print("=" * 90 + "\n")
    
    else:
        # Show performance report
        analytics.print_performance_report(days)
        
        # Show breakdown by confidence levels if we have data
        stats = analytics.get_performance_stats(days)
        if stats['completed'] > 0:
            print("\n" + "="*70)
            print("RECOMMENDATIONS:")
            print("="*70)
            
            win_rate = stats['win_rate']
            profit_factor = stats['profit_factor']
            
            if win_rate < 50:
                print("⚠️  Win rate below 50% - Consider:")
                print("   - Increasing min_confidence threshold")
                print("   - Tightening entry criteria (higher volume_multiplier)")
                print("   - Adjusting risk/reward ratio")
            elif win_rate > 65:
                print("✅ Strong win rate - System performing well")
            
            if profit_factor < 1.5:
                print("⚠️  Profit factor below 1.5 - Consider:")
                print("   - Widening targets (increase risk_reward_ratio)")
                print("   - Tightening stops (reduce atr_stop_multiplier)")
            elif profit_factor > 2.0:
                print("✅ Excellent profit factor - Strong system edge")
            
            avg_hold = stats['avg_hold_mins']
            if avg_hold < 30:
                print(f"\n🕒 Average hold time: {avg_hold:.0f}m (Fast scalping system)")
            elif avg_hold < 120:
                print(f"\n🕒 Average hold time: {avg_hold:.0f}m (Intraday swing system)")
            else:
                print(f"\n🕒 Average hold time: {avg_hold:.0f}m (Position holding system)")
            
            print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
