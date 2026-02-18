"""
PostgreSQL Database Setup
Migrates from SQLite to PostgreSQL for better performance
"""

import os
import psycopg2
from psycopg2 import sql
from datetime import datetime
from typing import List, Dict


class DatabaseManager:
    def __init__(self):
        # Railway provides DATABASE_URL environment variable
        self.db_url = os.getenv("DATABASE_URL")
        
        if not self.db_url:
            print("⚠️ DATABASE_URL not set, using SQLite fallback")
            self.use_postgres = False
        else:
            self.use_postgres = True
            self.conn = None
    
    def connect(self):
        """Establish PostgreSQL connection."""
        if not self.use_postgres:
            return
        
        try:
            self.conn = psycopg2.connect(self.db_url)
            print("✅ PostgreSQL connected")
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            self.use_postgres = False
    
    def create_tables(self):
        """Create all necessary tables."""
        if not self.use_postgres:
            return
        
        cursor = self.conn.cursor()
        
        # Bars table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bars (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                datetime TIMESTAMP NOT NULL,
                open DECIMAL(10, 2),
                high DECIMAL(10, 2),
                low DECIMAL(10, 2),
                close DECIMAL(10, 2),
                volume BIGINT,
                timeframe VARCHAR(5) DEFAULT '1m',
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(ticker, datetime, timeframe)
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bars_ticker_datetime 
            ON bars(ticker, datetime DESC);
        """)
        
        # Signals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                signal_time TIMESTAMP NOT NULL,
                direction VARCHAR(10) NOT NULL,
                grade VARCHAR(5) NOT NULL,
                confidence DECIMAL(5, 4),
                entry DECIMAL(10, 2),
                stop DECIMAL(10, 2),
                t1 DECIMAL(10, 2),
                t2 DECIMAL(10, 2),
                or_high DECIMAL(10, 2),
                or_low DECIMAL(10, 2),
                fvg_low DECIMAL(10, 2),
                fvg_high DECIMAL(10, 2),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                signal_id INTEGER REFERENCES signals(id),
                ticker VARCHAR(10) NOT NULL,
                direction VARCHAR(10) NOT NULL,
                entry DECIMAL(10, 2),
                exit DECIMAL(10, 2),
                stop DECIMAL(10, 2),
                contracts INTEGER,
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                exit_reason VARCHAR(50),
                pnl DECIMAL(10, 2),
                grade VARCHAR(5),
                confidence DECIMAL(5, 4),
                hold_duration_minutes DECIMAL(10, 2),
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Performance metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL UNIQUE,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate DECIMAL(5, 2),
                total_pnl DECIMAL(10, 2),
                max_drawdown DECIMAL(5, 2),
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        self.conn.commit()
        cursor.close()
        
        print("✅ PostgreSQL tables created")
    
    def insert_bars(self, ticker: str, bars: List[Dict]):
        """Insert bars into PostgreSQL."""
        if not self.use_postgres:
            return
        
        cursor = self.conn.cursor()
        
        for bar in bars:
            try:
                cursor.execute("""
                    INSERT INTO bars (ticker, datetime, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, datetime, timeframe) DO NOTHING
                """, (
                    ticker,
                    bar["datetime"],
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar["volume"]
                ))
            except Exception as e:
                print(f"Error inserting bar: {e}")
                continue
        
        self.conn.commit()
        cursor.close()
    
    def get_bars(self, ticker: str, limit: int = 300) -> List[Dict]:
        """Retrieve bars from PostgreSQL."""
        if not self.use_postgres:
            return []
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT datetime, open, high, low, close, volume
            FROM bars
            WHERE ticker = %s
            ORDER BY datetime DESC
            LIMIT %s
        """, (ticker, limit))
        
        rows = cursor.fetchall()
        cursor.close()
        
        bars = []
        for row in rows:
            bars.append({
                "datetime": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5])
            })
        
        # Return in chronological order
        return list(reversed(bars))
    
    def insert_signal(self, signal: Dict) -> int:
        """Insert a detected signal."""
        if not self.use_postgres:
            return -1
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO signals (
                ticker, signal_time, direction, grade, confidence,
                entry, stop, t1, t2, or_high, or_low, fvg_low, fvg_high
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            signal["ticker"],
            signal["signal_time"],
            signal["direction"],
            signal["grade"],
            signal["confidence"],
            signal["entry"],
            signal["stop"],
            signal["t1"],
            signal["t2"],
            signal["or_high"],
            signal["or_low"],
            signal["fvg_low"],
            signal["fvg_high"]
        ))
        
        signal_id = cursor.fetchone()[0]
        self.conn.commit()
        cursor.close()
        
        return signal_id
    
    def insert_trade(self, trade: Dict):
        """Insert a completed trade."""
        if not self.use_postgres:
            return
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO trades (
                signal_id, ticker, direction, entry, exit, stop, contracts,
                entry_time, exit_time, exit_reason, pnl, grade, confidence,
                hold_duration_minutes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            trade.get("signal_id"),
            trade["ticker"],
            trade["direction"],
            trade["entry"],
            trade["exit"],
            trade["stop"],
            trade["contracts"],
            trade["entry_time"],
            trade["exit_time"],
            trade["exit_reason"],
            trade["pnl"],
            trade["grade"],
            trade["confidence"],
            trade.get("hold_duration_minutes", 0)
        ))
        
        self.conn.commit()
        cursor.close()
    
    def get_daily_performance(self, date: str = None) -> Dict:
        """Get performance metrics for a specific date."""
        if not self.use_postgres:
            return {}
        
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl
            FROM trades
            WHERE DATE(entry_time) = %s
        """, (date,))
        
        row = cursor.fetchone()
        cursor.close()
        
        if row and row[0] > 0:
            win_rate = (row[1] / row[0]) * 100 if row[0] > 0 else 0
            return {
                "date": date,
                "total_trades": row[0],
                "wins": row[1],
                "losses": row[2],
                "win_rate": round(win_rate, 2),
                "total_pnl": float(row[3])
            }
        
        return {
            "date": date,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0
        }
    
    def get_win_rate_by_grade(self) -> Dict:
        """Get win rate breakdown by signal grade."""
        if not self.use_postgres:
            return {}
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                grade,
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as total_pnl
            FROM trades
            WHERE grade IS NOT NULL
            GROUP BY grade
            ORDER BY grade
        """)
        
        rows = cursor.fetchall()
        cursor.close()
        
        results = {}
        for row in rows:
            grade = row[0]
            total = row[1]
            wins = row[2]
            pnl = float(row[3])
            
            results[grade] = {
                "total": total,
                "wins": wins,
                "win_rate": (wins / total * 100) if total > 0 else 0,
                "total_pnl": pnl
            }
        
        return results
    
    def close(self):
        """Close database connection."""
        if self.use_postgres and self.conn:
            self.conn.close()
            print("PostgreSQL connection closed")


# Initialize and setup
def setup_database():
    """Initialize PostgreSQL database."""
    db = DatabaseManager()
    db.connect()
    
    if db.use_postgres:
        db.create_tables()
        print("✅ Database setup complete")
    else:
        print("⚠️ Running without PostgreSQL")
    
    return db


# Global instance
db_manager = None

def get_db():
    """Get or create database manager instance."""
    global db_manager
    if db_manager is None:
        db_manager = setup_database()
    return db_manager
