"""
Position Manager - Consolidated Position Tracking, Sizing, and Win Rate Analysis
Replaces: position_tracker.py, position_sizing.py, win_rate_tracker.py
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os

class PositionManager:
    def __init__(self, db_path: str = "war_machine_trades.db"):
        self.db_path = db_path
        self.positions = []  # Active positions
        self.initialize_database()
    
    def initialize_database(self):
        """Create positions table if not exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                t1_price REAL NOT NULL,
                t2_price REAL NOT NULL,
                contracts INTEGER DEFAULT 1,
                grade TEXT,
                confidence REAL,
                entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                exit_time TIMESTAMP,
                exit_price REAL,
                exit_reason TEXT,
                pnl REAL,
                status TEXT DEFAULT 'OPEN',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def calculate_position_size(self, 
                                confidence: float, 
                                grade: str, 
                                account_size: float = 5000,
                                risk_per_share: float = 1.0) -> Dict:
        """
        CFW6 OPTIMIZATION: Dynamic position sizing based on signal quality
        
        Grade-based risk allocation:
        - A+ signals (85%+ confidence): 3% account risk
        - A signals (75%+ confidence): 2.4% account risk  
        - A- signals (65%+ confidence): 2% account risk
        - Below 65%: 1.4% account risk
        """
        base_risk_pct = 0.02  # 2% base risk
        
        # Adjust risk based on confidence and grade
        if confidence >= 0.85 and grade == "A+":
            risk_multiplier = 1.5  # 3% risk
            allocation = "AGGRESSIVE"
        elif confidence >= 0.75 and grade in ["A+", "A"]:
            risk_multiplier = 1.2  # 2.4% risk
            allocation = "STANDARD+"
        elif confidence >= 0.65:
            risk_multiplier = 1.0  # 2% risk
            allocation = "STANDARD"
        else:
            risk_multiplier = 0.7  # 1.4% risk
            allocation = "CONSERVATIVE"
        
        position_risk = account_size * base_risk_pct * risk_multiplier
        contracts = max(1, int(position_risk / (risk_per_share * 100)))
        
        return {
            "contracts": contracts,
            "risk_dollars": position_risk,
            "risk_percentage": base_risk_pct * risk_multiplier * 100,
            "allocation_type": allocation
        }
    
    def open_position(self,
                     ticker: str,
                     direction: str,
                     entry: float,
                     stop: float,
                     t1: float,
                     t2: float,
                     grade: str,
                     confidence: float,
                     contracts: int = 1) -> int:
        """
        Open a new position and return position ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO positions 
            (ticker, direction, entry_price, stop_price, t1_price, t2_price, 
             contracts, grade, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (ticker, direction, entry, stop, t1, t2, contracts, grade, confidence))
        
        position_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Add to active positions cache
        self.positions.append({
            "id": position_id,
            "ticker": ticker,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "t1": t1,
            "t2": t2,
            "contracts": contracts,
            "grade": grade,
            "confidence": confidence
        })
        
        print(f"[POSITION] Opened {ticker} {direction.upper()} - ID: {position_id}")
        print(f"  Entry: ${entry:.2f} | Stop: ${stop:.2f} | T1: ${t1:.2f} | T2: ${t2:.2f}")
        print(f"  Contracts: {contracts} | Grade: {grade} | Confidence: {confidence:.1%}")
        
        return position_id
    
    def check_exits(self, current_prices: Dict[str, float]):
        """
        Check all open positions for stop/target hits
        """
        open_positions = self.get_open_positions()
        
        if not open_positions:
            return
        
        for pos in open_positions:
            ticker = pos["ticker"]
            
            if ticker not in current_prices:
                continue
            
            current_price = current_prices[ticker]
            direction = pos["direction"]
            stop = pos["stop"]
            t1 = pos["t1"]
            t2 = pos["t2"]
            entry = pos["entry"]
            
            exit_triggered = False
            exit_price = None
            exit_reason = None
            
            if direction == "bull":
                # Check stop loss
                if current_price <= stop:
                    exit_triggered = True
                    exit_price = stop
                    exit_reason = "STOP LOSS"
                # Check T2 first (higher priority)
                elif current_price >= t2:
                    exit_triggered = True
                    exit_price = t2
                    exit_reason = "TARGET 2"
                # Check T1
                elif current_price >= t1:
                    exit_triggered = True
                    exit_price = t1
                    exit_reason = "TARGET 1"
            
            else:  # bear
                # Check stop loss
                if current_price >= stop:
                    exit_triggered = True
                    exit_price = stop
                    exit_reason = "STOP LOSS"
                # Check T2 first
                elif current_price <= t2:
                    exit_triggered = True
                    exit_price = t2
                    exit_reason = "TARGET 2"
                # Check T1
                elif current_price <= t1:
                    exit_triggered = True
                    exit_price = t1
                    exit_reason = "TARGET 1"
            
            if exit_triggered:
                self.close_position(pos["id"], exit_price, exit_reason)
    
    def close_position(self, position_id: int, exit_price: float, exit_reason: str):
        """Close a position and calculate P&L"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get position details
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        pos = cursor.fetchone()
        
        if not pos:
            conn.close()
            return
        
        # Unpack position
        _, ticker, direction, entry, stop, t1, t2, contracts, grade, confidence, entry_time, *_ = pos
        
        # Calculate P&L
        if direction == "bull":
            pnl_per_share = exit_price - entry
        else:
            pnl_per_share = entry - exit_price
        
        pnl_total = pnl_per_share * 100 * contracts  # Options contracts
        
        # Update database
        cursor.execute("""
            UPDATE positions 
            SET exit_price = ?, exit_reason = ?, pnl = ?, 
                exit_time = CURRENT_TIMESTAMP, status = 'CLOSED'
            WHERE id = ?
        """, (exit_price, exit_reason, pnl_total, position_id))
        
        conn.commit()
        conn.close()
        
        # Remove from active cache
        self.positions = [p for p in self.positions if p["id"] != position_id]
        
        # Log exit
        win_loss = "✅ WIN" if pnl_total > 0 else "❌ LOSS"
        print(f"\n[EXIT] {win_loss} - {ticker} {direction.upper()}")
        print(f"  Entry: ${entry:.2f} → Exit: ${exit_price:.2f} ({exit_reason})")
        print(f"  P&L: ${pnl_total:+.2f} | Grade: {grade} | Confidence: {confidence:.1%}")
        
        # Record to AI learning
        try:
            from ai_learning import learning_engine
            learning_engine.record_trade({
                "ticker": ticker,
                "direction": direction,
                "entry": entry,
                "exit": exit_price,
                "pnl": pnl_total,
                "grade": grade,
                "confidence": confidence,
                "exit_reason": exit_reason
            })
        except Exception as e:
            print(f"[LEARNING] Error recording trade: {e}")
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, ticker, direction, entry_price, stop_price, t1_price, t2_price,
                   contracts, grade, confidence
            FROM positions 
            WHERE status = 'OPEN'
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        positions = []
        for row in rows:
            positions.append({
                "id": row[0],
                "ticker": row[1],
                "direction": row[2],
                "entry": row[3],
                "stop": row[4],
                "t1": row[5],
                "t2": row[6],
                "contracts": row[7],
                "grade": row[8],
                "confidence": row[9]
            })
        
        return positions
    
    def get_daily_stats(self) -> Dict:
        """Get today's trading statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now().date()
        
        cursor.execute("""
            SELECT COUNT(*), 
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END),
                   COALESCE(SUM(pnl), 0)
            FROM positions
            WHERE DATE(entry_time) = ? AND status = 'CLOSED'
        """, (today,))
        
        row = cursor.fetchone()
        conn.close()
        
        total_trades = row[0] or 0
        wins = row[1] or 0
        losses = row[2] or 0
        total_pnl = row[3] or 0
        
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        return {
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl
        }
    
    def get_win_rate_by_grade(self, days: int = 30) -> Dict:
        """
        Win rate analysis by grade (last N days)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        cursor.execute("""
            SELECT grade,
                   COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(pnl) as avg_pnl
            FROM positions
            WHERE status = 'CLOSED' AND entry_time >= ?
            GROUP BY grade
            ORDER BY grade DESC
        """, (cutoff_date,))
        
        rows = cursor.fetchall()
        conn.close()
        
        stats = {}
        for row in rows:
            grade = row[0]
            total = row[1]
            wins = row[2]
            avg_pnl = row[3]
            
            win_rate = (wins / total * 100) if total > 0 else 0
            
            stats[grade] = {
                "total_trades": total,
                "wins": wins,
                "win_rate": win_rate,
                "avg_pnl": avg_pnl
            }
        
        return stats
    
    def print_summary(self):
        """Print position summary"""
        daily = self.get_daily_stats()
        open_pos = self.get_open_positions()
        
        print(f"\n{'='*60}")
        print("POSITION MANAGER SUMMARY")
        print(f"{'='*60}")
        print(f"Open Positions: {len(open_pos)}")
        print(f"Today's Trades: {daily['trades']}")
        print(f"Win Rate: {daily['win_rate']:.1f}%")
        print(f"P&L: ${daily['total_pnl']:+.2f}")
        print(f"{'='*60}\n")

# Global instance
position_manager = PositionManager()
