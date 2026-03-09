"""
PostgreSQL Database Helper - Fixes SQL Syntax Errors

This module provides PostgreSQL-compatible database operations.
Replaces SQLite-style `?` placeholders with PostgreSQL `%s` placeholders.
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class PostgreSQLHelper:
    """PostgreSQL database helper with proper error handling"""
    
    def __init__(self, connection_string: str):
        """Initialize with connection string"""
        self.connection_string = connection_string
        self._conn = None
    
    def get_connection(self):
        """Get or create database connection"""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                self.connection_string,
                cursor_factory=RealDictCursor
            )
        return self._conn
    
    def execute_query(self, query: str, params: Tuple = None) -> bool:
        """
        Execute a query (INSERT, UPDATE, DELETE)
        
        Args:
            query: SQL query with %s placeholders
            params: Tuple of parameters
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            if self._conn:
                self._conn.rollback()
            return False
    
    def fetch_all(self, query: str, params: Tuple = None) -> List[Dict]:
        """
        Fetch all rows from a SELECT query
        
        Args:
            query: SQL SELECT query with %s placeholders
            params: Tuple of parameters
        
        Returns:
            List[Dict]: List of rows as dictionaries
        """
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"SQL query error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            return []
    
    def fetch_one(self, query: str, params: Tuple = None) -> Optional[Dict]:
        """
        Fetch one row from a SELECT query
        
        Args:
            query: SQL SELECT query with %s placeholders
            params: Tuple of parameters
        
        Returns:
            Optional[Dict]: Row as dictionary or None
        """
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"SQL query error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            return None
    
    def close(self):
        """Close database connection"""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


class SignalPersistence:
    """Handles signal persistence with PostgreSQL"""
    
    def __init__(self, db: PostgreSQLHelper):
        self.db = db
    
    def cleanup_old_watching_signals(self, cutoff_time: datetime) -> bool:
        """
        Clean up old watching signals before cutoff time
        
        FIXED: Changed ? to %s for PostgreSQL
        """
        query = """
            DELETE FROM watching_signals_persist 
            WHERE breakout_bar_dt < %s
        """
        success = self.db.execute_query(query, (cutoff_time,))
        if success:
            logger.info(f"[WATCH-DB] Cleaned up signals before {cutoff_time}")
        else:
            logger.error(f"[WATCH-DB] Cleanup error")
        return success
    
    def load_watching_signals(self, trade_date: date) -> List[Dict]:
        """
        Load watching signals for a specific date
        
        FIXED: Changed ? to %s for PostgreSQL
        """
        query = """
            SELECT ticker, direction, breakout_bar_dt, or_high, or_low, signal_type
            FROM   watching_signals_persist
            WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = %s
        """
        
        signals = self.db.fetch_all(query, (trade_date,))
        if signals:
            logger.info(f"[WATCH-DB] Loaded {len(signals)} watching signals for {trade_date}")
        else:
            logger.info(f"[WATCH-DB] No watching signals found for {trade_date}")
        return signals
    
    def load_armed_signals(self, trade_date: date) -> List[Dict]:
        """
        Load armed signals for a specific date
        
        FIXED: Changed ? to %s for PostgreSQL
        """
        query = """
            SELECT ticker, position_id, direction, entry_price, stop_price, t1, t2,
                   confidence, grade, signal_type, validation_data
            FROM   armed_signals_persist
            WHERE  DATE(saved_at AT TIME ZONE 'America/New_York') = %s
        """
        
        signals = self.db.fetch_all(query, (trade_date,))
        if signals:
            logger.info(f"[ARMED-DB] Loaded {len(signals)} armed signals for {trade_date}")
        else:
            logger.info(f"[ARMED-DB] No armed signals found for {trade_date}")
        return signals
    
    def save_watching_signal(self, ticker: str, direction: str, breakout_bar_dt: datetime,
                            or_high: float, or_low: float, signal_type: str) -> bool:
        """
        Save a watching signal
        
        FIXED: Changed ? to %s for PostgreSQL
        """
        query = """
            INSERT INTO watching_signals_persist 
            (ticker, direction, breakout_bar_dt, or_high, or_low, signal_type, saved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (ticker, direction, breakout_bar_dt, or_high, or_low, signal_type, datetime.now())
        return self.db.execute_query(query, params)
    
    def save_armed_signal(self, ticker: str, position_id: str, direction: str,
                         entry_price: float, stop_price: float, t1: float, t2: float,
                         confidence: float, grade: str, signal_type: str, 
                         validation_data: Optional[Dict] = None) -> bool:
        """
        Save an armed signal
        
        FIXED: Changed ? to %s for PostgreSQL
        """
        query = """
            INSERT INTO armed_signals_persist 
            (ticker, position_id, direction, entry_price, stop_price, t1, t2,
             confidence, grade, signal_type, validation_data, saved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        import json
        params = (ticker, position_id, direction, entry_price, stop_price, t1, t2,
                 confidence, grade, signal_type, json.dumps(validation_data) if validation_data else None,
                 datetime.now())
        return self.db.execute_query(query, params)


# Migration utility
def convert_sqlite_to_postgres_placeholders(query: str) -> str:
    """
    Convert SQLite ? placeholders to PostgreSQL %s placeholders
    
    Args:
        query: SQL query with ? placeholders
    
    Returns:
        str: Query with %s placeholders
    """
    return query.replace('?', '%s')
