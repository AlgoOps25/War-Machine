"""
COMPATIBILITY STUB - Deprecated

Database connection utilities have been moved to utils/db_connection.py (Phase 2B).
This stub maintains backwards compatibility for any code that imports from db_connection.

New code should use:
    from utils import get_conn, ph, dict_cursor  # Convenience imports
    # OR
    from utils.db_connection import get_conn     # Direct import

This file can be safely deleted after verifying no external dependencies.

PHASE 2B: Organizational cleanup - separates utilities from business logic.
"""

from utils.db_connection import (
    get_conn,
    ph,
    dict_cursor,
    serial_pk,
    upsert_bar_sql,
    upsert_bar_5m_sql,
    upsert_metadata_sql,
    USE_POSTGRES,
    DATABASE_URL
)

__all__ = [
    'get_conn',
    'ph',
    'dict_cursor',
    'serial_pk',
    'upsert_bar_sql',
    'upsert_bar_5m_sql',
    'upsert_metadata_sql',
    'USE_POSTGRES',
    'DATABASE_URL'
]
