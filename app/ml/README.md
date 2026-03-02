# ML Confidence Booster

XGBoost-based signal quality predictor that learns from historical trade outcomes to dynamically adjust confidence scores.

## Overview

The ML Confidence Booster analyzes 20+ features from each signal and outputs a confidence adjustment in the range of ±15%. This helps the system learn which market conditions, timing, and signal characteristics lead to profitable trades.

## Architecture

### Training Pipeline (`train_ml_booster.py`)

1. **Data Loading**
   - Fetches last 90 days of trade logs from database
   - Merges with bootstrapped synthetic trades (if available)
   - Requires minimum 50 samples to train

2. **Feature Engineering**
   - **Time features**: hour_of_day, day_of_week, time_since_open_min
   - **Gap features**: gap_pct, gap_abs, gap_direction
   - **Volume features**: entry_volume, volume_surge_ratio, or_volume, volume_log
   - **Price vs Levels**: price_vs_pdh, price_vs_or_high, pdh_distance_pct, pdl_distance_pct
   - **Volatility**: vix_level, or_range_pct, pd_range_pct
   - **Signal Type**: One-hot encoded signal categories

3. **Model Training**
   - XGBoost binary classifier (1=profit, 0=loss)
   - 75/25 train/val split with stratification
   - Early stopping on validation loss
   - Balanced class weights for imbalanced data
   
4. **Output**
   - Trained model saved to `/app/models/confidence_booster.pkl`
   - Feature importance saved to `/app/models/feature_importance.csv`
   - Training metrics logged (accuracy, precision, recall, AUC)

### Prediction Module (`ml_confidence_boost.py`)

1. **Model Loading**
   - Auto-loads trained model on initialization
   - Graceful fallback if no model exists (returns 0.0 adjustment)

2. **Prediction**
   - Extracts features from signal data
   - Model outputs probability [0.0, 1.0] for profitable trade
   - Maps to adjustment: `(prob - 0.5) × 0.30` → ±15%
   - Clips to safe range [-0.15, +0.15]

3. **Integration**
   - Called after base confidence calculation in signal generator
   - Adjustment applied: `confidence = base_confidence + ml_adjustment`
   - Logged when adjustment exceeds 1%

## Setup

### 1. Dependencies

Already added to `requirements.txt`:
```
xgboost==2.0.3
scikit-learn==1.4.0
```

Install locally:
```bash
pip install xgboost==2.0.3 scikit-learn==1.4.0
```

### 2. Create Models Directory

```bash
mkdir -p app/models
```

### 3. Railway Cron Configuration

The `railway.toml` is already configured with:
```toml
[[cron]]
name = "ml-retrain"
schedule = "0 7 * * 0"  # Sunday 7 AM UTC (2 AM ET)
command = "python app/ml/train_ml_booster.py"
```

Verify in Railway dashboard under **Cron Jobs** tab.

### 4. Database Schema

Ensure your `trade_logs` table includes these columns:

**Required**:
- `ticker` (TEXT)
- `entry_time` (TIMESTAMP)
- `exit_time` (TIMESTAMP)
- `entry_price` (REAL)
- `exit_price` (REAL)
- `pnl` (REAL) or `win` (BOOLEAN)
- `signal_type` (TEXT)

**For Feature Engineering**:
- `entry_volume`, `or_volume`, `volume_surge_ratio`
- `pdh`, `pdl`, `gap_pct`
- `or_high`, `or_low`
- `time_since_open_min`, `vix_level`
- `price_vs_pdh`, `price_vs_or_high`

## Usage

### Initial Training (Local)

```bash
# Requires 50+ trade logs
python app/ml/train_ml_booster.py
```

Output:
```
[TRAIN] ========== ML Confidence Booster Training ==========
[TRAIN] Loaded 120 historical trades
[TRAIN] Extracted 22 features: ['hour_of_day', 'day_of_week', ...]
[TRAIN] Label distribution: {0: 48, 1: 72}
[ML-TRAIN] Starting training with 120 samples, 22 features
[ML-TRAIN] Validation metrics: Acc=0.733, Prec=0.789, Rec=0.714, AUC=0.801
[ML] Feature importance saved to /app/models/feature_importance.csv
[ML] Top 10 features:
  volume_surge_ratio: 0.1523
  gap_abs: 0.1342
  time_since_open_min: 0.1189
  ...
[ML] Model saved to /app/models/confidence_booster.pkl
[TRAIN] ========== Training Complete ==========
```

### Verify Model Loads

```bash
python -c "from app.ml.ml_confidence_boost import MLConfidenceBooster; m = MLConfidenceBooster(); print(f'Trained: {m.is_trained}')"
```

Expected output:
```
[ML] Loaded model from /app/models/confidence_booster.pkl
Trained: True
```

## Monitoring

### Check Feature Importance

After each training run:
```bash
cat app/models/feature_importance.csv
```

Features with importance < 0.01 can be pruned in future iterations to reduce model complexity.

### Live Prediction Logs

Watch for `[ML-BOOST]` logs during signal generation:
```
[ML-BOOST] TSLA: 0.67 -> 0.78 (adj=+0.11)
[ML-BOOST] AAPL: 0.82 -> 0.71 (adj=-0.11)
```

Large adjustments indicate the model has strong conviction about signal quality.

### Training Metrics

Review after weekly retrain:
- **Accuracy**: Overall correct predictions
- **Precision**: % of predicted wins that are actual wins
- **Recall**: % of actual wins that are predicted
- **AUC**: Area under ROC curve (0.5 = random, 1.0 = perfect)

Target metrics:
- Accuracy > 0.65
- AUC > 0.70
- Balanced precision/recall

## Troubleshooting

### "No pre-trained model found"

**Cause**: Model hasn't been trained yet or file doesn't exist.

**Solution**: 
1. Ensure 50+ trade logs exist
2. Run `python app/ml/train_ml_booster.py` manually
3. Verify `/app/models/confidence_booster.pkl` was created

### "Insufficient data for training"

**Cause**: Less than 50 trade logs in database.

**Solution**: 
1. Continue live trading to accumulate logs
2. Wait for weekly cron to retry automatically
3. System will use base confidence (no ML adjustment) until then

### Model predictions always 0.0

**Cause**: Model not loaded or training failed.

**Solution**:
1. Check model file exists: `ls -la app/models/`
2. Verify feature extraction matches training features
3. Review training logs for errors

### Feature mismatch error

**Cause**: Feature names don't match between training and prediction.

**Solution**:
1. Ensure `_extract_ml_features()` extracts ALL features used in training
2. Check for typos in feature names
3. Retrain model if feature set changed

## Performance Expectations

Based on typical algorithmic trading ML systems:

**Realistic Targets**:
- 5-10% improvement in win rate
- 10-15% reduction in false signals
- 8-12% increase in average profit factor

**Not Expected**:
- Model won't eliminate losses (market uncertainty is fundamental)
- Not a "magic predictor" - it's a confidence tuner
- Performance degrades if market conditions shift dramatically

The model's primary goal is **reducing false positives** (high-confidence signals that fail) and **boosting true positives** (correctly identifying high-quality setups).
