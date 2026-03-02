# DTE Selector - Intelligence Architecture

## Overview

The DTE (Days to Expiration) selector uses a **3-layer intelligence system** to recommend optimal options expiration based on real market data, not arbitrary thresholds.

---

## Three-Layer Architecture

### 1. **PRIMARY: Historical Market Pattern Analysis (70% weight)**

**What it does:**
- Analyzes 90 days of 1-minute SPY bars from EODHD
- Simulates entry at every bar, measures time-to-target
- Buckets by context: Hour of day, ADX regime, VIX level
- Answers: *"How long do +0.75% moves typically take at 2:30 PM in choppy/high-VIX conditions?"*

**Why it's primary:**
- REAL market data, not guesses
- Accounts for market regime (trending vs choppy)
- Accounts for volatility environment (VIX)
- Accounts for time of day (9:30 AM vs 2:30 PM)

**How it works:**
```python
from app.options.dte_historical_analyzer import get_historical_dte_recommendation

result = get_historical_dte_recommendation(
    hour_of_day=14,  # 2:00 PM
    adx=12.5,        # Choppy market
    vix=21.3,        # Elevated volatility
    target_pct=0.75, # 0.75% profit target
    time_remaining_hours=1.8
)

print(result)
# {
#   'recommended_dte': 1,
#   'confidence': 78.5,
#   'p50_hold_time_min': 52,
#   'success_rate_60min': 45.2,
#   'sample_size': 142,
#   'reasoning': '1DTE recommended: Only 45% of moves completed in <60min...'
# }
```

---

### 2. **SECONDARY: Live Options Market Data (30% weight)**

**What it does:**
- Fetches real-time options chain from EODHD
- Analyzes liquidity (OI, volume)
- Checks theta decay rates
- Evaluates bid/ask spreads
- Can override historical recommendation if extreme conditions

**Why it's secondary:**
- Validates historical recommendation
- Catches extreme market conditions (wide spreads, no liquidity)
- Provides strike recommendations with Greeks

---

### 3. **TERTIARY: Personal Trade Outcomes (Future)**

**What it will do (not yet implemented):**
- Track your actual hold times by DTE
- Compare to historical expectations
- Answer: *"Did my 0DTE selections match my actual execution speed?"*
- Calibrate system to your specific patterns

**Why it's tertiary:**
- Feedback loop, not foundation
- Validates: "Am I entering too late? Exiting too early?"
- Self-corrects over time

---

## Setup Instructions

### Step 1: Run Database Migration

```bash
python app/data/migrations/001_add_dte_tracking.py
```

This adds columns to your `positions` table:
- `dte_selected`: Which DTE was chosen (0 or 1)
- `adx_at_entry`: ADX value when signal generated
- `vix_at_entry`: VIX value when signal generated
- `target_pct_t1`: Target 1 as percentage
- `target_pct_t2`: Target 2 as percentage
- `hour_of_entry`: Hour of day when entered

### Step 2: Build Historical Database (ONE-TIME)

This fetches 90 days of SPY 1-minute bars and analyzes time-to-target patterns:

```python
from app.options.dte_historical_analyzer import dte_historical_analyzer

dte_historical_analyzer.build_historical_database(
    ticker="SPY",
    lookback_days=90,
    target_pcts=[0.5, 0.75, 1.0]
)
```

**Expected output:**
```
[DTE-HISTORICAL] Fetching 1-min data from 2025-12-01 to 2026-03-02...
[DTE-HISTORICAL] Analyzing 125,000+ bars...
[DTE-HISTORICAL] Processed 1000 potential moves...
[DTE-HISTORICAL] Processed 2000 potential moves...
...
[DTE-HISTORICAL] ✅ Analysis complete! 35,478 moves catalogued.
[DTE-HISTORICAL] Ready for intelligent DTE recommendations.
```

**Time required:** 10-15 minutes (one-time process)

**Storage:** ~5-10 MB in `market_memory.db`

---

## Usage in sniper.py

### Current Signature (needs update):

```python
# OLD - missing ADX, VIX, target_pct
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction='BUY',
    confidence=signal_confidence
)
```

### New Signature (with historical analysis):

```python
# NEW - includes market context
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction='BUY',
    confidence=signal_confidence,
    adx=adx,  # From technical_indicators
    vix=vix,  # Fetch from EODHD or use SPY volatility proxy
    target_pct=(t1_price - entry_price) / entry_price * 100
)
```

### Full Integration Example:

```python
# In sniper.py after signal generation

# Calculate ADX (already done in your validator)
adx = technical_indicators.calculate_adx(bars, period=14)

# Get VIX (fetch from EODHD or estimate from SPY ATR)
try:
    vix_data = data_manager.fetch_realtime_quote('VIX')
    vix = vix_data['price']
except:
    # Fallback: estimate from SPY volatility
    vix = 20.0  # Or calculate from SPY bars

# Calculate target percentage
target_pct_t1 = (t1_price - entry_price) / entry_price * 100

# Get DTE recommendation
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction='BUY',
    confidence=final_confidence,
    adx=adx,
    vix=vix,
    target_pct=target_pct_t1
)

if dte_result['dte'] is None:
    print(f"[SIGNAL-SKIP] {dte_result['reasoning']}")
    return None

print(f"[DTE-SELECTED] {dte_result['dte']}DTE")
print(f"Reasoning:\n{dte_result['reasoning']}")
print(f"Confidence: {dte_result['confidence_pct']}%")
```

---

## Output Structure

```python
{
    'dte': 0 or 1 or None,  # None = skip signal
    'expiry_date': '2026-03-03',
    'recommended_strikes': [
        {
            'strike': 520.0,
            'delta': 0.52,
            'theta': -0.12,
            'bid': 2.45,
            'ask': 2.55,
            'mid_price': 2.50,
            'open_interest': 1250,
            'score': 27.5
        }
    ],
    'reasoning': '''📅 SELECTED: 1DTE
Combined Score: 78.5/100

📊 HISTORICAL ANALYSIS (70% weight):
   1DTE recommended: Only 45% of moves completed in <60min.
   Confidence: 78.5%
   Sample Size: 142 moves
   Median Hold Time: 52 min

💹 LIVE OPTIONS DATA (30% weight):
   0DTE Quality: 55/100
   1DTE Quality: 85/100
   ✅ 1DTE liquidity strong
   ✅ 1DTE theta acceptable
   ✅ 1DTE spreads tight
    ''',
    'historical_analysis': {...},
    'live_analysis': {...},
    'combined_score': 78.5,
    'confidence_pct': 78.5,
    'time_remaining_hours': 1.8
}
```

---

## Decision Logic

### Combined Score Calculation:

```
Combined Score = (Historical Score × 0.70) + (Live Options Score × 0.30)

IF Combined Score for 0DTE >= 70:
    Select 0DTE
ELSE:
    Select 1DTE
```

### Fallback Hierarchy:

1. **Both historical + live data available:** Use weighted combination
2. **Only historical data available:** Use historical with 70% weight
3. **Only live data available:** Use live with 30% weight (lower confidence)
4. **No data available:** Fall back to time-only logic:
   - `>= 3.5 hours remaining`: 0DTE
   - `>= 1.0 hours remaining`: 1DTE
   - `< 1.0 hour remaining`: SKIP

---

## Context Bucketing

### Hour of Day:
- **OPEN** (9:30-10:30): High volatility, fast moves
- **MID** (10:30-14:00): Grind, slower moves
- **LATE** (14:00-16:00): Power hour, moderate pace

### ADX Regime:
- **TRENDING** (ADX >= 25): Fast directional moves
- **MODERATE** (ADX 15-25): Mixed conditions
- **CHOPPY** (ADX < 15): Slow, whipsaw moves

### VIX Level:
- **HIGH** (VIX >= 25): Large swings, need more time buffer
- **ELEVATED** (VIX 20-25): Moderate volatility
- **NORMAL** (VIX 15-20): Standard conditions
- **LOW** (VIX < 15): Small moves, fast scalps possible

---

## Troubleshooting

### "No historical data found"

**Solution:** Run the historical database builder:
```python
from app.options.dte_historical_analyzer import dte_historical_analyzer
dte_historical_analyzer.build_historical_database()
```

### "EODHD API error"

**Check:**
1. `EODHD_API_KEY` environment variable is set
2. API key has sufficient credits
3. Network connectivity

### "Historical analyzer not available"

**Check:**
1. `app/options/dte_historical_analyzer.py` exists
2. No import errors (check Python console)
3. Database initialized properly

### Low confidence scores (<60%)

**Reasons:**
- Insufficient historical samples for this context (<30 moves)
- Live options data shows poor liquidity
- Conflicting signals between historical and live

**Action:** System will automatically fall back to time-only logic with warning

---

## Performance Expectations

### Initialization (one-time):
- Historical database build: **10-15 minutes**
- Storage: **5-10 MB**

### Runtime (per signal):
- Historical lookup: **<10 ms** (database query)
- Live options fetch: **200-500 ms** (EODHD API)
- Total: **<1 second per signal**

### Accuracy:
- Historical recommendations based on **30-200 samples per context**
- Confidence degrades gracefully with insufficient data
- System self-improves as your trade history grows

---

## Future Enhancements

### Phase 2: Personal Feedback Loop

```python
# After each trade closes
from app.options.dte_feedback_analyzer import record_dte_outcome

record_dte_outcome(
    ticker='SPY',
    dte_selected=0,
    adx_at_entry=12.5,
    vix_at_entry=21.3,
    target_pct=0.75,
    actual_hold_time_min=68,
    hit_target=True,
    exit_reason='T1'
)

# System learns: "0DTE at 2PM in choppy conditions took 68 min, longer than historical 52 min median"
# Next time: Boost 1DTE recommendation for similar context
```

### Phase 3: ML-Enhanced Scoring

- Train gradient boosting model on features: hour, ADX, VIX, target_pct, RSI, volume
- Predict `P(target within 60 min)`
- Use as additional input layer (20% weight)

---

## Summary

✅ **Foundation:** Historical EODHD market patterns (70% weight)

✅ **Validation:** Live options data (30% weight)

✅ **Feedback:** Your trade outcomes (future)

✅ **Transparency:** Detailed reasoning for every decision

✅ **Graceful degradation:** Falls back to time-only when data unavailable

✅ **Self-improving:** Learns from market + your personal execution

---

**This is data-driven intelligence, not arbitrary rules.** 🎯
