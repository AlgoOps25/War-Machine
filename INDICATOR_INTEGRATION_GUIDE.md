# Technical Indicators Integration Guide

## 📚 Overview

This guide covers the integration of 3 new technical indicator modules into War Machine:

1. **`technical_indicators.py`** - EODHD API integration with caching
2. **`vpvr_calculator.py`** - Volume Profile Visible Range calculator
3. **`signal_validator.py`** - Multi-indicator signal confirmation engine

---

## ✅ Step 1: Standalone Testing

### Prerequisites

1. **EODHD API Key** configured in `.env`
2. **Database with bar data** (WebSocket feed or backfilled data)
3. **Active market hours** (or historical bars for testing)

### Run Test Suite

```bash
cd War-Machine

# Test with default ticker (AAPL)
python test_indicators.py

# Test with specific ticker
python test_indicators.py TSLA
```

### Expected Output

The test suite will validate:

- ✅ **EODHD API connectivity** (ADX, Volume, Bollinger Bands, DMI, CCI)
- ✅ **Cache performance** (hit rates, TTL management)
- ✅ **VPVR calculation** (POC, Value Area, HVN/LVN detection)
- ✅ **Signal validation** (multi-indicator confirmation)
- ✅ **Performance metrics** (API calls, execution time)

### Interpreting Results

#### 🟢 All Tests Pass
```
✅ ADX: 28.5 - Strong Trend
✅ Average Volume: 45,823,091
✅ Band Width: 3.42% - NORMAL
✅ Trend Direction: BULLISH
✅ CCI: 45.2 - NEUTRAL
✅ VPVR Profile calculated successfully
✅ SIGNAL PASSED VALIDATION
```

**Action:** Proceed to integration (Step 2)

---

#### 🟡 Partial Success (Some Data Missing)
```
✅ ADX: 28.5 - Strong Trend
❌ Average Volume data not available
✅ Band Width: 3.42% - NORMAL
⚠️  No bar data available for TSLA
```

**Action:** Check these issues:
1. EODHD API rate limits or plan restrictions
2. Ticker not in today's watchlist (no bars stored)
3. WebSocket feed disconnected (no live data)

**Solution:**
- Run `python ws_feed.py` to start WebSocket feed
- Add ticker to watchlist in `dynamic_screener.py`
- Wait 5-10 minutes for bar data to accumulate

---

#### 🔴 All Tests Fail
```
❌ ADX test failed: HTTPError 401 Unauthorized
❌ Average Volume data not available
❌ Bollinger Bands data not available
```

**Action:** Critical issues to fix:
1. **Check EODHD API key** in `.env` file
2. **Verify API plan** supports technical indicators (All-In-One or higher)
3. **Check network connectivity** to eodhd.com

**Solution:**
```bash
# Verify API key
cat .env | grep EODHD_API_KEY

# Test API manually
curl "https://eodhd.com/api/technical/AAPL.US?function=adx&period=14&api_token=YOUR_KEY"
```

---

## ⚙️ Step 2: Signal Generator Integration

Once standalone tests pass, integrate into `signal_generator.py`.

### Integration Patch

Add this code to `signal_generator.py`:

```python
# At the top of signal_generator.py (imports section)
from signal_validator import get_validator

# In the SignalGenerator.__init__() method
class SignalGenerator:
    def __init__(self, ...):
        # ... existing init code ...
        
        # Add validator
        self.validator = get_validator()
        print("[SIGNALS] Multi-indicator validator enabled")
```

### Validation Hook (Option A: Full Filtering)

Add validation **after** CFW6 pattern detection:

```python
# In check_ticker() method, after signal is generated
def check_ticker(self, ticker: str, use_5m: bool = True):
    # ... existing CFW6 detection code ...
    
    if signal:
        # Get latest bar for volume
        bars = self.data_manager.get_today_5m_bars(ticker) if use_5m else self.data_manager.get_today_session_bars(ticker)
        latest_bar = bars[-1] if bars else None
        
        if latest_bar:
            # Run multi-indicator validation
            should_pass, adjusted_confidence, metadata = self.validator.validate_signal(
                ticker=ticker,
                signal_direction=signal['direction'],
                current_price=signal['entry_price'],
                current_volume=latest_bar['volume'],
                base_confidence=signal['confidence']
            )
            
            if not should_pass:
                print(f"[VALIDATOR] {ticker} signal filtered - weak confirmation")
                return None
            
            # Update signal with boosted confidence
            signal['confidence'] = adjusted_confidence
            signal['validation_metadata'] = metadata
            
            # Log validation details
            summary = metadata['summary']
            print(f"[VALIDATOR] {ticker} passed: {summary['check_score']} checks, "
                  f"confidence {adjusted_confidence:.1%} ({summary['confidence_adjustment']:+.1%})")
    
    return signal
```

### Validation Hook (Option B: Test Mode - No Filtering)

Run validator in parallel **without** filtering signals (safer for initial deployment):

```python
# In check_ticker() method, after signal is generated
if signal and latest_bar:
    # Test validation without filtering
    should_pass, adjusted_confidence, metadata = self.validator.validate_signal(
        ticker=ticker,
        signal_direction=signal['direction'],
        current_price=signal['entry_price'],
        current_volume=latest_bar['volume'],
        base_confidence=signal['confidence']
    )
    
    # Log results but don't filter
    summary = metadata['summary']
    print(f"[VALIDATOR TEST] {ticker}: Pass={should_pass}, "
          f"Conf={adjusted_confidence:.1%} ({summary['confidence_adjustment']:+.1%})")
    
    # Store metadata for analysis (optional)
    signal['validation_test'] = {
        'should_pass': should_pass,
        'adjusted_confidence': adjusted_confidence,
        'checks': summary
    }
    
    # Continue with original signal (don't filter)
    return signal
```

**Recommendation:** Start with **Option B (Test Mode)** for 1-2 trading days, then switch to **Option A (Full Filtering)** once confident.

---

## 📊 API Call Budget & Optimization

### API Call Costs (EODHD)

| Indicator | API Credits | Cache TTL | Calls/Hour (Cached) |
|-----------|-------------|-----------|---------------------|
| ADX | 5 | 2-5 min | 6-15 |
| Bollinger Bands | 5 | 2-5 min | 6-15 |
| Average Volume | 5 | 2-5 min | 6-15 |
| DMI | 5 | 2-5 min | 6-15 |
| CCI | 5 | 2-5 min | 6-15 |
| VPVR | 0 | N/A | 0 (local calc) |

### Optimization Strategy

1. **Cache indicators aggressively** (2-5 min TTL)
2. **Validate only on signal detection** (not every scan cycle)
3. **Use VPVR heavily** (zero API cost)
4. **Batch fetch multiple tickers** (future enhancement)

### Example: 50-Ticker Watchlist, 3 Signals/Hour

**Without Indicators:**
- Bar data: 50 tickers × 1 call = 50 calls/scan
- Scan every 60s = ~50 calls/hour

**With Indicators (Full Filtering):**
- Bar data: 50 calls/scan
- Indicators: 3 signals × 5 indicators × 5 credits = 75 calls/hour (first fetch)
- Indicators: 3 signals × 0 credits = 0 calls/hour (cached)
- **Total: 50-125 calls/hour** (depending on cache hits)

**With Indicators (Test Mode):**
- Same as above, but validation runs on all signals (not just passed)
- Slightly higher API usage during testing

---

## 🛡️ Troubleshooting

### Issue: "ADX data not available"

**Cause:** EODHD API error or plan limitation

**Solution:**
1. Check EODHD plan includes technical indicators
2. Verify API key in `.env`
3. Check API rate limits

```bash
# Test API manually
curl "https://eodhd.com/api/technical/AAPL.US?function=adx&period=14&api_token=YOUR_KEY&fmt=json"
```

---

### Issue: "No bar data available for VPVR"

**Cause:** Ticker not in today's watchlist or WebSocket disconnected

**Solution:**
1. Check WebSocket feed status: `python ws_feed.py`
2. Add ticker to `dynamic_screener.py` watchlist
3. Wait 5-10 minutes for bars to accumulate
4. Verify database has today's data:

```python
import data_manager
bars = data_manager.data_manager.get_today_session_bars('AAPL')
print(f"Bars: {len(bars)}")
```

---

### Issue: "HTTPError 429 Too Many Requests"

**Cause:** Exceeded EODHD API rate limits

**Solution:**
1. Increase cache TTL in `technical_indicators.py`:
   ```python
   def _get_ttl_seconds(self) -> int:
       if dtime(9, 30) <= now < dtime(16, 0):
           return 300  # Increase to 5 minutes during market hours
   ```

2. Validate fewer signals (stricter CFW6 thresholds)
3. Upgrade EODHD plan for higher rate limits

---

### Issue: "Signal always filtered - pass rate 0%"

**Cause:** Validation thresholds too strict

**Solution:** Adjust thresholds in `signal_validator.py`:

```python
# Lower thresholds for initial testing
validator = SignalValidator(
    min_adx=15.0,           # Lower from 20
    min_volume_ratio=1.2,   # Lower from 1.3
    enable_vpvr=True,
    strict_mode=False       # Keep False
)
```

Or disable specific checks temporarily:

```python
# In signal_validator.py, comment out strict checks
# if adx_value < self.min_adx:
#     failed_checks.append('ADX_WEAK')
```

---

## 📈 Performance Tuning

### Cache TTL Adjustment

Edit `technical_indicators.py` to tune cache duration:

```python
def _get_ttl_seconds(self) -> int:
    now = datetime.now(ET).time()
    
    if dtime(4, 0) <= now < dtime(9, 30):
        return 600  # 10 min pre-market (slow moving)
    elif dtime(9, 30) <= now < dtime(10, 0):
        return 90   # 1.5 min opening range (fast)
    elif dtime(10, 0) <= now < dtime(16, 0):
        return 180  # 3 min regular hours (balanced)
    else:
        return 900  # 15 min after hours (very slow)
```

### Validation Strictness

**Conservative (High Win Rate, Fewer Signals):**
```python
validator = SignalValidator(
    min_adx=30.0,           # Strong trends only
    min_volume_ratio=1.8,   # High volume only
    enable_vpvr=True,
    strict_mode=True        # All checks must pass
)
```

**Aggressive (More Signals, Lower Win Rate):**
```python
validator = SignalValidator(
    min_adx=15.0,           # Accept weaker trends
    min_volume_ratio=1.1,   # Accept lower volume
    enable_vpvr=False,      # Disable VPVR checks
    strict_mode=False
)
```

---

## 📊 Monitoring & Analytics

### View Validator Statistics

Add this to your main scanner loop:

```python
# After each scan cycle
stats = validator.get_validation_stats()
print(f"[VALIDATOR] Pass Rate: {stats.get('pass_rate', 0)*100:.1f}%, "
      f"Boosted: {stats.get('boost_rate', 0)*100:.1f}%")
```

### View Cache Performance

Add this to your startup or monitoring:

```python
import technical_indicators as ti

cache_stats = ti.get_cache_stats()
print(f"[CACHE] Entries: {cache_stats['valid_entries']}/{cache_stats['total_entries']}, "
      f"TTL: {cache_stats['current_ttl']}s")
```

### Clear Cache Daily

Add to your end-of-day cleanup:

```python
import technical_indicators as ti

# At market close (16:00 ET)
ti.clear_indicator_cache()
print("[CLEANUP] Indicator cache cleared")
```

---

## ✅ Integration Checklist

- [ ] **Test Suite Passes** (`python test_indicators.py AAPL`)
- [ ] **EODHD API Key Verified** (check technical indicators access)
- [ ] **Database Has Bar Data** (WebSocket feed active)
- [ ] **Import Validator** in `signal_generator.py`
- [ ] **Add Validation Hook** (start with Test Mode)
- [ ] **Monitor for 1-2 Days** (check logs, pass rates)
- [ ] **Tune Thresholds** (adjust based on results)
- [ ] **Switch to Full Filtering** (once confident)
- [ ] **Deploy to Railway** (`git push origin main`)

---

## 🚀 Next Steps

1. **Run standalone tests** to verify all modules work
2. **Integrate in Test Mode** (Option B) for 1-2 days
3. **Analyze validation logs** to tune thresholds
4. **Switch to Full Filtering** (Option A) when ready
5. **Monitor win rate improvements** over 1-2 weeks

---

## 📞 Support

If you encounter issues:

1. Check this guide's troubleshooting section
2. Review test output for specific error messages
3. Verify EODHD API plan and rate limits
4. Check database for bar data availability

Good luck! 🎯
