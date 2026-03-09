"""
Entry Timing Optimizer
Analyzes historical entry timing patterns to identify optimal windows
Focus: 9:30-9:40 AM critical window for capturing early momentum
"""
from datetime import time
from typing import Dict, List, Optional, Tuple
import statistics

class EntryTimingOptimizer:
    """Track and optimize entry timing based on historical win rates."""
    
    def __init__(self):
        self.time_buckets = {
            '09:30-09:35': [],
            '09:35-09:40': [],
            '09:40-09:45': [],
            '09:45-10:00': [],
            '10:00-10:30': [],
            '10:30-11:00': [],
            '11:00-12:00': [],
            '12:00-13:00': [],
            '13:00-14:00': [],
            '14:00-15:00': [],
            '15:00-16:00': []
        }
    
    def get_time_bucket(self, entry_time: time) -> str:
        """Map entry time to bucket."""
        hour = entry_time.hour
        minute = entry_time.minute
        
        if hour == 9:
            if minute < 35:
                return '09:30-09:35'
            elif minute < 40:
                return '09:35-09:40'
            elif minute < 45:
                return '09:40-09:45'
            else:
                return '09:45-10:00'
        elif hour == 10:
            if minute < 30:
                return '10:00-10:30'
            else:
                return '10:30-11:00'
        elif hour == 11:
            return '11:00-12:00'
        elif hour == 12:
            return '12:00-13:00'
        elif hour == 13:
            return '13:00-14:00'
        elif hour == 14:
            return '14:00-15:00'
        else:
            return '15:00-16:00'
    
    def record_trade(self, entry_time: time, won: bool):
        """Record trade outcome by entry time."""
        bucket = self.get_time_bucket(entry_time)
        self.time_buckets[bucket].append(1 if won else 0)
    
    def get_bucket_stats(self, bucket: str) -> Dict:
        """Get win rate stats for a time bucket."""
        trades = self.time_buckets.get(bucket, [])
        if not trades:
            return {'trades': 0, 'win_rate': 0.0, 'confidence': 'none'}
        
        win_rate = statistics.mean(trades) * 100
        confidence = 'high' if len(trades) >= 10 else 'medium' if len(trades) >= 5 else 'low'
        
        return {
            'trades': len(trades),
            'win_rate': win_rate,
            'confidence': confidence
        }
    
    def should_take_entry(self, entry_time: time, min_win_rate: float = 50.0) -> Tuple[bool, str]:
        """Determine if entry timing is favorable."""
        bucket = self.get_time_bucket(entry_time)
        stats = self.get_bucket_stats(bucket)
        
        if stats['trades'] < 5:
            return True, f"Insufficient data for {bucket} ({stats['trades']} trades)"
        
        if stats['win_rate'] >= min_win_rate:
            return True, f"{bucket} favorable ({stats['win_rate']:.1f}% WR, {stats['trades']} trades)"
        else:
            return False, f"{bucket} unfavorable ({stats['win_rate']:.1f}% WR, {stats['trades']} trades)"
    
    def get_best_windows(self, min_trades: int = 5) -> List[Tuple[str, Dict]]:
        """Get time windows ranked by win rate."""
        windows = []
        for bucket in self.time_buckets:
            stats = self.get_bucket_stats(bucket)
            if stats['trades'] >= min_trades:
                windows.append((bucket, stats))
        
        # Sort by win rate descending
        windows.sort(key=lambda x: x[1]['win_rate'], reverse=True)
        return windows
    
    def print_timing_report(self):
        """Print EOD report of entry timing performance."""
        print("\n" + "="*80)
        print("ENTRY TIMING ANALYSIS")
        print("="*80)
        print(f"{'Time Window':<20} {'Trades':<10} {'Win Rate':<15} {'Confidence':<15}")
        print("-"*80)
        
        for bucket in sorted(self.time_buckets.keys()):
            stats = self.get_bucket_stats(bucket)
            if stats['trades'] > 0:
                print(f"{bucket:<20} {stats['trades']:<10} {stats['win_rate']:<14.1f}% {stats['confidence']:<15}")
        
        print("="*80)
        
        # Highlight best windows
        best_windows = self.get_best_windows(min_trades=5)
        if best_windows:
            print("\n🏆 TOP PERFORMING WINDOWS:")
            for i, (bucket, stats) in enumerate(best_windows[:3], 1):
                print(f"  {i}. {bucket}: {stats['win_rate']:.1f}% WR ({stats['trades']} trades)")
        
        print("\n")


# Global instance
_timing_optimizer = None

def get_timing_optimizer() -> EntryTimingOptimizer:
    global _timing_optimizer
    if _timing_optimizer is None:
        _timing_optimizer = EntryTimingOptimizer()
    return _timing_optimizer
