#!/usr/bin/env python3
"""
Test Greeks Cache Integration with Discord Alerts
Tests live market data flow: Greeks validation → Discord alert with recommendations
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

print("="*80)
print("GREEKS + DISCORD INTEGRATION TEST")
print("="*80)
print(f"Test Time: {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %I:%M %p ET')}\n")

# Test 1: Greeks validation for AAPL (should pass)
print("Test 1: AAPL CALL validation (expected: VALID)")
print("-" * 80)

try:
    from app.validation.greeks_precheck import validate_signal_greeks, get_cached_greeks
    
    ticker = "AAPL"
    direction = "bull"
    entry_price = 265.00  # Approximate current price
    
    # Phase 1: Fast Greeks validation
    is_valid, reason = validate_signal_greeks(ticker, direction, entry_price)
    
    print(f"Ticker: {ticker}")
    print(f"Direction: {direction.upper()}")
    print(f"Entry Price: ${entry_price:.2f}")
    print(f"\nGreeks Result: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Reason: {reason}")
    
    # Get detailed Greeks data for Discord alert
    if is_valid:
        greeks_list = get_cached_greeks(ticker, direction)
        if greeks_list:
            best_option = greeks_list[0]  # Already sorted by quality
            
            greeks_data = {
                'is_valid': True,
                'reason': reason,
                'best_strike': best_option['strike'],
                'details': {
                    'delta': best_option['delta'],
                    'iv': best_option['iv'],
                    'dte': best_option['dte'],
                    'spread_pct': best_option['spread_pct'],
                    'liquidity_ok': best_option['is_liquid']
                }
            }
            
            print("\nGreeks Data for Discord:")
            print(f"  Best Strike: ${greeks_data['best_strike']}")
            print(f"  Delta: {greeks_data['details']['delta']:+.2f}")
            print(f"  IV: {greeks_data['details']['iv']*100:.0f}%")
            print(f"  DTE: {greeks_data['details']['dte']}")
            print(f"  Spread: {greeks_data['details']['spread_pct']:.1f}%")
            print(f"  Liquid: {'✅' if greeks_data['details']['liquidity_ok'] else '❌'}")
        else:
            greeks_data = {'is_valid': True, 'reason': reason, 'best_strike': None, 'details': {}}
    else:
        greeks_data = {'is_valid': False, 'reason': reason, 'best_strike': None, 'details': {}}
    
    print("\n" + "="*80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Test Discord alert with Greeks data
print("\nTest 2: Discord Alert with Greeks Metrics")
print("-" * 80)

try:
    from app.discord_helpers import send_options_signal_alert
    
    # Simulate a signal
    send_options_signal_alert(
        ticker="AAPL",
        direction="bull",
        entry=265.00,
        stop=262.50,
        t1=267.50,
        t2=270.00,
        confidence=0.75,
        timeframe="5m",
        grade="A",
        options_data={
            'contract_label': '$265C 2DTE',
            'strike': 265,
            'dte': 2,
            'delta': 0.50,
            'theta': -0.15,
            'iv': 0.314,
            'bid': 3.30,
            'ask': 3.45,
            'mid': 3.38,
            'limit_entry': 3.35,
            'max_entry': 3.45,
            'spread_pct': 4.4
        },
        confirmation="A+",
        candle_type="Hammer",
        greeks_data=greeks_data  # NEW: Pass Greeks validation data
    )
    
    print("✅ Discord alert sent successfully with Greeks metrics!")
    print("\nCheck your Discord channel for the alert.")
    print("\nExpected Greeks Section:")
    if greeks_data['is_valid']:
        print(f"  ✅ Greeks Analysis")
        print(f"  **BUY CALL** @ ${greeks_data['best_strike']}")
        print(f"  {greeks_data['reason']}")
        print(f"  ")
        print(f"  **Greeks Quality:**")
        print(f"  Δ {greeks_data['details']['delta']:+.2f} ✅  |  IV {greeks_data['details']['iv']*100:.0f}% ✅  |  {greeks_data['details']['dte']}DTE")
        print(f"  Spread {greeks_data['details']['spread_pct']:.1f}% ✅  |  Liquidity ✅")
    else:
        print(f"  ⚠️ Greeks Analysis")
        print(f"  **WAIT** — {greeks_data['reason']}")
    
except Exception as e:
    print(f"❌ Discord alert error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*80)
print("✅ Integration test complete!")
print("="*80)
