# WAR MACHINE - TESTING GUIDE

## Overview

This guide walks you through testing the complete signal generation and validation pipeline, with special focus on the new **Regime Filter** integration.

## System Architecture

```
┌──────────────────────────┐
│   SCANNER (scanner.py)    │
│  - Builds watchlist       │
│  - Manages scan cycles    │
└─────────┬───────────────┘
         │
         ▼
┌─────────├──────────────────────────────────────┐
│         │   SIGNAL GENERATOR (signal_generator.py)   │
│         │   - Detects CFW6 breakouts                │
│         │   - Manages cooldown periods              │
│         └─────────┬────────────────────────────┘
│                   │
│                   ▼
│         ┌─────────┴───────────────────────────┐
│         │   SIGNAL VALIDATOR (signal_validator.py) │
│         │   - Multi-indicator confirmation          │
│         │   - 10 validation checks                  │
│         └─────────┬───────────────────────────┘
│                   │
│    ┌──────────────┼───────────────┐
│    │              │              │
│    ▼              ▼              ▼
│ CHECK 0        CHECK 0A       CHECK 1-9
│ Daily Bias     REGIME         Time/EMA/RSI
│ Engine         FILTER         ADX/Volume/DMI
│                (NEW!)         CCI/BBands/VPVR
└────────────────────────────────────────────────────┘
```

## Validation Pipeline

Signals pass through 10 validation checks:

### Layer 0: Daily Bias (ICT Top-Down)
- **Purpose**: Penalize counter-trend signals
- **Action**: -25% penalty for strong counter-trend
- **Can be rescued by**: VPVR (excellent entry points)

### Layer 0A: Regime Filter (NEW!) 🆕
- **Purpose**: Block signals during unfavorable market conditions
- **Regimes**:
  - ✅ **TRENDING**: VIX < 30, SPY ADX > 25 → Allow signals (+5% boost)
  - ❌ **CHOPPY**: VIX < 30, SPY ADX < 25 → Heavy penalty (-30%)
  - ❌ **VOLATILE**: VIX > 30 → Heavy penalty (-30%)

### Layers 1-9: Technical Confirmation
1. **Time-of-Day**: Morning/power hour boost, dead zone penalty
2. **EMA Stack**: 9>20>50 alignment check
3. **RSI Divergence**: Early reversal warnings
4. **ADX**: Trend strength (threshold: 25)
5. **Volume**: Institutional confirmation (1.5x average)
6. **DMI**: Trend direction alignment
7. **CCI**: Overbought/oversold momentum
8. **Bollinger Bands**: Volatility context
9. **VPVR**: Volume profile entry scoring (can rescue counter-trend)

---

## Testing Workflow

### Step 1: Run Full Pipeline Test

This comprehensive test verifies all components:

```bash
python test_full_pipeline.py
```

**Expected Output:**
```
╔==============================================================================╗
║                    WAR MACHINE PIPELINE TEST                             ║
║                                                                          ║
║  Test Time: 2026-02-25 04:19:00 PM ET                                   ║
╚==============================================================================╝

================================================================================
  TEST 1: IMPORT VERIFICATION
================================================================================
✅ data_manager import
   DB: trades.db
✅ regime_filter import
✅ daily_bias_engine import
✅ signal_validator import
✅ signal_generator import
✅ breakout_detector import

================================================================================
  TEST 2: DATA MANAGER
================================================================================
✅ VIX fetch
   VIX = 18.25
✅ SPY bars fetch
   50 bars available
✅ Today's session bars
   78 bars

================================================================================
  TEST 3: REGIME FILTER
================================================================================

Regime Analysis:
  Regime:    TRENDING
  VIX:       18.25
  SPY Trend: BULL
  ADX:       32.5
  Favorable: YES ✅
  Reason:    Strong uptrend with moderate volatility

✅ Regime classification
   TRENDING
✅ Favorable regime check
   Favorable

...(more tests)

================================================================================
  TEST SUMMARY
================================================================================

Results: 8/8 tests passed

  ✅ Imports
  ✅ Data Manager
  ✅ Regime Filter
  ✅ Daily Bias
  ✅ Signal Validator
  ✅ Signal Generator
  ✅ Pipeline Integration
  ✅ Regime In Validator  <-- KEY TEST

================================================================================
🎉 ALL TESTS PASSED - System is fully operational!
================================================================================
```

---

### Step 2: Integrate Regime Filter (if not already done)

If Test 8 fails ("Regime In Validator"), run the integration script:

```bash
python integrate_regime_filter.py
```

**What this does:**
1. Creates a backup of `signal_validator.py`
2. Adds `regime_filter` import statement
3. Inserts CHECK 0A between daily bias and time-of-day checks
4. Tests the integration automatically

**Expected Output:**
```
================================================================================
  REGIME FILTER INTEGRATION
================================================================================

[1/5] Creating backup...
✅ Backup created: signal_validator.py.backup_20260225_161900

[2/5] Reading signal_validator.py...

[3/5] Checking for existing integration...

[4/5] Adding regime filter import...
✅ Import added

[5/5] Adding CHECK 0A (Regime Filter)...
✅ CHECK 0A added

[6/6] Writing updated signal_validator.py...
✅ File updated successfully

================================================================================
✅ REGIME FILTER INTEGRATION COMPLETE
================================================================================

Next steps:
  1. Review the changes in signal_validator.py
  2. Run: python test_full_pipeline.py
  3. Commit and push changes to GitHub
  4. Deploy to Railway

================================================================================
  Running integration test...
================================================================================

✅ Validator imported successfully
✅ Regime check executed
   Regime: TRENDING
   Favorable: True
   Reason: Strong uptrend with moderate volatility

✅ Integration verified - regime filter is working!
```

---

### Step 3: Manual Validation Testing

Test specific scenarios:

#### Test Scenario A: TRENDING Market (Should PASS)

```python
python -c "
from regime_filter import regime_filter
from signal_validator import get_validator

# Check regime
state = regime_filter.get_regime_state(force_refresh=True)
print(f'Regime: {state.regime}')
print(f'Favorable: {state.favorable}')

# Validate a signal
validator = get_validator()
should_pass, conf, metadata = validator.validate_signal(
    'SPY', 'BUY', 500.0, 50_000_000, 0.75
)

print(f'\nSignal Decision: {"PASS" if should_pass else "FILTER"}')
print(f'Confidence: {conf*100:.1f}%')
if 'regime_filter' in metadata['checks']:
    print(f'Regime Check: {metadata["checks"]["regime_filter"]}')
"
```

**Expected Result:**
- Regime: TRENDING
- Signal: PASS
- Confidence boost: +5%

#### Test Scenario B: VOLATILE Market (Should PENALIZE)

```python
python -c "
from data_manager import data_manager

# Simulate high VIX
data_manager.vix_cache = {'value': 35.0, 'timestamp': ...}

# Now test validation
# (same code as above)
"
```

**Expected Result:**
- Regime: VOLATILE
- Signal: Heavy penalty (-30%)
- May still pass if base confidence is high enough

---

### Step 4: Live System Test

Run the scanner in a controlled environment:

```bash
# Start scanner (will run pre-market watchlist build)
python scanner.py
```

**What to watch for:**

1. **Pre-Market Bias Analysis** (4:00-9:30 AM ET)
   ```
   ========================================================================
   📋  PRE-MARKET DAILY BIAS ANALYSIS  (ICT Top-Down)
   ========================================================================
     [BULL   ] SPY    85% conf | PDH: $500.25  PDL: $495.10
     [NEUTRAL] QQQ    45% conf | PDH: $425.50  PDL: $420.75
   ========================================================================
   ```

2. **Regime Filter Check** (each scan cycle)
   ```
   [OPTIONS] Context — 20/25 scored | Avg: 65 | High(≥60): 12 | Weak(<30): 2
   [REGIME] Current: TRENDING | VIX: 18.5 | SPY ADX: 32 | FAVORABLE ✅
   ```

3. **Signal Validation** (when breakout detected)
   ```
   [VALIDATOR] ✅ AAPL in TRENDING regime (+5%): Strong uptrend with moderate volatility
   [VALIDATOR TEST] AAPL ✅ | Conf: 75% → 82% 📈 (+7%) | Score: 7/10
   
   🚨 BREAKOUT SIGNAL DETECTED: AAPL
   Signal: BUY @ $175.50
   Confidence: 82%
   Stop: $174.20
   Target: $177.80
   ```

4. **Regime Penalty** (when market turns choppy)
   ```
   [VALIDATOR] ⚠️  TSLA in CHOPPY regime (-30%): Low ADX indicates consolidation
   [VALIDATOR TEST] TSLA ❌ | Conf: 70% → 45% 📉 (-25%) | Score: 3/10
   Would filter: REGIME_CHOPPY, ADX_WEAK, VOLUME_WEAK
   
   [SIGNALS] TSLA FILTERED - weak confirmation
   ```

---

## Validation Logic Summary

### Signal Passes If:
1. **Base confidence ≥ 60%** (from CFW6 detector)
2. **More checks passed than failed** (normal mode)
3. **Adjusted confidence ≥ 30%** (after all boosts/penalties)

### Regime Filter Impact:

| Regime | VIX | SPY ADX | Confidence Change | Pass Rate Impact |
|--------|-----|---------|-------------------|------------------|
| TRENDING | < 30 | > 25 | **+5%** | High (80-90%) |
| CHOPPY | < 30 | < 25 | **-30%** | Low (20-30%) |
| VOLATILE | > 30 | Any | **-30%** | Low (10-20%) |

### Example Calculations:

**Scenario 1: TRENDING Market**
```
Base Confidence:     75%
Regime Boost:       + 5%
EMA Stack:          + 7%
Volume Strong:      +10%
ADX Strong:         + 5%
                    ----
Final Confidence:   102% (capped at 100%)
Decision:           PASS ✅
```

**Scenario 2: CHOPPY Market**
```
Base Confidence:     75%
Regime Penalty:     -30%
ADX Weak:           - 5%
Time Dead Zone:     - 3%
Volume OK:          + 3%
                    ----
Final Confidence:    40%
Decision:           FILTERED ❌
```

**Scenario 3: CHOPPY Market with VPVR Rescue**
```
Base Confidence:     75%
Regime Penalty:     -30%
VPVR Strong (POC):  +24% (80% of penalty recovered)
Volume Strong:      +10%
EMA Full Stack:     + 7%
                    ----
Final Confidence:    86%
Decision:           PASS ✅ (rescued by excellent entry)
```

---

## Troubleshooting

### Issue: "regime_filter not available"

**Cause**: `regime_filter.py` not in the same directory

**Fix**:
```bash
# Verify file exists
ls -la regime_filter.py

# If missing, check Git
git status
git pull origin main
```

### Issue: "VIX data not available"

**Cause**: EODHD API key not set or invalid

**Fix**:
```bash
# Check API key
echo $EODHD_API_KEY

# Test VIX fetch manually
python -c "from data_manager import data_manager; print(data_manager.get_vix_level())"
```

### Issue: "SPY bars insufficient for ADX"

**Cause**: Not enough historical data in database

**Fix**:
```bash
# Backfill SPY data
python -c "
from data_manager import data_manager
data_manager.startup_backfill(['SPY'], days=30)
print('Backfill complete')
"
```

### Issue: All signals being filtered

**Cause**: Market in unfavorable regime OR validation too strict

**Debug**:
```bash
# Check current regime
python -c "from regime_filter import regime_filter; regime_filter.print_regime_summary()"

# Check validation stats
python -c "
from signal_generator import signal_generator
print(signal_generator.get_validation_stats_summary())
"
```

---

## Deployment Checklist

### Local Testing
- [ ] `test_full_pipeline.py` passes all 8 tests
- [ ] `integrate_regime_filter.py` completes successfully
- [ ] Manual validation tests pass (TRENDING/CHOPPY/VOLATILE scenarios)
- [ ] Scanner runs without errors in pre-market
- [ ] Signals generate and validate correctly

### Git Commit
```bash
git add signal_validator.py regime_filter.py
git add test_full_pipeline.py integrate_regime_filter.py TESTING_GUIDE.md
git commit -m "Add regime filter to signal validator - CHECK 0A integration"
git push origin main
```

### Railway Deployment
1. Push changes to GitHub (triggers auto-deploy)
2. Monitor deployment logs
3. Check for regime filter initialization message:
   ```
   [VALIDATOR] ✅ Regime filter enabled (TRENDING/CHOPPY/VOLATILE)
   ```
4. Watch first scan cycle for regime check output

### Post-Deployment Monitoring

Watch Discord for:
- Pre-market bias analysis (confirms bias engine working)
- Signal alerts with validation metadata (confirms validator working)
- Regime status in signal validation logs

Expected in Discord:
```
🚨 **BREAKOUT ALERT**
👉 AAPL BUY @ $175.50
Confidence: 82% (⬆️ +7%)
Stop: $174.20 | Target: $177.80
Risk/Reward: 1:2.0

✅ **Validation Test:** 7/10 checks
Confidence: 75% → 82%
```

---

## Performance Metrics

### Expected Signal Quality Improvement

**Before Regime Filter:**
- Signal count: ~50-80 per day
- Win rate: 45-55%
- False breakouts: High during choppy markets

**After Regime Filter:**
- Signal count: ~30-50 per day (filtered out 30-40%)
- Win rate: 60-70% (target)
- False breakouts: Significantly reduced

### Key Metrics to Track

1. **Regime Distribution**
   - % of day in each regime
   - Correlation with win rate

2. **Filter Impact**
   - Signals blocked by regime filter
   - Win rate of blocked vs allowed signals

3. **VPVR Rescue Rate**
   - Counter-trend signals rescued by VPVR
   - Win rate of rescued signals

---

## Next Steps

1. **Run full pipeline test**: `python test_full_pipeline.py`
2. **Integrate if needed**: `python integrate_regime_filter.py`
3. **Test manually**: Run through scenarios A & B
4. **Deploy to Railway**: Push to GitHub
5. **Monitor first trading day**: Watch for regime checks in Discord

---

## Support

If you encounter issues:

1. Check logs in `test_full_pipeline.py` output
2. Review backups in `signal_validator.py.backup_*`
3. Verify all modules are up to date: `git pull origin main`
4. Test individual components before full system test

---

**Last Updated**: February 25, 2026
**War Machine Version**: CFW6 + Regime Filter (Phase 2C)
