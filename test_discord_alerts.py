"""
Test Enhanced Discord Alerts

Tests the new visual format with:
- RVOL indicators
- MTF convergence badges
- Better Greeks visualization
- Performance metrics
"""
from app.discord_helpers import send_options_signal_alert

def test_enhanced_alerts():
    """Test different alert scenarios with enhanced format."""
    
    print("\n" + "="*80)
    print("🧪 TESTING ENHANCED DISCORD ALERTS")
    print("="*80 + "\n")
    
    # Test 1: A+ Grade Signal with High RVOL
    print("📤 Test 1: A+ Signal (Explosive Mover)")
    send_options_signal_alert(
        ticker="NVDA",
        direction="bull",
        entry=130.50,
        stop=128.00,
        t1=133.00,
        t2=136.50,
        confidence=0.88,
        timeframe="5m",
        grade="A+",
        rvol=4.2,
        volume_rank=95,
        composite_score=87.5,
        mtf_convergence=4,  # All 4 timeframes aligned
        explosive_mover=True,
        options_data={
            'strike': 131,
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
    print("   ✅ Sent\n")
    
    # Test 2: Regular A Signal
    print("📤 Test 2: A Signal (Balanced)")
    send_options_signal_alert(
        ticker="SPY",
        direction="bull",
        entry=582.00,
        stop=579.50,
        t1=584.50,
        t2=587.50,
        confidence=0.75,
        timeframe="5m",
        grade="A",
        rvol=2.3,
        composite_score=72.0,
        mtf_convergence=2,  # 2 timeframes
        explosive_mover=False,
        options_data={
            'strike': 583,
            'dte': 0,
            'delta': 0.45,
            'iv': 0.38,
            'bid': 1.50,
            'ask': 1.58,
            'mid': 1.54,
            'limit_entry': 1.54,
            'max_entry': 1.58,
            'spread_pct': 3.2
        },
        confirmation="A",
        candle_type="Hammer",
        greeks_data={
            'is_valid': True,
            'details': {
                'delta': 0.45,
                'iv': 0.38,
                'dte': 0,
                'spread_pct': 3.2,
                'liquidity_ok': True
            }
        }
    )
    print("   ✅ Sent\n")
    
    # Test 3: B Grade Signal (Lower confidence)
    print("📤 Test 3: B Signal (Conservative)")
    send_options_signal_alert(
        ticker="TSLA",
        direction="bear",
        entry=350.00,
        stop=353.00,
        t1=347.00,
        t2=343.00,
        confidence=0.68,
        timeframe="5m",
        grade="B",
        rvol=1.8,
        composite_score=65.0,
        mtf_convergence=1,
        explosive_mover=False,
        options_data={
            'strike': 349,
            'dte': 0,
            'delta': -0.38,
            'iv': 0.52,
            'bid': 3.10,
            'ask': 3.30,
            'mid': 3.20,
            'limit_entry': 3.20,
            'max_entry': 3.30,
            'spread_pct': 4.8
        },
        confirmation="A-",
        candle_type="Shooting Star",
        greeks_data={
            'is_valid': True,
            'details': {
                'delta': -0.38,
                'iv': 0.52,
                'dte': 0,
                'spread_pct': 4.8,
                'liquidity_ok': True
            }
        }
    )
    print("   ✅ Sent\n")
    
    print("="*80)
    print("✅ ALL TESTS COMPLETE - Check Discord!")
    print("="*80 + "\n")
    print("Expected enhancements:")
    print("  🚀 Explosive mover badge on NVDA")
    print("  ⚡4TF Multi-timeframe badge on NVDA")
    print("  📊 RVOL indicators (4.2x, 2.3x, 1.8x)")
    print("  🟢🟡🟠 Color-coded deltas")
    print("  █████████ Confidence bars")
    print("  ✅⚠️ Quality check emojis")
    print()

if __name__ == "__main__":
    test_enhanced_alerts()
