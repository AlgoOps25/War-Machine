"""
SQL INJECTION PREVENTION MODULE
Provides safe SQL query execution with parameterized queries

CRITICAL SECURITY FIX #3:
- Replaces all f-string SQL queries with parameterized versions
- Prevents SQL injection attacks through user input
- Maintains compatibility with existing code patterns

FIX (MAR 26, 2026): SafeQueryBuilder.order_by() raw-string injection
- ORDER BY clause was appended as an unsanitized f-string, inconsistent
  with the module's own purpose. Each token is now validated:
    column            → sanitize_table_name(column)
    column ASC/DESC   → sanitize_table_name(column) + direction whitelist
  Raises ValueError on any invalid token so callers fail loudly rather
  than silently passing attacker-controlled SQL into the query.

Usage:
    from app.data.sql_safe import safe_execute, safe_query, build_insert, build_update
    
    # Instead of:
    # cursor.execute(f"INSERT INTO table (col) VALUES ({value})")
    
    # Use:
    # safe_execute(cursor, "INSERT INTO table (col) VALUES (?)", (value,))
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)

# ── Module-level placeholder helper ───────────────────────────────────────────
# Reads USE_POSTGRES once at import time so pooled connections (which don't
# carry a reliable class name) always get the right placeholder character.
try:
    from app.data.db_connection import USE_POSTGRES as _USE_POSTGRES
except ImportError:
    _USE_POSTGRES = False

def ph() -> str:
    """
    Return the correct SQL placeholder for the active database backend.
    Use this everywhere instead of get_placeholder(conn).

    Returns:
        "%s" when PostgreSQL mode is active, "?" for SQLite.
    """
    return "%s" if _USE_POSTGRES else "?"


def safe_execute(cursor, query: str, params: Optional[Tuple] = None) -> None:
    """
    Execute a parameterized query safely.
    
    Args:
        cursor: Database cursor
        query: SQL query with ? or %s placeholders
        params: Tuple of parameters to bind
    
    Example:
        safe_execute(cursor, "INSERT INTO trades (ticker, price) VALUES (?, ?)", 
                    ("AAPL", 150.25))
    """
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
    except Exception as e:
        logger.error(f"SQL execution error: {e}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise


def safe_query(cursor, query: str, params: Optional[Tuple] = None) -> List[Any]:
    """
    Execute a parameterized SELECT query and return results.
    
    Args:
        cursor: Database cursor
        query: SQL query with ? or %s placeholders
        params: Tuple of parameters to bind
    
    Returns:
        List of result rows
    
    Example:
        results = safe_query(cursor, "SELECT * FROM trades WHERE ticker = ?", ("AAPL",))
    """
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"SQL query error: {e}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise


def build_insert(table: str, columns: List[str], placeholder: str = "?") -> str:
    """
    Build a safe parameterized INSERT statement.
    
    Args:
        table: Table name
        columns: List of column names
        placeholder: Parameter placeholder (? for SQLite, %s for PostgreSQL)
    
    Returns:
        SQL INSERT statement with placeholders
    
    Example:
        query = build_insert("trades", ["ticker", "price", "timestamp"])
        # Returns: "INSERT INTO trades (ticker, price, timestamp) VALUES (?, ?, ?)"
        safe_execute(cursor, query, ("AAPL", 150.25, datetime.now()))
    """
    cols = ", ".join(columns)
    placeholders = ", ".join([placeholder] * len(columns))
    return f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"


def build_update(table: str, columns: List[str], where_clause: str, 
                placeholder: str = "?") -> str:
    """
    Build a safe parameterized UPDATE statement.
    
    Args:
        table: Table name
        columns: List of column names to update
        where_clause: WHERE clause with placeholders
        placeholder: Parameter placeholder (? for SQLite, %s for PostgreSQL)
    
    Returns:
        SQL UPDATE statement with placeholders
    
    Example:
        query = build_update("trades", ["price", "status"], "ticker = ?")
        # Returns: "UPDATE trades SET price = ?, status = ? WHERE ticker = ?"
        safe_execute(cursor, query, (151.00, "closed", "AAPL"))
    """
    set_clause = ", ".join([f"{col} = {placeholder}" for col in columns])
    return f"UPDATE {table} SET {set_clause} WHERE {where_clause}"


def build_delete(table: str, where_clause: str) -> str:
    """
    Build a safe parameterized DELETE statement.
    
    Args:
        table: Table name
        where_clause: WHERE clause with placeholders
    
    Returns:
        SQL DELETE statement with placeholders
    
    Example:
        query = build_delete("trades", "ticker = ? AND status = ?")
        # Returns: "DELETE FROM trades WHERE ticker = ? AND status = ?"
        safe_execute(cursor, query, ("AAPL", "closed"))
    """
    return f"DELETE FROM {table} WHERE {where_clause}"


def safe_insert_dict(cursor, table: str, data: Dict[str, Any], 
                     placeholder: str = "?") -> None:
    """
    Insert a dictionary of data safely with automatic parameterization.
    
    Args:
        cursor: Database cursor
        table: Table name
        data: Dictionary mapping column names to values
        placeholder: Parameter placeholder (? for SQLite, %s for PostgreSQL)
    
    Example:
        safe_insert_dict(cursor, "trades", {
            "ticker": "AAPL",
            "price": 150.25,
            "timestamp": datetime.now()
        })
    """
    columns = list(data.keys())
    values = tuple(data.values())
    query = build_insert(table, columns, placeholder)
    safe_execute(cursor, query, values)


def safe_update_dict(cursor, table: str, data: Dict[str, Any], 
                     where_column: str, where_value: Any,
                     placeholder: str = "?") -> None:
    """
    Update using a dictionary of data safely with automatic parameterization.
    
    Args:
        cursor: Database cursor
        table: Table name
        data: Dictionary mapping column names to new values
        where_column: Column name for WHERE clause
        where_value: Value for WHERE clause
        placeholder: Parameter placeholder (? for SQLite, %s for PostgreSQL)
    
    Example:
        safe_update_dict(cursor, "trades", 
                        {"price": 151.00, "status": "closed"},
                        "ticker", "AAPL")
    """
    columns = list(data.keys())
    values = list(data.values())
    values.append(where_value)  # Add WHERE value at the end
    
    query = build_update(table, columns, f"{where_column} = {placeholder}", placeholder)
    safe_execute(cursor, query, tuple(values))


def sanitize_table_name(name: str) -> str:
    """
    Sanitize table/column names (not for parameterized queries, for dynamic table names).
    
    SECURITY NOTE: Only use this for table/column names, NEVER for values.
    Table names cannot be parameterized in SQL.
    
    Args:
        name: Table or column name
    
    Returns:
        Sanitized name (alphanumeric + underscore only)
    
    Raises:
        ValueError: If name contains invalid characters
    """
    # Only allow alphanumeric and underscore
    if not all(c.isalnum() or c == '_' for c in name):
        raise ValueError(f"Invalid table/column name: {name}")
    
    # Prevent SQL keywords (basic list)
    sql_keywords = {
        'select', 'insert', 'update', 'delete', 'drop', 'create', 
        'alter', 'truncate', 'union', 'where', 'from', 'join'
    }
    if name.lower() in sql_keywords:
        raise ValueError(f"SQL keyword not allowed as table/column name: {name}")
    
    return name


def sanitize_order_by(order: str) -> str:
    """
    Validate and sanitize an ORDER BY expression before embedding in SQL.

    FIX MAR 26, 2026: SafeQueryBuilder.order_by() previously accepted any
    raw string, creating an unsanitized injection path inconsistent with the
    rest of this module.

    Accepts comma-separated tokens of the form:
        column
        column ASC
        column DESC

    Each column part is validated via sanitize_table_name().
    Raises ValueError on any malformed token.

    Examples:
        sanitize_order_by("datetime DESC")        -> "datetime DESC"
        sanitize_order_by("ticker ASC, price DESC") -> "ticker ASC, price DESC"
        sanitize_order_by("1; DROP TABLE bars")   -> raises ValueError
    """
    _VALID_DIRECTIONS = {"ASC", "DESC"}
    sanitized_tokens = []

    for token in order.split(","):
        parts = token.strip().split()
        if len(parts) == 1:
            sanitized_tokens.append(sanitize_table_name(parts[0]))
        elif len(parts) == 2:
            col = sanitize_table_name(parts[0])
            direction = parts[1].upper()
            if direction not in _VALID_DIRECTIONS:
                raise ValueError(
                    f"Invalid ORDER BY direction '{parts[1]}' — must be ASC or DESC"
                )
            sanitized_tokens.append(f"{col} {direction}")
        else:
            raise ValueError(
                f"Invalid ORDER BY token '{token.strip()}' — "
                f"expected 'column' or 'column ASC/DESC'"
            )

    return ", ".join(sanitized_tokens)


def safe_in_clause(items: List[Any], placeholder: str = "?") -> Tuple[str, List[Any]]:
    """
    Build a safe IN clause for SQL queries.
    
    Args:
        items: List of items for IN clause
        placeholder: Parameter placeholder (? for SQLite, %s for PostgreSQL)
    
    Returns:
        Tuple of (placeholder string, flattened list of values)
    
    Example:
        tickers = ["AAPL", "MSFT", "GOOGL"]
        in_clause, params = safe_in_clause(tickers)
        # in_clause = "?, ?, ?"
        # params = ["AAPL", "MSFT", "GOOGL"]
        
        query = f"SELECT * FROM trades WHERE ticker IN ({in_clause})"
        results = safe_query(cursor, query, tuple(params))
    """
    placeholders = ", ".join([placeholder] * len(items))
    return placeholders, list(items)


class SafeQueryBuilder:
    """
    Fluent query builder with automatic parameterization.
    
    Example:
        builder = SafeQueryBuilder("trades")
        builder.select(["ticker", "price"]) \\
               .where("ticker = ?") \\
               .order_by("timestamp DESC") \\
               .limit(10)
        
        query, params = builder.build()
        results = safe_query(cursor, query, params)
    """
    
    def __init__(self, table: str, placeholder: str = "?"):
        self.table = sanitize_table_name(table)
        self.placeholder = placeholder
        self._select_cols = []
        self._where_clauses = []
        self._where_params = []
        self._order_by = None
        self._limit = None
        self._offset = None
    
    def select(self, columns: List[str]):
        """Add SELECT columns"""
        self._select_cols = [sanitize_table_name(col) for col in columns]
        return self
    
    def where(self, clause: str, *params):
        """Add WHERE clause with parameters"""
        self._where_clauses.append(clause)
        self._where_params.extend(params)
        return self
    
    def where_in(self, column: str, values: List[Any]):
        """Add WHERE IN clause"""
        column = sanitize_table_name(column)
        placeholders, params = safe_in_clause(values, self.placeholder)
        self._where_clauses.append(f"{column} IN ({placeholders})")
        self._where_params.extend(params)
        return self
    
    def order_by(self, order: str):
        """
        Add ORDER BY clause.

        FIX MAR 26, 2026: validates via sanitize_order_by() instead of
        embedding the raw string directly. Accepted format per token:
            column | column ASC | column DESC
        Raises ValueError on any malformed or injection-suspicious input.
        """
        self._order_by = sanitize_order_by(order)
        return self
    
    def limit(self, limit: int):
        """Add LIMIT"""
        self._limit = int(limit)  # int cast ensures no string injection
        return self
    
    def offset(self, offset: int):
        """Add OFFSET"""
        self._offset = int(offset)  # int cast ensures no string injection
        return self
    
    def build(self) -> Tuple[str, Tuple]:
        """Build the final query and parameters"""
        # SELECT
        cols = ", ".join(self._select_cols) if self._select_cols else "*"
        query = f"SELECT {cols} FROM {self.table}"
        
        # WHERE
        if self._where_clauses:
            query += " WHERE " + " AND ".join(self._where_clauses)
        
        # ORDER BY
        if self._order_by:
            query += f" ORDER BY {self._order_by}"
        
        # LIMIT
        if self._limit:
            query += f" LIMIT {self._limit}"
        
        # OFFSET
        if self._offset:
            query += f" OFFSET {self._offset}"
        
        return query, tuple(self._where_params)


# Convenience function for getting placeholder character
def get_placeholder(conn) -> str:
    """
    Get the correct placeholder character for the database connection.
    Delegates to ph() which reads USE_POSTGRES at module level — safe
    for pooled connections that don't carry a reliable class name.
    """
    return ph()


if __name__ == "__main__":
    # Demo usage patterns
    logger.info("=" * 80)
    logger.info("SQL INJECTION PREVENTION MODULE - Usage Examples")
    logger.info("=" * 80)
    
    # Example 1: Basic parameterized query
    logger.info("\n1. Basic parameterized INSERT:")
    query = build_insert("trades", ["ticker", "price", "timestamp"])
    logger.info(f"   Query: {query}")
    logger.info(f"   Usage: safe_execute(cursor, query, ('AAPL', 150.25, datetime.now()))")
    
    # Example 2: Dictionary insert
    logger.info("\n2. Dictionary-based INSERT:")
    logger.info("   safe_insert_dict(cursor, 'trades', {")
    logger.info("       'ticker': 'AAPL',")
    logger.info("       'price': 150.25,")
    logger.info("       'timestamp': datetime.now()")
    logger.info("   })")
    
    # Example 3: Safe IN clause
    logger.info("\n3. Safe IN clause:")
    tickers = ["AAPL", "MSFT", "GOOGL"]
    in_clause, params = safe_in_clause(tickers)
    logger.info(f"   Tickers: {tickers}")
    logger.info(f"   IN clause: ({in_clause})")
    logger.info(f"   Query: SELECT * FROM trades WHERE ticker IN ({in_clause})")
    logger.info(f"   Params: {params}")
    
    # Example 4: Query builder
    logger.info("\n4. Fluent query builder:")
    builder = SafeQueryBuilder("trades")
    builder.select(["ticker", "price"]) \
           .where("ticker = ?", "AAPL") \
           .order_by("timestamp DESC") \
           .limit(10)
    query, params = builder.build()
    logger.info(f"   Query: {query}")
    logger.info(f"   Params: {params}")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ SQL Injection Prevention Module Ready")
    logger.info("=" * 80)
