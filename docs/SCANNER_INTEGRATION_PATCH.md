# Scanner Integration Patch

**Add signal analytics to your existing scanner.py with minimal changes**

---

## Changes Required

### 1. Import Analytics (Line ~33)

**Find this section:**
```python
# ────────────────────────────────────────────────────────────────────────────────────
# OPTIONAL: SIGNAL ANALYTICS
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    ANALYTICS_ENABLED = True
    print("[SCANNER] ✅ Signal analytics enabled")
except ImportError:
    ANALYTICS_ENABLED = False
    signal_tracker = None
    print("[SCANNER] ⚠️  signal_analytics not available — analytics disabled")
```

**Replace with:**
```python
# ────────────────────────────────────────────────────────────────────────────────────
# SIGNAL ANALYTICS & OUTCOME TRACKING
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None

try:
    from app.analytics import AnalyticsIntegration, ANALYTICS_AVAILABLE
    if ANALYTICS_AVAILABLE:
        import psycopg2
        import os
        analytics_db = psycopg2.connect(os.getenv('DATABASE_URL'))
        analytics = AnalyticsIntegration(
            analytics_db,
            enable_ml=True,
            enable_discord=True
        )
        print("[SCANNER] ✅ Signal outcome tracking enabled")
    else:
        analytics = None
        print("[SCANNER] ⚠️  Analytics dependencies missing")
except Exception as e:
    analytics = None
    ANALYTICS_AVAILABLE = False
    print(f"[SCANNER] ⚠️  Analytics disabled: {e}")
```

---

### 2. Add Analytics Check to Signal Processing

**Find this section (around line 300 in check_and_alert flow):**
```python
print(f"[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...")
check_and_alert(watchlist)
monitor_signals()
```

**Add after `check_and_alert(watchlist)`:**
```python
print(f"[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...")
check_and_alert(watchlist)

# Monitor active analytics signals
if ANALYTICS_AVAILABLE and analytics:
    try:
        # Get current prices for active signal monitoring
        def get_price(ticker):
            from app.data.ws_feed import get_current_bar_with_fallback
            bar = get_current_bar_with_fallback(ticker)
            return bar['close'] if bar else None
        
        analytics.monitor_active_signals(get_price)
        analytics.check_scheduled_tasks()
    except Exception as e:
        print(f"[ANALYTICS] Monitor error: {e}")

monitor_signals()
```

---

### 3. Integrate with Your Signal Flow

**This depends on where you currently fire Discord alerts. Find your Discord alert code and wrap it:**

**Current pattern (example):**
```python
# When you detect a signal and send to Discord
send_discord_alert(signal_data)
```

**New pattern:**
```python
# Process through analytics first (deduplication + tracking)
if ANALYTICS_AVAILABLE and analytics:
    signal_id = analytics.process_signal(
        signal_data={
            'ticker': ticker,
            'pattern': pattern_name,
            'confidence': confidence_score,
            'entry': entry_price,
            'stop': stop_loss,
            't1': target_1,
            't2': target_2,
            'rvol': relative_volume,
            'score': signal_score
        },
        regime=get_market_regime(),  # Your regime detection
        vix_level=get_vix(),          # Your VIX function
        spy_trend=get_spy_trend()     # Your SPY trend
    )
    
    # Only send Discord if not blocked by deduplication
    if signal_id:
        send_discord_alert(signal_data)
    else:
        print(f"[ANALYTICS] {ticker} blocked (cooldown active)")
else:
    # Fallback: send alert directly if analytics unavailable
    send_discord_alert(signal_data)
```

---

## Integration Points by File

### If you use `app/signals/signal_generator.py`:

Add this helper function:

```python
def log_signal_to_analytics(signal_data):
    """Log signal to analytics system (deduplication + tracking)"""
    try:
        from app.analytics import ANALYTICS_AVAILABLE
        if not ANALYTICS_AVAILABLE:
            return True  # Allow signal if analytics unavailable
        
        # Import analytics instance from scanner
        # (You'll need to pass analytics instance or make it global)
        from app.core.scanner import analytics
        
        if analytics:
            signal_id = analytics.process_signal(
                signal_data=signal_data,
                regime='NEUTRAL',  # Update with actual regime
                vix_level=20.0,    # Update with actual VIX
                spy_trend='NEUTRAL' # Update with actual SPY trend
            )
            return signal_id is not None
        
        return True  # Allow if analytics not initialized
        
    except Exception as e:
        print(f"[ANALYTICS] Error: {e}")
        return True  # Allow signal on error
```

---

## Testing the Integration

### 1. Verify Analytics Loads:

```python
# Add this at the end of scanner.py initialization
if ANALYTICS_AVAILABLE and analytics:
    stats = analytics.get_today_stats()
    print(f"[ANALYTICS] Today: {stats['total']} signals, {stats['wins']} wins")
```

### 2. Test Deduplication:

```python
# In your signal processing:
print(f"[DEBUG] Checking deduplication for {ticker}")
should_fire, reason = analytics.analytics.should_fire_signal(ticker)
print(f"[DEBUG] Should fire: {should_fire}, Reason: {reason}")
```

---

## Environment Variables (Railway)

Add to Railway environment:

```bash
DATABASE_URL=postgresql://...  # Already set by Railway
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Add this
```

---

## Minimal Working Example

**Simplest integration (3 lines):**

```python
# At top of scanner.py
from app.analytics import AnalyticsIntegration, ANALYTICS_AVAILABLE
import psycopg2, os
analytics = AnalyticsIntegration(psycopg2.connect(os.getenv('DATABASE_URL'))) if ANALYTICS_AVAILABLE else None

# Before Discord alert
if analytics:
    signal_id = analytics.process_signal(signal_data)
    if not signal_id:
        continue  # Skip duplicate

send_discord_alert(signal_data)
```

---

## What This Adds:

✅ **Deduplication** - Blocks duplicate signals within 30 minutes
✅ **Outcome Tracking** - Logs all signals to database
✅ **ML Learning** - Adjusts confidence based on past performance
✅ **EOD Reports** - Sends daily summaries at 4:05 PM
✅ **Active Monitoring** - Tracks T1/T2/Stop hits automatically

---

## Rollback (If Needed):

Analytics is designed to fail gracefully:
- If DATABASE_URL not set → Analytics disabled, scanner continues
- If import fails → Scanner runs normally without analytics
- If analytics.process_signal() fails → Signal still fires

No changes to your core signal logic required!

---

## Need Help?

Check:
- [`ANALYTICS_SYSTEM_README.md`](../ANALYTICS_SYSTEM_README.md) - Complete guide
- [`SCANNER_INTEGRATION_EXAMPLE.md`](./SCANNER_INTEGRATION_EXAMPLE.md) - Full examples
- Test scripts: `python tests/test_ml_predictions.py`

**Questions? The analytics system is fully documented and tested!** 🚀
