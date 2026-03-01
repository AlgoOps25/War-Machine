# RTH Filter Integration Guide

## Overview

The RTH filter (`app/analytics/rth_filter.py`) provides market calendar-aware validation for blocking signals outside regular trading hours.

## Installation

```bash
cd C:\Dev\War-Machine
git pull origin main
pip install -r requirements.txt  # Installs pandas_market_calendars
```

## Integration Points

### 1. Pre-Market Check (scanner.py startup)

**Location**: `scanner.py` before main loop

```python
from app.analytics.rth_filter import is_market_open, get_market_hours_today

# Before starting scanner loop
if not is_market_open():
    print("[SCANNER] Market closed today (holiday or weekend) - exiting")
    return

hours = get_market_hours_today()
if hours:
    print(f"[SCANNER] Market hours today: {hours['open'].strftime('%H:%M')} - {hours['close'].strftime('%H:%M')} ET")
    if hours['early_close']:
        print("[SCANNER] ⚠️ Early close today at 1:00 PM ET")
```

### 2. Signal Blocking (scanner.py main loop)

**Location**: `scanner.py` before calling `sniper.arm_signal()`

```python
from app.analytics.rth_filter import is_rth_now

# Inside scan loop, before arming signals
for signal in detected_signals:
    # Block signals outside RTH
    if not is_rth_now():
        print(f"[SCANNER] 🚫 Signal blocked (outside RTH): {signal.ticker}")
        continue
    
    # Existing signal arming logic
    sniper.arm_signal(signal)
```

### 3. Complete Integration Example

```python
# scanner.py - Complete RTH integration

from app.analytics.rth_filter import (
    is_market_open,
    is_rth_now,
    get_market_hours_today,
    is_early_close_today
)

def main():
    print("[SCANNER] Starting War Machine...")
    
    # Pre-flight check: Market open today?
    if not is_market_open():
        print("[SCANNER] Market closed today - exiting")
        return
    
    # Log market hours
    hours = get_market_hours_today()
    if hours:
        open_time = hours['open'].strftime('%H:%M')
        close_time = hours['close'].strftime('%H:%M')
        print(f"[SCANNER] Market hours: {open_time} - {close_time} ET")
        
        if is_early_close_today():
            print("[SCANNER] ⚠️ EARLY CLOSE at 1:00 PM today")
    
    # Start WebSocket, load data, etc.
    # ...
    
    # Main scan loop
    while True:
        # Check RTH before scanning
        if not is_rth_now():
            print("[SCANNER] Outside RTH - waiting...")
            time.sleep(60)
            continue
        
        # Run signal detection
        signals = detect_signals()
        
        for signal in signals:
            # Double-check RTH (in case we're near close)
            if not is_rth_now():
                print(f"[SCANNER] 🚫 {signal.ticker} blocked (RTH ended)")
                continue
            
            # Arm signal
            sniper.arm_signal(signal)
        
        time.sleep(30)  # Next scan cycle
```

## Diagnostic Commands

### Test RTH Filter Manually

```bash
# Run RTH filter diagnostics
python -m app.analytics.rth_filter
```

**Expected Output:**
```
============================================================
RTH FILTER - Market Status Check
============================================================

Current Time (ET): 2026-03-03 10:45:00 EST
Calendar Available: True

Market Open Today: True
Market Hours: 09:30 - 16:00 ET
Early Close: False

Currently in RTH: True

✅ Market is OPEN and in RTH

============================================================
```

### Test in Python REPL

```python
from app.analytics.rth_filter import *

# Check if market open
print(is_market_open())  # True or False

# Check if in RTH right now
print(is_rth_now())  # True or False

# Get market hours
hours = get_market_hours_today()
if hours:
    print(f"Open: {hours['open']}")
    print(f"Close: {hours['close']}")
    print(f"Early close: {hours['early_close']}")

# Full status
from pprint import pprint
pprint(get_rth_status())
```

## Fallback Behavior

If `pandas_market_calendars` is not installed or fails:
- Assumes market open Monday-Friday
- Assumes standard hours: 9:30 AM - 4:00 PM ET
- No holiday detection
- No early close detection

**Recommendation**: Always install the dependency for production use.

## Market Holidays Detected

The NYSE calendar automatically handles:
- New Year's Day
- Martin Luther King Jr. Day
- Presidents' Day
- Good Friday
- Memorial Day
- Juneteenth
- Independence Day
- Labor Day
- Thanksgiving
- Christmas

## Early Close Days

Early closes (1:00 PM ET) automatically detected for:
- Day before Independence Day (if weekday)
- Black Friday (day after Thanksgiving)
- Christmas Eve (if weekday)

## Performance

- **First call**: Fetches NYSE calendar (~50ms)
- **Subsequent calls**: Cached (< 1ms)
- **Cache refresh**: Once per day at midnight
- **Thread-safe**: Multiple scanners can call simultaneously

## Integration Checklist

- [ ] `pip install -r requirements.txt` completed
- [ ] Import RTH filter in `scanner.py`
- [ ] Add pre-market check before main loop
- [ ] Add RTH check before arming signals
- [ ] Test with `python -m app.analytics.rth_filter`
- [ ] Run scanner on market holiday to verify blocking
- [ ] Run scanner during after-hours to verify blocking

## Next Steps

After RTH filter is integrated:
1. Monitor logs for `🚫 Signal blocked (outside RTH)` messages
2. Verify no signals fire on holidays
3. Verify no signals fire before 9:30 AM or after 4:00 PM
4. Proceed to #4: VIX-Based Position Sizing
