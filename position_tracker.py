"""
Position Tracker - Monitors Live Trades
Tracks entries, exits, P&L in real-time
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class PositionTracker:
    def __init__(self, positions_file: str = "active_positions.json"):
        self.positions_file = positions_file
        self.positions = self.load_positions()
        
    def load_positions(self) -> Dict:
        """Load active positions from disk."""
        if os.path.exists(self.positions_file):
            with open(self.positions_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_positions(self):
        """Save positions to disk."""
        with open(self.positions_file, 'w') as f:
            json.dump(self.positions, f, indent=2)
    
    def open_position(self, ticker: str, direction: str, entry: float, 
                     stop: float, t1: float, t2: float, contracts: int,
                     grade: str, confidence: float):
        """Record a new position entry."""
        position_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.positions[position_id] = {
            "ticker": ticker,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "t1": t1,
            "t2": t2,
            "contracts": contracts,
            "grade": grade,
            "confidence": confidence,
            "entry_time": datetime.now().isoformat(),
            "status": "open",
            "current_pnl": 0,
            "current_price": entry,
            "exit_price": None,
            "exit_time": None,
            "exit_reason": None
        }
        
        self.save_positions()
        
        print(f"[TRACKER] 📍 Position opened: {ticker} {direction.upper()}")
        print(f"  Entry: ${entry:.2f} | Stop: ${stop:.2f} | T1: ${t1:.2f} | T2: ${t2:.2f}")
        print(f"  Grade: {grade} | Confidence: {confidence*100:.1f}%")
        
        return position_id
    
    def update_position(self, position_id: str, current_price: float):
        """Update position with current price and P&L."""
        if position_id not in self.positions:
            return
        
        pos = self.positions[position_id]
        
        if pos["status"] != "open":
            return
        
        entry = pos["entry"]
        direction = pos["direction"]
        contracts = pos["contracts"]
        
        # Calculate unrealized P&L
        if direction == "bull":
            pnl_per_share = current_price - entry
        else:
            pnl_per_share = entry - current_price
        
        unrealized_pnl = pnl_per_share * 100 * contracts
        pos["current_pnl"] = round(unrealized_pnl, 2)
        pos["current_price"] = current_price
        
        self.save_positions()
    
    def close_position(self, position_id: str, exit_price: float, exit_reason: str):
        """Close a position and record final P&L."""
        if position_id not in self.positions:
            print(f"[TRACKER] ⚠️ Position {position_id} not found")
            return
        
        pos = self.positions[position_id]
        
        if pos["status"] == "closed":
            print(f"[TRACKER] ⚠️ Position already closed")
            return
        
        entry = pos["entry"]
        direction = pos["direction"]
        contracts = pos["contracts"]
        
        # Calculate final P&L
        if direction == "bull":
            pnl_per_share = exit_price - entry
        else:
            pnl_per_share = entry - exit_price
        
        final_pnl = pnl_per_share * 100 * contracts
        
        pos["status"] = "closed"
        pos["exit_price"] = exit_price
        pos["exit_time"] = datetime.now().isoformat()
        pos["exit_reason"] = exit_reason
        pos["final_pnl"] = round(final_pnl, 2)
        
        # Calculate hold duration
        entry_time = datetime.fromisoformat(pos["entry_time"])
        exit_time = datetime.fromisoformat(pos["exit_time"])
        hold_duration = (exit_time - entry_time).total_seconds() / 60
        pos["hold_duration_minutes"] = round(hold_duration, 1)
        
        self.save_positions()
        
        # Record to AI learning engine
        from ai_learning import learning_engine
        learning_engine.record_trade({
            "ticker": pos["ticker"],
            "direction": pos["direction"],
            "grade": pos["grade"],
            "entry": entry,
            "exit": exit_price,
            "pnl": final_pnl,
            "hold_duration": hold_duration,
            "timeframe": "1m"
        })
        
        status = "✅ WIN" if final_pnl > 0 else "❌ LOSS"
        print(f"[TRACKER] {status} Position closed: {pos['ticker']} {direction.upper()}")
        print(f"  Entry: ${entry:.2f} → Exit: ${exit_price:.2f} ({exit_reason})")
        print(f"  P&L: ${final_pnl:+.2f} | Hold: {hold_duration:.1f} min")
        
        return final_pnl
    
    def get_open_positions(self) -> List[Dict]:
        """Get all currently open positions."""
        return [
            {"id": pid, **pos} 
            for pid, pos in self.positions.items() 
            if pos["status"] == "open"
        ]
    
    def check_exits(self, current_prices: Dict[str, float]):
        """Check if any positions should be closed based on current prices."""
        for position_id, pos in list(self.positions.items()):
            if pos["status"] != "open":
                continue
            
            ticker = pos["ticker"]
            if ticker not in current_prices:
                continue
            
            current_price = current_prices[ticker]
            direction = pos["direction"]
            stop = pos["stop"]
            t1 = pos["t1"]
            t2 = pos["t2"]
            
            # Update current P&L
            self.update_position(position_id, current_price)
            
            # Check exit conditions
            if direction == "bull":
                if current_price <= stop:
                    self.close_position(position_id, stop, "Stop Loss")
                elif current_price >= t2:
                    self.close_position(position_id, t2, "Target 2")
                elif current_price >= t1:
                    self.close_position(position_id, t1, "Target 1")
            
            else:  # bear
                if current_price >= stop:
                    self.close_position(position_id, stop, "Stop Loss")
                elif current_price <= t2:
                    self.close_position(position_id, t2, "Target 2")
                elif current_price <= t1:
                    self.close_position(position_id, t1, "Target 1")
    
    def get_total_pnl(self) -> float:
        """Calculate total P&L across all positions (open + closed)."""
        total = 0
        
        for pos in self.positions.values():
            if pos["status"] == "closed":
                total += pos.get("final_pnl", 0)
            else:
                total += pos.get("current_pnl", 0)
        
        return round(total, 2)
    
    def get_daily_stats(self) -> Dict:
        """Get today's trading statistics."""
        today = datetime.now().strftime("%Y-%m-%d")
        
        today_trades = [
            pos for pos in self.positions.values()
            if pos.get("entry_time", "").startswith(today)
        ]
        
        closed_today = [t for t in today_trades if t["status"] == "closed"]
        
        if not closed_today:
            return {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": 0
            }
        
        wins = [t for t in closed_today if t.get("final_pnl", 0) > 0]
        losses = [t for t in closed_today if t.get("final_pnl", 0) <= 0]
        
        total_pnl = sum(t.get("final_pnl", 0) for t in closed_today)
        win_rate = (len(wins) / len(closed_today)) * 100 if closed_today else 0
        
        return {
            "trades": len(closed_today),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2)
        }
    
    def print_summary(self):
        """Print position tracker summary."""
        open_pos = self.get_open_positions()
        daily_stats = self.get_daily_stats()
        
        print("\n" + "="*60)
        print("POSITION TRACKER SUMMARY")
        print("="*60)
        print(f"Open Positions: {len(open_pos)}")
        
        if open_pos:
            print("\nActive Trades:")
            for pos in open_pos:
                print(f"  {pos['ticker']} {pos['direction'].upper()} | "
                      f"Entry: ${pos['entry']:.2f} | "
                      f"Current: ${pos['current_price']:.2f} | "
                      f"P&L: ${pos['current_pnl']:+.2f}")
        
        print(f"\nToday's Stats:")
        print(f"  Trades: {daily_stats['trades']}")
        print(f"  Wins: {daily_stats['wins']} | Losses: {daily_stats['losses']}")
        print(f"  Win Rate: {daily_stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${daily_stats['total_pnl']:+.2f}")
        print("="*60 + "\n")


# Global instance
position_tracker = PositionTracker()
