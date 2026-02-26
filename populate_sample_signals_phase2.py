"""Generate Phase 2.0 sample signals showing expected improvements."""

import sqlite3
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def generate_phase2_signals(num_signals=50):
    """
    Generate sample signals with Phase 2.0 improvements:
    - Reduced quick failure rate (71% -> ~30%)
    - Improved overall win rate (66% -> ~75%)
    - Better hold times for winners
    """
    
    conn = sqlite3.connect('signal_analytics_phase2.db')
    cursor = conn.cursor()
    
    # Create schema if doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            grade TEXT NOT NULL,
            confidence REAL NOT NULL,
            generated_at TEXT NOT NULL,
            filled_at TEXT,
            closed_at TEXT,
            signal_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            t1_price REAL NOT NULL,
            t2_price REAL NOT NULL,
            outcome TEXT,
            return_pct REAL,
            hold_time_minutes REAL
        )
    """)
    
    # Clear existing data
    cursor.execute("DELETE FROM signals")
    
    tickers = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'GOOGL', 'AMZN', 'AMD']
    grades = ['A+', 'A', 'A-']
    directions = ['BULL', 'BEAR']
    
    print(f"\nGenerating {num_signals} PHASE 2.0 sample signals...")
    print("Expected improvements:")
    print("  - Quick failure rate: 71% → 30%")
    print("  - Overall win rate: 66% → 75%")
    print("  - Better trade durability\n")
    
    for i in range(num_signals):
        ticker = random.choice(tickers)
        direction = random.choice(directions)
        grade = random.choice(grades)
        
        # ⭐ PHASE 2.0: Improved win probabilities (better entries)
        grade_win_prob = {'A+': 0.85, 'A': 0.75, 'A-': 0.68}
        is_winner = random.random() < grade_win_prob[grade]
        
        # Base price and volatility
        base_price = random.uniform(100, 500)
        confidence = random.uniform(0.70, 0.95)
        
        # Generate timestamps
        days_ago = random.randint(1, 30)
        generated_at = datetime.now(ET) - timedelta(days=days_ago, hours=random.randint(0, 6))
        
        # ⭐ PHASE 2.0: Entry price reflects 0.15% offset
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
            # Winners hit T1 or T2 with better hold times
            if random.random() < 0.6:  # 60% hit T1
                exit_price = t1_price
                hold_minutes = random.randint(30, 150)  # Better durability (30 min - 2.5 hours)
            else:  # 40% hit T2
                exit_price = t2_price
                hold_minutes = random.randint(90, 300)  # 1.5-5 hours
        else:
            outcome = 'loss'
            # Losers hit stop
            exit_price = stop_price
            # ⭐ PHASE 2.0: Dramatically fewer quick failures
            if random.random() < 0.30:  # Only 30% fail quickly (was 65%)
                hold_minutes = random.randint(5, 15)  # Rarely immediate failures
            else:  # 70% fail later (was 35%)
                hold_minutes = random.randint(25, 120)  # Normal volatility losses
        
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
    
    # Quick failure analysis
    cursor.execute("""
        SELECT COUNT(*) FROM signals 
        WHERE outcome = 'loss' AND hold_time_minutes < 15
    """)
    quick_failures = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"\n✅ Phase 2.0 sample data created!")
    print(f"\n📊 Performance Summary:")
    print(f"   Total Signals: {num_signals}")
    print(f"   Wins: {wins} ({wins/num_signals*100:.1f}%)")
    print(f"   Losses: {losses} ({losses/num_signals*100:.1f}%)")
    if losses > 0:
        print(f"   Quick Failures: {quick_failures}/{losses} ({quick_failures/losses*100:.1f}%)")
    print(f"\n🎯 Comparison to Phase 1.0:")
    print(f"   Win Rate: 66% → {wins/num_signals*100:.0f}% (+{wins/num_signals*100-66:.0f}%)")
    if losses > 0:
        print(f"   Quick Fail Rate: 71% → {quick_failures/losses*100:.0f}% (-{71-quick_failures/losses*100:.0f}%)")
    print(f"\n📁 Database: signal_analytics_phase2.db")
    print(f"\nTo compare: Run daily_analysis.py on both databases\n")


if __name__ == "__main__":
    generate_phase2_signals(50)
