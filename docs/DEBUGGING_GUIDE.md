# War Machine Debugging Guide

## Overview

**Purpose:** Systematic debugging of War Machine after Phase 4 data collection.

**When to Use:** After 2-4 weeks of Phase 4 monitoring, when you have:
- 20+ closed trades
- Signal funnel data (generated → validated → armed → traded)
- Performance metrics by grade, ticker, time

**Execution Order:** Run Phase 4 first, collect data, then debug systematically.

---

## Current Situation Analysis

### Your Current Stats (3 trades):
- **Win Rate: 0%** (0W-3L)
- **Total P&L: -$1,143**
- **All Grade A trades**
- **No stops hit** (0% stop hit rate)
- **Tickers: MCD, WFC, MS**

### Initial Assessment:

⚠️ **Too early for conclusions** - 3 trades is statistically insignificant. Could be:
1. Bad luck (3 losses can happen even with 70% win rate system)
2. Adverse market conditions during those 3 trades
3. System issues that need fixing
4. Combination of above

**Action:** Collect 20+ trades before debugging. Then follow this guide.

---

## Debugging Workflow

### Phase 1: Data Collection (Weeks 1-2)

**Goal:** Gather comprehensive data via Phase 4 monitoring.

**What to Track:**
- ✅ Signal generation rate (signals per day)
- ✅ Validation pass rate (% signals that pass filters)
- ✅ Armed rate (% validated signals that confirm)
- ✅ Trade execution rate (% armed signals that trade)
- ✅ Win rate by grade (A+, A, A-)
- ✅ Win rate by ticker
- ✅ Win rate by time of day
- ✅ Stop hit rate by grade
- ✅ Average hold time winners vs losers

**Minimum Thresholds:**
- 20+ closed trades for basic analysis
- 50+ trades for robust conclusions
- 100+ trades for statistical significance

---

### Phase 2: Signal Funnel Analysis (After Week 2)

**Query the signal funnel:**

```sql
SELECT 
    stage,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM signal_events
WHERE session_date >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY stage
ORDER BY 
    CASE stage
        WHEN 'GENERATED' THEN 1
        WHEN 'VALIDATED' THEN 2
        WHEN 'REJECTED' THEN 3
        WHEN 'ARMED' THEN 4
        WHEN 'TRADED' THEN 5
    END;
```

**Healthy Funnel Metrics:**
- Generated: 100 (baseline)
- Validated: 30-50 (30-50% pass rate)
- Rejected: 50-70 (50-70% rejection rate)
- Armed: 15-25 (50-80% of validated get armed)
- Traded: 10-20 (60-80% of armed get traded)

**Red Flags:**

🚨 **Too few signals generated** (<20/day):
- Check scanner is running
- Verify tickers list not too narrow
- Review signal criteria (too strict?)

🚨 **Too many rejections** (>80%):
- Validators too strict
- Check rejection reasons:
  ```sql
  SELECT rejection_reason, COUNT(*) 
  FROM signal_events 
  WHERE stage = 'REJECTED'
  GROUP BY rejection_reason
  ORDER BY COUNT(*) DESC;
  ```
- Consider relaxing dominant rejection criteria

🚨 **Low arm rate** (<40% of validated):
- Confirmation logic too strict
- Signals expiring before confirmation
- Check bars_to_confirmation average:
  ```sql
  SELECT AVG(bars_to_confirmation), MAX(bars_to_confirmation)
  FROM signal_events
  WHERE stage = 'ARMED';
  ```

🚨 **Low trade rate** (<50% of armed):
- Check position limits
- Review capital availability
- Check order execution logs

---

### Phase 3: Grade Validation (After Week 2)

**Objective:** Verify grading system accuracy.

**Query grade performance:**

```sql
SELECT 
    grade,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as win_rate,
    ROUND(AVG(pnl), 2) as avg_pnl,
    ROUND(SUM(pnl), 2) as total_pnl
FROM positions
WHERE UPPER(status) = 'CLOSED'
  AND pnl IS NOT NULL
  AND grade IS NOT NULL
GROUP BY grade
ORDER BY grade;
```

**Expected vs Actual:**

| Grade | Expected WR | Actual WR | Assessment |
|-------|-------------|-----------|------------|
| A+    | 75%         | ?         | ?          |
| A     | 65%         | ?         | ?          |
| A-    | 55%         | ?         | ?          |

**Debugging by Result:**

#### Case 1: Grade A+ below 65%
🚨 **Problem:** A+ grading too lenient.

**Diagnosis Steps:**
1. Review A+ grading criteria in code
2. Check confidence thresholds
3. Analyze what made losing A+ signals get graded A+:
   ```sql
   SELECT ticker, signal_type, base_confidence, pnl
   FROM signal_events se
   JOIN positions p ON se.position_id = p.id
   WHERE grade = 'A+' AND pnl < 0
   ORDER BY pnl ASC
   LIMIT 10;
   ```

**Fixes:**
- Raise A+ confidence threshold (e.g., 80 → 85)
- Add additional A+ requirements (e.g., must have UOA boost)
- Review false positive patterns

#### Case 2: All grades below target
🚨 **Problem:** System-wide issue.

**Possible Causes:**
1. **Entry timing:** Entering too late?
2. **Stop placement:** Stops too tight?
3. **Target placement:** Targets too aggressive?
4. **Market conditions:** Adverse conditions during sample period?
5. **Signal quality:** Underlying edge weak?

**Diagnosis:**

**Check Entry Slippage:**
```sql
SELECT 
    ticker,
    entry_price,
    -- Compare to signal's intended entry (if tracked)
    ROUND(ABS(entry_price - intended_entry) / intended_entry * 100, 2) as slippage_pct
FROM positions
WHERE UPPER(status) = 'CLOSED';
```

**Check Stop Hit Rate:**
```sql
SELECT 
    grade,
    COUNT(*) as total,
    SUM(CASE WHEN exit_reason = 'stop_loss' THEN 1 ELSE 0 END) as stop_hits,
    ROUND(SUM(CASE WHEN exit_reason = 'stop_loss' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as stop_hit_rate
FROM positions
WHERE UPPER(status) = 'CLOSED'
GROUP BY grade;
```

**Ideal Stop Hit Rate:** 20-30%
- **>40%:** Stops too tight → widen by 15-20%
- **<15%:** Stops too wide → tighten by 10%

**Check Target Hit Rate:**
```sql
SELECT 
    grade,
    COUNT(*) as total,
    SUM(CASE WHEN t1_hit THEN 1 ELSE 0 END) as t1_hits,
    ROUND(SUM(CASE WHEN t1_hit THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as t1_hit_rate
FROM positions
WHERE UPPER(status) = 'CLOSED'
GROUP BY grade;
```

**Ideal T1 Hit Rate:** 60-70%
- **<50%:** Targets too aggressive → reduce by 10-15%
- **>80%:** Targets too conservative → increase by 10%

---

### Phase 4: Ticker Analysis (After Week 2)

**Query ticker performance:**

```sql
SELECT 
    ticker,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as win_rate,
    ROUND(AVG(pnl), 2) as avg_pnl,
    ROUND(SUM(pnl), 2) as total_pnl
FROM positions
WHERE UPPER(status) = 'CLOSED'
  AND pnl IS NOT NULL
GROUP BY ticker
HAVING COUNT(*) >= 3  -- Minimum 3 trades
ORDER BY win_rate DESC;
```

**Action Items:**

**Whitelist** (70%+ WR, 5+ trades):
- Add to preferred ticker list
- Increase position size allocation
- Consider lowering grade threshold for these tickers

**Blacklist** (<40% WR, 5+ trades):
- Temporarily block from trading
- Investigate why performing poorly
- Revisit after parameter adjustments

**Watch List** (40-70% WR or <5 trades):
- Continue monitoring
- No changes yet

---

### Phase 5: Time-Based Analysis (After Week 2)

**Query performance by hour:**

```sql
SELECT 
    EXTRACT(HOUR FROM entry_time) as hour,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as win_rate,
    ROUND(AVG(pnl), 2) as avg_pnl
FROM positions
WHERE UPPER(status) = 'CLOSED'
  AND pnl IS NOT NULL
GROUP BY EXTRACT(HOUR FROM entry_time)
ORDER BY hour;
```

**Common Patterns:**

✅ **10:00-11:00 AM:** Often best time (post-open volatility settled)
⚠️ **9:30-10:00 AM:** Risky (opening volatility)
⚠️ **3:30-4:00 PM:** Risky (closing volatility, gamma)

**Action:**
- Block trading during poor-performing hours
- Focus on high-win-rate time windows

---

### Phase 6: Parameter Optimization (After Week 3-4)

**After 30+ trades, run parameter optimizer:**

```bash
python parameter_optimizer.py --min-trades 30
```

**Review Recommendations:**

Example Output:
```
=== STOP LOSS OPTIMIZATION ===
A+: Current 1.8% | Recommended 2.1% | Stop Hit Rate: 42% → Target: 25%
A:  Current 2.2% | Recommended 2.5% | Stop Hit Rate: 38% → Target: 25%
A-: Current 2.5% | Keep current    | Stop Hit Rate: 28% ✓

=== TARGET OPTIMIZATION ===
A+: T1 hit 48% | Recommended: Reduce T1 by 10% (too aggressive)
A:  T1 hit 62% | Keep current ✓
A-: T1 hit 71% | Consider increasing T1 by 5%

=== TICKER RECOMMENDATIONS ===
Whitelist: AAPL (75% WR, 12 trades), SPY (80% WR, 10 trades)
Blacklist: AMD (30% WR, 10 trades), TSLA (25% WR, 8 trades)
```

**Apply Changes:**

1. Update `config.py`:
```python
GRADE_PARAMETERS = {
    'A+': {
        'stop_width_pct': 2.1,  # Was 1.8
        't1_multiplier': 1.8,   # Was 2.0 (reduced)
        't2_multiplier': 3.0
    },
    # ...
}

TICKER_WHITELIST = ['AAPL', 'SPY', 'MSFT', 'GOOGL']  # High performers
TICKER_BLACKLIST = ['AMD', 'TSLA']  # Poor performers
```

2. Commit and deploy:
```bash
git add config.py
git commit -m "feat: Apply parameter optimizer recommendations"
git push origin main
```

3. Monitor for 1-2 weeks, then re-run optimizer

---

## Specific Issue Debugging

### Issue: Win Rate Too Low (<50%)

**Step 1:** Check if it's grade-specific
```sql
SELECT grade, win_rate FROM grade_performance;
```

- All grades low? → System-wide issue (entry/exit logic)
- Only certain grades? → Grade-specific issue (grading criteria)

**Step 2:** Review losing trades manually
```sql
SELECT ticker, grade, entry_price, exit_price, pnl, exit_reason, entry_time, exit_time
FROM positions
WHERE pnl < 0
ORDER BY pnl ASC
LIMIT 10;
```

**Step 3:** Look for patterns:
- Same exit reason? (e.g., all stop losses)
- Same time of day?
- Same ticker?
- Same market condition? (check SPY that day)

**Step 4:** Apply targeted fix based on pattern

---

### Issue: Stops Getting Hit Too Often (>40%)

**Diagnosis:**

```sql
SELECT 
    grade,
    AVG(ABS(stop_price - entry_price) / entry_price * 100) as avg_stop_width_pct,
    COUNT(*) filter (WHERE exit_reason = 'stop_loss') as stop_hits,
    COUNT(*) as total
FROM positions
WHERE UPPER(status) = 'CLOSED'
GROUP BY grade;
```

**Fix: Widen stops by 15-20%**

Example:
```python
# Before:
stop_width_pct = 1.8  # A+ grade

# After:
stop_width_pct = 2.1  # Widened by 17%
```

**Tradeoff:** Wider stops = lower win rate but better R:R

---

### Issue: Not Trading Enough (<5 trades/day)

**Diagnosis: Check signal funnel**

```sql
SELECT stage, COUNT(*) 
FROM signal_events 
WHERE session_date = CURRENT_DATE 
GROUP BY stage;
```

**Bottleneck Analysis:**

**1. Few signals generated:**
- Expand ticker universe
- Relax signal criteria
- Check scanner is running properly

**2. High rejection rate:**
- Review rejection reasons
- Relax most common rejection criteria

**3. Low arm rate:**
- Reduce confirmation bars required
- Relax confirmation criteria

**4. Low trade rate:**
- Check capital availability
- Review position limits
- Check order execution

---

### Issue: Consistent Daily Losses

**Pattern: Profitable some days, losing others**

This is normal. Even 70% win rate = 30% loss days.

**Pattern: Losing 5+ days in a row**

🚨 **Red Flag:** Circuit breaker should have triggered.

Check:
1. Circuit breaker enabled? (`ENABLE_CIRCUIT_BREAKER = True`)
2. Threshold appropriate? (default: 3 losses)
3. Is it bypassed somehow?

**Pattern: Losing trend over 2+ weeks**

**Possible Causes:**
1. **Market regime changed** (strategy performs better in certain conditions)
2. **Parameters need retuning** (run optimizer)
3. **Signal quality degraded** (check signal funnel)
4. **External factor** (new regulations, volatility collapse, etc.)

**Action:**
1. Stop trading
2. Review recent trades
3. Check market conditions (VIX, market internals)
4. Retrain/retune if needed
5. Paper trade for 1 week before resuming

---

## Systematic Debugging Checklist

After 20+ trades, work through this list:

- [ ] **Step 1:** Run `adaptive_historical_tuner.py` → Get overview
- [ ] **Step 2:** Query signal funnel → Identify bottlenecks
- [ ] **Step 3:** Validate grade performance → Check if grading accurate
- [ ] **Step 4:** Analyze stop hit rates → Adjust stop widths
- [ ] **Step 5:** Review target hit rates → Adjust targets
- [ ] **Step 6:** Check ticker performance → Whitelist/blacklist
- [ ] **Step 7:** Time-of-day analysis → Block bad hours
- [ ] **Step 8:** Run `parameter_optimizer.py` → Get recommendations
- [ ] **Step 9:** Apply optimized parameters → Update config.py
- [ ] **Step 10:** Deploy and monitor → Collect 2 more weeks data
- [ ] **Step 11:** Repeat from Step 1 → Continuous optimization

---

## When to Stop and Redesign

If after 100+ trades and multiple optimization cycles:
- Win rate still <50%
- Sharpe ratio <0.5
- Max drawdown >20%
- No consistent edge visible

**Action: Major Redesign**
1. Review core strategy assumptions
2. Test different timeframes
3. Try different signal types
4. Consider ML-based approach (Phase 5)
5. Backtest extensively before deploying again

---

## Summary

**Execution Order:**
1. ✅ Deploy Phase 4 (2-3 hours)
2. ⏳ Collect 2-4 weeks of data (passive)
3. 🔍 Run debugging analysis (this guide)
4. 🔧 Apply fixes and optimizations
5. 🔁 Repeat every 2-4 weeks

**Key Principle:** Data-driven optimization beats guessing. Let the data tell you what's working and what's not.

---

**Start by deploying Phase 4, then return to this guide after 20+ trades!**
