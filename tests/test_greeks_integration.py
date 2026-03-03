"""
Quick test to validate Greeks cache integration with sniper logic.
"""
from app.validation.greeks_precheck import validate_signal_greeks

# Test with AAPL (we know this works from earlier tests)
test_cases = [
    ("AAPL", "bull", 265.0),
    ("AAPL", "bear", 265.0),
    ("TSLA", "bull", 180.0),  # Test with different ticker
]

print("\n" + "="*70)
print("GREEKS CACHE INTEGRATION TEST")
print("="*70 + "\n")

for ticker, direction, price in test_cases:
    print(f"Testing {ticker} {direction.upper()} @ ${price:.2f}")
    is_valid, reason = validate_signal_greeks(ticker, direction, price)
    
    status = "✅ PASS" if is_valid else "❌ FAIL"
    print(f"  Result: {status}")
    print(f"  Reason: {reason}\n")

print("="*70)
print("Integration test complete!")
print("="*70)
