# ML Confidence Booster Integration Guide

## ✅ Status: Ready to Integrate

The ML model is trained and working! Now wire it into `signal_generator.py` to get live confidence adjustments.

---

## 🎯 What This Does

- **Analyzes every signal** using 22 market features
- **Adjusts confidence by ±15%** based on ML predictions
- **No false signal reduction** - only confidence tuning
- **Transparent logging** - shows adjustment reasoning

---

## 📝 Integration Steps

### Step 1: Add Import (Line ~23)

```python
# Add after target_discovery imports
try:
    from app.ml.ml_confidence_boost import MLConfidenceBooster
    ML_BOOSTER_ENABLED = True
    print("[SIGNALS] ✅ ML Confidence Booster enabled (Day 6 ML predictions)")
except ImportError as e:
    ML_BOOSTER_ENABLED = False
    print(f"[SIGNALS] ⚠️  ML Confidence Booster not available ({e})")
```

### Step 2: Initialize in `__init__` (Line ~91)

```python
# Add after validator initialization
# ML Confidence Booster (Day 6)
self.ml_booster = None
if ML_BOOSTER_ENABLED:
    try:
        self.ml_booster = MLConfidenceBooster()
        status = "trained" if self.ml_booster.is_trained else "untrained"
        print(f"[SIGNALS] ML Booster loaded: {status}")
    except Exception as e:
        print(f"[SIGNALS] ML Booster initialization error: {e}")
        self.ml_booster = None
```

### Step 3: Add Feature Extraction Method (Before `_format_discord_alert`)

```python
def _extract_ml_features(self, ticker: str, signal: Dict, latest_bar: Dict) -> Dict[str, float]:
    """
    Extract ML features from signal data for confidence prediction.
    
    Args:
        ticker: Stock ticker
        signal: Signal dict with entry/stop/targets
        latest_bar: Latest price bar
    
    Returns:
        Dict of feature_name -> value
    """
    import numpy as np
    
    features = {}
    now_et = datetime.now(ET)
    
    # Time features
    features['hour_of_day'] = now_et.hour
    features['day_of_week'] = now_et.weekday()
    features['time_since_open_min'] = signal.get('time_since_open_min', 0)
    
    # Gap features
    gap_pct = signal.get('gap_pct', 0.0)
    features['gap_pct'] = gap_pct
    features['gap_abs'] = abs(gap_pct)
    features['gap_direction'] = 1 if gap_pct > 0 else 0
    
    # Volume features
    volume = latest_bar.get('volume', signal.get('volume', 0))
    features['entry_volume'] = volume
    features['volume_surge_ratio'] = signal.get('volume_surge', 1.0)
    features['or_volume'] = signal.get('or_volume', 0)
    features['volume_log'] = np.log1p(volume)
    
    # Price vs key levels
    features['price_vs_pdh'] = signal.get('price_vs_pdh', 0.0)
    features['price_vs_or_high'] = signal.get('price_vs_or_high', 0.0)
    
    # PDH/PDL distance
    entry_price = signal['entry']
    pdh = signal.get('pdh', 0)
    pdl = signal.get('pdl', 0)
    
    if pdh and pdl and entry_price:
        features['pdh_distance_pct'] = (entry_price - pdh) / pdh * 100
        features['pdl_distance_pct'] = (entry_price - pdl) / pdl * 100
        features['pd_range_pct'] = (pdh - pdl) / pdl * 100
    else:
        features['pdh_distance_pct'] = 0.0
        features['pdl_distance_pct'] = 0.0
        features['pd_range_pct'] = 0.0
    
    # OR breakout
    or_high = signal.get('or_high', 0)
    or_low = signal.get('or_low', 0)
    
    if or_high and or_low and entry_price:
        features['or_breakout_size_pct'] = (entry_price - or_high) / or_high * 100
        features['or_range_pct'] = (or_high - or_low) / or_low * 100
    else:
        features['or_breakout_size_pct'] = 0.0
        features['or_range_pct'] = 0.0
    
    # VIX
    features['vix_level'] = signal.get('vix', 15.0)
    
    # Signal type one-hot
    signal_type = signal.get('type', 'unknown')
    for sig_type in ['gap_breakout', 'volume_surge', 'momentum', 'reversal']:
        features[f'signal_{sig_type}'] = 1 if sig_type in signal_type.lower() else 0
    
    return features
```

### Step 4: Add ML Adjustment in `check_ticker()` (After Cooldown Update)

Find this code around line 265:

```python
# Update cooldown (only for validated signals)
self.recent_signals[ticker] = datetime.now(ET)
print(f"[SIGNALS] {ticker} cooldown started ({self.cooldown_minutes}m)")
```

**Add this block right after:**

```python
# === DAY 6: ML CONFIDENCE ADJUSTMENT ===
if ML_BOOSTER_ENABLED and self.ml_booster and self.ml_booster.is_trained:
    try:
        # Extract features
        latest_bar = bars[-1] if bars else {}
        ml_features = self._extract_ml_features(ticker, signal, latest_bar)
        
        # Get ML confidence adjustment (±15%)
        adjustment = self.ml_booster.predict_confidence_adjustment(ml_features)
        
        # Apply adjustment (clamp to 0-100)
        original_conf = signal['confidence']
        adjusted_conf = max(0, min(100, original_conf + (adjustment * 100)))
        signal['confidence'] = round(adjusted_conf, 1)
        
        # Store ML metadata
        signal['ml_adjustment'] = {
            'original': original_conf,
            'adjusted': adjusted_conf,
            'delta': adjusted_conf - original_conf,
            'model_confidence': adjustment
        }
        
        # Log significant adjustments
        if abs(adjustment * 100) > 1.0:
            emoji = "📈" if adjustment > 0 else "📉"
            print(f"[ML-BOOST] {ticker} {emoji} | "
                  f"Conf: {original_conf:.0f}% → {adjusted_conf:.0f}% "
                  f"({adjustment*100:+.1f}%)")
    
    except Exception as e:
        print(f"[ML-BOOST] {ticker} error: {e}")
        # Keep original confidence on error
```

---

## 🎨 Optional: Add to Discord Alerts

In `_format_discord_alert()`, after the confidence line:

```python
# Show ML adjustment if available
if 'ml_adjustment' in signal:
    ml = signal['ml_adjustment']
    if abs(ml['delta']) > 1.0:
        emoji = "📈" if ml['delta'] > 0 else "📉"
        msg += f"   ML Adjustment: {emoji} {ml['delta']:+.1f}% "
        msg += f"({ml['original']:.0f}% → {ml['adjusted']:.0f}%)\n"
```

---

## 📊 Testing

After integration:

```bash
# Test in Python console
python
>>> from app.signals.signal_generator import signal_generator
>>> print(f"ML enabled: {signal_generator.ml_booster is not None}")
>>> print(f"ML trained: {signal_generator.ml_booster.is_trained if signal_generator.ml_booster else False}")
```

Expected output:
```
ML enabled: True
ML trained: True
```

---

## 📈 What to Expect

### Positive Adjustments (+)
- High volume with tight spreads
- Clean breakout above PDH
- Early morning momentum (9:30-10:00)
- Low VIX environment
- Strong volume surge (>2.5x)

### Negative Adjustments (-)
- Low volume breakouts
- Late session signals (>14:00)
- High VIX (>22)
- Weak OR range
- Gap fading patterns

---

## 🔄 Retraining

The model automatically retrains weekly via Railway cron (Sundays 2 AM ET). To manually retrain:

```bash
python tests/test_ml_training.py
```

Requires 50+ trade logs in the database.

---

## 🐛 Troubleshooting

### Model not loading
- Check `app/models/confidence_booster.pkl` exists
- Run training: `python tests/test_ml_training.py`

### Features mismatch
- Model expects exactly 22 features
- Missing features default to 0.0
- Check logs for feature extraction errors

### No adjustments showing
- Only adjustments >1% are logged
- Check `ML_BOOSTER_ENABLED = True`
- Verify model is trained: `ml_booster.is_trained`

---

## 📚 Files Modified

- `app/signals/signal_generator.py` - Add 4 code blocks
- No other files need changes
- Backward compatible (works without model)

---

## ✅ Done!

Once integrated, every signal will get ML confidence tuning automatically. Monitor the logs for `[ML-BOOST]` messages to see adjustments in real-time.
