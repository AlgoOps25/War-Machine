#!/usr/bin/env python3
"""
Standalone test for EODHD Economic Calendar integration.
Run this to verify get_session_risk() before Monday open.

Usage:
    python test_econ_calendar.py
"""
import sys
from datetime import datetime

try:
    from premarket_scanner import get_session_risk, get_economic_events
except ImportError:
    print("ERROR: Could not import premarket_scanner.py")
    print("Make sure you're running from the War-Machine directory.")
    sys.exit(1)

print("="*70)
print("ECONOMIC CALENDAR TEST")
print("="*70)
print(f"Testing date: {datetime.now().strftime('%A, %B %d, %Y')}")
print("="*70)

# Test 1: Raw event fetch
print("\n[TEST 1] Fetching raw economic events from EODHD...\n")
events = get_economic_events()
print(f"Events returned: {len(events)}")

if events:
    print("\nFirst 3 events (raw):")
    for i, e in enumerate(events[:3], 1):
        print(f"\n{i}. Event dict keys: {list(e.keys())}")
        print(f"   Raw data: {e}")
else:
    print("No events found (this is normal for weekends or dates with no scheduled events)")

# Test 2: Full risk assessment
print("\n" + "="*70)
print("[TEST 2] Full session risk assessment\n")

risk = get_session_risk()

print(f"Risk Level: {risk['risk_level']}")
print(f"Total Events: {risk['event_count']}")
print(f"High-Impact Events: {risk['high_count']}")
print(f"\nRecommendation:\n{risk['recommendation']}")

if risk['high_events']:
    print("\nHigh-Impact Events:")
    for i, e in enumerate(risk['high_events'], 1):
        name = str(e.get('type') or e.get('event') or e.get('name') or 'Unknown')
        date = str(e.get('date', ''))
        impact = str(e.get('impact') or e.get('importance') or '')
        print(f"{i}. {name}")
        print(f"   Time: {date}")
        print(f"   Impact: {impact}")

if risk['all_events'] and not risk['high_events']:
    print("\nMedium-Impact Events:")
    for i, e in enumerate(risk['all_events'][:3], 1):
        name = str(e.get('type') or e.get('event') or e.get('name') or 'Unknown')
        date = str(e.get('date', ''))
        print(f"{i}. {name} at {date}")

# Test 3: Simulate main.py integration
print("\n" + "="*70)
print("[TEST 3] Simulating main.py integration\n")

import config

effective_max_contracts = config.MAX_CONTRACTS
effective_conf_floor = config.MIN_CONFIDENCE_OR

if risk['risk_level'] == "HIGH":
    effective_max_contracts = max(1, config.MAX_CONTRACTS // 2)
    effective_conf_floor = 0.80
    print("HIGH-IMPACT DAY adjustments:")
    print(f"  MAX_CONTRACTS: {config.MAX_CONTRACTS} → {effective_max_contracts}")
    print(f"  MIN_CONFIDENCE: {config.MIN_CONFIDENCE_OR:.2f} → {effective_conf_floor:.2f}")
elif risk['risk_level'] == "MEDIUM":
    print("MEDIUM-IMPACT DAY: Normal sizing, heightened awareness")
else:
    print("LOW-IMPACT DAY: No adjustments needed")

print("\n" + "="*70)
print("TEST COMPLETE")
print("="*70)
print("\nIf you see events listed above, the integration is working correctly.")
print("If no events, either:")
print("  1. Today has no scheduled US economic events (normal)")
print("  2. EODHD_API_KEY is not set in .env (check config)")
print("  3. The API endpoint format has changed (unlikely)")
print("\nRun this again Monday morning at 8 AM to see Monday's actual calendar.")
print("="*70)
