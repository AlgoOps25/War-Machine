# Scanner Integration Example

## Quick Integration into `app/core/scanner.py`

This shows exactly what to add to your scanner to enable analytics.

---

## Step 1: Add Import

**Add to top of scanner.py:**

```python
from app.core.analytics_integration import AnalyticsIntegration
```

---

## Step 2: Initialize in Scanner Class

**In your Scanner `__init__` method:**

```python
class Scanner:
    def __init__(self, db_connection, config):
        self.db = db_connection
        self.config = config
        
        # ... your existing initialization ...
        
        # ✅ ADD THIS: Initialize analytics
        self.analytics = AnalyticsIntegration(
            db_connection,
            enable_ml=True,      # Set False to disable ML
            enable_discord=True  # Set False to disable Discord reports
        )
        
        logging.info("[SCANNER] Initialized with analytics")
```

---

## Step 3: Process Signals (CRITICAL - Prevents Duplicates!)

**Find where you send Discord alerts and REPLACE with:**

### ❌ **BEFORE (Without Analytics):**
```python
def process_signals(self, signals):
    for signal in signals:
        # Send Discord alert directly
        self.send_discord_alert(signal)
```

### ✅ **AFTER (With Analytics & Deduplication):**
```python
def process_signals(self, signals):
    for signal in signals:
        # Process through analytics (deduplication + ML + logging)
        signal_id = self.analytics.process_signal(
            signal_data=signal,
            regime=self.get_current_regime(),
            vix_level=self.get_vix(),
            spy_trend=self.get_spy_trend()
        )
        
        # Only send Discord if signal was logged (not blocked)
        if signal_id:
            self.send_discord_alert(signal)
        # Duplicates automatically blocked here!
```

**This single change:**
- ✅ Blocks duplicate signals within 30 minutes
- ✅ Logs all signals to database
- ✅ Applies ML confidence adjustments
- ✅ Tracks outcomes automatically

---

## Step 4: Monitor Active Signals

**In your main scanner loop (runs every 60 seconds):**

```python
def run(self):
    while self.is_market_open():
        # Your existing scan logic
        signals = self.scan_for_signals()
        self.process_signals(signals)
        
        # ✅ ADD THIS: Monitor active signals for T1/T2/Stop
        self.analytics.monitor_active_signals(
            price_fetcher=lambda ticker: self.get_current_price(ticker)
        )
        
        # ✅ ADD THIS: Run scheduled tasks (market open/close)
        self.analytics.check_scheduled_tasks()
        
        # Wait 60 seconds
        time.sleep(60)
```

---

## Step 5: Helper Method for Prices

**Add this method to your Scanner class:**

```python
def get_current_price(self, ticker):
    """Get current price for a ticker"""
    try:
        # Use your existing data client
        quote = self.data_client.get_quote(ticker)
        return quote['price']
    except Exception as e:
        logging.error(f"Failed to get price for {ticker}: {e}")
        return None
```

---

## Complete Example

**Minimal working scanner with analytics:**

```python
import time
import logging
from datetime import datetime
from app.core.analytics_integration import AnalyticsIntegration

class Scanner:
    def __init__(self, db_connection, data_client):
        self.db = db_connection
        self.data_client = data_client
        
        # Initialize analytics
        self.analytics = AnalyticsIntegration(db_connection)
        
    def run(self):
        logging.info("[SCANNER] Starting...")
        
        while self.is_market_open():
            # Scan for signals
            signals = self.scan_for_signals()
            
            # Process each signal
            for signal in signals:
                signal_id = self.analytics.process_signal(
                    signal_data=signal,
                    regime='BULL',  # Replace with actual regime detection
                    vix_level=20.0,  # Replace with actual VIX
                    spy_trend='UP'   # Replace with actual SPY trend
                )
                
                if signal_id:
                    self.send_discord_alert(signal)
            
            # Monitor active signals
            self.analytics.monitor_active_signals(
                price_fetcher=self.get_current_price
            )
            
            # Check scheduled tasks
            self.analytics.check_scheduled_tasks()
            
            time.sleep(60)
    
    def get_current_price(self, ticker):
        quote = self.data_client.get_quote(ticker)
        return quote['price']
    
    def scan_for_signals(self):
        # Your existing signal detection logic
        return []
    
    def is_market_open(self):
        # Your existing market hours check
        return True
    
    def send_discord_alert(self, signal):
        # Your existing Discord alert logic
        pass
```

---

## What This Fixes

### ❌ **Before Integration:**
- META fired at 9:59 AM
- META fired again at 10:29 AM ← **DUPLICATE**
- QQQ fired at 10:09 AM
- QQQ fired again at 10:25 AM ← **DUPLICATE**
- No tracking of outcomes

### ✅ **After Integration:**
```
[ANALYTICS] ✅ META signal logged (ID: 1)
[DISCORD] 🔔 META alert sent

[ANALYTICS] ⏸️ META blocked: Cooldown active (10m / 30m)
← Second META signal automatically blocked!

[ANALYTICS] 🎯 META T1 HIT @ $520.50
[ANALYTICS] ✅ META closed: WIN | P&L: +2.1% (2.8R)
```

---

## Testing the Integration

```powershell
# Test signal processing
python -c "
from app.core.analytics_integration import AnalyticsIntegration
import psycopg2, os
from datetime import datetime

db = psycopg2.connect(os.getenv('DATABASE_URL'))
analytics = AnalyticsIntegration(db)

test_signal = {
    'ticker': 'TEST',
    'pattern': 'GAP_MOVER',
    'confidence': 75,
    'entry': 100.0,
    'stop': 98.0,
    't1': 102.0,
    't2': 104.0,
    'rvol': 3.0,
    'score': 80
}

signal_id = analytics.process_signal(test_signal)
print(f'Signal ID: {signal_id}')

# Try duplicate
signal_id2 = analytics.process_signal(test_signal)
print(f'Duplicate: {signal_id2}')  # Should be None
"
```

---

## Environment Variables

**Set these in Railway or .env:**

```bash
DATABASE_URL=postgresql://...  # Required
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Optional for reports
```

---

## Summary

**3 Lines to Add:**
1. Import: `from app.core.analytics_integration import AnalyticsIntegration`
2. Initialize: `self.analytics = AnalyticsIntegration(db_connection)`
3. Process: `signal_id = self.analytics.process_signal(signal_data)`

**Result:**
- ✅ Duplicate signals blocked
- ✅ All outcomes tracked
- ✅ ML learning enabled
- ✅ Daily reports automated

**You're ready to integrate!** 🚀
