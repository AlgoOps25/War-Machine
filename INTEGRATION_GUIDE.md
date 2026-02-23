# Breakout Detector Integration Guide

## Overview

This guide shows you how to integrate the new **Breakout Entry Detector** into your existing War Machine scanner.

## What Was Added

### 1. `breakout_detector.py` - Core Detection Logic
- Detects 5-minute breakouts above resistance with volume confirmation
- Calculates ATR-based dynamic stops and targets
- Provides confidence scoring (0-100%)
- Supports both bull breakouts and bear breakdowns

### 2. `signal_generator.py` - Scanner Integration
- Scans watchlist for breakout signals
- Manages signal cooldown (prevents duplicate alerts)
- Sends Discord alerts with entry/stop/target
- Monitors active signals for stop/target hits

---

## Quick Integration (2 Steps)

### Step 1: Add to Scanner Imports

In `scanner.py`, add at the top:

```python
from signal_generator import (
    scan_for_signals,
    check_and_alert,
    monitor_signals,
    print_active_signals,
    signal_generator
)
```

### Step 2: Add Signal Check to Main Loop

In `scanner.py`, find the main scanning loop (around line 150) and add:

```python
# After building watchlist, scan for breakout signals
print(f"\n[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...")
check_and_alert(watchlist)  # Scan and send Discord alerts

# Monitor any active signals
monitor_signals()  # Check if stops/targets hit

# Print active signals summary
if signal_generator.active_signals:
    print_active_signals()
```

---

## Full Integration Example

Here's what your scanner loop should look like:

```python
def start_scanner_loop():
    # ... existing startup code ...
    
    while True:
        try:
            now_et = _now_et()
            
            if is_premarket():
                # Pre-market logic
                if not premarket_built:
                    watchlist_data = get_watchlist_with_metadata(force_refresh=True)
                    premarket_watchlist = watchlist_data['watchlist']
                    premarket_built = True
                    
                    # NEW: Scan pre-market watchlist for breakouts
                    print("\n[SIGNALS] Pre-market breakout scan...")
                    check_and_alert(premarket_watchlist)
                    
                time.sleep(60)
                continue
            
            elif is_market_hours():
                # Market hours logic
                cycle_count += 1
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}")
                
                # Build watchlist
                watchlist = get_current_watchlist(force_refresh=False)
                optimal_size = calculate_optimal_watchlist_size()
                watchlist = watchlist[:optimal_size]
                
                print(f"[SCANNER] {len(watchlist)} tickers | {', '.join(watchlist[:10])}...\n")
                
                # NEW: Scan for breakout signals
                print(f"\n[SIGNALS] Scanning for breakouts...")
                check_and_alert(watchlist)
                
                # NEW: Monitor active signals
                monitor_signals()
                
                # NEW: Show active signals summary
                if signal_generator.active_signals:
                    print_active_signals()
                
                # Monitor existing positions (your existing code)
                monitor_open_positions()
                
                # Process tickers (your existing CFW6 logic)
                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        print(f"\n--- [{idx}/{len(watchlist)}] {ticker} ---")
                        process_ticker(ticker)  # Your existing sniper logic
                    except Exception as e:
                        print(f"[SCANNER] Error on {ticker}: {e}")
                        continue
                
                # Sleep between scans
                scan_interval = get_adaptive_scan_interval()
                print(f"\n[SCANNER] Sleeping {scan_interval}s...\n")
                time.sleep(scan_interval)
            
            else:
                # After hours - EOD cleanup
                print(f"[EOD] Market Closed - Generating Reports")
                
                # NEW: Clear stale signals
                signal_generator.clear_expired_signals()
                
                # Your existing EOD logic...
                
        except KeyboardInterrupt:
            print("\n[SCANNER] Shutdown signal received")
            raise
```

---

## Configuration

You can customize the signal generator in `signal_generator.py` (bottom of file):

```python
signal_generator = SignalGenerator(
    lookback_bars=12,           # Bars for support/resistance (default: 12 = 1 hour on 5m)
    volume_multiplier=2.0,       # Volume must be 2x average (adjust for sensitivity)
    cooldown_minutes=15,         # Wait 15min before alerting same ticker again
    min_confidence=60            # Only send signals with 60%+ confidence
)
```

### Tuning Parameters

**More Signals (Lower Quality):**
```python
volume_multiplier=1.5,  # Lower threshold
min_confidence=50       # Accept lower confidence
```

**Fewer Signals (Higher Quality):**
```python
volume_multiplier=2.5,  # Require stronger volume
min_confidence=70       # Only high-confidence signals
```

---

## What You'll See

### Console Output

```
[SIGNALS] Scanning 10 tickers for breakouts...

======================================================================
🚨 BREAKOUT SIGNAL DETECTED: TSLA
======================================================================
📈 **BUY TSLA** @ $245.50
Stop: $243.20 | Target: $250.10
Risk: $2.30 | Reward: $4.60 | R:R 2.0:1
Volume: 2.3x avg | ATR: $1.53
Confidence: 75% - Breakout above $244.80 with 2.3x volume
======================================================================

[SIGNALS] Discord alert sent for TSLA
```

### Discord Alert

```
🚨 **BREAKOUT ALERT**
📈 **BUY TSLA** @ $245.50
Stop: $243.20 | Target: $250.10
Risk: $2.30 | Reward: $4.60 | R:R 2.0:1
Volume: 2.3x avg | ATR: $1.53
Confidence: 75% - Breakout above $244.80 with 2.3x volume
```

### When Target Hit

```
✅ TSLA HIT_TARGET: $250.30 | P&L: $4.80 (+1.96%)
```

### Active Signals Summary

```
======================================================================
ACTIVE SIGNALS
======================================================================
Ticker   Signal Entry    Stop     Target   Conf 
----------------------------------------------------------------------
TSLA     BUY    $245.50  $243.20  $250.10  75%  
NVDA     BUY    $890.25  $883.50  $903.75  82%  
======================================================================
```

---

## Testing

Before running live, test the detector:

```bash
# Test breakout detector with sample data
python breakout_detector.py

# Test signal generator (requires database with bars)
python signal_generator.py
```

---

## Position Sizing (Optional)

To calculate how many shares to buy based on account risk:

```python
from breakout_detector import BreakoutDetector

detector = BreakoutDetector()

# For a $10,000 account risking 1% per trade
shares = detector.calculate_position_size(
    account_balance=10000,
    risk_percent=1.0,        # Risk 1% = $100
    entry=signal['entry'],
    stop=signal['stop']
)

print(f"Buy {shares} shares of {ticker}")
print(f"Total risk: ${shares * (signal['entry'] - signal['stop']):.2f}")
```

---

## Next Steps

1. **Pull and test:**
   ```bash
   git pull origin main
   python signal_generator.py  # Test signal detection
   ```

2. **Add to scanner.py** (see Step 2 above)

3. **Run scanner and monitor Discord for alerts**

4. **Tune parameters** based on signal quality

5. **Optional: Add automated order execution** (next phase)

---

## Differences from CFW6/Sniper

Your existing system:
- ✅ CFW6 confirmation (bias, FVG, order flow)
- ✅ Entry watching and arming
- ✅ Manual execution

New breakout detector:
- ✅ **Simpler logic** - Pure breakout + volume
- ✅ **Faster signals** - No waiting for perfect confluence
- ✅ **Automatic stops/targets** - No manual calculation
- ✅ **Position sizing** - Built-in risk management

**Recommendation:** Run both systems in parallel!
- Use CFW6 for high-confidence discretionary trades
- Use breakout detector for momentum scalps

---

## FAQ

**Q: Will this replace my CFW6 scanner?**  
A: No! This is an **addition**. Your CFW6 logic still runs. This just adds simpler breakout signals.

**Q: How many signals will I get?**  
A: With default settings (2x volume, 60% confidence), expect 2-5 signals per day on a 10-ticker watchlist.

**Q: Can I run this on 1-minute bars?**  
A: Yes! Change `use_5m=False` in `scan_for_signals()`. But 5m bars are cleaner and less noisy.

**Q: Does this execute trades automatically?**  
A: No, it only generates alerts. You still execute manually. (Auto-execution can be added next.)

**Q: What if I get too many signals?**  
A: Increase `volume_multiplier` to 2.5 or `min_confidence` to 70.

---

## Support

If you have issues:
1. Check console for error messages
2. Verify database has today's bars: `data_manager.get_today_5m_bars("SPY")`
3. Test detector standalone: `python breakout_detector.py`

Happy trading! 🚀
