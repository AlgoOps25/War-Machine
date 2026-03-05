# Phase 1.14 Integration Tests

## Overview

This test suite validates all Phase 1.14 enhancements:
- EODHD Options API integration
- SPY Correlation Checker
- ML Model Training Pipeline
- Signal-to-Validation Wiring

---

## Prerequisites

### Environment Variables

Before running tests, ensure these environment variables are set:

```bash
# Required for options API
export EODHD_API_KEY="your_eodhd_api_key_here"

# Required for ML training (optional for tests)
export DATABASE_URL="postgresql://user:pass@host:port/dbname?sslmode=require"
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

Key dependencies:
- `requests` (for EODHD API)
- `numpy` (for correlation calculation)
- `scikit-learn` (for ML training)
- `joblib` (for model serialization)
- `psycopg2-binary` (for database access)

---

## Running Tests

### Full Test Suite

```bash
python tests/test_phase_1_14.py
```

### Individual Component Tests

**Test EODHD Options API:**
```python
python -c "
from app.options import get_greeks
greeks = get_greeks('NVDA', 485.0, '2026-03-20', 'CALL')
print(f'Delta: {greeks[\"delta\"]}, Price: ${greeks[\"price\"]}')
"
```

**Test SPY Correlation:**
```python
python -c "
from app.filters.correlation import check_spy_correlation
result = check_spy_correlation('TSLA')
print(f'Correlation: {result[\"correlation\"]:.3f}')
print(f'Adjustment: {result[\"confidence_adjustment\"]:+d}%')
"
```

**Test ML Model Status:**
```python
python -c "
from app.ml.ml_trainer import get_model_info
info = get_model_info()
print(f'Status: {info[\"status\"]}')
if info[\"status\"] == \"trained\":
    print(f'Accuracy: {info[\"metrics\"][\"accuracy\"]:.2%}')
"
```

---

## Expected Output

### Successful Test Run

```
================================================================================
PHASE 1.14 INTEGRATION TESTS
================================================================================
Test Time: 2026-03-05 02:16:42 PM ET


[TEST 1] EODHD Options API Integration
--------------------------------------------------------------------------------

Testing get_greeks() with NVDA...

Greeks Retrieved:
  Delta:  0.55
  Gamma:  0.03
  Theta:  -0.12
  Vega:   0.25
  IV:     42%
  Price:  $12.50

✅ PASS: Real Greeks fetched from EODHD API

Testing build_options_trade() with AAPL...

Options Trade Built:
  Contract: AAPL260320C00150000
  Strike:   $150.0
  DTE:      15 days
  Price:    $3.25
  Quantity: 3 contracts
  IV Rank:  55%

✅ PASS: Options trade built successfully


[TEST 2] SPY Correlation Checker
--------------------------------------------------------------------------------

Testing NVDA...
  Correlation:      0.350
  Ticker Strength:  independent
  Conf Adjustment:  +5%
  Reason:           Low SPY correlation (0.35) - ticker-specific move
  Divergence Score: 67.5/100
  Market-Driven:    False

Testing TSLA...
  Correlation:      0.820
  Ticker Strength:  market_driven
  Conf Adjustment:  -5%
  Reason:           High SPY correlation (0.82) - market-driven move
  Divergence Score: 22.3/100
  Market-Driven:    True

✅ PASS: SPY correlation checker working


[TEST 3] ML Model Status
--------------------------------------------------------------------------------

Model Status:
  Status:          no_model
  Message:         No model trained yet (need 100+ signal outcomes)

  Needs Retraining: False

⚠️  INFO: No ML model trained yet (need 100+ signal outcomes)
   Model will train automatically once data is collected


[TEST 4] Signal-to-Validation Wiring
--------------------------------------------------------------------------------

Simulating signal validation...
  Ticker:     NVDA
  Direction:  BUY
  Confidence: 72.5%
  RVOL:       2.3x
  ADX:        28.5

  SPY Correlation: 0.350
  Adjustment:      +5%

Validation Result:
  Should Pass:      True
  Adjusted Conf:    78.2%
  Original Conf:    72.5%
  Adjustment:       +5.7%

  Passed Checks:  BIAS_ALIGNED_BULL, REGIME_TRENDING, TIME_MORNING_SESSION, VOLUME_STRONG, ADX_OK
  Failed Checks:  
  Check Score:    5/5

✅ PASS: Signal-to-validation wiring functional


================================================================================
TEST SUMMARY
================================================================================

✅ All Phase 1.14 components tested

Next Steps:
  1. Verify EODHD_API_KEY is set for real options data
  2. Monitor SPY correlation adjustments in production
  3. Collect 100+ signal outcomes to train ML model
  4. Review validation logs for confidence adjustments

================================================================================
```

---

## Troubleshooting

### Issue: Placeholder Greeks (not real data)

**Symptom:**
```
⚠️  WARNING: Using placeholder Greeks (API may be unavailable)
   Check EODHD_API_KEY environment variable
```

**Solution:**
1. Check `EODHD_API_KEY` is set:
   ```bash
   echo $EODHD_API_KEY
   ```
2. Verify API key is valid:
   ```bash
   curl "https://eodhd.com/api/options/AAPL.US?api_token=$EODHD_API_KEY"
   ```
3. Check API rate limits (100K requests/day)

---

### Issue: Correlation calculation fails

**Symptom:**
```
❌ FAIL: Insufficient data for NVDA (need 20, got 0)
```

**Solution:**
1. Ensure data manager is running and populating bars
2. Check SPY is in watchlist and receiving updates
3. Verify `data_manager.get_bars_from_memory()` returns data:
   ```python
   from app.data.data_manager import data_manager
   bars = data_manager.get_bars_from_memory('SPY', limit=20)
   print(f"SPY bars: {len(bars)}")
   ```

---

### Issue: ML model not found

**Symptom:**
```
Model Status: no_model
Message: No trained model found
```

**Solution:**
1. This is expected until 100+ signal outcomes are collected
2. Check database for signals:
   ```bash
   psql $DATABASE_URL -c "SELECT COUNT(*) FROM signals WHERE outcome IN ('WIN', 'LOSS')"
   ```
3. Once 100+ outcomes exist, train model:
   ```python
   from app.ml.ml_trainer import train_model
   model, metrics = train_model()
   ```

---

### Issue: Validation fails with errors

**Symptom:**
```
❌ FAIL: 'NoneType' object has no attribute 'validate_signal'
```

**Solution:**
1. Ensure validation module is imported correctly
2. Check dependencies are installed (ADX, RVOL, EMA calculators)
3. Verify technical_indicators module is available

---

## Test Coverage

| Component | Test | Status |
|-----------|------|--------|
| EODHD API | `get_greeks()` | ✅ |
| EODHD API | `build_options_trade()` | ✅ |
| EODHD API | IV Rank calculation | ✅ |
| Correlation | SPY correlation coefficient | ✅ |
| Correlation | Divergence detection | ✅ |
| Correlation | Market-driven classification | ✅ |
| ML Trainer | Model info retrieval | ✅ |
| ML Trainer | Retrain detection | ✅ |
| ML Trainer | Feature extraction | ⏳ (needs data) |
| ML Trainer | Model training | ⏳ (needs 100+ outcomes) |
| Validation | Signal validation | ✅ |
| Validation | Correlation integration | ✅ |
| Validation | Confidence adjustment | ✅ |

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| `get_greeks()` | ~500ms | EODHD API call |
| `check_spy_correlation()` | ~50ms | Cached bars |
| `validate_signal()` | ~200ms | Multi-indicator checks |
| `build_options_trade()` | ~600ms | API + calculations |

---

## Continuous Testing

### Run Tests on Deployment

```bash
# In Railway deployment
python tests/test_phase_1_14.py > /tmp/phase_1_14_test_results.log 2>&1
cat /tmp/phase_1_14_test_results.log
```

### Automated Test Schedule

Add to cron (optional):
```bash
# Test Phase 1.14 daily at 9:00 AM ET
0 9 * * * cd /app && python tests/test_phase_1_14.py
```

---

## Next Steps After Tests Pass

1. **Deploy to Production**
   - Push changes to Railway
   - Verify environment variables are set
   - Monitor logs for Phase 1.14 components

2. **Monitor Performance**
   - Watch for SPY correlation adjustments in logs
   - Track options API call counts (stay under 100K/day)
   - Review validation pass/fail rates

3. **Collect ML Training Data**
   - Let system run and record signal outcomes
   - Check database daily: `SELECT COUNT(*) FROM signals WHERE outcome IN ('WIN', 'LOSS')`
   - Train model once 100+ outcomes collected

4. **Production Validation**
   - Test EODHD API with live signals
   - Verify SPY correlation reduces false signals
   - Confirm validation adjustments improve win rate

---

## Support

**Issues:** Open a GitHub issue with test output logs  
**Documentation:** See `docs/Phase_1_14_Implementation_Notes.md`  
**Status:** Check Railway logs for component health
