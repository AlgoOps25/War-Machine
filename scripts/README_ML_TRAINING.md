# ML Training Data Generation Guide

## Overview

Bootstrap your ML Confidence Booster without waiting for live signals by generating training data from your **60-90 days of cached historical candles**.

## 🎯 Quick Start

### Step 1: Generate Training Data (2-5 minutes)

```bash
# Basic - 60 days, 15 signals per ticker, target 120 total
python scripts/generate_ml_training_data.py

# Extended - 90 days for more training data
python scripts/generate_ml_training_data.py --days 90

# Custom configuration
python scripts/generate_ml_training_data.py --days 75 --per-ticker 20 --target 150
```

### Step 2: Train ML Model (30-60 seconds)

Once 100+ signal outcomes are generated:

```bash
python app/ml/train_ml_booster.py
```

### Step 3: Deploy

The trained model is automatically loaded on next War Machine restart. You'll see:

```
[SIGNALS] ML Booster loaded: trained (v1.0)
```

## 📊 What This Script Does

1. **Scans Historical Candles**
   - Reads your 60-90 days of cached 5-minute bars
   - 8 tickers: SPY, QQQ, AAPL, MSFT, NVDA, TSLA, META, AMD

2. **Detects BOS + FVG Patterns**
   - Identifies Break of Structure (bullish/bearish)
   - Confirms with Fair Value Gap
   - Same logic as live signal generator

3. **Simulates Signal Validation**
   - Runs through your production validator
   - Calculates confidence scores
   - Applies all filters (volume, time-of-day, etc.)

4. **Tracks Real Outcomes**
   - Follows price action for 30 bars (2.5 hours)
   - Marks WIN/LOSS/BREAKEVEN based on:
     - Stop loss: 1.5% (1R)
     - Target: 3.0% (2R)
   - Records actual P&L percentage

5. **Stores to Database**
   - Saves to `signal_analytics` table
   - Ready for ML model training

## 🎓 ML Training Process

### Feature Engineering

The ML model learns from these signal characteristics:

- **Price Action**: Entry price, ATR, volatility
- **Volume Profile**: Volume ratio, above/below average
- **Pattern Quality**: BOS strength, FVG gap size
- **Time Context**: Hour of day, market phase
- **Technical Indicators**: RSI, EMA alignment, ADX
- **Market Regime**: VIX level, SPY trend

### Model Architecture

- Algorithm: **Random Forest Classifier**
- Target: Predict signal win probability (0-100%)
- Training: 80/20 split with cross-validation
- Output: Confidence boost/penalty (-10% to +15%)

### Performance Metrics

After training, you'll see:

```
[ML] Model Performance:
  Accuracy: 62.5%
  Precision: 0.68
  Recall: 0.58
  Win Rate (predicted winners): 68%
  Samples: 120 signals
```

## 📈 Expected Results

### Typical Generation Output

```
✅ SPY: 18 signals
✅ QQQ: 16 signals  
✅ AAPL: 15 signals
✅ MSFT: 17 signals
✅ NVDA: 14 signals
✅ TSLA: 12 signals
✅ META: 15 signals
✅ AMD: 13 signals

Total Signals Generated: 120
🎯 READY FOR ML TRAINING!
```

### Win Rate Analysis

Historical backtests typically show:

- **Raw Signals**: ~40-45% win rate
- **After Validation**: ~55-60% win rate
- **With ML Boost**: ~62-68% win rate (target)

## 🛠️ Configuration Options

### Command-Line Arguments

```bash
--days <int>        # Lookback period (default: 60, max: 90)
--per-ticker <int>  # Min signals per ticker (default: 15)
--target <int>      # Target total signals (default: 120)
```

### Examples

```bash
# Conservative (60 days, high quality)
python scripts/generate_ml_training_data.py --days 60 --per-ticker 10

# Aggressive (90 days, more data)
python scripts/generate_ml_training_data.py --days 90 --per-ticker 20 --target 150

# Quick test (30 days)
python scripts/generate_ml_training_data.py --days 30 --per-ticker 5 --target 50
```

## 🔧 Troubleshooting

### Issue: "Insufficient data for ticker"

**Solution**: Your cache may not have 60-90 days. Try:

```bash
# Reduce lookback
python scripts/generate_ml_training_data.py --days 30

# Or run cache backfill first
python scripts/backfill_cache.py --days 90
```

### Issue: "Only generated 45/100 signals"

**Solutions**:

1. Increase lookback period:
   ```bash
   python scripts/generate_ml_training_data.py --days 90
   ```

2. Add more tickers (edit script):
   ```python
   tickers = ['SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'AMD']
   ```

3. Lower confidence threshold temporarily:
   ```python
   validator = SignalValidator(min_final_confidence=0.45)  # Was 0.50
   ```

### Issue: Database connection errors

**Solution**: Ensure PostgreSQL is running and accessible:

```bash
# Test database connection
psql $DATABASE_URL -c "SELECT 1;"

# Check Railway logs
railway logs
```

## 📝 Database Schema

Signal outcomes are stored in:

```sql
CREATE TABLE signal_analytics (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price DECIMAL(12, 4),
    confidence DECIMAL(5, 4),
    volume_ratio DECIMAL(8, 2),
    pattern_type VARCHAR(50),
    outcome VARCHAR(20),        -- WIN, LOSS, BREAKEVEN
    pnl_pct DECIMAL(8, 4),     -- Actual P&L %
    exit_price DECIMAL(12, 4),
    bars_held INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 🚀 Production Workflow

### Initial Setup (One-Time)

```bash
# 1. Generate historical training data
python scripts/generate_ml_training_data.py --days 90

# 2. Train initial model
python app/ml/train_ml_booster.py

# 3. Restart War Machine to load trained model
railway restart
```

### Weekly Retraining (Automated)

Configured in `railway.toml`:

```toml
[[cron]]
name = "ml-retrain"
schedule = "0 7 * * 0"  # Sunday 7 AM UTC
command = "python app/ml/train_ml_booster.py"
```

Every week, the model retrains with:
- All historical synthetic signals (120+)
- New live signal outcomes from the week
- Combined dataset improves over time

## 📊 Monitoring ML Performance

Check Discord alerts for ML confidence adjustments:

```
🎯 SIGNAL: AAPL BULLISH @ $185.50
Confidence: 58% (base) → 65% (+7% ML boost)
ML Prediction: 68% win probability
```

Track in logs:

```bash
railway logs | grep "ML"
```

## 🎓 Understanding ML Confidence Boost

### How It Works

1. **Base Confidence**: Your validator calculates 50-70%
2. **ML Prediction**: Model predicts win probability
3. **Adjustment**:
   - If ML predicts **higher** win rate → boost confidence (+5% to +15%)
   - If ML predicts **lower** win rate → reduce confidence (-5% to -10%)
   - If ML uncertain → no change

### Example Flow

```
Signal Generated:
  Ticker: NVDA
  Direction: BULLISH
  Base Confidence: 55%
  
ML Analysis:
  Features extracted: ✅
  Win probability: 72%
  Historical similar signals: 15 (68% win rate)
  
ML Decision:
  Boost: +10%
  Final Confidence: 65%
  
Result: Signal PASSED (≥50% threshold)
```

## 🎯 Next Steps

1. ✅ **Generate training data**: `python scripts/generate_ml_training_data.py`
2. ✅ **Train model**: `python app/ml/train_ml_booster.py`
3. ✅ **Deploy**: Restart War Machine
4. 📊 **Monitor**: Watch Discord for ML-boosted signals
5. 🔄 **Improve**: Weekly auto-retraining incorporates new outcomes

---

**Status Check**:

```bash
# View generated signals
psql $DATABASE_URL -c "SELECT COUNT(*) FROM signal_analytics;"

# Check model file
ls -lh app/ml/models/ml_booster_v*.pkl

# View recent outcomes
psql $DATABASE_URL -c "SELECT ticker, outcome, COUNT(*) FROM signal_analytics GROUP BY ticker, outcome ORDER BY ticker;"
```
