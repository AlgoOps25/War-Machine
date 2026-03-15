"""
sniper_log.py — Lightweight proposed-trade DB logger + validation stat reporters
Extracted from sniper.py so arm_signal.py can import it without
creating a circular dependency back into sniper.
"""

from datetime import datetime


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


def _get_signal_id(ticker: str, direction: str, price: float) -> str:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    return f"{ticker}_{direction}_{price:.2f}_{timestamp}"


def _track_validation_call(ticker: str, direction: str, price: float) -> bool:
    from app.core.thread_safe_state import get_state
    _state = get_state()
    signal_id = _get_signal_id(ticker, direction, price)
    call_count = _state.track_validation_call(signal_id)
    if call_count > 1:
        print(
            f"[VALIDATOR] ⚠️  WARNING: {ticker} validated {call_count} times "
            f"(possible duplicate call - signal_id: {signal_id})"
        )
        return True
    else:
        return False


def print_validation_stats(validator_enabled=True, validator_test_mode=False):
    if not validator_enabled:
        return
    from app.core.thread_safe_state import get_state
    _state = get_state()
    stats = _state.get_validator_stats()
    if stats['tested'] == 0:
        return
    total = stats['tested']
    pass_pct = (stats['passed'] / total * 100) if total > 0 else 0
    filter_pct = (stats['filtered'] / total * 100) if total > 0 else 0
    boost_pct = (stats['boosted'] / total * 100) if total > 0 else 0
    print("\n" + "="*80)
    print("VALIDATOR DAILY STATISTICS")
    print("="*80)
    print(f"Total Signals Tested: {total}")
    print(f"Passed: {stats['passed']} ({pass_pct:.1f}%)")
    print(f"Filtered: {stats['filtered']} ({filter_pct:.1f}%)")
    print(f"Confidence Boosted: {stats['boosted']} ({boost_pct:.1f}%)")
    print(f"Confidence Penalized: {stats['penalized']}")
    print("="*80)
    if validator_test_mode:
        print("⚠️  TEST MODE ACTIVE - Signals NOT being filtered")
    print("="*80 + "\n")


def print_validation_call_stats():
    from app.core.thread_safe_state import get_state
    _state = get_state()
    tracker = _state.get_validation_call_tracker()
    if not tracker:
        return
    total_signals = len(tracker)
    duplicate_calls = [
        (sig_id, count) for sig_id, count in tracker.items()
        if count > 1
    ]
    print("\n" + "="*80)
    print("VALIDATOR CALL TRACKING - DAILY STATISTICS")
    print("="*80)
    print(f"Total Unique Signals: {total_signals}")
    print(f"Signals with Duplicate Validations: {len(duplicate_calls)}")
    if duplicate_calls:
        print(f"\n⚠️  DUPLICATE VALIDATIONS DETECTED:")
        for sig_id, count in duplicate_calls:
            print(f"  • {sig_id}: validated {count} times")
        print(f"\n⚠️  Action required: Investigate duplicate validation calls")
    else:
        print(f"\n✅ No duplicate validations detected - all signals validated exactly once")
    print("="*80 + "\n")
