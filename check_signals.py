#!/usr/bin/env python3
"""Quick script to check what signals are in the database."""

from signal_analytics import analytics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("SIGNALS LOGGED TODAY")
print("="*70)

# Get all signals from today
recent = analytics.get_recent_signals(limit=100)

today = datetime.now(ET).date()
today_signals = [s for s in recent if isinstance(s['signal_time'], str) and s['signal_time'].startswith(str(today))]

if not today_signals:
    print("\n⚠️  NO SIGNALS LOGGED TODAY")
    print(f"\nMost recent signal:")
    if recent:
        latest = recent[0]
        print(f"  {latest['ticker']} {latest['direction']} @ ${latest['entry_price']:.2f}")
        print(f"  Time: {latest['signal_time']}")
        print(f"  Confidence: {latest['confidence']}%")
    else:
        print("  No signals in database at all")
else:
    print(f"\n✅ Found {len(today_signals)} signals logged today:\n")
    for sig in today_signals:
        time_str = sig['signal_time'].split('T')[1][:8] if 'T' in sig['signal_time'] else sig['signal_time']
        print(f"  {time_str} | {sig['ticker']:6} {sig['direction']:4} @ ${sig['entry_price']:7.2f} | "
              f"Stop: ${sig['stop_price']:7.2f} | Target: ${sig['target_price']:7.2f} | "
              f"Conf: {sig['confidence']}%")

print("\n" + "="*70)

# Show performance stats
stats = analytics.get_performance_stats(days=1)
print(f"\nToday's Stats:")
print(f"  Total Signals: {stats['total_signals']}")
print(f"  Completed: {stats['completed']}")
print(f"  Wins: {stats['wins']}")
print(f"  Losses: {stats['losses']}")
if stats['completed'] > 0:
    print(f"  Win Rate: {stats['win_rate']:.1f}%")
    print(f"  Total P&L: ${stats['total_pnl']:+.2f}")

print("\n")
