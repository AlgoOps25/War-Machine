"""
SQL INJECTION PREVENTION MODULE
Provides safe SQL query execution with parameterized queries

CRITICAL SECURITY FIX #3:
- Replaces all f-string SQL queries with parameterized versions
- Prevents SQL injection attacks through user input
- Maintains compatibility with existing code patterns

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
        """Add ORDER BY clause"""
        self._order_by = order
        return self
    
    def limit(self, limit: int):
        """Add LIMIT"""
        self._limit = limit
        return self
    
    def offset(self, offset: int):
        """Add OFFSET"""
        self._offset = offset
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
    
    Args:
        conn: Database connection
    
    Returns:
        "?" for SQLite, "%s" for PostgreSQL
    """
    # Check if PostgreSQL
    if hasattr(conn, '_use_postgres') and conn._use_postgres:
        return "%s"
    # Check connection type
    if hasattr(conn, '__class__'):
        conn_type = conn.__class__.__name__.lower()
        if 'postgres' in conn_type or 'psycopg' in conn_type:
            return "%s"
    # Default to SQLite
    return "?"


if __name__ == "__main__":
    # Demo usage patterns
    print("=" * 80)
    print("SQL INJECTION PREVENTION MODULE - Usage Examples")
    print("=" * 80)
    
    # Example 1: Basic parameterized query
    print("\n1. Basic parameterized INSERT:")
    query = build_insert("trades", ["ticker", "price", "timestamp"])
    print(f"   Query: {query}")
    print(f"   Usage: safe_execute(cursor, query, ('AAPL', 150.25, datetime.now()))")
    
    # Example 2: Dictionary insert
    print("\n2. Dictionary-based INSERT:")
    print("   safe_insert_dict(cursor, 'trades', {")
    print("       'ticker': 'AAPL',")
    print("       'price': 150.25,")
    print("       'timestamp': datetime.now()")
    print("   })")
    
    # Example 3: Safe IN clause
    print("\n3. Safe IN clause:")
    tickers = ["AAPL", "MSFT", "GOOGL"]
    in_clause, params = safe_in_clause(tickers)
    print(f"   Tickers: {tickers}")
    print(f"   IN clause: ({in_clause})")
    print(f"   Query: SELECT * FROM trades WHERE ticker IN ({in_clause})")
    print(f"   Params: {params}")
    
    # Example 4: Query builder
    print("\n4. Fluent query builder:")
    builder = SafeQueryBuilder("trades")
    builder.select(["ticker", "price"]) \
           .where("ticker = ?", "AAPL") \
           .order_by("timestamp DESC") \
           .limit(10)
    query, params = builder.build()
    print(f"   Query: {query}")
    print(f"   Params: {params}")
    
    print("\n" + "=" * 80)
    print("✅ SQL Injection Prevention Module Ready")
    print("=" * 80)
