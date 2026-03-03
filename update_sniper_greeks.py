#!/usr/bin/env python3
"""
Patch Script: Update sniper.py arm_ticker() to extract and pass Greeks data
This script adds Greeks metrics to Discord alerts for live trading signals.
"""

print("\n" + "="*80)
print("PATCHING SNIPER.PY - Adding Greeks Data to Discord Alerts")
print("="*80 + "\n")

# Read sniper.py
try:
    with open('app/core/sniper.py', 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print("❌ Error: app/core/sniper.py not found!")
    print("Make sure you're running this from the War-Machine project root.")
    exit(1)

# Find the arm_ticker function's send_options_signal_alert call
old_alert_call = '''send_options_signal_alert(
                ticker=ticker, direction=direction,
                entry=entry_price, stop=stop_price, t1=t1, t2=t2,
                confidence=confidence, timeframe="5m", grade=grade, 
                options_data=options_rec,
                confirmation=bos_confirmation, candle_type=bos_candle_type
            )'''

# Updated version with Greeks data extraction and passing
new_alert_call = '''# Extract Greeks data for Discord alert
            greeks_data = None
            if options_rec:
                try:
                    from app.validation.greeks_precheck import get_cached_greeks
                    greeks_list = get_cached_greeks(ticker, direction)
                    if greeks_list:
                        best_option = greeks_list[0]  # Already sorted by quality
                        greeks_data = {
                            'is_valid': True,
                            'reason': f"ATM {direction.upper()} options available with good Greeks",
                            'best_strike': best_option['strike'],
                            'details': {
                                'delta': best_option['delta'],
                                'iv': best_option['iv'],
                                'dte': best_option['dte'],
                                'spread_pct': best_option['spread_pct'],
                                'liquidity_ok': best_option['is_liquid']
                            }
                        }
                except Exception as greeks_err:
                    print(f"[ARM] Greeks data extraction error (non-fatal): {greeks_err}")
            
            send_options_signal_alert(
                ticker=ticker, direction=direction,
                entry=entry_price, stop=stop_price, t1=t1, t2=t2,
                confidence=confidence, timeframe="5m", grade=grade, 
                options_data=options_rec,
                confirmation=bos_confirmation, candle_type=bos_candle_type,
                greeks_data=greeks_data  # NEW: Pass Greeks validation data
            )'''

# Check if already patched
if 'greeks_data=greeks_data' in content:
    print("✅ sniper.py already patched with Greeks data!")
    print("No changes needed.\n")
    exit(0)

# Apply patch
if old_alert_call in content:
    content = content.replace(old_alert_call, new_alert_call)
    
    # Write updated content
    with open('app/core/sniper.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Successfully patched sniper.py!")
    print("\nChanges made:")
    print("  - Added Greeks data extraction from cached options")
    print("  - Passing greeks_data to send_options_signal_alert()")
    print("  - Discord alerts will now show Greeks metrics with recommendations")
    print("\nNext steps:")
    print("  1. Commit: git add app/core/sniper.py")
    print("  2. Commit: git commit -m 'Add Greeks data to Discord alerts'")
    print("  3. Push: git push origin main")
    print("  4. Test: python test_greeks_discord.py")
else:
    print("⚠️ Warning: Could not find expected code pattern in sniper.py")
    print("The file structure may have changed. Manual patching required.")
    print("\nLook for the send_options_signal_alert() call in arm_ticker() function")
    print("and add the Greeks data extraction code before it.")
    exit(1)

print("\n" + "="*80 + "\n")
