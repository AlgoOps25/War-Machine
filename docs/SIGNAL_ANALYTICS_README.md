# War Machine Signal Analytics System

## Overview

The Signal Analytics system tracks all signal outcomes, learns from wins/losses, and prevents duplicate signals.

## Features

### 1. **Signal Deduplication (30-min Cooldown)**
- Prevents same ticker from firing multiple times within 30 minutes
- Fixes duplicate signal issue (META fired at 9:59 AM + 10:29 AM)
- Tracks `fired_today` dict with last signal time per ticker

### 2. **Outcome Tracking**
- Monitors active signals for T1/T2 hits or stop loss
- Auto-closes after 30 minutes with time-based exit
- Logs all outcomes to PostgreSQL database

### 3. **ML Feedback Loop**
- Trains Random Forest model on past signal outcomes
- Adjusts confidence scoring based on win probability:
  - 70%+ win prob → +10% confidence boost
  - 60-70% win prob → +5% confidence boost
  - 50-60% win prob → No adjustment
  - 40-50% win prob → -5% confidence penalty
  - <40% win prob → -15% confidence penalty

### 4. **Performance Reporting**
- Daily EOD summaries (W/L, P&L, avg hold time)
- Pattern performance breakdown
- Top/worst trades of the day

## Database Schema

### Tables:
1. **`signal_outcomes`** - Main tracking (entry, exit, P&L, hold time)
2. **`pattern_performance`** - Aggregate stats by pattern type
3. **`ml_training_data`** - Features for ML model training

## Integration

### Step 1: Create Database Tables
```bash
psql $DATABASE_URL -f database/signal_outcomes_schema.sql
```

### Step 2: Add to main.py
```python
from src.analytics import SignalAnalytics, MLFeedbackLoop

# Initialize
analytics = SignalAnalytics(db_connection)
ml_loop = MLFeedbackLoop(db_connection)
ml_loop.load_model()  # Load existing model if available

# At market open (9:30 AM)
analytics.reset_daily_cooldowns()

# Before sending Discord alert
should_fire, reason = analytics.should_fire_signal(ticker)
if not should_fire:
    logging.info(f"⏸️ {ticker} blocked: {reason}")
    continue

# Get ML prediction
signal_features = {
    'rvol': rvol,
    'vix': vix,
    'score': score,
    'time_of_day': datetime.now().strftime('%H:%M'),
    'confidence': confidence,
    'regime': regime
}
win_prob, confidence_adj = ml_loop.predict_signal_quality(signal_features)
adjusted_confidence = int(confidence * confidence_adj)

# Log signal
signal_id = analytics.log_signal({
    'ticker': ticker,
    'signal_time': datetime.now(),
    'pattern': 'BOS/FVG Breakout',
    'confidence': adjusted_confidence,
    'entry_price': entry,
    'stop_loss': stop,
    'target_1': t1,
    'target_2': t2,
    'regime': regime,
    'vix_level': vix,
    'spy_trend': spy_trend,
    'rvol': rvol,
    'score': score,
    'explosive_override': explosive_override
})

# In scanner loop (every minute)
current_prices = {'SPY': spy_price, 'NVDA': nvda_price, ...}
analytics.monitor_active_signals(current_prices)

# At market close (4:00 PM)
ml_loop.retrain_daily()
```

## Bootstrap Data

The schema includes your NVDA winner from today:
- Entry: $181.61 @ 9:40 AM
- Exit: $184.50 @ 10:01 AM (60% to T1)
- Profit: +1.59% (1.99R)
- Hold: 21 minutes
- Pattern: BOS/FVG Breakout with 100% MTF convergence

## Requirements

Add to `requirements.txt`:
```
joblib>=1.3.0
scikit-learn>=1.3.0
```

## Logs Example

```
[ANALYTICS] ✅ Signal logged: NVDA (ID: 1)
[ML] Signal quality: 85.0% win prob | Confidence adj: 1.10x
[ANALYTICS] ⏸️ META signal blocked: Cooldown active (15m / 30m)
[ANALYTICS] 🎯 NVDA T1 HIT @ $184.50
[ANALYTICS] ✅ NVDA closed: WIN | P&L: +1.59% (1.99R) | Hold: 21m
[TODAY] Trades: 1 | W/L: 1/0 | P&L: +1.59%
```
