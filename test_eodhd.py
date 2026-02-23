from premarket_scanner import get_economic_events

events = get_economic_events('2026-02-27')
print(f'Friday Feb 27 EODHD events: {len(events)}')
for e in events[:5]:
    print(f"  - {e.get('event','?')} | {e.get('date','?')} | importance={e.get('importance','?')}")
