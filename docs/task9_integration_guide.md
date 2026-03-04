# Task 9: Funnel Analytics Integration Guide

## Overview

Task 9 adds comprehensive funnel analytics and A/B testing to War Machine:

1. **Funnel Tracker** - Tracks signal progression through 7 stages
2. **A/B Test Framework** - Tests parameter variants for optimization
3. **Discord EOD Report** - Automated daily summaries

---

## Signal Funnel Stages

```
SCREENED → BOS → FVG → VALIDATOR → ARMED → FIRED → FILLED
```

- **SCREENED**: Ticker appears in pre-market scanner
- **BOS**: Break of Structure detected
- **FVG**: Fair Value Gap confirmed
- **VALIDATOR**: Passes signal_validator.py checks
- **ARMED**: Confirmation via wait_for_confirmation()
- **FIRED**: Signal sent to Discord / Position opened
- **FILLED**: Order filled successfully

---

## Integration Points

### 1. Pre-Market Scanner (`premarket_scanner.py`)

```python
from app.analytics import log_screened

# When ticker appears in scanner
for ticker in top_movers:
    log_screened(ticker, passed=True)
```

### 2. BOS Detector (`app/signals/breakout_detector.py`)

```python
from app.analytics import log_bos

# When checking for BOS
if bos_detected:
    log_bos(ticker, passed=True)
else:
    log_bos(ticker, passed=False, reason='no_bos_pattern')
```

### 3. FVG Detector (`app/signals/signal_generator.py`)

```python
from app.analytics import log_fvg

# When checking FVG
if fvg_detected:
    log_fvg(ticker, passed=True, confidence=0.75)
else:
    log_fvg(ticker, passed=False, reason='no_fvg')
```

### 4. Signal Validator (`app/signals/signal_validator.py`)

```python
from app.analytics import log_validator

# After validation checks
if passed:
    log_validator(ticker, passed=True, confidence=final_confidence)
else:
    log_validator(ticker, passed=False, reason='low_volume', confidence=base_confidence)
```

### 5. Signal Armed (`sniper.py` or signal pipeline)

```python
from app.analytics import log_armed

# After wait_for_confirmation() passes
log_armed(ticker, confidence=0.85)
```

### 6. Signal Fired (Discord send or position open)

```python
from app.analytics import log_fired

# When signal sent to Discord
await send_signal_to_discord(signal)
log_fired(ticker, confidence=0.88)
```

### 7. Order Filled (`position_manager.py`)

```python
from app.analytics import log_filled

# When order confirmed filled
if order.status == 'filled':
    log_filled(ticker)
```

---

## A/B Testing Integration

### Using A/B Test Parameters

```python
from app.analytics import ab_test

# Get volume threshold for this ticker (A/B tested)
volume_threshold = ab_test.get_param(ticker, 'volume_threshold')

if rvol >= volume_threshold:
    # Signal passes volume check
    pass
```

### Recording Outcomes

```python
from app.analytics import ab_test

# After trade closes
if hit_target:
    ab_test.record_outcome(ticker, 'volume_threshold', hit_target=True)
else:
    ab_test.record_outcome(ticker, 'volume_threshold', hit_target=False)
```

### Available Parameters

- `volume_threshold`: RVOL threshold (2.0 vs 3.0)
- `min_confidence`: Minimum confidence (60 vs 70)
- `cooldown_minutes`: Cooldown between signals (10 vs 15)
- `atr_stop_multiplier`: Stop loss multiplier (2.0 vs 2.5)
- `lookback_bars`: Pattern lookback period (10 vs 15)

---

## Discord EOD Report Setup

### Option 1: Event Loop Integration

Add to your main event loop (`main.py` or `sniper.py`):

```python
from app.analytics.eod_discord_report import send_eod_report, should_send_eod_report
import asyncio

# In your main loop
while True:
    if should_send_eod_report():
        asyncio.run(send_eod_report())
    
    await asyncio.sleep(60)  # Check every minute
```

### Option 2: Scheduled Task (Railway Cron)

Create `eod_report_cron.py`:

```python
import asyncio
from app.analytics.eod_discord_report import send_eod_report

if __name__ == "__main__":
    asyncio.run(send_eod_report())
```

Schedule in Railway:
```bash
0 16 * * 1-5 python eod_report_cron.py
```

---

## Testing Locally

Run the test suite:

```bash
python test_task9_funnel_analytics.py
```

**Expected Output:**
- ✅ All tests passing
- Funnel report showing test signals
- A/B test report showing variant assignments

---

## Monitoring Production

### Railway Logs to Watch For:

```
[FUNNEL] Funnel analytics database initialized
[AB_TEST] A/B test framework database initialized
[DISCORD] EOD report sent to channel #war-machine-signals
```

### Discord EOD Report (4:15 PM ET):

```
📊 EOD REPORT - War Machine
Session: 2026-03-04

🔍 Signal Funnel
SCREENED      45
BOS           28  (62.2% of SCREENED)
FVG           18  (64.3% of BOS)
VALIDATOR     12  (66.7% of FVG)
ARMED          8  (66.7% of VALIDATOR)
FIRED          6  (75.0% of ARMED)
FILLED         5  (83.3% of FIRED)

❌ Top Rejections
1. low_volume: 8x
2. vix_too_high: 5x
3. no_fvg: 4x
4. failed_adx: 3x
5. cooldown_active: 2x

🏆 A/B Test Winners
volume_threshold: B=3.0 (71.2% vs 62.5%)
```

---

## Database Schema

### `funnel_events` Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| ticker | TEXT | Stock symbol |
| session | TEXT | Trading date |
| stage | TEXT | Funnel stage |
| passed | INTEGER | 1=passed, 0=failed |
| reason | TEXT | Rejection reason (if failed) |
| confidence | REAL | Signal confidence |
| timestamp | TIMESTAMP | Event timestamp |
| signal_id | TEXT | Optional signal ID |
| hour | INTEGER | Hour of day (0-23) |

### `ab_test_results` Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| ticker | TEXT | Stock symbol |
| param_name | TEXT | Parameter name |
| variant | TEXT | 'A' or 'B' |
| param_value | TEXT | Parameter value used |
| outcome | INTEGER | 1=win, 0=loss |
| session | TEXT | Trading date |
| timestamp | TIMESTAMP | Event timestamp |

---

## Troubleshooting

### "No signals today" in funnel report
- Check that funnel tracking calls are in place
- Verify database connection
- Check Railway logs for errors

### A/B test shows 0 samples
- Record outcomes after trades close
- Wait for 30+ samples per variant
- Check `ab_test_results` table

### Discord report not sending
- Verify `DISCORD_BOT_TOKEN` in config
- Verify `DISCORD_CHANNEL_ID` in config
- Check bot permissions (send messages, embeds)
- Check Railway logs for Discord errors

---

## Performance Impact

- **Funnel tracking**: ~1ms per event (async DB write)
- **A/B test lookup**: ~0.1ms (in-memory hash)
- **EOD report**: Runs once daily, no runtime impact

---

## Next Steps

1. Deploy to Railway: `git push origin main`
2. Monitor first day for funnel stats
3. Wait 30 days for A/B test winners
4. Promote winning parameters to production
5. Create new A/B tests for other parameters
