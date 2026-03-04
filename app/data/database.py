"""
Database Connection Helper
Provides database connections for analytics and other modules
"""
import os
import psycopg2
import logging

_db_connection = None

def get_db_connection():
    """
    Get or create database connection
    Returns: psycopg2 connection object
    """
    global _db_connection
    
    if _db_connection is not None and not _db_connection.closed:
        return _db_connection
    
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    try:
        _db_connection = psycopg2.connect(db_url)
        logging.info("[DATABASE] Connection established")
        return _db_connection
    except Exception as e:
        logging.error(f"[DATABASE] Connection failed: {e}")
        raise

def close_db_connection():
    """
    Close database connection
    """
    global _db_connection
    if _db_connection is not None and not _db_connection.closed:
        _db_connection.close()
        logging.info("[DATABASE] Connection closed")
        _db_connection = None
