"""
sniper_log.py — Lightweight proposed-trade DB logger
Extracted from sniper.py so arm_signal.py can import it without
creating a circular dependency back into sniper.
"""


def log_proposed_trade(ticker, signal_type, direction, price, confidence, grade):
    """Insert one row into the proposed_trades table (best-effort, non-blocking)."""
    from app.data.db_connection import get_conn, return_conn, serial_pk
    from app.data.sql_safe import build_insert, safe_execute, get_placeholder

    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        p = get_placeholder(conn)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS proposed_trades (
                id {serial_pk()}, ticker TEXT, signal_type TEXT,
                direction TEXT, price REAL, confidence REAL, grade TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        query = build_insert(
            "proposed_trades",
            ["ticker", "signal_type", "direction", "price", "confidence", "grade"],
            p
        )
        safe_execute(cursor, query, (ticker, signal_type, direction, price, confidence, grade))
        conn.commit()
    except Exception as e:
        print(f"[TRACKER] Error: {e}")
    finally:
        if conn:
            return_conn(conn)
