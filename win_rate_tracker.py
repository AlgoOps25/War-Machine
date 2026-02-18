"""
Win Rate Tracker - Real-time Win Rate Monitoring
Tracks win rate by grade, ticker, timeframe, and time of day
"""

from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict
import json
import os


class WinRateTracker:
    def __init__(self, data_file: str = "win_rate_data.json"):
        self.data_file = data_file
        self.trades = []
        self.load_from_file()
    
    def load_from_file(self):
        """Load historical trades from file."""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.trades = data.get("trades", [])
                # Convert timestamp strings back to datetime
                for trade in self.trades:
                    trade["timestamp"] = datetime.fromisoformat(trade["timestamp"])
    
    def save_to_file(self):
        """Save trades to file."""
        # Convert datetime to string for JSON serialization
        trades_serializable = []
        for trade in self.trades:
            t = trade.copy()
            t["timestamp"] = trade["timestamp"].isoformat()
            trades_serializable.append(t)
        
        with open(self.data_file, 'w') as f:
            json.dump({"trades": trades_serializable}, f, indent=2)
    
    def record_trade(self, trade: Dict):
        """Record a new completed trade."""
        self.trades.append({
            "timestamp": datetime.now(),
            "ticker": trade["ticker"],
            "direction": trade["direction"],
            "grade": trade["grade"],
            "timeframe": trade.get("timeframe", "1m"),
            "entry_time": trade.get("entry_time"),
            "pnl": trade["pnl"],
            "win": trade["pnl"] > 0,
            "hour": datetime.now().hour
        })
        
        self.save_to_file()
    
    def get_overall_win_rate(self, days: int = 30) -> Dict:
        """Calculate overall win rate for last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        recent_trades = [t for t in self.trades if t["timestamp"] > cutoff]
        
        if not recent_trades:
            return {
                "win_rate": 0, 
                "total_trades": 0, 
                "wins": 0,
                "losses": 0,
                "sample": "insufficient"
            }
        
        wins = sum(1 for t in recent_trades if t["win"])
        total = len(recent_trades)
        
        return {
            "win_rate": round((wins / total) * 100, 2),
            "wins": wins,
            "losses": total - wins,
            "total_trades": total,
            "period_days": days
        }
    
    def get_win_rate_by_grade(self) -> Dict:
        """Win rate breakdown by CFW6 grade (A+, A, A-)."""
        grade_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0})
        
        for trade in self.trades:
            grade = trade["grade"]
            grade_stats[grade]["total"] += 1
            grade_stats[grade]["pnl"] += trade["pnl"]
            if trade["win"]:
                grade_stats[grade]["wins"] += 1
        
        results = {}
        for grade in ["A+", "A", "A-"]:
            if grade in grade_stats:
                stats = grade_stats[grade]
                wr = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
                results[grade] = {
                    "win_rate": round(wr, 2),
                    "wins": stats["wins"],
                    "losses": stats["total"] - stats["wins"],
                    "total": stats["total"],
                    "total_pnl": round(stats["pnl"], 2)
                }
        
        return results
    
    def get_win_rate_by_ticker(self, min_trades: int = 5) -> Dict:
        """Win rate by ticker (minimum N trades required)."""
        ticker_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0})
        
        for trade in self.trades:
            ticker = trade["ticker"]
            ticker_stats[ticker]["total"] += 1
            ticker_stats[ticker]["pnl"] += trade["pnl"]
            if trade["win"]:
                ticker_stats[ticker]["wins"] += 1
        
        results = {}
        for ticker, stats in ticker_stats.items():
            if stats["total"] >= min_trades:
                wr = (stats["wins"] / stats["total"]) * 100
                results[ticker] = {
                    "win_rate": round(wr, 2),
                    "wins": stats["wins"],
                    "total": stats["total"],
                    "total_pnl": round(stats["pnl"], 2)
                }
        
        # Sort by win rate
        return dict(sorted(results.items(), key=lambda x: x[1]["win_rate"], reverse=True))
    
    def get_win_rate_by_timeframe(self) -> Dict:
        """Win rate by timeframe (1m, 2m, 3m, 5m)."""
        tf_stats = defaultdict(lambda: {"wins": 0, "total": 0})
        
        for trade in self.trades:
            tf = trade.get("timeframe", "1m")
            tf_stats[tf]["total"] += 1
            if trade["win"]:
                tf_stats[tf]["wins"] += 1
        
        results = {}
        for tf in ["5m", "3m", "2m", "1m"]:
            if tf in tf_stats:
                stats = tf_stats[tf]
                wr = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
                results[tf] = {
                    "win_rate": round(wr, 2),
                    "wins": stats["wins"],
                    "total": stats["total"]
                }
        
        return results
    
    def get_win_rate_by_hour(self) -> Dict:
        """Win rate by hour of day (market hours only)."""
        hour_stats = defaultdict(lambda: {"wins": 0, "total": 0})
        
        for trade in self.trades:
            hour = trade.get("hour", 0)
            if 9 <= hour <= 16:  # Market hours
                hour_stats[hour]["total"] += 1
                if trade["win"]:
                    hour_stats[hour]["wins"] += 1
        
        results = {}
        for hour in range(9, 17):
            if hour in hour_stats:
                stats = hour_stats[hour]
                wr = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
                
                # Format hour as 12-hour time
                hour_12 = hour if hour <= 12 else hour - 12
                am_pm = "AM" if hour < 12 else "PM"
                
                results[f"{hour_12}:00 {am_pm}"] = {
                    "win_rate": round(wr, 2),
                    "wins": stats["wins"],
                    "total": stats["total"]
                }
        
        return results
    
    def get_win_rate_by_direction(self) -> Dict:
        """Win rate by trade direction (bull vs bear)."""
        direction_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0})
        
        for trade in self.trades:
            direction = trade["direction"]
            direction_stats[direction]["total"] += 1
            direction_stats[direction]["pnl"] += trade["pnl"]
            if trade["win"]:
                direction_stats[direction]["wins"] += 1
        
        results = {}
        for direction in ["bull", "bear"]:
            if direction in direction_stats:
                stats = direction_stats[direction]
                wr = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
                results[direction] = {
                    "win_rate": round(wr, 2),
                    "wins": stats["wins"],
                    "total": stats["total"],
                    "total_pnl": round(stats["pnl"], 2)
                }
        
        return results
    
    def generate_report(self) -> str:
        """Generate comprehensive win rate report."""
        overall = self.get_overall_win_rate(30)
        by_grade = self.get_win_rate_by_grade()
        by_ticker = self.get_win_rate_by_ticker()
        by_direction = self.get_win_rate_by_direction()
        
        report = "\n" + "="*60 + "\n"
        report += "WIN RATE ANALYSIS (Last 30 Days)\n"
        report += "="*60 + "\n"
        
        # Overall
        report += f"\nOverall Performance:\n"
        report += f"  Win Rate: {overall['win_rate']:.1f}%\n"
        report += f"  Trades: {overall['total_trades']} ({overall['wins']} W / {overall['losses']} L)\n"
        
        # By Grade
        report += f"\nBy Grade:\n"
        for grade in ["A+", "A", "A-"]:
            if grade in by_grade:
                g = by_grade[grade]
                report += f"  {grade}: {g['win_rate']:.1f}% WR ({g['wins']}/{g['total']}) | P&L: ${g['total_pnl']:+.2f}\n"
        
        # By Direction
        report += f"\nBy Direction:\n"
        for direction in ["bull", "bear"]:
            if direction in by_direction:
                d = by_direction[direction]
                report += f"  {direction.upper()}: {d['win_rate']:.1f}% WR ({d['wins']}/{d['total']}) | P&L: ${d['total_pnl']:+.2f}\n"
        
        # Top Tickers
        report += f"\nTop Performing Tickers (min 5 trades):\n"
        for ticker, stats in list(by_ticker.items())[:5]:
            report += f"  {ticker}: {stats['win_rate']:.1f}% WR ({stats['wins']}/{stats['total']}) | P&L: ${stats['total_pnl']:+.2f}\n"
        
        report += "="*60 + "\n"
        
        return report
    
    def print_report(self):
        """Print win rate report to console."""
        print(self.generate_report())


# Global instance
win_rate_tracker = WinRateTracker()
