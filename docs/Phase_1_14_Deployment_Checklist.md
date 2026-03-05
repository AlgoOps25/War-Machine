# Phase 1.14 Production Deployment Checklist

**Version:** 1.0  
**Date:** March 5, 2026  
**Components:** EODHD Options API, SPY Correlation, ML Training Pipeline  

---

## Pre-Deployment Checklist

### ☐ 1. Code Review

- [ ] All Phase 1.14 commits merged to `main` branch
- [ ] Code review completed (no merge conflicts)
- [ ] Unit tests passing locally
- [ ] Integration tests passing (`tests/test_phase_1_14.py`)

**Verify:**
```bash
git log --oneline | head -10
# Should see commits:
# - "Phase 1.14: EODHD options API integration"
# - "Phase 1.14: SPY correlation checker"
# - "Phase 1.14: ML trainer pipeline"
# - "Phase 1.14: Integration test suite"
```

---

### ☐ 2. Environment Variables

#### Railway Environment Variables

Log into Railway dashboard and verify/add:

**Required:**
```bash
EODHD_API_KEY="your_eodhd_api_key_here"
```

**Optional (for ML training):**
```bash
DATABASE_URL="postgresql://..."  # Already set by Railway
```

**Verification:**
```bash
# In Railway shell
echo $EODHD_API_KEY  # Should output your key (not empty)
echo $DATABASE_URL   # Should output PostgreSQL connection string
```

---

### ☐ 3. Dependencies

**Verify `requirements.txt` includes:**
```
requests>=2.31.0
numpy>=1.24.0
scikit-learn>=1.3.0
joblib>=1.3.0
psycopg2-binary>=2.9.0
```

**Test locally:**
```bash
pip install -r requirements.txt
python -c "import requests, numpy, sklearn, joblib, psycopg2"
# Should run without errors
```

---

### ☐ 4. Database Schema

**Verify `signals` table exists:**
```sql
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'signals';
```

**Required columns for ML training:**
- `id` (SERIAL PRIMARY KEY)
- `ticker` (VARCHAR)
- `confidence` (FLOAT)
- `rvol` (FLOAT)
- `adx` (FLOAT)
- `signal_time` (TIMESTAMP)
- `spy_correlation` (FLOAT)
- `pattern_type` (VARCHAR)
- `or_classification` (VARCHAR)
- `iv_rank` (FLOAT)
- `mtf_convergence` (FLOAT)
- `outcome` (VARCHAR) -- 'WIN' or 'LOSS'
- `completed_at` (TIMESTAMP)

**If missing, create with:**
```sql
ALTER TABLE signals ADD COLUMN IF NOT EXISTS spy_correlation FLOAT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS pattern_type VARCHAR(50);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS or_classification VARCHAR(20);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS iv_rank FLOAT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS mtf_convergence FLOAT;
```

---

## Deployment Steps

### ☐ Step 1: Run Local Tests

```bash
# Full test suite
python tests/test_phase_1_14.py

# Expected: All tests pass with ✅ marks
```

**If tests fail:**
- Review error logs
- Check environment variables
- Verify API keys are valid
- Ensure data manager is running

---

### ☐ Step 2: Test Individual Components

**EODHD API:**
```python
python -c "
from app.options import get_greeks
greeks = get_greeks('AAPL', 150.0, '2026-03-20', 'CALL')
print(f'Delta: {greeks[\"delta\"]}, Price: ${greeks[\"price\"]}')
assert greeks['delta'] != 0.5, 'Using placeholder Greeks - API not working'
print('\u2705 EODHD API working')
"
```

**SPY Correlation:**
```python
python -c "
from app.filters.correlation import check_spy_correlation
result = check_spy_correlation('TSLA')
print(f'Correlation: {result[\"correlation\"]:.3f}')
assert -1 <= result['correlation'] <= 1, 'Invalid correlation'
print('\u2705 SPY correlation working')
"
```

**ML Model Status:**
```python
python -c "
from app.ml.ml_trainer import get_model_info
info = get_model_info()
print(f'Status: {info[\"status\"]}')
if info['status'] == 'trained':
    print(f'Accuracy: {info[\"metrics\"][\"accuracy\"]:.2%}')
print('\u2705 ML pipeline functional')
"
```

---

### ☐ Step 3: Deploy to Railway

**Push to GitHub:**
```bash
git status
git add .
git commit -m "Phase 1.14: Production deployment"
git push origin main
```

**Railway Auto-Deploy:**
- Railway detects new commit
- Builds Docker image
- Deploys to production
- Monitor build logs in Railway dashboard

**Manual Deploy (if needed):**
```bash
railway up
```

---

### ☐ Step 4: Verify Deployment

**Check Railway logs:**
```bash
railway logs
```

**Look for startup messages:**
```
[SIGNALS] ✅ Adaptive target discovery enabled (90-day historical analysis)
[SIGNALS] ✅ ML Confidence Booster enabled (Task 4 - ML signal scoring)
[SIGNALS] ✅ MTF Validator enabled (Task 5 - Multi-timeframe validation)
[SIGNALS] ✅ Opening Range Detection enabled (Task 7 - OR tight/wide classification)
[VALIDATOR] ✅ Multi-indicator validator ACTIVE (FULL MODE)
```

**Test API in production:**
```bash
# SSH into Railway
railway shell

# Run test
python tests/test_phase_1_14.py
```

---

## Post-Deployment Monitoring

### ☐ 1. Monitor Logs (First Hour)

**Watch for Phase 1.14 components:**
```bash
railway logs --tail 100
```

**Expected log entries:**

**EODHD API calls:**
```
[OPTIONS] Fetching options chain for NVDA...
[OPTIONS] ✅ NVDA: Real Greeks fetched (delta=0.55, IV=42%)
[IVR] NVDA: IV=42.0% | IVR=55 (100 obs) | 1.05x [IVR-NORMAL]
```

**SPY Correlation adjustments:**
```
[CORRELATION] TSLA: SPY corr=0.82 (MARKET_DRIVEN) -> confidence -5%
[CORRELATION] NVDA: SPY corr=0.35 (INDEPENDENT) -> confidence +5%
[CORRELATION] AAPL: SPY corr=0.15 (DIVERGENT) -> confidence +10%
```

**Validation with new features:**
```
[VALIDATOR] NVDA BUY signal validated: 5/5 checks passed
[VALIDATOR]   Passed: BIAS_ALIGNED_BULL, REGIME_TRENDING, VOLUME_STRONG, ADX_OK, EMA_FULL_STACK
[VALIDATOR]   Adjusted confidence: 72.5% -> 78.2% (+5.7%)
```

---

### ☐ 2. Verify Signal Quality (First Day)

**Check signal outcomes:**
```sql
SELECT 
    COUNT(*) as total_signals,
    COUNT(CASE WHEN spy_correlation IS NOT NULL THEN 1 END) as signals_with_correlation,
    AVG(spy_correlation) as avg_correlation,
    COUNT(CASE WHEN iv_rank IS NOT NULL THEN 1 END) as signals_with_ivr
FROM signals
WHERE signal_time >= NOW() - INTERVAL '1 day';
```

**Expected:**
- `signals_with_correlation` = `total_signals` (100%)
- `avg_correlation` between 0.3-0.6
- `signals_with_ivr` > 0 (if options trades generated)

---

### ☐ 3. Monitor Performance Metrics

**API Call Volume:**
```bash
# Count EODHD API calls in logs
railway logs | grep "[OPTIONS] Fetching" | wc -l

# Should be < 100,000 per day (API rate limit)
```

**Correlation Impact:**
```sql
SELECT 
    CASE 
        WHEN spy_correlation > 0.7 THEN 'Market-Driven'
        WHEN spy_correlation < 0.3 THEN 'Independent'
        ELSE 'Neutral'
    END as correlation_type,
    COUNT(*) as signal_count,
    AVG(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as win_rate
FROM signals
WHERE spy_correlation IS NOT NULL
    AND outcome IN ('WIN', 'LOSS')
GROUP BY correlation_type;
```

**Expected:**
- Independent signals: Higher win rate
- Market-driven signals: Lower win rate (validates filter)

---

## Rollback Plan

**If issues detected:**

### Option 1: Disable Phase 1.14 Features

**Revert to previous commit:**
```bash
git revert HEAD~4..HEAD  # Revert last 4 commits
git push origin main
```

### Option 2: Disable Specific Components

**Disable EODHD API (fallback to placeholders):**
```bash
# In Railway environment variables
EODHD_API_KEY=""  # Empty string
```

**Disable SPY Correlation:**
Comment out in `signal_generator.py`:
```python
# corr_result = check_spy_correlation(ticker)
# base_confidence += corr_result['confidence_adjustment'] / 100.0
```

### Option 3: Emergency Stop

```bash
railway down  # Stop service
# Fix issues
railway up    # Restart service
```

---

## Success Criteria

### Day 1
- [ ] All components start without errors
- [ ] EODHD API returns real Greeks (not placeholders)
- [ ] SPY correlation adjustments logged
- [ ] Validation confidence adjustments applied
- [ ] No critical errors in logs

### Week 1
- [ ] 10+ signals with SPY correlation data
- [ ] Options trades generated with IV Rank
- [ ] Correlation filter reduces false signals
- [ ] Win rate maintained or improved

### Month 1
- [ ] 100+ signal outcomes collected
- [ ] ML model trained with 70%+ accuracy
- [ ] ML predictions improving confidence adjustments
- [ ] 5-10% win rate improvement documented

---

## Troubleshooting

### Issue: EODHD API returning placeholders

**Check:**
1. `EODHD_API_KEY` set in Railway
2. API key valid (test with curl)
3. Rate limit not exceeded (< 100K/day)

**Test:**
```bash
curl "https://eodhd.com/api/options/AAPL.US?api_token=$EODHD_API_KEY"
```

---

### Issue: SPY correlation always 0.0

**Check:**
1. SPY in watchlist
2. Data manager populating SPY bars
3. Minimum 20 bars available

**Test:**
```python
from app.data.data_manager import data_manager
spy_bars = data_manager.get_bars_from_memory('SPY', limit=20)
print(f"SPY bars: {len(spy_bars)}")
```

---

### Issue: Validation adjustments too aggressive

**Tune thresholds:**
- Reduce correlation boost/penalty (currently ±5%)
- Adjust ADX threshold (currently 25)
- Modify volume multiplier (currently 1.5x)

**Edit:** `app/validation/validation.py`

---

## Sign-Off

**Deployed by:** __________________  
**Date:** __________________  
**Version:** Phase 1.14  
**Status:** ☐ Deployed ☐ Rolled Back  

**Notes:**

---

**Next Phase:** Phase 1.15 - Broker Integration (IBKR/Robinhood)
