\"\"\"
Position Manager - Consolidated Position Tracking, Sizing, and Win Rate Analysis
Replaces: position_tracker.py, position_sizing.py, win_rate_tracker.py
Handles Scaling Out (closing 50% at T1) and Moving Stop to Break Even
\"\"\"
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
import config

class PositionManager:
    def __init__(self, db_path: str = config.TRADES_DB_PATH):
        self.db_path = db_path
        self.positions = [] # Active positions
        self.initialize_database()
    
    def initialize_database(self):
        \"\"\"Create positions table if not exists.\"\"\"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(\"\"\"
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                t1_price REAL NOT NULL,
                t2_price REAL NOT NULL,
                contracts INTEGER DEFAULT 1,
                remaining_contracts INTEGER,
                grade TEXT,
                confidence REAL,
                entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                exit_time TIMESTAMP,
                exit_price REAL,
                exit_reason TEXT,
                pnl REAL DEFAULT 0,
                status TEXT DEFAULT 'OPEN',
                t1_hit BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        \"\"\")
        
        conn.commit()
        conn.close()
    
    def calculate_position_size(self, 
                               confidence: float, 
                               grade: str, 
                               account_size: float = 5000,
                               risk_per_share: float = 1.0) -> Dict:
        \"\"\"
        CFW6 OPTIMIZATION: Dynamic position sizing based on signal quality
        \"\"\"
        if confidence >= 0.85 and grade == \"A+\":
            risk_pct = config.POSITION_RISK[\"A+_high_confidence\"]
            allocation = \"AGGRESSIVE\"
        elif confidence >= 0.75 and grade in [\"A+\", \"A\"]:
            risk_pct = config.POSITION_RISK[\"A_high_confidence\"]
            allocation = \"STANDARD+\"
        elif confidence >= 0.65:
            risk_pct = config.POSITION_RISK[\"standard\"]
            allocation = \"STANDARD\"
        else:
            risk_pct = config.POSITION_RISK[\"conservative\"]
            allocation = \"CONSERVATIVE\"
        
        position_risk = account_size * risk_pct
        # Ensure even number of contracts for 50% scaling
        contracts = max(2, int(position_risk / (risk_per_share * 100)))
        if contracts % 2 != 0:
            contracts += 1

        return {
            \"contracts\": contracts,
            \"risk_dollars\": position_risk,
            \"risk_percentage\": risk_pct * 100,
            \"allocation_type\": allocation
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
                     contracts: int = 2) -> int:
        \"\"\"
        Open a new position and return position ID
        \"\"\"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(\"\"\"
            INSERT INTO positions 
            (ticker, direction, entry_price, stop_price, t1_price, t2_price, 
             contracts, remaining_contracts, grade, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        \"\"\", (ticker, direction, entry, stop, t1, t2, contracts, contracts, grade, confidence))
        
        position_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        print(f\"[POSITION] Opened {ticker} {direction.upper()} - ID: {position_id}\")
        print(f\" Entry: ${entry:.2f} | Stop: ${stop:.2f} | T1: ${t1:.2f} | T2: ${t2:.2f}\")
        print(f\" Contracts: {contracts} | Grade: {grade} | Confidence: {confidence:.1%}\")
        
        return position_id
    
    def check_exits(self, current_prices: Dict[str, float]):
        \"\"\"
        Check all open positions for stop/target hits with scaling logic
        \"\"\"
        open_positions = self.get_open_positions()
        
        for pos in open_positions:
            ticker = pos[\"ticker\"]
            if ticker not in current_prices:
                continue
            
            current_price = current_prices[ticker]
            direction = pos[\"direction\"]
            stop = pos[\"stop\"]
            t1 = pos[\"t1\"]
            t2 = pos[\"t2\"]
            entry = pos[\"entry\"]
            t1_hit = pos.get(\"t1_hit\", False)
            
            if direction == \"bull\":
                # Check Stop Loss
                if current_price <= stop:
                    self.close_position(pos[\"id\"], stop, \"STOP LOSS\")
                # Check Target 2
                elif current_price >= t2:
                    self.close_position(pos[\"id\"], t2, \"TARGET 2\")
                # Check Target 1 (only if not already hit)
                elif not t1_hit and current_price >= t1:
                    self.scale_out(pos[\"id\"], t1, \"TARGET 1\")
                    
            else: # bear
                if current_price >= stop:
                    self.close_position(pos[\"id\"], stop, \"STOP LOSS\")
                elif current_price <= t2:
                    self.close_position(pos[\"id\"], t2, \"TARGET 2\")
                elif not t1_hit and current_price <= t1:
                    self.scale_out(pos[\"id\"], t1, \"TARGET 1\")

    def scale_out(self, position_id: int, price: float, reason: str):
        \"\"\"Sell 50% of position and move stop to break even\"\"\"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(\"SELECT ticker, direction, entry_price, remaining_contracts FROM positions WHERE id = ?\", (position_id,))
        ticker, direction, entry, remaining = cursor.fetchone()
        
        sell_count = remaining // 2
        new_remaining = remaining - sell_count
        
        # Calculate P&L for the half sold
        pnl = (price - entry if direction == \"bull\" else entry - price) * 100 * sell_count
        
        cursor.execute(\"\"\"
            UPDATE positions 
            SET remaining_contracts = ?, 
                stop_price = entry_price, 
                t1_hit = 1,
                pnl = pnl + ?
            WHERE id = ?
        \"\"\", (new_remaining, pnl, position_id))
        
        conn.commit()
        conn.close()
        
        print(f\"[SCALING] Scaled out 50% ({sell_count} contracts) of {ticker} at ${price:.2f} ({reason})\")
        print(f\"[SCALING] Stop moved to break even at ${entry:.2f}. Remaining: {new_remaining}\")

    def close_position(self, position_id: int, exit_price: float, exit_reason: str):
        \"\"\"Close remaining position and finalize P&L\"\"\"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(\"SELECT ticker, direction, entry_price, remaining_contracts, grade, confidence, pnl FROM positions WHERE id = ?\", (position_id,))
        row = cursor.fetchone()
        if not row: return
        
        ticker, direction, entry, remaining, grade, confidence, current_pnl = row
        
        # Calculate P&L for remaining
        pnl_final = (exit_price - entry if direction == \"bull\" else entry - exit_price) * 100 * remaining
        total_pnl = current_pnl + pnl_final
        
        cursor.execute(\"\"\"
            UPDATE positions 
            SET exit_price = ?, exit_reason = ?, pnl = ?, 
                exit_time = CURRENT_TIMESTAMP, status = 'CLOSED', remaining_contracts = 0
            WHERE id = ?
        \"\"\", (exit_price, exit_reason, total_pnl, position_id))
        
        conn.commit()
        conn.close()
        
        win_loss = \"✅ WIN\" if total_pnl > 0 else \"❌ LOSS\"
        print(f\"\
[EXIT] {win_loss} - {ticker} {direction.upper()} ({exit_reason})\")
        print(f\" Total P&L: ${total_pnl:+.2f} | Final Exit: ${exit_price:.2f}\")
        
        # Record to AI learning
        try:
            from ai_learning import learning_engine
            learning_engine.record_trade({
                \"ticker\": ticker, \"direction\": direction, \"entry\": entry,
                \"exit\": exit_price, \"pnl\": total_pnl, \"grade\": grade,
                \"confidence\": confidence, \"exit_reason\": exit_reason
            })
        except: pass

    def get_open_positions(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(\"SELECT * FROM positions WHERE status = 'OPEN'\")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Map DB keys to internal keys
        for r in rows:
            r['entry'] = r['entry_price']
            r['stop'] = r['stop_price']
            r['t1'] = r['t1_price']
            r['t2'] = r['t2_price']
        return rows

    def get_daily_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        today = datetime.now().strftime(\"%Y-%m-%d\")
        cursor.execute(\"\"\"
            SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), COALESCE(SUM(pnl), 0)
            FROM positions WHERE DATE(entry_time) = ? AND status = 'CLOSED'
        \"\"\", (today,))
        row = cursor.fetchone()
        conn.close()
        return {\"trades\": row[0] or 0, \"wins\": row[1] or 0, \"total_pnl\": row[2] or 0}

# Global instance
position_manager = PositionManager()
