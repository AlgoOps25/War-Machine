"""
Generate synthetic trade logs for testing ML Confidence Booster.
Creates 100 realistic trades with proper schema and varied outcomes.
"""

import sqlite3
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DB_PATH = "marketmemory.db"

# Realistic ticker pool
TICKERS = ["TSLA", "NVDA", "AAPL", "MSFT", "AMD", "META", "GOOGL", "AMZN", 
           "SPY", "QQQ", "PLTR", "COIN", "SHOP", "NFLX", "DIS"]

SIGNAL_TYPES = ["gap_breakout", "volume_surge", "momentum", "reversal"]

def create_trade_logs_table():
    """Create trade_logs table with proper schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            exit_time TIMESTAMP NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            pnl REAL NOT NULL,
            win INTEGER NOT NULL,
            hold_minutes INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            entry_volume INTEGER,
            pdh REAL,
            pdl REAL,
            gap_pct REAL,
            vix_level REAL,
            time_since_open_min INTEGER,
            or_high REAL,
            or_low REAL,
            or_volume INTEGER,
            volume_surge_ratio REAL,
            price_vs_pdh REAL,
            price_vs_or_high REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print("[GEN] ✅ Created trade_logs table")

def generate_trade(base_time, ticker):
    """Generate one realistic trade."""
    
    # Entry time: random time during market hours over last 60 days
    days_ago = random.randint(1, 60)
    hour = random.randint(9, 15)
    minute = random.randint(0, 59)
    entry_time = (base_time - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    
    # Trade duration: 5-120 minutes
    hold_minutes = random.randint(5, 120)
    exit_time = entry_time + timedelta(minutes=hold_minutes)
    
    # Price action
    entry_price = random.uniform(50, 500)
    pdh = entry_price * random.uniform(0.98, 1.05)
    pdl = entry_price * random.uniform(0.92, 1.02)
    
    # Gap
    gap_pct = random.uniform(-5, 8)  # Bias toward gap ups
    
    # OR levels
    or_high = entry_price * random.uniform(0.995, 1.02)
    or_low = entry_price * random.uniform(0.98, 1.005)
    
    # Volume
    entry_volume = random.randint(100000, 5000000)
    or_volume = random.randint(50000, 2000000)
    volume_surge_ratio = random.uniform(0.5, 5.0)
    
    # Price relationships
    price_vs_pdh = ((entry_price - pdh) / pdh * 100)
    price_vs_or_high = ((entry_price - or_high) / or_high * 100)
    
    # VIX
    vix_level = random.uniform(12, 28)
    
    # Time since open (9:30 AM)
    time_since_open_min = (hour - 9) * 60 + (minute - 30)
    if time_since_open_min < 0:
        time_since_open_min = 0
    
    # Signal type
    signal_type = random.choice(SIGNAL_TYPES)
    
    # Outcome - make it somewhat realistic based on conditions
    # Better conditions = higher win probability
    win_probability = 0.5  # Base 50%
    
    # Adjust based on conditions
    if abs(gap_pct) > 3:
        win_probability += 0.1  # Big gaps slightly favor wins
    if volume_surge_ratio > 2.5:
        win_probability += 0.15  # Strong volume surge helps
    if time_since_open_min < 30:
        win_probability += 0.1  # Early trades slightly better
    if vix_level > 22:
        win_probability -= 0.1  # High VIX reduces win rate
    
    win = 1 if random.random() < win_probability else 0
    
    # PnL calculation
    if win:
        # Winners: 0.5% to 3% gain
        pnl_pct = random.uniform(0.005, 0.03)
        exit_price = entry_price * (1 + pnl_pct)
        pnl = round(100 * pnl_pct, 2)  # $100 position size
    else:
        # Losers: -0.3% to -1.5% loss
        pnl_pct = random.uniform(-0.015, -0.003)
        exit_price = entry_price * (1 + pnl_pct)
        pnl = round(100 * pnl_pct, 2)
    
    return {
        'ticker': ticker,
        'entry_time': entry_time.isoformat(),
        'exit_time': exit_time.isoformat(),
        'entry_price': round(entry_price, 2),
        'exit_price': round(exit_price, 2),
        'pnl': pnl,
        'win': win,
        'hold_minutes': hold_minutes,
        'signal_type': signal_type,
        'entry_volume': entry_volume,
        'pdh': round(pdh, 2),
        'pdl': round(pdl, 2),
        'gap_pct': round(gap_pct, 2),
        'vix_level': round(vix_level, 2),
        'time_since_open_min': time_since_open_min,
        'or_high': round(or_high, 2),
        'or_low': round(or_low, 2),
        'or_volume': or_volume,
        'volume_surge_ratio': round(volume_surge_ratio, 2),
        'price_vs_pdh': round(price_vs_pdh, 2),
        'price_vs_or_high': round(price_vs_or_high, 2)
    }

def insert_trades(trades):
    """Insert trades into database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for trade in trades:
        cursor.execute("""
            INSERT INTO trade_logs (
                ticker, entry_time, exit_time, entry_price, exit_price,
                pnl, win, hold_minutes, signal_type, entry_volume,
                pdh, pdl, gap_pct, vix_level, time_since_open_min,
                or_high, or_low, or_volume, volume_surge_ratio,
                price_vs_pdh, price_vs_or_high
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade['ticker'], trade['entry_time'], trade['exit_time'],
            trade['entry_price'], trade['exit_price'], trade['pnl'],
            trade['win'], trade['hold_minutes'], trade['signal_type'],
            trade['entry_volume'], trade['pdh'], trade['pdl'],
            trade['gap_pct'], trade['vix_level'], trade['time_since_open_min'],
            trade['or_high'], trade['or_low'], trade['or_volume'],
            trade['volume_surge_ratio'], trade['price_vs_pdh'],
            trade['price_vs_or_high']
        ))
    
    conn.commit()
    conn.close()

def main():
    print("[GEN] ========== Generate Test Trades ==========")
    
    # Create table
    create_trade_logs_table()
    
    # Generate 100 trades
    print("[GEN] Generating 100 synthetic trades...")
    base_time = datetime.now(ET)
    
    trades = []
    for i in range(100):
        ticker = random.choice(TICKERS)
        trade = generate_trade(base_time, ticker)
        trades.append(trade)
        
        if (i + 1) % 20 == 0:
            print(f"[GEN] Generated {i + 1}/100 trades...")
    
    # Insert into database
    print("[GEN] Inserting trades into database...")
    insert_trades(trades)
    
    # Stats
    wins = sum(1 for t in trades if t['win'] == 1)
    losses = len(trades) - wins
    win_rate = wins / len(trades) * 100
    
    print("[GEN] ========== Complete ==========")
    print(f"[GEN] ✅ Generated 100 trades")
    print(f"[GEN] 📊 Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"[GEN] 💰 Avg PnL: ${sum(t['pnl'] for t in trades) / len(trades):.2f}")
    print(f"[GEN] 📈 Tickers: {len(set(t['ticker'] for t in trades))} unique")
    print(f"[GEN] 🎯 Signal types: {', '.join(set(t['signal_type'] for t in trades))}")
    print("\n[GEN] Ready to train ML model!")
    print("[GEN] Run: python tests/test_ml_training.py")

if __name__ == "__main__":
    main()
