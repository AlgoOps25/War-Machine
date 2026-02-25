# Multi-Timeframe Infrastructure - Testing Guide

**Status**: Phase 1 & 2 Complete - Ready for Testing  
**Date**: February 24, 2026

---

## What Was Built (Phases 1-2)

### Phase 1: MTF Data Manager
**File**: `mtf_data_manager.py`

**Features**:
- Fetches and caches 5m, 3m, 2m, 1m bars
- Smart caching to minimize API calls
- Session-based cache management
- Compatible with existing `data_manager.py`

### Phase 2: MTF FVG Engine
**File**: `mtf_fvg_engine.py`

**Features**:
- Runs CFW6 BOS+FVG detection on all timeframes
- Calculates zone overlap and convergence scores
- Timeframe weighting: 5m (40%) > 3m (30%) > 2m (20%) > 1m (10%)
- Returns signals only when convergence ≥ 60%

---

## Testing Phase 1: Data Manager

### Test 1: Single Timeframe Fetch

```bash
python mtf_data_manager.py SPY 5m
```

**Expected Output**:
```
[MTF] Multi-Timeframe Data Manager initialized
[MTF] Supported timeframes: 5m, 3m, 2m, 1m

Fetching SPY 5m bars...

[MTF] SPY 5m: 78 bars (from data_manager)

Received 78 bars:
First bar: 2026-02-24 09:30:00-05:00 | Close: $540.25
Last bar:  2026-02-24 15:55:00-05:00 | Close: $542.10
```

**Validation**:
- ✅ Should retrieve ~78 bars (9:30 AM - 4:00 PM)
- ✅ Timestamps in Eastern Time
- ✅ All prices reasonable (no zeros or nulls)

### Test 2: All Timeframes Fetch

```bash
python mtf_data_manager.py SPY
```

**Expected Output**:
```
[MTF] Multi-Timeframe Data Manager initialized
[MTF] Supported timeframes: 5m, 3m, 2m, 1m

Fetching SPY across all timeframes...

[MTF] SPY 5m: 78 bars (from data_manager)
[MTF] SPY 3m: 130 bars (from API)
[MTF] SPY 2m: 195 bars (from API)
[MTF] SPY 1m: 390 bars (from API)
[MTF] SPY timeframes available: 5m, 3m, 2m, 1m

============================================================
RESULTS
============================================================
 5m:  78 bars | Latest: $ 542.10 @ 03:55 PM
 3m: 130 bars | Latest: $ 542.10 @ 03:57 PM
 2m: 195 bars | Latest: $ 542.10 @ 03:58 PM
 1m: 390 bars | Latest: $ 542.10 @ 03:59 PM
============================================================

============================================================
MTF DATA MANAGER - CACHE STATISTICS
============================================================
Session Date:    2026-02-24
Cached Tickers:  1
Total Entries:   4

By Timeframe:
   1m:  1 tickers
   2m:  1 tickers
   3m:  1 tickers
   5m:  1 tickers
============================================================
```

**Validation**:
- ✅ All 4 timeframes should have data
- ✅ Bar counts: 1m (~390) > 2m (~195) > 3m (~130) > 5m (~78)
- ✅ Latest prices should be similar across timeframes
- ✅ Cache statistics showing 1 ticker, 4 entries

### Test 3: Cache Efficiency

```bash
# Run twice in quick succession
python mtf_data_manager.py AAPL
python mtf_data_manager.py AAPL
```

**Expected Behavior**:
- First run: Fetches from API
- Second run: Returns from cache (faster, no API calls)
- Check logs for "from data_manager" vs "from API"

### Test 4: Multiple Tickers

```bash
python mtf_data_manager.py SPY
python mtf_data_manager.py QQQ
python mtf_data_manager.py AAPL
```

**Expected**:
- Each ticker cached separately
- Cache stats should show 3 tickers, 12 total entries (3 × 4 timeframes)

---

## Testing Phase 2: FVG Engine

### Test 5: MTF Signal Detection

```bash
python mtf_fvg_engine.py SPY
```

**Expected Output (if signal present)**:
```
[MTF] Multi-Timeframe Data Manager initialized
[MTF] Supported timeframes: 5m, 3m, 2m, 1m
[MTF-FVG] Engine initialized
[MTF-FVG] Min convergence: 60.0%
[MTF-FVG] Min timeframes: 2
[MTF-FVG] Min overlap: 30.0%

================================================================================
MTF FVG DETECTION TEST: SPY
================================================================================

Fetching SPY data across all timeframes...

[MTF] SPY 5m: 78 bars (from data_manager)
[MTF] SPY 3m: 130 bars (from API)
[MTF] SPY 2m: 195 bars (from API)
[MTF] SPY 1m: 390 bars (from API)
[MTF] SPY timeframes available: 5m, 3m, 2m, 1m

Running MTF FVG detection...

[MTF-FVG] ✅ SPY MTF BULL signal
[MTF-FVG]    Convergence: 80.5% | TFs: 5m, 3m, 2m
[MTF-FVG]    Zone: $541.25 - $541.85

================================================================================
MTF SIGNAL DETECTED
================================================================================
Direction:        BULL
Convergence:      80.5%
Timeframes:       5m, 3m, 2m
Zone:             $541.25 - $541.85
BOS Price:        $540.50
Primary TF:       5m

--------------------------------------------------------------------------------
PER-TIMEFRAME DETAILS
--------------------------------------------------------------------------------
 5m: bull | Zone: $541.20 - $541.90
 3m: bull | Zone: $541.25 - $541.85
 2m: bull | Zone: $541.30 - $541.80

MTF Confidence Boost: +5.13%
================================================================================
```

**Expected Output (if no signal)**:
```
[... same initialization ...]

[MTF-FVG] SPY - Convergence 0.45 below threshold 0.60

================================================================================
NO MTF SIGNAL
================================================================================
Reasons: Insufficient convergence, timeframes, or zone overlap
================================================================================
```

**Validation**:
- ✅ Convergence score between 0.0 - 1.0
- ✅ At least 2 timeframes aligned
- ✅ Zone overlap makes sense (high > low)
- ✅ Direction consistent across aligned timeframes
- ✅ MTF boost reasonable (0.00 - 0.15)

### Test 6: Multiple Tickers

```bash
# Test various tickers to find signals
python mtf_fvg_engine.py SPY
python mtf_fvg_engine.py QQQ
python mtf_fvg_engine.py AAPL
python mtf_fvg_engine.py NVDA
python mtf_fvg_engine.py TSLA
```

**Expected**:
- Some tickers will have MTF signals, others won't
- Higher convergence = stronger signal
- More timeframes aligned = better quality

---

## Programmatic Testing

### Python Interactive Test

```python
from mtf_data_manager import mtf_data_manager
from mtf_fvg_engine import mtf_fvg_engine

# Test data fetching
ticker = 'SPY'
bars_dict = mtf_data_manager.get_all_timeframes(ticker)

print(f"Timeframes available: {list(bars_dict.keys())}")
for tf, bars in bars_dict.items():
    print(f"{tf}: {len(bars)} bars")

# Test MTF detection
result = mtf_fvg_engine.detect_mtf_signal(ticker, bars_dict)

if result:
    print(f"\nMTF Signal: {result['direction'].upper()}")
    print(f"Convergence: {result['convergence_score']:.1%}")
    print(f"Zone: ${result['zone_low']:.2f} - ${result['zone_high']:.2f}")
    print(f"Timeframes: {result['timeframes_aligned']}")
    
    # Calculate confidence boost
    boost = mtf_fvg_engine.get_mtf_boost_value(result['convergence_score'])
    print(f"MTF Boost: +{boost:.2%}")
else:
    print("\nNo MTF signal detected")

# Check cache stats
mtf_data_manager.print_cache_stats()
```

---

## Expected Behaviors

### Data Manager

**✅ Good Signs**:
- All 4 timeframes fetch successfully
- Bar counts logical (1m > 2m > 3m > 5m)
- Caching works (second call faster)
- No API errors or timeouts
- Prices aligned across timeframes

**❌ Red Flags**:
- Missing timeframes (check API key)
- Zero bars returned
- Prices wildly different across timeframes
- Timestamps outside trading hours
- API rate limit errors

### FVG Engine

**✅ Good Signs**:
- Convergence scores in reasonable range (60-100%)
- Zone overlap positive (high > low)
- Direction consistent across timeframes
- At least 2-3 timeframes aligned
- Confidence boost proportional to convergence

**❌ Red Flags**:
- Convergence always 0% or 100%
- Zone overlap negative or zero
- Conflicting directions in same signal
- Single timeframe dominating all signals
- Confidence boost outside 0.00-0.15 range

---

## Troubleshooting

### Issue: No data returned for 3m/2m/1m

**Possible Causes**:
1. EODHD API key not configured
2. API doesn't support these intervals
3. Rate limiting
4. Outside trading hours

**Fixes**:
1. Check `config.py` has `EODHD_API_TOKEN`
2. Verify EODHD plan includes intraday data
3. Add delays between requests
4. Test during market hours (9:30 AM - 4:00 PM ET)

### Issue: MTF engine never finds signals

**Possible Causes**:
1. Market conditions (low volatility, no BOS patterns)
2. Thresholds too strict
3. FVG detection not working on smaller timeframes

**Fixes**:
1. Test during volatile market periods
2. Lower convergence threshold:
   ```python
   mtf_fvg_engine.update_config(min_convergence_score=0.50)
   ```
3. Test on known volatile tickers (TSLA, NVDA)

### Issue: Cache not clearing

**Fix**:
```python
from mtf_data_manager import mtf_data_manager
mtf_data_manager.clear_cache()  # Clear all
# OR
mtf_data_manager.clear_cache(ticker='SPY')  # Clear specific ticker
```

### Issue: Zone overlap always 0%

**Cause**: Timeframes showing FVGs in very different price ranges

**Analysis**: This is actually correct behavior - it means there's no true MTF convergence. The engine should reject these signals.

---

## Integration Readiness Checklist

Before proceeding to Phase 3 (sniper.py integration), verify:

- [ ] Data manager fetches all 4 timeframes successfully
- [ ] Cache works correctly (faster on second call)
- [ ] FVG engine detects signals with reasonable convergence scores
- [ ] At least 2-3 timeframes align in test signals
- [ ] Zone overlap is positive and logical
- [ ] Confidence boost values in 0.00-0.15 range
- [ ] No API errors or rate limiting issues
- [ ] Performance acceptable (test completes in <5 seconds)
- [ ] Cache clears properly at session rollover
- [ ] Multiple tickers can be tested sequentially

**If all checkboxes pass** → Ready for Phase 3 Integration ✅

**If any fail** → Review and fix before proceeding ⚠️

---

## Performance Benchmarks

**Target Performance**:
- Single ticker, all timeframes: <3 seconds
- MTF signal detection: <2 seconds
- Cache hit: <0.1 seconds

**Test**:
```bash
time python mtf_fvg_engine.py SPY
```

Should complete in <5 seconds total.

---
## Next Steps (Phase 3)

Once testing is complete:

1. **Update `sniper.py`**:
   - Replace single-TF BOS detection with MTF engine
   - Apply MTF boost to confidence calculation
   - Track MTF metrics in signal_events

2. **Update `signal_analytics.py`**:
   - Add MTF convergence tracking fields
   - Record timeframes_aligned per signal

3. **Update `monitoring_dashboard.py`**:
   - Add MTF effectiveness metrics
   - Compare single-TF vs MTF win rates

4. **Backtest**:
   - Run on historical data
   - Measure win rate improvement
   - Validate convergence thresholds

---

**Status**: Awaiting Test Results  
**Ready for Integration**: After checklist passes ✅
