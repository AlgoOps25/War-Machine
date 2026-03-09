# T3 Target (1-Hour Structure Level) - Integration Guide

## Overview

The T3 target implements the YouTube methodology: "I like to go for the next key level which is an hourly high."

This creates a **3-tier exit strategy**:
1. **T1 (1R)**: Quick profit, de-risk position
2. **T2 (2R)**: Standard target, lock in gains  
3. **T3 (1H level)**: Let winners run to structure

## Changes Made

### 1. Updated `trade_calculator.py`

#### New Functions
```python
def get_next_hourly_high(ticker, bars, current_price) -> float:
    """Find next 1-hour resistance above current price"""
    # Groups 5-min bars into 1-hour candles
    # Returns nearest hourly high above entry

def get_next_hourly_low(ticker, bars, current_price) -> float:
    """Find next 1-hour support below current price"""
    # Groups 5-min bars into 1-hour candles
    # Returns nearest hourly low below entry
```

#### Updated `compute_stop_and_targets()`
```python
# OLD signature
compute_stop_and_targets(
    bars, direction, or_high, or_low, entry_price, grade
) -> Tuple[float, float, float]  # Returns: stop, t1, t2

# NEW signature
compute_stop_and_targets(
    ticker, bars, direction, or_high, or_low, entry_price, grade
) -> Tuple[float, float, float, float]  # Returns: stop, t1, t2, t3
```

#### Updated Target Ratios
```python
# OLD (from previous version)
T1 = 2R  # 2:1 risk/reward
T2 = 3.5R  # 3.5:1 risk/reward

# NEW (matches YouTube video)
T1 = 1R  # 1:1 risk/reward
T2 = 2R  # 2:1 risk/reward
T3 = Next 1H structure level (dynamic)
```

## Integration Steps

### 1. Update All Calls to `compute_stop_and_targets()`

#### In `sniper.py`

**Line ~750** (preliminary targets):
```python
# OLD
_prelim_stop, _prelim_t1, _prelim_t2 = compute_stop_and_targets(
    bars_session, direction, or_high_ref, or_low_ref, entry_price,
    grade=final_grade
)

# NEW
_prelim_stop, _prelim_t1, _prelim_t2, _prelim_t3 = compute_stop_and_targets(
    ticker, bars_session, direction, or_high_ref, or_low_ref, entry_price,
    grade=final_grade
)
```

**Line ~950** (final targets):
```python
# OLD
stop_price, t1, t2 = compute_stop_and_targets(
    bars_session, direction, or_high_ref, or_low_ref, entry_price,
    grade=final_grade
)

# NEW  
stop_price, t1, t2, t3 = compute_stop_and_targets(
    ticker, bars_session, direction, or_high_ref, or_low_ref, entry_price,
    grade=final_grade
)
```

### 2. Update `arm_ticker()` Call

**Line ~1000**:
```python
# OLD
arm_ticker(
    ticker, direction, zone_low, zone_high,
    or_low_ref, or_high_ref,
    entry_price, stop_price, t1, t2,
    final_confidence, final_grade, options_rec,
    # ... other params
)

# NEW
arm_ticker(
    ticker, direction, zone_low, zone_high,
    or_low_ref, or_high_ref,
    entry_price, stop_price, t1, t2, t3,  # Added t3
    final_confidence, final_grade, options_rec,
    # ... other params
)
```

### 3. Update `arm_ticker()` Function Signature

**Line ~1050**:
```python
# OLD
def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade,
               options_rec=None, ...):

# NEW
def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, t3, confidence, grade,
               options_rec=None, ...):
```

### 4. Update Position Manager Calls

**In `arm_ticker()` around line ~1100**:
```python
# OLD
position_id = position_manager.open_position(
    ticker=ticker, direction=direction,
    zone_low=zone_low, zone_high=zone_high,
    or_low=or_low, or_high=or_high,
    entry_price=entry_price, stop_price=stop_price,
    t1=t1, t2=t2, confidence=confidence, grade=grade, 
    options_rec=options_rec
)

# NEW
position_id = position_manager.open_position(
    ticker=ticker, direction=direction,
    zone_low=zone_low, zone_high=zone_high,
    or_low=or_low, or_high=or_high,
    entry_price=entry_price, stop_price=stop_price,
    t1=t1, t2=t2, t3=t3, confidence=confidence, grade=grade,
    options_rec=options_rec
)
```

### 5. Update Discord Alert Calls

**Around line ~1080**:
```python
# OLD
send_options_signal_alert(
    ticker=ticker, direction=direction,
    entry=entry_price, stop=stop_price, t1=t1, t2=t2,
    # ... other params
)

# NEW
send_options_signal_alert(
    ticker=ticker, direction=direction,
    entry=entry_price, stop=stop_price, t1=t1, t2=t2, t3=t3,
    # ... other params
)
```

### 6. Update Phase 4 Tracking

**Around line ~780**:
```python
# OLD
signal_tracker.record_signal_generated(
    ticker=ticker,
    signal_type=signal_type,
    direction=direction,
    grade=final_grade,
    confidence=compute_confidence(final_grade, "5m", ticker),
    entry_price=entry_price,
    stop_price=_prelim_stop,
    t1_price=_prelim_t1,
    t2_price=_prelim_t2
)

# NEW
signal_tracker.record_signal_generated(
    ticker=ticker,
    signal_type=signal_type,
    direction=direction,
    grade=final_grade,
    confidence=compute_confidence(final_grade, "5m", ticker),
    entry_price=entry_price,
    stop_price=_prelim_stop,
    t1_price=_prelim_t1,
    t2_price=_prelim_t2,
    t3_price=_prelim_t3  # Added
)
```

## Position Manager Updates

You'll also need to update `position_manager.py`:

### 1. Update Position Schema
```python
# In open_position() - add t3 field
CREATE TABLE IF NOT EXISTS positions (
    # ... existing fields
    t1 REAL NOT NULL,
    t2 REAL NOT NULL,
    t3 REAL NOT NULL,  -- NEW
    # ... rest of schema
)
```

### 2. Update Exit Logic
```python
# In check_exit_conditions()
def check_exit_conditions(self, ticker, current_price):
    pos = self.get_position(ticker)
    
    # Check T1 (25% position)
    if not pos['t1_hit'] and self._price_hit_target(current_price, pos['t1'], pos['direction']):
        self.partial_exit(ticker, 0.25, pos['t1'], 'T1')
    
    # Check T2 (50% position)
    if not pos['t2_hit'] and self._price_hit_target(current_price, pos['t2'], pos['direction']):
        self.partial_exit(ticker, 0.50, pos['t2'], 'T2')
    
    # Check T3 (25% position) - NEW
    if not pos['t3_hit'] and self._price_hit_target(current_price, pos['t3'], pos['direction']):
        self.partial_exit(ticker, 0.25, pos['t3'], 'T3')
```

## Exit Strategy

### Position Scaling
```
Entry: 100% position
├─ T1 (1R):  Exit 25% → 75% remaining
├─ T2 (2R):  Exit 50% → 25% remaining  
└─ T3 (1H):  Exit 25% → Position closed
```

### Example Trade
```
Ticker: AAPL
Entry: $150.00
Stop:  $149.00 (1R = $1.00)

T1: $151.00 (1R)  → Exit 25 shares
T2: $152.00 (2R)  → Exit 50 shares
T3: $153.80 (1H resistance) → Exit 25 shares

Total R-multiple: (0.25×1R) + (0.50×2R) + (0.25×3.8R) = 2.20R
```

## Validation

T3 must be beyond T2, or it gets adjusted:
```python
# In compute_stop_and_targets()
if direction == 'bull':
    if t3 <= t2:
        t3 = t2 * 1.002  # 0.2% above T2
```

## Monitoring

### Log Output
```
[TARGETS] A: T1=$151.00 (1R) | T2=$152.00 (2R) | Risk=$1.00
[T3] AAPL - Next 1H resistance: $153.80 (from 3 levels)
```

### Discord Alert
```
✅ AAPL ARMED [OR]: BULL
Entry: $150.00 | Stop: $149.00
T1: $151.00 (1R) | T2: $152.00 (2R) | T3: $153.80 (1H)
90.0% confidence (A)
```

## Fallback Logic

If hourly structure calculation fails:
1. Use recent swing high/low
2. Add 0.5% buffer
3. Emergency fallback: 3R from entry

## Testing Checklist

- [ ] Verify T3 calculation logic with sample bars
- [ ] Confirm T3 > T2 validation
- [ ] Test bull and bear T3 targets
- [ ] Check position manager accepts T3 field
- [ ] Validate Discord alerts show T3
- [ ] Review Phase 4 tracking includes T3

## Version History

- **v1.0.0** (2026-03-09): Initial implementation from YouTube video
- Target ratios updated: T1=1R, T2=2R, T3=1H structure
