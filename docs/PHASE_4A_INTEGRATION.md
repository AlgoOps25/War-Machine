# Phase 4A.1: Signal Analytics Integration Guide

## Overview

`signal_analytics.py` tracks the complete lifecycle of every CFW6 signal from pattern detection through trade execution. This guide shows how to integrate it into the existing codebase.

## Integration Points

### 1. Signal Generation (sniper.py)

**Location:** After CFW6 pattern detected but before confirmation

**Current code location:** Around line 900-1000 in `sniper.py`, after grade assignment

```python
# Add at top of sniper.py
from signal_analytics import signal_tracker

# In _run_signal_pipeline() after grade is assigned:
if watch_status == "confirmed":
    # Record signal generation
    signal_tracker.record_signal_generated(
        ticker=ticker,
        signal_type=signal_type,  # 'CFW6_OR' or 'CFW6_INTRADAY'
        direction=direction,       # 'bull' or 'bear'
        grade=grade,               # 'A+', 'A', or 'A-'
        confidence=base_confidence,
        entry_price=entry_price,
        stop_price=stop_loss,
        t1_price=t1,
        t2_price=t2
    )
```

### 2. Validation Result (signal_validator.py)

**Location:** After validator returns pass/fail decision

**Current code location:** Around line 300-400 in `signal_validator.py`, after confidence calculation

```python
# Add at top of signal_validator.py
from signal_analytics import signal_tracker

# In validate() function after all checks complete:
if validation_result['passed']:
    signal_tracker.record_validation_result(
        ticker=ticker,
        passed=True,
        confidence_after=validation_result['final_confidence'],
        ivr_multiplier=options_data.get('ivr_multiplier', 1.0),
        uoa_multiplier=options_data.get('uoa_multiplier', 1.0),
        gex_multiplier=options_data.get('gex_multiplier', 1.0),
        mtf_boost=validation_result.get('mtf_boost', 0.0),
        ticker_multiplier=validation_result.get('ticker_multiplier', 1.0),
        ivr_label=options_data.get('ivr_label', ''),
        uoa_label=options_data.get('uoa_label', ''),
        gex_label=options_data.get('gex_label', ''),
        checks_passed=validation_result['passed_checks'],
        rejection_reason=''
    )
else:
    signal_tracker.record_validation_result(
        ticker=ticker,
        passed=False,
        rejection_reason=validation_result['rejection_reason']
    )
```

### 3. Signal Armed (sniper.py)

**Location:** After `wait_for_confirmation()` returns True

**Current code location:** Around line 1000-1100 in `sniper.py`, after confirmation logic

```python
# After wait_for_confirmation() returns True:
if confirmed:
    # Calculate bars waited
    bars_to_confirmation = len(watch_data.get('watch_bars', []))
    
    # Record arming
    signal_tracker.record_signal_armed(
        ticker=ticker,
        final_confidence=final_confidence,
        bars_to_confirmation=bars_to_confirmation,
        confirmation_type='retest'  # or 'rejection' based on confirmation type
    )
```

### 4. Trade Execution (position_manager.py)

**Location:** After position is successfully opened

**Current code location:** Around line 200-300 in `position_manager.py`, after `open_position()`

```python
# Add at top of position_manager.py
from signal_analytics import signal_tracker

# In open_position() after position is committed to DB:
if position_id:
    signal_tracker.record_trade_executed(
        ticker=ticker,
        position_id=position_id
    )
```

### 5. EOD Summary (main loop or scheduler)

**Location:** At end of trading day, before shutdown

**Current code location:** Add to EOD cleanup routine (around line 1500-1600 in `sniper.py`)

```python
# At EOD (after market close):
def print_eod_analytics():
    """Print end-of-day analytics summary."""
    from signal_analytics import signal_tracker
    
    # Print daily summary
    print(signal_tracker.get_daily_summary())
    
    # Clear session cache for next day
    signal_tracker.clear_session_cache()

# Call this in your EOD routine:
if is_force_close_time():  # or similar EOD condition
    print_eod_analytics()
```

---

## Example Output

### Daily Summary

```
================================================================================
SIGNAL ANALYTICS - DAILY SUMMARY
================================================================================
Session Date: 2026-02-24

── Signal Funnel ──────────────────────────────────────────────────────────────
  Generated:  150
  Validated:   89  ( 59.3% pass rate)
  Armed:       42  ( 47.2% confirmation rate)
  Traded:      18  ( 42.9% execution rate)

── Grade Distribution ─────────────────────────────────────────────────────────
  A+ :  34  ( 22.7%)
  A  :  81  ( 54.0%)
  A- :  35  ( 23.3%)

── Multiplier Impact ──────────────────────────────────────────────────────────
  IVR Multiplier:  1.042x
  UOA Multiplier:  1.062x
  GEX Multiplier:  0.987x
  MTF Boost:       +0.078
  Base → Final:    0.724 → 0.807  (+11.5%)
================================================================================
```

### Funnel Visualization

```
150 generated → 89 validated (59%) → 42 armed (47%) → 18 traded (43%)
```

---

## Metrics Tracked

### Signal Lifecycle
- Total signals generated
- Validation pass rate
- Confirmation rate (armed signals)
- Execution rate (traded signals)

### Grade Quality
- A+/A/A- distribution
- Win rate by grade (requires trade outcome data)
- Average confidence by grade

### Multiplier Effectiveness
- Average IVR multiplier effect
- Average UOA multiplier effect
- Average GEX multiplier effect
- Average MTF boost
- Total confidence boost percentage

### Confirmation Analysis
- Average bars to confirmation
- Retest vs rejection confirmation breakdown
- Timeout rate (signals that never confirm)

---

## Database Schema

### signal_events Table

```sql
CREATE TABLE signal_events (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    grade TEXT,
    
    -- Lifecycle stages
    stage TEXT NOT NULL,  -- 'GENERATED', 'VALIDATED', 'ARMED', 'TRADED', 'REJECTED'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Confidence tracking
    base_confidence REAL,
    final_confidence REAL,
    
    -- Multipliers
    ivr_multiplier REAL DEFAULT 1.0,
    uoa_multiplier REAL DEFAULT 1.0,
    gex_multiplier REAL DEFAULT 1.0,
    mtf_boost REAL DEFAULT 0.0,
    ticker_multiplier REAL DEFAULT 1.0,
    
    -- Multiplier labels
    ivr_label TEXT,
    uoa_label TEXT,
    gex_label TEXT,
    
    -- Validation details
    validation_passed INTEGER,
    validation_checks TEXT,
    rejection_reason TEXT,
    
    -- Confirmation details
    bars_to_confirmation INTEGER,
    confirmation_type TEXT,
    
    -- Trade linkage
    position_id INTEGER,
    
    -- Additional metadata
    entry_price REAL,
    stop_price REAL,
    t1_price REAL,
    t2_price REAL,
    session_date TEXT,
    hour_of_day INTEGER
);
```

---

## Query Examples

### Get Validation Pass Rate by Grade

```sql
SELECT 
    grade,
    COUNT(*) as total,
    SUM(CASE WHEN stage = 'VALIDATED' THEN 1 ELSE 0 END) as validated,
    ROUND(100.0 * SUM(CASE WHEN stage = 'VALIDATED' THEN 1 ELSE 0 END) / COUNT(*), 1) as pass_rate
FROM signal_events
WHERE session_date = '2026-02-24' AND stage IN ('GENERATED', 'VALIDATED', 'REJECTED')
GROUP BY grade;
```

### Get Hourly Signal Distribution

```sql
SELECT 
    hour_of_day,
    COUNT(*) as signals_generated,
    AVG(base_confidence) as avg_confidence
FROM signal_events
WHERE session_date = '2026-02-24' AND stage = 'GENERATED'
GROUP BY hour_of_day
ORDER BY hour_of_day;
```

### Get Top Performing Tickers

```sql
SELECT 
    ticker,
    COUNT(*) as signals_traded,
    AVG(final_confidence) as avg_confidence
FROM signal_events
WHERE session_date >= '2026-02-17' AND stage = 'TRADED'
GROUP BY ticker
HAVING COUNT(*) >= 3
ORDER BY signals_traded DESC
LIMIT 10;
```

---

## Next Steps

1. **Week 1:** Integrate tracking calls into sniper.py and signal_validator.py
2. **Week 2:** Add EOD summary to main loop, collect 5 days of data
3. **Week 3:** Analyze conversion rates, identify bottlenecks
4. **Week 4:** Tune thresholds based on validation pass rates

---

## Troubleshooting

### "No GENERATED signal found" Warning

**Cause:** Validation called before signal was recorded as generated

**Fix:** Ensure `record_signal_generated()` is called before validator runs

### Session Cache Growing Too Large

**Cause:** `clear_session_cache()` not called at EOD

**Fix:** Add EOD cleanup routine to call `signal_tracker.clear_session_cache()`

### Database Lock Errors

**Cause:** SQLite concurrent writes (Railway deployment)

**Fix:** Already handled via `dict_cursor()` and proper connection management in code
