"""
Integration layer for War Machine signal analytics.
Logs signals from your trading system into signal_analytics.db
"""

import sqlite3
from datetime import datetime
from typing import Optional
import os

DB_PATH = "signal_analytics.db"

class SignalAnalyticsLogger:
    """Logs trading signals for analysis."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Ensure database exists."""
        if not os.path.exists(self.db_path):
            print(f"⚠️ Analytics database not found: {self.db_path}")
            print(f"   Run: python create_analytics_schema.py")
    
    def log_signal_generated(
        self,
        ticker: str,
        direction: str,
        grade: str,
        confidence: float,
        entry_price: float,
        stop_price: float,
        t1_price: float,
        t2_price: float
    ) -> str:
        """
        Log when a new signal is generated.
        
        Returns:
            signal_id: Unique identifier for this signal
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        signal_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        generated_at = datetime.now()
        
        cursor.execute("""
            INSERT INTO signals (
                signal_id, ticker, direction, grade, confidence,
                generated_at, signal_time, 
                entry_price, stop_price, t1_price, t2_price,
                outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            signal_id, ticker, direction, grade, confidence,
            generated_at.isoformat(), generated_at.isoformat(),
            entry_price, stop_price, t1_price, t2_price
        ))
        
        conn.commit()
        conn.close()
        
        print(f"[ANALYTICS] 📊 Signal logged: {signal_id}")
        return signal_id
    
    def log_signal_filled(self, signal_id: str, filled_at: Optional[datetime] = None):
        """Log when a signal is filled (position entered)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        filled_at = filled_at or datetime.now()
        
        cursor.execute("""
            UPDATE signals 
            SET filled_at = ?
            WHERE signal_id = ?
        """, (filled_at.isoformat(), signal_id))
        
        conn.commit()
        conn.close()
        
        print(f"[ANALYTICS] ✅ Signal filled: {signal_id}")
    
    def log_signal_closed(
        self,
        signal_id: str,
        exit_price: float,
        outcome: str,  # 'win' or 'loss'
        closed_at: Optional[datetime] = None
    ):
        """Log when a signal is closed (position exited)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get signal details
        cursor.execute("""
            SELECT entry_price, direction, filled_at 
            FROM signals 
            WHERE signal_id = ?
        """, (signal_id,))
        
        row = cursor.fetchone()
        if not row:
            print(f"[ANALYTICS] ⚠️ Signal not found: {signal_id}")
            conn.close()
            return
        
        entry_price, direction, filled_at = row
        closed_at = closed_at or datetime.now()
        
        # Calculate return percentage
        if direction == 'BULL':
            return_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # BEAR
            return_pct = ((entry_price - exit_price) / entry_price) * 100
        
        # Calculate hold time
        if filled_at:
            filled_dt = datetime.fromisoformat(filled_at)
            hold_minutes = (closed_at - filled_dt).total_seconds() / 60
        else:
            hold_minutes = 0
        
        # Update signal
        cursor.execute("""
            UPDATE signals 
            SET closed_at = ?, outcome = ?, return_pct = ?, hold_time_minutes = ?
            WHERE signal_id = ?
        """, (
            closed_at.isoformat(),
            outcome,
            return_pct,
            hold_minutes,
            signal_id
        ))
        
        conn.commit()
        conn.close()
        
        print(f"[ANALYTICS] 📈 Signal closed: {signal_id} | {outcome.upper()} | {return_pct:+.2f}% | {hold_minutes:.0f}m")


# Global instance
analytics_logger = SignalAnalyticsLogger()


# Convenience functions
def log_signal(ticker, direction, grade, confidence, entry, stop, t1, t2):
    """Quick function to log a new signal."""
    return analytics_logger.log_signal_generated(
        ticker, direction, grade, confidence, entry, stop, t1, t2
    )

def log_fill(signal_id):
    """Quick function to log signal fill."""
    analytics_logger.log_signal_filled(signal_id)

def log_close(signal_id, exit_price, outcome):
    """Quick function to log signal close."""
    analytics_logger.log_signal_closed(signal_id, exit_price, outcome)
