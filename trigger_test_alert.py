"""Trigger a test enhanced alert on Railway."""
import os
os.environ.setdefault('EODHD_API_KEY', 'test')  # Prevent import errors

from app.discord_helpers import send_options_signal_alert

# Send one test alert with all enhanced features
send_options_signal_alert(
    ticker="TEST",
    direction="bull",
    entry=100.00,
    stop=98.00,
    t1=102.00,
    t2=105.00,
    confidence=0.85,
    timeframe="5m",
    grade="A+",
    rvol=4.2,
    composite_score=87.5,
    mtf_convergence=4,
    explosive_mover=True,
    options_data={
        'strike': 101,
        'dte': 0,
        'delta': 0.52,
        'iv': 0.45,
        'bid': 2.80,
        'ask': 2.95,
        'mid': 2.88,
        'limit_entry': 2.88,
        'max_entry': 2.95,
        'spread_pct': 2.6
    },
    confirmation="A+",
    candle_type="Bullish Engulfing",
    greeks_data={
        'is_valid': True,
        'details': {
            'delta': 0.52,
            'iv': 0.45,
            'dte': 0,
            'spread_pct': 2.6,
            'liquidity_ok': True
        }
    }
)

print("✅ Test alert sent! Check Discord.")
