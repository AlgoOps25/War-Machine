# Tasks 4 & 6 Integration Guide

## Overview

Both **Task 4 (ML-Based Signal Scoring)** and **Task 6 (Options Flow Integration)** are now fully integrated into War Machine's signal generation pipeline.

---

## Task 4: ML-Based Signal Scoring

### What It Does

Uses machine learning to predict signal win probability and automatically adjust confidence scores based on:

- Historical signal performance patterns
- Time-of-day effectiveness
- Gap characteristics and volume profiles
- Price levels relative to PDH/PDL and OR
- VIX and market conditions

### How It Works

1. **Feature Extraction**: Extracts 22 features from each signal
   - Time features (hour, day, time since open)
   - Gap features (size, direction, absolute value)
   - Volume features (current, surge ratio, OR volume)
   - Price level features (vs PDH/PDL/OR)
   - Market conditions (VIX)
   - Signal type encoding

2. **ML Prediction**: Trained Random Forest model predicts confidence adjustment
   - Output: -0.15 to +0.15 (±15% adjustment)
   - Model trained on historical signal outcomes
   - Walk-forward validation ensures no lookahead bias

3. **Confidence Update**: Original confidence score adjusted
   - Example: 65% base → 72% after ML boost
   - Clamped to 0-100% range

### Configuration

**File**: `signal_generator.py`

```python
# ML Booster automatically loaded if available
from app.ml.ml_confidence_boost import MLConfidenceBooster

# Initialized in SignalGenerator.__init__()
if ML_BOOSTER_ENABLED:
    self.ml_booster = MLConfidenceBooster()
```

**Training the Model**:

```bash
# From project root
python app/ml/ml_signal_scorer.py

# Output: trained_model.pkl (auto-loaded on next run)
```

### Signal Output

Each signal now includes:

```python
signal['ml_adjustment'] = {
    'original': 65.0,          # Base confidence
    'adjusted': 72.0,          # ML-adjusted
    'delta': +7.0,             # Change
    'model_confidence': 0.07   # ML prediction
}
```

### Discord Alert Enhancement

```
📊 SIGNAL QUALITY:
   Confidence: 72% (📈 ML: +7.0%)
   Pattern: BOS/FVG Breakout
```

---

## Task 6: Options Flow Integration (UOA)

### What It Does

Detects unusual options activity and whale orders to:

- Identify institutional money flow
- Correlate dark pool prints with signals
- Detect sweep orders and large premium trades
- Boost confidence when smart money aligns with signal

### Data Sources

**Primary**: Unusual Whales API (optional, premium recommended)
- Real-time options flow
- Sweep detection
- Dark pool tracking

**Fallback**: EODHD Options Data
- Volume vs Open Interest analysis
- Call/Put premium imbalance
- ATM options activity

### Scoring System

**Whale Score (0-10)**:
- Large orders (>$100k premium): up to 4 pts
- Sweep frequency: up to 3 pts
- Total premium flow: up to 3 pts

**Flow Score (0-10)**:
- Strong directional bias (≥75% calls for BUY): 9 pts
- Moderate bias (≥65%): 7 pts
- Slight bias (≥55%): 5 pts

**Dark Pool Score (0-10)**:
- Correlation with large prints
- Direction alignment

**Overall Score**: Weighted average
- Whale: 50%
- Flow: 30%
- Dark Pool: 20%

### Confidence Boost

- **Strong Whale Activity** (Score ≥7.0): +10-15% confidence
- **Moderate Activity** (Score ≥5.0): +5-10% confidence
- **Normal Activity** (<5.0): No adjustment

### Configuration

**Environment Variables** (`.env`):

```bash
# Optional - enhances whale detection significantly
UNUSUAL_WHALES_API_KEY=your_key_here

# Already configured for options data
EODHD_API_KEY=your_key_here
```

**Get Unusual Whales API**: [unusualwhales.com/pricing](https://unusualwhales.com/pricing)
- Recommended tier: Premium ($49/mo)
- Includes: Real-time flow, sweeps, dark pool

**File**: `signal_generator.py`

```python
# UOA Detector automatically loaded
from app.data.unusual_options import uoa_detector

# Called during signal validation
whale_data = uoa_detector.check_whale_activity(ticker, direction)
```

### Signal Output

Each signal now includes:

```python
signal['uoa'] = {
    'is_unusual': True,
    'whale_score': 8.5,
    'flow_score': 9.0,
    'dark_pool_score': 6.0,
    'overall_score': 8.1,
    'confidence_boost': 0.12,  # +12%
    'summary': 'Strong whale activity detected (Score: 8.1/10)',
    'details': {
        'large_orders': 3,
        'sweep_count': 5,
        'total_premium': 2500000,
        'call_premium': 2100000,
        'put_premium': 400000,
        'flow_ratio': 0.84
    }
}
```

### Discord Alert Enhancement

```
📊 SIGNAL QUALITY:
   Confidence: 77% (🐋 Whale: +12.0%)
   Pattern: BOS/FVG Breakout
```

### Console Output

```
[UOA] 🐋 AAPL | Strong whale activity detected (Score: 8.1/10) | Boost: +12.0%
[UOA-BOOST] AAPL 🐋 | Conf: 65% → 77% (+12.0%) | Score: 8.1/10
```

---

## Combined Impact

Both systems work together sequentially:

1. **Base Signal**: Breakout detector generates 65% confidence
2. **Validation**: Multi-indicator checks (may adjust to 68%)
3. **ML Scoring** (Task 4): Predicts +7% boost → 75%
4. **UOA Detection** (Task 6): Detects whale activity +12% → 87%
5. **Final Signal**: 87% confidence with institutional backing

### Example Signal Flow

```
[SIGNALS] AAPL breakout detected | Base: 65%
[VALIDATOR] ✅ | Conf: 65% → 68% (+3%)
[ML-BOOST] AAPL 📈 | Conf: 68% → 75% (+7%)
[UOA] 🐋 AAPL | Strong whale activity | Score: 8.1/10
[UOA-BOOST] AAPL 🐋 | Conf: 75% → 87% (+12%)
[SIGNALS] Final Confidence: 87% (🚀 High Conviction)
```

---

## Testing

### Test ML Booster

```python
from app.ml.ml_confidence_boost import MLConfidenceBooster

booster = MLConfidenceBooster()
if booster.is_trained:
    features = {...}  # Extract from signal
    adjustment = booster.predict_confidence_adjustment(features)
    print(f"ML Adjustment: {adjustment*100:+.1f}%")
```

### Test UOA Detector

```python
from app.data.unusual_options import uoa_detector

whale_data = uoa_detector.check_whale_activity('AAPL', 'CALL')
print(f"Unusual: {whale_data['is_unusual']}")
print(f"Score: {whale_data['overall_score']:.1f}/10")
print(f"Boost: +{whale_data['confidence_boost']*100:.1f}%")
```

### Run Test Script

```bash
# Test both modules
python app/data/unusual_options.py
```

---
## Benefits

### Task 4 (ML Scoring)

✅ **Higher Win Rate**: Filters weak patterns, boosts strong ones  
✅ **Adaptive Learning**: Model improves as more data collected  
✅ **Pattern Recognition**: Identifies subtle factors humans miss  
✅ **Time-Based Edge**: Knows which hours/days perform best

### Task 6 (UOA)

✅ **Front-Run Institutions**: Enter before whale orders fully execute  
✅ **Smart Money Confirmation**: Aligns retail signals with institutional flow  
✅ **Dark Pool Correlation**: Detects hidden accumulation/distribution  
✅ **Sweep Detection**: Catches aggressive premium buying

---

## Monitoring

### Check ML Model Status

```python
from signal_generator import signal_generator

if signal_generator.ml_booster:
    print(f"ML Model: {'Trained' if signal_generator.ml_booster.is_trained else 'Untrained'}")
```

### Check UOA Status

```python
from app.data.unusual_options import uoa_detector

print(f"Unusual Whales: {'✅' if uoa_detector.has_unusual_whales else '❌'}")
print(f"EODHD Fallback: {'✅' if uoa_detector.has_eodhd else '❌'}")
```

### View Enhancement Stats

All enhancements logged in signal metadata:

```python
# After signal generation
if 'ml_adjustment' in signal:
    print(f"ML Delta: {signal['ml_adjustment']['delta']:+.1f}%")

if 'uoa' in signal and signal['uoa']['is_unusual']:
    print(f"Whale Boost: +{signal['uoa']['confidence_boost']*100:.1f}%")
```

---

## Performance Tracking

Both enhancements are tracked in `signal_analytics.db`:

```sql
-- Check ML impact on win rate
SELECT 
  AVG(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as win_rate,
  AVG(confidence) as avg_confidence
FROM signals
WHERE ml_adjustment IS NOT NULL;

-- Check UOA impact
SELECT 
  AVG(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as win_rate
FROM signals
WHERE uoa_detected = 1;
```

---

## Troubleshooting

### ML Model Not Loading

```bash
# Check if model file exists
ls app/ml/trained_model.pkl

# Retrain if missing
python app/ml/ml_signal_scorer.py
```

### UOA Not Working

```bash
# Check API keys
echo $UNUSUAL_WHALES_API_KEY
echo $EODHD_API_KEY

# Test API connection
python -c "from app.data.unusual_options import uoa_detector; print(uoa_detector.has_unusual_whales)"
```

### Low Confidence Boosts

- **ML**: Model needs more training data (run for 30+ days)
- **UOA**: Check if ticker has liquid options (high OI/volume)
- **Both**: Verify base signal quality is already strong

---

## Next Steps

### Optimize ML Model

1. Collect 30+ days of signal outcomes
2. Retrain with walk-forward validation
3. Tune hyperparameters for your strategy

### Enhance UOA Detection

1. Add custom dark pool data feed
2. Implement real-time sweep alerts via Discord
3. Track institutional order flow throughout day

### Multi-Timeframe Enhancement (Task 5)

Now that ML (Task 4) and UOA (Task 6) are complete, consider:
- Strengthening 15m/30m confirmation layers
- Adding volume profile across timeframes
- Reducing false breakouts with better MTF convergence

---

## Commit Summary

**Commits**:
1. [769b9a7](https://github.com/AlgoOps25/War-Machine/commit/769b9a717d3656d35202a4964c8b7d4e5b6962ab) - Task 6: UOA whale detection module
2. [7877417](https://github.com/AlgoOps25/War-Machine/commit/7877417e4606c2d4df4ff565e0ce44961a63a19f) - Tasks 4+6: Full integration

**Files Modified**:
- ✅ `app/data/unusual_options.py` (new)
- ✅ `app/signals/signal_generator.py` (enhanced)
- ✅ `docs/TASKS_4_6_INTEGRATION.md` (new)

**Status**: 🚀 **READY FOR PRODUCTION**
