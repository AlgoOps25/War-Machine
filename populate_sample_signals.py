"""Generate sample signals for testing the analysis pipeline."""

import sqlite3
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def generate_sample_signals(num_signals=50):
    """Generate sample signals with realistic patterns."""
    
    conn = sqlite3.connect('signal_analytics.db')
    cursor = conn.cursor()
    
    tickers = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'GOOGL', 'AMZN', 'AMD']
    grades = ['A+', 'A', 'A-']
    directions = ['BULL', 'BEAR']
    
    print(f"Generating {num_signals} sample signals...")
    
    for i in range(num_signals):
        ticker = random.choice(tickers)
        direction = random.choice(directions)
        grade = random.choice(grades)
        
        # Grade affects win probability
        grade_win_prob = {'A+': 0.70, 'A': 0.60, 'A-': 0.50}
        is_winner = random.random() < grade_win_prob[grade]
        
        # Base price and volatility
        base_price = random.uniform(100, 500)
        confidence = random.uniform(0.65, 0.95)
        
        # Generate timestamps
        days_ago = random.randint(1, 30)
        generated_at = datetime.now(ET) - timedelta(days=days_ago, hours=random.randint(0, 6))
        
        # Entry price (slightly above breakout for bulls, below for bears)
        entry_price = base_price * (1.0015 if direction == 'BULL' else 0.9985)
        
        # Stop and targets
        atr = base_price * 0.02  # 2% ATR
        if direction == 'BULL':
            stop_price = entry_price - (1.5 * atr)
            t1_price = entry_price + (2.0 * atr)
            t2_price = entry_price + (3.5 * atr)
        else:
            stop_price = entry_price + (1.5 * atr)
            t1_price = entry_price - (2.0 * atr)
            t2_price = entry_price - (3.5 * atr)
        
        # Determine outcome
        if is_winner:
            outcome = 'win'
            # Winners hit T1 or T2
            if random.random() < 0.7:  # 70% hit T1
                exit_price = t1_price
                hold_minutes = random.randint(15, 120)  # 15 min to 2 hours
            else:  # 30% hit T2
                exit_price = t2_price
                hold_minutes = random.randint(60, 240)  # 1-4 hours
        else:
            outcome = 'loss'
            # Losers hit stop
            exit_price = stop_price
            # Immediate failures (within 5-15 min) are common
            if random.random() < 0.65:  # 65% fail quickly
                hold_minutes = random.randint(2, 15)
            else:  # 35% fail later
                hold_minutes = random.randint(20, 90)
        
        # Calculate return
        if direction == 'BULL':
            return_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            return_pct = ((entry_price - exit_price) / entry_price) * 100
        
        # Timestamps
        filled_at = generated_at + timedelta(minutes=random.randint(1, 5))
        closed_at = filled_at + timedelta(minutes=hold_minutes)
        
        signal_id = f"{ticker}_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        
        # Insert signal
        cursor.execute("""
            INSERT INTO signals (
                signal_id, ticker, direction, grade, confidence,
                generated_at, filled_at, closed_at, signal_time,
                entry_price, stop_price, t1_price, t2_price,
                outcome, return_pct, hold_time_minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id, ticker, direction, grade, confidence,
            generated_at.isoformat(), filled_at.isoformat(), closed_at.isoformat(), generated_at.isoformat(),
            entry_price, stop_price, t1_price, t2_price,
            outcome, return_pct, hold_minutes
        ))
        
        if (i + 1) % 10 == 0:
            print(f"  Generated {i + 1}/{num_signals} signals...")
    
    conn.commit()
    
    # Print summary
    cursor.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'win'")
    wins = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'loss'")
    losses = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"\n✅ Sample data created!")
    print(f"   Total Signals: {num_signals}")
    print(f"   Wins: {wins} ({wins/num_signals*100:.1f}%)")
    print(f"   Losses: {losses} ({losses/num_signals*100:.1f}%)")
    print(f"\nReady to run analysis: python run_full_analysis.py\n")


if __name__ == "__main__":
    generate_sample_signals(50)
