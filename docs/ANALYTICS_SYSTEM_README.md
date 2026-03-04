# 🚀 War Machine Analytics System

**Complete signal tracking, ML learning, and performance reporting for War Machine scanner**

---

## 🎯 What This System Does

### **Fixes Today's Problem:**
- ❌ **BEFORE:** META fired at 9:59 AM + 10:29 AM (duplicate alert)
- ❌ **BEFORE:** QQQ fired at 10:09 AM + 10:25 AM (duplicate alert)
- ✅ **AFTER:** 30-minute cooldown blocks duplicate signals automatically

### **Automatic Outcome Tracking:**
- ✅ Tracks every signal fired
- ✅ Monitors for T1/T2/Stop hits
- ✅ Calculates profit %, R-multiples, hold time
- ✅ Auto-closes positions after 30 minutes

### **ML Learning:**
- ✅ Trains on past winners/losers
- ✅ Predicts win probability for new signals
- ✅ Adjusts confidence (±15%) based on quality
- ✅ Improves over time as you trade

### **Daily Reports:**
- ✅ EOD performance summaries at 4:05 PM
- ✅ Pattern-specific stats
- ✅ Best/worst trades
- ✅ Sent via Discord webhook

---

## 🛠️ Setup (First Time)

### **1. Database Setup**

```powershell
# Set your Railway DATABASE_URL
$env:DATABASE_URL = "postgresql://postgres:PASSWORD@HOST.railway.app:PORT/railway"

# Create tables
python setup_database.py
```

**Output:**
```
✅ Database tables created successfully!
Tables created:
  • signal_outcomes (main tracking)
  • pattern_performance (aggregate stats)
  • ml_training_data (ML features)
```

### **2. Verify Installation**

```powershell
# Test analytics module
python -c "
from src.analytics.signal_analytics import SignalAnalytics
import psycopg2, os
db = psycopg2.connect(os.getenv('DATABASE_URL'))
analytics = SignalAnalytics(db)
print('✅ Analytics working!')
"
```

### **3. Configure Discord (Optional)**

```powershell
# Get webhook URL from Discord:
# Server Settings → Integrations → Webhooks → New Webhook

$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"

# Add to Railway environment variables for production
```

---

## 💻 Integration into Scanner

### **Option 1: Easy Integration (Recommended)**

Use the helper class:

```python
# In your scanner.py
from app.core.analytics_integration import AnalyticsIntegration

class Scanner:
    def __init__(self, db_connection):
        self.db = db_connection
        
        # Initialize analytics
        self.analytics = AnalyticsIntegration(db_connection)
    
    def process_signals(self, signals):
        for signal in signals:
            # Process through analytics (deduplication + ML + logging)
            signal_id = self.analytics.process_signal(
                signal_data=signal,
                regime=self.get_regime(),
                vix_level=self.get_vix(),
                spy_trend=self.get_spy_trend()
            )
            
            # Only send Discord if not blocked
            if signal_id:
                self.send_discord_alert(signal)
    
    def run(self):
        while self.is_market_open():
            signals = self.scan_for_signals()
            self.process_signals(signals)
            
            # Monitor active signals
            self.analytics.monitor_active_signals(
                price_fetcher=self.get_current_price
            )
            
            # Run scheduled tasks
            self.analytics.check_scheduled_tasks()
            
            time.sleep(60)
```

**Full example:** See [`docs/SCANNER_INTEGRATION_EXAMPLE.md`](docs/SCANNER_INTEGRATION_EXAMPLE.md)

### **Option 2: Manual Integration**

See [`docs/SIGNAL_ANALYTICS_INTEGRATION.md`](docs/SIGNAL_ANALYTICS_INTEGRATION.md) for detailed step-by-step.

---

## ✅ Testing

### **Test 1: Deduplication**

```powershell
python -c "
from src.analytics.signal_analytics import SignalAnalytics
from datetime import datetime
import psycopg2, os

db = psycopg2.connect(os.getenv('DATABASE_URL'))
analytics = SignalAnalytics(db)

print('First signal:', analytics.should_fire_signal('TEST'))
analytics.fired_today['TEST'] = datetime.now()
print('Duplicate signal:', analytics.should_fire_signal('TEST'))
"
```

**Expected:**
```
First signal: (True, 'New signal')
Duplicate signal: (False, 'Cooldown active (0m / 30m)')
```

### **Test 2: ML Predictions**

```powershell
python tests/test_ml_predictions.py
```

**Expected:**
```
🧠 Training ML model...
ML Training: ✅ Success

📊 ML Prediction for TSLA:
   Win Probability: 60.0%
   Confidence Adjustment: +5%
   New Confidence: 80%
```

### **Test 3: Discord Reports**

```powershell
python tests/test_discord_reports.py
```

**Expected:**
```
✅ EOD Report Generated:
   Total Signals: 1
   Wins: 1
   Win Rate: 100.0%
   Total P&L: 1.59%

👌 Sending to Discord...
✅ Report sent to Discord successfully!
```

---

## 📊 How It Works

### **Signal Flow:**

```
1. Scanner finds signal (META at 9:59 AM)
   ↓
2. Analytics.process_signal()
   • Check deduplication → ✅ New signal
   • ML prediction → Confidence +5%
   • Log to database → signal_id = 1
   ↓
3. Send Discord alert
   ↓
4. Monitor every minute:
   • 10:01 AM: Price hits T1 → Mark T1 hit
   • 10:15 AM: Price hits T2 → Close as WIN
   • Calculate: +2.1% profit, 2.8R, 16 min hold
   ↓
5. Same scanner finds META again (10:29 AM)
   ↓
6. Analytics.process_signal()
   • Check deduplication → ❌ Cooldown active
   • BLOCKED → return None
   ↓
7. No Discord alert sent
```

### **Scheduled Tasks:**

```
9:30 AM  → Reset daily cooldowns
4:00 PM  → Train ML model on today's trades
4:05 PM  → Generate and send EOD report
```

---

## 📁 Files & Modules

### **Core Analytics:**
- `src/analytics/signal_analytics.py` - Deduplication, logging, monitoring
- `src/learning/ml_feedback_loop.py` - ML predictions, training
- `src/reporting/performance_reporter.py` - EOD reports, Discord

### **Integration Helper:**
- `app/core/analytics_integration.py` - Easy scanner integration

### **Database:**
- `database/signal_outcomes_schema.sql` - Table definitions
- `setup_database.py` - One-time setup script

### **Tests:**
- `tests/test_ml_predictions.py` - Test ML system
- `tests/test_discord_reports.py` - Test Discord reports

### **Documentation:**
- `docs/SCANNER_INTEGRATION_EXAMPLE.md` - Quick integration guide
- `docs/SIGNAL_ANALYTICS_INTEGRATION.md` - Detailed integration
- `docs/SIGNAL_ANALYTICS_README.md` - Technical details

---

## 🔧 Common Tasks

### **Check Today's Stats:**

```python
from src.analytics.signal_analytics import SignalAnalytics
import psycopg2, os

db = psycopg2.connect(os.getenv('DATABASE_URL'))
analytics = SignalAnalytics(db)
stats = analytics.get_today_stats()
print(stats)
```

### **Manual EOD Report:**

```python
from src.reporting.performance_reporter import PerformanceReporter
import psycopg2, os
from datetime import date

db = psycopg2.connect(os.getenv('DATABASE_URL'))
reporter = PerformanceReporter(db, os.getenv('DISCORD_WEBHOOK_URL'))
report = reporter.generate_eod_report(date.today())
if report:
    reporter.send_to_discord(report)
```

### **Retrain ML Model:**

```python
from src.learning.ml_feedback_loop import MLFeedbackLoop
import psycopg2, os

db = psycopg2.connect(os.getenv('DATABASE_URL'))
ml = MLFeedbackLoop(db)
success = ml.train_model()
print(f'Training: {"Success" if success else "Need more data"}')
```

---

## ⚠️ Troubleshooting

### **"DATABASE_URL not set"**
```powershell
# Get from Railway dashboard: Project → PostgreSQL → Variables
$env:DATABASE_URL = "postgresql://..."
```

### **"Insufficient data for ML training"**
- ML needs 20+ completed trades to train
- System works without ML (no confidence adjustment)
- Keep trading, model will train automatically at 4:00 PM

### **"Discord webhook failed"**
- Check webhook URL is correct
- Test in browser: Paste webhook URL, should show "401: Unauthorized"
- Verify channel permissions in Discord

### **"Signal not blocking duplicates"**
- Verify `analytics.fired_today` is being updated
- Check cooldown window (30 minutes default)
- Ensure `reset_daily_cooldowns()` runs at market open

---

## 📊 Database Schema

### **signal_outcomes**
```sql
id, ticker, signal_time, pattern, confidence, entry_price, 
stop_loss, target_1, target_2, outcome, exit_price, exit_time,
hold_minutes, profit_pct, profit_r, hit_t1, hit_t2, stopped_out,
regime, vix_level, spy_trend, rvol, score, explosive_override
```

### **pattern_performance**
```sql
pattern, total_trades, wins, losses, win_rate, 
avg_profit_pct, avg_hold_minutes
```

### **ml_training_data**
```sql
signal_id, rvol, vix, score, time_of_day, 
confidence, regime, outcome, profit_r
```

---

## 🚀 Deployment (Railway)

### **Environment Variables:**

```bash
DATABASE_URL=postgresql://...  # Auto-set by Railway
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Manual
```

### **On Push to Main:**
1. Railway auto-deploys from GitHub
2. Tables already exist (one-time setup)
3. Scanner starts with analytics enabled
4. System begins logging signals automatically

---

## ✅ Success Checklist

- [ ] Database tables created (`setup_database.py` ran successfully)
- [ ] Analytics imports working (no import errors)
- [ ] Deduplication test passes (blocks duplicates)
- [ ] ML prediction test runs (even if insufficient data)
- [ ] Discord webhook set (optional)
- [ ] Scanner integrated with `AnalyticsIntegration`
- [ ] Test signal logged to database
- [ ] Active signal monitoring working

---

## 📞 Support

**Documentation:**
- [Scanner Integration Example](docs/SCANNER_INTEGRATION_EXAMPLE.md)
- [Detailed Integration Guide](docs/SIGNAL_ANALYTICS_INTEGRATION.md)
- [Technical Details](docs/SIGNAL_ANALYTICS_README.md)

**Quick Links:**
- Test ML: `python tests/test_ml_predictions.py`
- Test Discord: `python tests/test_discord_reports.py`
- Check Stats: `analytics.get_today_stats()`

---

## 🎯 Summary

**3 Lines to Add to Scanner:**
```python
from app.core.analytics_integration import AnalyticsIntegration
self.analytics = AnalyticsIntegration(db_connection)
signal_id = self.analytics.process_signal(signal_data)
```

**Result:**
- ✅ Duplicates blocked (30-min cooldown)
- ✅ Outcomes tracked automatically
- ✅ ML learning enabled
- ✅ Daily reports automated

**Your trading system just got smarter!** 🧠🚀
