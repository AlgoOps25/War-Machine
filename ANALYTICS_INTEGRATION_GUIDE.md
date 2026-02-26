# Analytics Integration Guide

## 🎯 Overview

This guide shows you how to complete the analytics integration in `signal_generator.py`. Your code already tracks signal generation (✅), but needs to track signal closes to complete the performance loop.

## ✅ Current Status

### What's Already Working:

1. **Signal Generation Tracking** (Line 317-330 in `signal_generator.py`)
   ```python
   if ANALYTICS_ENABLED and signal_tracker:
       signal_id = signal_tracker.record_signal_generated(...)
       signal['signal_id'] = signal_id  # Stored for later use
   ```

2. **Database Schema** - `signal_analytics.db` is created
3. **Analysis Tools** - `daily_analysis.py`, `view_signals.py`, `run_full_analysis.py` all working

### What's Missing:

1. **Signal Close Tracking** - When positions hit stop/target
2. **(Optional) Fill Tracking** - For manual entries on Robinhood

---

## 🔧 Implementation Steps

### Step 1: Add Close Tracking to `_close_signal()` Method

**Location:** `signal_generator.py`, line ~605 (in the `_close_signal()` method)

**Add this code block after P&L calculation and before Discord alert:**

```python
# Log signal outcome to analytics database
if ANALYTICS_ENABLED and signal_tracker and 'signal_id' in signal:
    try:
        outcome = 'win' if pnl > 0 else 'loss'
        signal_tracker.record_signal_closed(
            signal_id=signal['signal_id'],
            exit_price=exit_price,
            outcome=outcome
        )
        print(f"[ANALYTICS] Signal {signal['signal_id']} closed - {outcome.upper()} (${pnl:.2f}, {pnl_pct:+.2f}%)")
    except Exception as e:
        print(f"[ANALYTICS] Close tracking error: {e}")
```

**Full method should look like:**

```python
def _close_signal(self, ticker: str, status: str, exit_price: float) -> None:
    if ticker not in self.active_signals:
        return
    
    signal = self.active_signals[ticker]
    entry = signal['entry']
    
    # Calculate P&L
    if signal['signal'] == 'BUY':
        pnl = exit_price - entry
        pnl_pct = (pnl / entry) * 100
    else:  # SELL
        pnl = entry - exit_price
        pnl_pct = (pnl / entry) * 100
    
    # ⭐ ADD THIS BLOCK ⭐
    # Log signal outcome to analytics database
    if ANALYTICS_ENABLED and signal_tracker and 'signal_id' in signal:
        try:
            outcome = 'win' if pnl > 0 else 'loss'
            signal_tracker.record_signal_closed(
                signal_id=signal['signal_id'],
                exit_price=exit_price,
                outcome=outcome
            )
            print(f"[ANALYTICS] Signal {signal['signal_id']} closed - {outcome.upper()} (${pnl:.2f}, {pnl_pct:+.2f}%)")
        except Exception as e:
            print(f"[ANALYTICS] Close tracking error: {e}")
    # ⭐ END BLOCK ⭐
    
    # Console output (existing code)
    emoji = "✅" if status == 'HIT_TARGET' else "❌"
    print(f"\n{emoji} {ticker} {status}: ${exit_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)\n")
    
    # Discord alert (existing code)
    try:
        msg = (
            f"{emoji} **{ticker} {status}**\n"
            f"Entry: ${entry:.2f} → Exit: ${exit_price:.2f}\n"
            f"P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)"
        )
        send_simple_message(msg)
    except Exception as e:
        print(f"[SIGNALS] Discord error: {e}")
    
    # Remove from active signals (existing code)
    del self.active_signals[ticker]
```

---

### Step 2 (Optional): Add Fill Tracking Helper

If you manually enter positions on Robinhood, add this helper function at the end of `signal_generator.py` (before `if __name__ == "__main__"`):

```python
def log_signal_filled(ticker: str) -> None:
    """
    Log when a signal is manually filled.
    Call this after you enter a position on your broker.
    
    Args:
        ticker: Stock ticker that was filled
    
    Usage:
        >>> log_signal_filled("AAPL")  # After entering AAPL position
    """
    if ticker not in signal_generator.active_signals:
        print(f"[SIGNALS] ⚠️ No active signal found for {ticker}")
        return
    
    signal = signal_generator.active_signals[ticker]
    
    if ANALYTICS_ENABLED and signal_tracker and 'signal_id' in signal:
        try:
            signal_tracker.record_signal_filled(signal['signal_id'])
            print(f"[ANALYTICS] ✅ Signal {signal['signal_id']} marked as FILLED for {ticker}")
        except Exception as e:
            print(f"[ANALYTICS] ❌ Fill tracking error: {e}")
    else:
        print(f"[SIGNALS] ⚠️ Analytics not enabled or signal_id missing")
```

---

## ✅ Testing the Integration

### Test 1: Verify Signal Generation Tracking

```powershell
# Generate some signals
python main.py  # Or your scanner script

# Check if signals are being logged
python view_signals.py
```

**Expected output:**
```
[RECENT SIGNALS (Last 10)]
ticker direction grade  conf_pct outcome  return_pct  hold_min
  AAPL      BULL     A      75.0  pending        0.00       0.0
  TSLA      BEAR    A+      82.0  pending        0.00       0.0
```

### Test 2: Verify Close Tracking (Simulated)

```powershell
# In Python console or your code:
from signal_generator import signal_generator

# Simulate a signal close
signal_generator._close_signal("AAPL", "HIT_TARGET", 185.50)

# Check analytics
python daily_analysis.py
```

**Expected output:**
```
[ANALYTICS] Signal AAPL_20260226_103000 closed - WIN ($2.50, +1.36%)
```

### Test 3: Full Analysis

```powershell
python run_full_analysis.py
```

**Expected output:**
```
[1] SIGNAL GRADE PERFORMANCE
grade  total_signals  wins  losses  avg_win_pct  avg_loss_pct
   A+             5     4       1         4.50         -3.00
    A            10     6       4         3.20         -2.80
   A-             8     5       3         2.90         -2.50

[4] QUICK FAILURE ANALYSIS
total_losses  quick_failures  quick_fail_pct
           8              6            75.0

⚠️ WARNING: High quick failure rate! Consider:
   - Implementing 2-bar holding period
   - Stricter entry confirmation
```

---

## 🔄 Daily Workflow

### Morning (Market Open)

```powershell
# Start scanner
python main.py

# Signals detected automatically log to database
# [ANALYTICS] Signal AAPL_20260226_093015 logged for AAPL
```

### During Trading

```python
# Option 1: Automatic monitoring (recommended)
# monitor_active_signals() automatically tracks stop/target hits

# Option 2: Manual fill tracking (if needed)
from signal_generator import log_signal_filled
log_signal_filled("AAPL")  # After entering position
```

### After Market Close

```powershell
# View today's performance
python daily_analysis.py

# Run weekly analysis
python run_full_analysis.py

# Review recommendations in generated report
cat full_analysis_report_YYYYMMDD_HHMMSS.txt
```

---

## 📊 Analytics Reports

### Quick View (`view_signals.py`)
- Recent signals (last 10)
- Overall win rate
- Grade performance summary

### Daily Report (`daily_analysis.py`)
- Today's performance
- Last 7 days breakdown
- Grade statistics
- Quick failure analysis
- Recent signals

### Full Analysis (`run_full_analysis.py`)
- Comprehensive grade performance
- Losing signal timing (immediate vs delayed failures)
- Winning signal hold times by grade
- Post-breakout price action analysis
- Data-driven recommendations
- Implementation priorities

---

## 🎯 Key Metrics to Watch

### Grade Performance
- **A+ signals should have 70%+ win rate** (target)
- **A signals should have 60%+ win rate** (target)
- **A- signals should have 50%+ win rate** (minimum threshold)

### Timing Analysis
- **Quick failures (<15 min) should be <40%** of total losses
- If quick failure rate is >60%, implement 2-bar holding period

### Hold Time
- **Winners should hold 15-90 minutes** on average
- **Immediate winners (<5 min) indicate strong momentum**
- **Extended winners (>2 hours) may need tighter trailing stops**

---

## 🚨 Troubleshooting

### Issue: "signal_analytics not available"

**Solution:**
```powershell
# Check if signal_analytics.py exists
ls signal_analytics.py

# If missing, you're on the wrong branch
git checkout feature/analytics-integration
git pull origin feature/analytics-integration
```

### Issue: "No signal_id found"

**Cause:** Signal was generated before analytics integration

**Solution:**
- Only NEW signals (after integration) will have signal_id
- Restart scanner to generate fresh signals

### Issue: "Database locked"

**Solution:**
```powershell
# Close any open Python processes using the DB
# Then restart your scanner
```

---

## 📝 Summary

After implementing Step 1, your analytics will:

✅ **Track signal generation** - When breakout detected  
✅ **Track signal fills** - (Optional) When you enter position  
✅ **Track signal closes** - When stop/target hit  
✅ **Calculate performance** - Win rate, avg return, hold times  
✅ **Generate insights** - Quick failures, grade performance  
✅ **Provide recommendations** - Data-driven improvements  

**Next actions:**
1. Add the close tracking code block to `_close_signal()` method
2. Test with sample data (`python populate_sample_signals.py`)
3. Verify with `python daily_analysis.py`
4. Run your live scanner and let it collect real data
5. Review daily reports to optimize your strategy

---

## 🔗 Related Files

- `signal_analytics_integration.py` - Core analytics module
- `signal_analytics_schema.py` - Database schema
- `daily_analysis.py` - Daily performance report
- `view_signals.py` - Quick signal viewer
- `run_full_analysis.py` - Comprehensive analysis
- `populate_sample_signals.py` - Generate test data
- `analytics_commands.py` - Analysis helper commands

---

For questions or issues, check `ANALYTICS_README.md` for detailed documentation.
