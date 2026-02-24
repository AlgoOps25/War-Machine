# Phase 4 Deployment Guide: Monitoring Integration

## Overview

**Goal:** Integrate Phase 4 monitoring into War Machine to track every signal from generation to execution.

**Time Required:** 2-3 hours  
**Complexity:** Medium (copy-paste code into existing files)  
**Risk Level:** Low (monitoring is read-only, doesn't affect trading logic)  

---

## Prerequisites

✅ Phase 4 modules committed to repository:  
- `signal_analytics.py` (25KB)  
- `performance_monitor.py` (25KB)  
- `performance_alerts.py` (15KB)  
- `eod_digest.py` (24KB)  
- `parameter_optimizer.py` (24KB)  

✅ Database schema includes `signal_events` table  
✅ Discord webhook configured (for alerts)  

---

## Integration Steps

### Step 1: Import Modules in Main Files

#### **File: `sniper.py`** (Top of file)

```python
# Add these imports near the top with other imports
from signal_analytics import signal_tracker
from performance_alerts import alert_manager
from eod_digest import digest_manager
```

---

### Step 2: Track Signal Generation

#### **File: `sniper.py`** (After grade is assigned)

Find where you assign the grade to a signal (after `grade_signal()` or similar). Add:

```python
# Example location: After determining grade, entry, stop, targets
# YOUR EXISTING CODE:
grade = grade_signal(ticker, signal_type, direction, confidence)
entry_price = calculate_entry(ticker, direction)
stop_loss = calculate_stop(entry_price, direction, atr)
t1_price = calculate_target_1(entry_price, direction, atr)
t2_price = calculate_target_2(entry_price, direction, atr)

# NEW: Track signal generation
signal_tracker.record_signal_generated(
    ticker=ticker,
    signal_type=signal_type,  # e.g., 'CFW6_OR', 'CFW6_INTRADAY'
    direction=direction,  # 'bull' or 'bear'
    grade=grade,  # 'A+', 'A', 'A-'
    confidence=confidence,  # Base confidence score
    entry_price=entry_price,
    stop_price=stop_loss,
    t1_price=t1_price,
    t2_price=t2_price
)
```

**Location hint:** Search for where you log "Signal generated" or where grade is first assigned.

---

### Step 3: Track Validation Results

#### **File: `signal_validator.py`** (After validation runs)

Find the validation function (e.g., `validate_signal()`) and add tracking at the end:

```python
def validate_signal(ticker, signal_data):
    # YOUR EXISTING VALIDATION LOGIC
    # ...
    # At the end, before returning:
    
    # NEW: Track validation result
    if passed_validation:
        signal_tracker.record_validation_result(
            ticker=ticker,
            passed=True,
            confidence_after=final_confidence,  # After multipliers applied
            ivr_multiplier=ivr_mult,
            uoa_multiplier=uoa_mult,
            gex_multiplier=gex_mult,
            mtf_boost=mtf_boost,
            rejection_reason=None
        )
    else:
        signal_tracker.record_validation_result(
            ticker=ticker,
            passed=False,
            confidence_after=None,
            rejection_reason=rejection_reason  # e.g., "Low volume", "ADX < 20"
        )
    
    return passed_validation
```

**Location hint:** Search for validator return statement or where you log "Validation passed/failed".

---

### Step 4: Track Signal Armed (Confirmation)

#### **File: `sniper.py`** (After confirmation received)

Find where signal gets confirmed (after price action confirms the setup):

```python
# YOUR EXISTING CODE:
if confirmation_received:
    # Signal is now armed and ready to trade
    
    # NEW: Track signal armed
    signal_tracker.record_signal_armed(
        ticker=ticker,
        final_confidence=final_confidence,  # Confidence after all multipliers
        bars_to_confirmation=bars_waited  # How many bars it took to confirm
    )
    
    # Proceed to trade execution...
```

**Location hint:** Search for where you transition from "waiting for confirmation" to "placing order".

---

### Step 5: Track Trade Execution

#### **File: `position_manager.py`** (After position opened)

Find where you successfully open a position and add:

```python
def open_position(ticker, signal_data, contracts):
    # YOUR EXISTING CODE to open position
    # ...
    position_id = db.insert_position(...)
    
    # NEW: Link signal to trade
    signal_tracker.record_trade_executed(
        ticker=ticker,
        position_id=position_id
    )
    
    return position_id
```

**Location hint:** Search for where positions table INSERT happens or where you log "Position opened".

---

### Step 6: Integrate Alert System

#### **File: `sniper.py` or your main trading loop** (Every scan cycle)

```python
# In your main loop (runs every X seconds):
while is_market_hours():
    # YOUR EXISTING SCAN LOGIC
    scan_for_signals()
    manage_positions()
    
    # NEW: Check and send alerts
    alert_manager.check_and_send_alerts()
    
    # Check if it's the top of the hour for hourly digest
    current_time = datetime.now(ET)
    if current_time.minute == 0 and not hourly_digest_sent:
        alert_manager.send_hourly_digest()
        hourly_digest_sent = True
    elif current_time.minute != 0:
        hourly_digest_sent = False
    
    time.sleep(SCAN_INTERVAL)
```

**Location hint:** Your main trading loop that runs continuously during market hours.

---

### Step 7: EOD Processing

#### **File: `sniper.py` or EOD routine** (At market close)

```python
def end_of_day_routine():
    """Run at market close (4:00 PM ET)."""
    
    # YOUR EXISTING EOD LOGIC
    close_all_positions()
    
    # NEW: Generate and display daily digest
    print("\n" + "="*100)
    print("END OF DAY DIGEST")
    print("="*100)
    daily_report = digest_manager.generate_daily_digest()
    print(daily_report)
    
    # Send Discord EOD summary
    alert_manager.send_eod_summary()
    
    # Friday: Generate weekly digest
    if datetime.now(ET).weekday() == 4:  # Friday
        print("\n" + "="*100)
        print("WEEKLY DIGEST")
        print("="*100)
        weekly_report = digest_manager.generate_weekly_digest()
        print(weekly_report)
    
    # Export daily data to CSV
    session_date = datetime.now(ET).strftime("%Y-%m-%d")
    csv_path = f"reports/daily_{session_date}.csv"
    digest_manager.export_to_csv(csv_path)
    print(f"\n[INFO] Daily data exported to: {csv_path}")
    
    # Reset daily state
    alert_manager.reset_daily_state()
    signal_tracker.clear_session_cache()
```

**Location hint:** Your existing EOD routine, or call this from your main loop when market closes.

---

## Database Schema Check

Ensure `signal_events` table exists. If not, run this SQL:

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    session_date DATE NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    stage VARCHAR(20) NOT NULL,  -- 'GENERATED', 'VALIDATED', 'REJECTED', 'ARMED', 'TRADED'
    signal_type VARCHAR(50),
    direction VARCHAR(10),
    grade VARCHAR(5),
    base_confidence FLOAT,
    final_confidence FLOAT,
    entry_price FLOAT,
    stop_price FLOAT,
    t1_price FLOAT,
    t2_price FLOAT,
    ivr_multiplier FLOAT,
    uoa_multiplier FLOAT,
    gex_multiplier FLOAT,
    mtf_boost FLOAT,
    bars_to_confirmation INTEGER,
    rejection_reason TEXT,
    position_id INTEGER REFERENCES positions(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_signal_events_ticker_date ON signal_events(ticker, session_date);
CREATE INDEX idx_signal_events_stage ON signal_events(stage);
CREATE INDEX idx_signal_events_timestamp ON signal_events(timestamp);
```

Run this on Railway:
1. Go to Railway dashboard
2. Click PostgreSQL service
3. Click "Data" tab
4. Click "Query" and paste SQL
5. Execute

---

## Testing Checklist

### Local Testing (Before Deployment)

```powershell
# Test imports
python -c "from signal_analytics import signal_tracker; print('✅ signal_analytics')"
python -c "from performance_alerts import alert_manager; print('✅ performance_alerts')"
python -c "from eod_digest import digest_manager; print('✅ eod_digest')"

# Test database connection
python -c "from signal_analytics import signal_tracker; signal_tracker._init_db(); print('✅ Database connected')"
```

### Integration Testing

- [ ] Signal generation tracked (check `signal_events` table after signal detected)
- [ ] Validation result tracked (both pass and fail cases)
- [ ] Armed signals tracked (after confirmation)
- [ ] Trade execution linked to signal
- [ ] Alerts trigger correctly (test circuit breaker warning)
- [ ] Hourly digest sends at :00 minutes
- [ ] EOD digest generates and prints
- [ ] CSV export works (check `reports/` directory)

### Query to Check Signal Tracking

```sql
-- Check recent signal events
SELECT 
    ticker, 
    stage, 
    signal_type, 
    grade, 
    base_confidence,
    timestamp
FROM signal_events 
ORDER BY timestamp DESC 
LIMIT 20;

-- Check signal funnel
SELECT 
    stage, 
    COUNT(*) as count 
FROM signal_events 
WHERE session_date = CURRENT_DATE 
GROUP BY stage;
```

---

## Deployment to Railway

### Step 1: Commit Changes

```bash
git add sniper.py signal_validator.py position_manager.py
git commit -m "feat: Integrate Phase 4 monitoring

- Add signal tracking to signal generation
- Add validation result tracking
- Add armed signal tracking
- Add trade execution linking
- Integrate alert system in main loop
- Add EOD digest generation

Phase 4 monitoring now fully integrated."
git push origin main
```

### Step 2: Railway Auto-Deploy

Railway will automatically deploy the changes. Monitor the deployment:

1. Go to Railway dashboard
2. Click on your War-Machine service
3. Go to "Deployments" tab
4. Watch the build/deploy progress
5. Check logs for any errors

### Step 3: Verify Deployment

Once deployed, check Railway logs:

```
[INFO] Signal tracker initialized
[INFO] Performance monitor ready
[INFO] Alert manager configured
[INFO] EOD digest manager ready
```

### Step 4: Monitor First Session

Watch for:
- Signal generation events in logs
- Validation pass/fail messages
- Hourly digest at top of each hour
- EOD digest at market close
- Discord alerts (if configured)

---

## Troubleshooting

### Issue: Import errors

**Error:** `ModuleNotFoundError: No module named 'signal_analytics'`

**Fix:** Ensure all Phase 4 files are committed and pushed to repository.

```bash
ls -la | grep -E "signal_analytics|performance_monitor|performance_alerts|eod_digest"
git add *.py
git push origin main
```

### Issue: Database errors

**Error:** `relation "signal_events" does not exist`

**Fix:** Run the CREATE TABLE SQL above in Railway PostgreSQL.

### Issue: No signals being tracked

**Problem:** `signal_events` table empty after running.

**Debug:**
1. Check if `record_signal_generated()` is being called (add print statement)
2. Verify ticker name is correct
3. Check database connection in Railway logs
4. Query database directly to confirm inserts

### Issue: Alerts not sending

**Problem:** No Discord alerts appearing.

**Debug:**
1. Check `config.py` has `ALERTS_ENABLED = True`
2. Verify Discord webhook URL is configured
3. Check Railway environment variables
4. Test webhook manually with curl

### Issue: EOD digest not generating

**Problem:** No digest at market close.

**Debug:**
1. Verify EOD routine is called (add print statement)
2. Check timezone handling (should use ET)
3. Confirm market close time logic (4:00 PM ET)
4. Check Railway logs at 4:00 PM ET

---

## Validation Queries

### Check Signal Funnel Today

```sql
SELECT 
    stage,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM signal_events
WHERE session_date = CURRENT_DATE
GROUP BY stage
ORDER BY 
    CASE stage
        WHEN 'GENERATED' THEN 1
        WHEN 'VALIDATED' THEN 2
        WHEN 'REJECTED' THEN 3
        WHEN 'ARMED' THEN 4
        WHEN 'TRADED' THEN 5
    END;
```

### Check Grade Distribution

```sql
SELECT 
    grade,
    COUNT(*) as signals,
    COUNT(DISTINCT ticker) as unique_tickers
FROM signal_events
WHERE stage = 'GENERATED'
  AND session_date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY grade
ORDER BY grade;
```

### Check Validation Pass Rate

```sql
SELECT 
    COUNT(CASE WHEN stage = 'VALIDATED' THEN 1 END) as passed,
    COUNT(CASE WHEN stage = 'REJECTED' THEN 1 END) as rejected,
    ROUND(
        COUNT(CASE WHEN stage = 'VALIDATED' THEN 1 END) * 100.0 / 
        (COUNT(CASE WHEN stage = 'VALIDATED' THEN 1 END) + COUNT(CASE WHEN stage = 'REJECTED' THEN 1 END)),
        1
    ) as pass_rate_pct
FROM signal_events
WHERE session_date = CURRENT_DATE;
```

---

## Expected Outcomes

After successful deployment, you should see:

### During Market Hours:
- ✅ Signal generation events in logs
- ✅ Validation pass/fail tracking
- ✅ Armed signals when confirmed
- ✅ Trade execution links
- ✅ Hourly P&L digests (every hour at :00)
- ✅ Real-time alerts for:
  - Circuit breaker warnings
  - Daily profit target hit
  - Win/loss streaks
  - Risk exposure warnings

### At Market Close (4:00 PM ET):
- ✅ Comprehensive daily digest printed
- ✅ EOD summary sent to Discord
- ✅ CSV export of daily data
- ✅ Weekly digest (Fridays only)

### In Database:
- ✅ `signal_events` table populated with signal lifecycle
- ✅ `positions` table linked to signals via `position_id`
- ✅ Complete audit trail from signal → validation → confirmation → trade

---

## Next Steps After Deployment

### Week 1:
- Monitor signal funnel daily
- Verify all tracking points working
- Check for any errors in Railway logs
- Review first EOD digests

### Week 2:
- Collect 10+ trading days of data
- Review weekly digest (Friday)
- Identify any tracking gaps
- Tune alert thresholds if needed

### Week 3-4:
- Run parameter optimizer after 14 days
- Generate optimization report
- Review recommendations
- Implement tuned parameters

### After 1 Month:
- Complete performance analysis
- Compare pre/post monitoring metrics
- Identify system improvements
- Move to Phase 5 (ML features)

---

## Summary

**Integration Points:** 7 total
1. ✅ Import statements (1 location)
2. ✅ Signal generation tracking (1 location)
3. ✅ Validation tracking (1 location)
4. ✅ Armed signal tracking (1 location)
5. ✅ Trade execution tracking (1 location)
6. ✅ Alert system (1 location)
7. ✅ EOD processing (1 location)

**Time Estimate:** 2-3 hours
**Difficulty:** Medium (mostly copy-paste)
**Risk:** Low (monitoring doesn't affect trading logic)
**Benefit:** Complete visibility + automated optimization

---

**Ready to start integration? Begin with Step 1 and work through each step sequentially. Test after each integration point before moving to the next!**
