# Phase 4 Monitoring Integration Guide

Phase 4 files exist but are **NOT** wired into the main execution flow. This guide shows where to add the integration points.

---

## ✅ Fixed Issues

### Database Schema Issue (RESOLVED)
- **Problem:** `performance_monitor.py` queried `realized_pnl` column but positions table uses `pnl`
- **Fix:** Updated all queries in `performance_monitor.py` to use `pnl` column ([commit a3b7d2e](https://github.com/AlgoOps25/War-Machine/commit/a3b7d2ee6052585966c92f2646815966d1d26286))
- **Status:** ✅ No more Railway crashes from missing column

---

## 🔌 Integration Points

### File 1: `signal_analytics.py`
**Purpose:** Tracks signal lifecycle (GENERATED → VALIDATED → ARMED → TRADED → CLOSED)

#### Integration Points:

**1. After pattern detection in `sniper.py`:**
```python
# After detecting OR breakout or BOS+FVG pattern
from signal_analytics import signal_tracker

event_id = signal_tracker.record_signal_generated(
    ticker=ticker,
    signal_type="CFW6_OR" or "CFW6_INTRADAY",
    direction="bull" or "bear",
    grade=grade,  # "A+", "A", or "A-"
    confidence=base_confidence,
    entry_price=entry_price,
    stop_price=stop_loss,
    t1_price=t1,
    t2_price=t2
)
```

**2. After validation in `signal_validator.py`:**
```python
# After applying ADX/DMI/Volume/VPVR checks and multipliers
from signal_analytics import signal_tracker

event_id = signal_tracker.record_validation_result(
    ticker=ticker,
    passed=True or False,
    confidence_after=final_confidence,
    ivr_multiplier=ivr_mult,
    uoa_multiplier=uoa_mult,
    gex_multiplier=gex_mult,
    mtf_boost=mtf_boost,
    ticker_multiplier=ticker_mult,
    ivr_label="IVR-FAVORABLE",
    uoa_label="UOA-ALIGNED-CALL",
    gex_label="GEX-POSITIVE",
    checks_passed=["ADX", "VOLUME", "DMI", "VPVR"],
    rejection_reason="" if passed else "ADX too weak"
)
```

**3. After confirmation in `sniper.py`:**
```python
# After wait_for_confirmation() returns True
from signal_analytics import signal_tracker

event_id = signal_tracker.record_signal_armed(
    ticker=ticker,
    final_confidence=final_confidence,
    bars_to_confirmation=bars_waited,
    confirmation_type="retest" or "rejection"
)
```

**4. Trade execution already wired** ✅
- `position_manager.py` already has Phase 4 integration point
- Calls `signal_tracker.record_trade_executed()` when position opens
- See `position_manager.py` lines 467-476

**5. EOD summary in `sniper.py`:**
```python
# At end of trading day, before closing
from signal_analytics import signal_tracker

print(signal_tracker.get_daily_summary())

funnel_stats = signal_tracker.get_funnel_stats()
print(f"Signal Funnel: {funnel_stats['generated']} → {funnel_stats['validated']} → "
      f"{funnel_stats['armed']} → {funnel_stats['traded']}")
```

---

### File 2: `performance_monitor.py`
**Purpose:** Real-time P&L tracking, risk metrics, circuit breaker monitoring

#### Integration Points:

**1. Initialization in `sniper.py` (top of file):**
```python
from performance_monitor import performance_monitor
```

**2. Before opening any position:**
```python
# Check circuit breaker BEFORE calling position_manager.open_position()
cb_status = performance_monitor.get_circuit_breaker_status()
if cb_status['triggered']:
    print(f"[RISK] 🛑 Circuit breaker triggered - No new positions")
    continue  # Skip this signal
```

**3. Periodic dashboard updates (every 30-60 minutes):**
```python
# In main loop, check if it's been 30+ minutes since last dashboard
if time_since_last_dashboard > 30 * 60:
    print(performance_monitor.get_live_dashboard())
    last_dashboard_time = datetime.now()
```

**4. EOD report:**
```python
# At end of trading day, before closing all positions
print(performance_monitor.get_daily_performance_report())
```

**5. Discord alerts for risk warnings:**
```python
# After each trade closes, check exposure
risk = performance_monitor.get_risk_exposure()
if risk['approaching_limits']:
    for warning in risk['approaching_limits']:
        send_discord_message(f"⚠️ {warning}")
```

---

### File 3: `performance_alerts.py`
**Purpose:** Alert manager for performance thresholds (win streaks, loss streaks, drawdown)

#### Integration Points:

**1. Import in `sniper.py`:**
```python
from performance_alerts import alert_manager
```

**2. After each position closes:**
```python
# In position_manager.close_position() or after check_exits()
alerts = alert_manager.check_all_conditions()
if alerts:
    for alert in alerts:
        print(f"[ALERT] {alert['emoji']} {alert['title']}")
        print(f"        {alert['message']}")
        # Optionally send to Discord
        send_discord_message(f"{alert['emoji']} {alert['title']}\n{alert['message']}")
```

**3. Periodic checks (every 15-30 minutes):**
```python
# In main loop
if time_since_last_alert_check > 15 * 60:
    alerts = alert_manager.check_all_conditions()
    for alert in alerts:
        # Send Discord notification
        send_discord_message(f"{alert['emoji']} {alert['title']}\n{alert['message']}")
    last_alert_check = datetime.now()
```

---

## 📊 Full Integration Example

Here's how a complete signal flow would look with Phase 4 integrated:

```python
# In sniper.py main loop

for ticker in tickers:
    # 1. Pattern Detection
    if or_breakout_detected:
        event_id = signal_tracker.record_signal_generated(
            ticker=ticker, signal_type="CFW6_OR", direction="bull",
            grade="A", confidence=0.72, entry_price=595.50, ...
        )
        
        # 2. Validation
        if signal_validator.validate(ticker):
            signal_tracker.record_validation_result(
                ticker=ticker, passed=True, confidence_after=0.81, ...
            )
            
            # 3. Confirmation
            if wait_for_confirmation(ticker):
                signal_tracker.record_signal_armed(
                    ticker=ticker, final_confidence=0.81, bars_to_confirmation=3
                )
                
                # 4. Risk Check
                cb_status = performance_monitor.get_circuit_breaker_status()
                if cb_status['triggered']:
                    print("[RISK] Circuit breaker - skipping trade")
                    continue
                
                # 5. Open Position
                position_id = position_manager.open_position(...)
                # signal_tracker.record_trade_executed() called inside open_position()
                
                # 6. Check Alerts
                alerts = alert_manager.check_all_conditions()
                for alert in alerts:
                    send_discord_message(f"{alert['emoji']} {alert['title']}")
        else:
            signal_tracker.record_validation_result(
                ticker=ticker, passed=False, rejection_reason="ADX too weak"
            )

# EOD Reports
print(signal_tracker.get_daily_summary())
print(performance_monitor.get_daily_performance_report())
```

---

## 🎯 Quick Win: Minimum Viable Integration

If you want Phase 4 working **today**, add these 3 lines:

### 1. In `sniper.py` at EOD (before `position_manager.close_all_eod()`):
```python
try:
    from signal_analytics import signal_tracker
    print(signal_tracker.get_daily_summary())
except Exception as e:
    print(f"[PHASE 4] Analytics error: {e}")

try:
    from performance_monitor import performance_monitor
    print(performance_monitor.get_daily_performance_report())
except Exception as e:
    print(f"[PHASE 4] Monitor error: {e}")
```

### 2. In `sniper.py` before opening positions:
```python
try:
    from performance_monitor import performance_monitor
    cb = performance_monitor.get_circuit_breaker_status()
    if cb['triggered']:
        print("[RISK] 🛑 Circuit breaker triggered - skipping signals")
        continue
except Exception as e:
    print(f"[PHASE 4] Circuit breaker check error: {e}")
```

That's it! Phase 4 will now provide:
- ✅ EOD signal funnel analysis
- ✅ EOD performance dashboard with best/worst trades
- ✅ Circuit breaker protection

---

## 📝 Testing Phase 4

To test without live trading:

```bash
# Test signal analytics
python signal_analytics.py

# Test performance monitor
python performance_monitor.py

# Test alert manager
python performance_alerts.py
```

All three files have standalone test harnesses at the bottom.

---

## 🚀 Next Steps

1. **Add EOD reports** (5 minutes) - Just the 3 lines above
2. **Add circuit breaker** (5 minutes) - The before-position check
3. **Full lifecycle tracking** (30 minutes) - All 5 signal_tracker calls
4. **Alert system** (15 minutes) - Wire up alert_manager after position closes
5. **Dashboard polling** (10 minutes) - Periodic live dashboard in main loop

**Total time to full integration: ~1 hour**
