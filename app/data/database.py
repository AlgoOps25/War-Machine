"""
app/data/database.py  — Compatibility shim

This module is a thin re-export wrapper over app.data.db_connection,
which is the canonical pooled database layer for War Machine.

Why this exists
---------------
Two scripts call `get_db_connection()` / `close_db_connection()` from
this module (train_from_analytics.py, scripts/generate_ml_training_data.py).
Rather than deleting this file and breaking those callers, it is kept as a
shim so both import paths resolve to the same production connection pool.

Do NOT add new business logic here.  All logic lives in db_connection.py.
"""

from app.data.db_connection import (
    get_conn,
    return_conn,
    get_connection,       # context manager  (with get_connection() as conn:)
    check_pool_health,
    close_pool,
    ph,
    dict_cursor,
    serial_pk,
    USE_POSTGRES,
)


def get_db_connection():
    """
    Compatibility alias for app.data.db_connection.get_conn().

    Returns a pooled PostgreSQL connection (Railway) or a fresh SQLite
    connection (local dev).  Caller is responsible for returning the
    connection via close_db_connection() when finished.
    """
    return get_conn()


def close_db_connection(conn=None):
    """
    Compatibility alias for app.data.db_connection.return_conn().

    Returns *conn* to the pool (PostgreSQL) or closes it (SQLite).
    If called with no argument it is a no-op (legacy usage where the old
    module held a global singleton and close meant "mark as closed").
    """
    if conn is not None:
        return_conn(conn)


__all__ = [
    # Legacy API
    "get_db_connection",
    "close_db_connection",
    # Full db_connection API re-exported for convenience
    "get_conn",
    "return_conn",
    "get_connection",
    "check_pool_health",
    "close_pool",
    "ph",
    "dict_cursor",
    "serial_pk",
    "USE_POSTGRES",
]
