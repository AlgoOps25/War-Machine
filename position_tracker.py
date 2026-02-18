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
        entry_time = datetime.fromisoformat(
