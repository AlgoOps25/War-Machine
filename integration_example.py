"""Complete integration examples for War Machine analytics system."""

# ============================================================================
# EXAMPLE 1: Minimal Integration (3 Lines)
# ============================================================================

from signal_analytics_integration import log_signal, log_fill, log_close

def minimal_integration_example():
    """Simplest possible integration."""
    
    # When you detect a signal:
    signal_id = log_signal(
        ticker="AAPL",
        direction="BULL",
        grade="A",
        confidence=75,
        entry=150.00,
        stop=148.50,
        t1=152.00,
        t2=154.00
    )
    
    # When position is filled:
    log_fill(signal_id)
    
    # When position closes:
    log_close(signal_id, exit_price=152.50, outcome='win')


# ============================================================================
# EXAMPLE 2: Signal Generator Integration
# ============================================================================

def signal_generator_integration():
    """
    Integration pattern for signal_generator.py.
    
    Add this to your existing check_ticker() method.
    """
    
    # Your existing code:
    signal = {
        'ticker': 'AAPL',
        'signal': 'BUY',
        'entry': 150.00,
        'stop': 148.50,
        'target': 154.00,
        'confidence': 75,
        'grade': 'A'
    }
    
    # ⭐ ADD THIS:
    from signal_analytics_integration import analytics_logger
    
    signal_id = analytics_logger.log_signal_generated(
        ticker=signal['ticker'],
        direction='BULL' if signal['signal'] == 'BUY' else 'BEAR',
        grade=signal.get('grade', 'A'),
        confidence=signal['confidence'] / 100.0,  # Convert to 0-1
        entry_price=signal['entry'],
        stop_price=signal['stop'],
        t1_price=signal.get('t1', signal['target']),
        t2_price=signal.get('t2', signal['target'])
    )
    
    # Store signal_id for later tracking
    signal['signal_id'] = signal_id
    
    return signal


# ============================================================================
# EXAMPLE 3: Position Manager Integration
# ============================================================================

def position_manager_integration():
    """
    Integration pattern for position_manager.py.
    
    Add this to your open_position() and close_position() methods.
    """
    
    from signal_analytics_integration import analytics_logger
    
    # ───────────────────────────────────────────────────────────────────────
    # In open_position() method:
    # ───────────────────────────────────────────────────────────────────────
    
    def open_position(ticker, entry_price, signal_id=None, **kwargs):
        """Open position with analytics tracking."""
        
        # Your existing position opening code
        position_id = insert_into_database(...)
        
        # ⭐ ADD THIS:
        if signal_id:
            analytics_logger.log_signal_filled(signal_id)
        
        return position_id
    
    # ───────────────────────────────────────────────────────────────────────
    # In close_position() method:
    # ───────────────────────────────────────────────────────────────────────
    
    def close_position(position_id, exit_price, exit_reason):
        """Close position with analytics tracking."""
        
        # Get signal_id from position (if you stored it)
        signal_id = get_signal_id_from_position(position_id)
        
        # Calculate P&L
        pnl = calculate_pnl(...)
        outcome = 'win' if pnl > 0 else 'loss'
        
        # Your existing position closing code
        update_position_status(...)
        
        # ⭐ ADD THIS:
        if signal_id:
            analytics_logger.log_signal_closed(
                signal_id=signal_id,
                exit_price=exit_price,
                outcome=outcome
            )
        
        return pnl


# ============================================================================
# EXAMPLE 4: Full Workflow Integration
# ============================================================================

def full_workflow_example():
    """
    Complete workflow from signal to close.
    """
    
    from signal_analytics_integration import analytics_logger
    
    # ───────────────────────────────────────────────────────────────────────
    # STEP 1: Signal Detection
    # ───────────────────────────────────────────────────────────────────────
    
    # Your breakout detector finds a signal
    ticker = "TSLA"
    direction = "BULL"
    entry = 250.00
    stop = 247.00
    t1 = 254.00
    t2 = 258.00
    grade = "A+"
    confidence = 85
    
    # Log signal generation
    signal_id = analytics_logger.log_signal_generated(
        ticker=ticker,
        direction=direction,
        grade=grade,
        confidence=confidence / 100.0,
        entry_price=entry,
        stop_price=stop,
        t1_price=t1,
        t2_price=t2
    )
    
    print(f"[ANALYTICS] Signal logged: {signal_id}")
    
    # ───────────────────────────────────────────────────────────────────────
    # STEP 2: Position Fill
    # ───────────────────────────────────────────────────────────────────────
    
    # Position gets filled at entry price
    analytics_logger.log_signal_filled(signal_id)
    
    print(f"[ANALYTICS] Signal filled: {signal_id}")
    
    # ───────────────────────────────────────────────────────────────────────
    # STEP 3: Position Close
    # ───────────────────────────────────────────────────────────────────────
    
    # Position closes at T1 (winner)
    exit_price = 254.50
    outcome = 'win'
    
    analytics_logger.log_signal_closed(
        signal_id=signal_id,
        exit_price=exit_price,
        outcome=outcome
    )
    
    print(f"[ANALYTICS] Signal closed: {signal_id} | {outcome.upper()}")


# ============================================================================
# EXAMPLE 5: Error Handling
# ============================================================================

def error_handling_example():
    """
    Proper error handling for analytics integration.
    """
    
    from signal_analytics_integration import analytics_logger
    
    try:
        signal_id = analytics_logger.log_signal_generated(
            ticker="AAPL",
            direction="BULL",
            grade="A",
            confidence=0.75,
            entry_price=150.00,
            stop_price=148.50,
            t1_price=152.00,
            t2_price=154.00
        )
        
        return signal_id
    
    except Exception as e:
        # Analytics should never break your trading system
        print(f"[ANALYTICS] Error logging signal: {e}")
        # Continue without analytics
        return None


# ============================================================================
# EXAMPLE 6: Batch Signal Updates
# ============================================================================

def batch_update_example():
    """
    Update multiple signals at once (EOD cleanup).
    """
    
    from signal_analytics_integration import analytics_logger
    
    # Your open positions
    open_positions = [
        {'signal_id': 'AAPL_20250226_093015', 'exit_price': 151.50, 'pnl': 150},
        {'signal_id': 'TSLA_20250226_093120', 'exit_price': 248.00, 'pnl': -200},
        {'signal_id': 'NVDA_20250226_093245', 'exit_price': 890.00, 'pnl': 350},
    ]
    
    # Close all positions at EOD
    for position in open_positions:
        outcome = 'win' if position['pnl'] > 0 else 'loss'
        
        analytics_logger.log_signal_closed(
            signal_id=position['signal_id'],
            exit_price=position['exit_price'],
            outcome=outcome
        )


# ============================================================================
# EXAMPLE 7: Custom Analysis Query
# ============================================================================

def custom_analysis_example():
    """
    Custom queries on your analytics data.
    """
    
    import sqlite3
    import pandas as pd
    
    # Connect to database
    conn = sqlite3.connect('signal_analytics.db')
    
    # Example: Get all A+ signals from last 7 days
    query = """
    SELECT 
        ticker,
        direction,
        confidence,
        outcome,
        return_pct,
        hold_time_minutes
    FROM signals
    WHERE grade = 'A+'
    AND DATE(generated_at) >= DATE('now', '-7 days')
    AND outcome IN ('win', 'loss')
    ORDER BY generated_at DESC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Calculate custom metrics
    win_rate = (df['outcome'] == 'win').sum() / len(df) * 100
    avg_return = df['return_pct'].mean()
    avg_hold = df['hold_time_minutes'].mean()
    
    print(f"A+ Signals (Last 7 Days):")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Avg Return: {avg_return:+.2f}%")
    print(f"  Avg Hold Time: {avg_hold:.0f} minutes")
    
    return df


# ============================================================================
# EXAMPLE 8: Real-Time Performance Tracking
# ============================================================================

def real_time_tracking_example():
    """
    Track performance during trading session.
    """
    
    import sqlite3
    from datetime import datetime
    
    def get_session_stats():
        """Get today's performance in real-time."""
        
        conn = sqlite3.connect('signal_analytics.db')
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Query today's closed signals
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                AVG(return_pct) as avg_return,
                SUM(return_pct) as total_return
            FROM signals
            WHERE DATE(generated_at) = ?
            AND outcome IN ('win', 'loss')
        """, (today,))
        
        row = cursor.fetchone()
        conn.close()
        
        total, wins, losses, avg_return, total_return = row
        win_rate = (wins / total * 100) if total > 0 else 0
        
        return {
            'total': total or 0,
            'wins': wins or 0,
            'losses': losses or 0,
            'win_rate': win_rate,
            'avg_return': avg_return or 0,
            'total_return': total_return or 0
        }
    
    # Usage in your trading loop
    stats = get_session_stats()
    print(f"Session: {stats['wins']}W / {stats['losses']}L | "
          f"Win Rate: {stats['win_rate']:.1f}% | "
          f"Total Return: {stats['total_return']:+.2f}%")


if __name__ == "__main__":
    print("War Machine Analytics - Integration Examples\n")
    print("See function docstrings for detailed integration patterns.\n")
    
    # Run examples
    print("[1] Minimal Integration Example")
    minimal_integration_example()
    
    print("\n[2] Full Workflow Example")
    full_workflow_example()
    
    print("\n[3] Real-Time Tracking Example")
    real_time_tracking_example()
