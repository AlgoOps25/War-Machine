# ML Signal Scorer V2 — Full Integration Guide

> **Status**: Historical pre-training pipeline complete.  
> Follow these steps in order to activate ML scoring in the live system.

---

## Overview

```
Historical OHLCV (EODHD)
        ↓
 HistoricalMLTrainer          ← app/backtesting/historical_trainer.py
  replay + label bars
        ↓
 train_from_dataframe()       ← app/ml/ml_trainer.py
  RandomForest (200 trees)
        ↓
 models/ml_model_historical.pkl
        ↓
 MLSignalScorerV2.score()     ← app/ml/ml_signal_scorer_v2.py
  called from validation gate
        ↓
 app/validation/__init__.py   ← Gate 5 — adjusts confidence ±15 pts
        ↓
 sniper.py / Discord embed    ← shows ML-adjusted score + delta
        ↓
 analytics DB                 ← outcome recorded → EOD auto-retrain
```

---

## Step 0 — Run the Pre-Training (one time)

```powershell
# From project root, venv activated
# Daily bars — fast, 2+ years of history
python -m app.ml.train_historical `
    --interval d --months 36 `
    --tickers AAPL TSLA NVDA MSFT AMD META GOOGL AMZN SPY QQQ `
    --min-samples 30

# Expected output when successful:
#   Total signals : 120+
#   Model saved → models/ml_model_historical.pkl
```

The model file lands at `models/ml_model_historical.pkl`.  
The full labelled dataset is at `models/training_dataset.csv` — review it to spot any data quality issues before going live.

---

## Step 1 — Point MLSignalScorerV2 at the Historical Model

Edit **`app/ml/ml_signal_scorer_v2.py`**, find the `MODEL_PATH` constant near the top of the file and change it:

```python
# Before:
MODEL_PATH = os.path.join(os.getcwd(), 'models', 'ml_signal_scorer_v2.pkl')

# After:
MODEL_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'models',
    os.getenv('ML_MODEL_FILE', 'ml_model_historical.pkl')
)
```

Using an env var (`ML_MODEL_FILE`) means you can swap models on Railway without a code push:  
`ML_MODEL_FILE=ml_model_historical.pkl`  → historical pre-trained  
`ML_MODEL_FILE=ml_model.pkl`             → live auto-retrained model  

---

## Step 2 — Wire the Scorer into the Validation Gate

Open **`app/validation/__init__.py`**.  The file already has Gate 5 stubbed with a comment.  Replace it:

```python
# ── Gate 5: ML confidence adjustment ─────────────────────────────────────────
ml_adjustment = 0.0
ml_source     = 'none'
try:
    from app.ml.ml_signal_scorer_v2 import MLSignalScorerV2
    scorer = MLSignalScorerV2()          # singleton — loads model once at startup
    if scorer.is_ready:
        result      = scorer.score_signal(signal)
        ml_adjustment = result.get('confidence_adjustment', 0.0)   # float, e.g. +0.08
        ml_source     = result.get('model_version', 'v2')
        logger.info(
            f"[VALIDATION] Gate 5 ML: {ticker} adjustment={ml_adjustment:+.2f} "
            f"source={ml_source}"
        )
except Exception as exc:
    logger.warning(f"[VALIDATION] Gate 5 ML skipped: {exc}")

# Apply — clamp final confidence to [0, 1]
confidence_adj = max(0.0, min(1.0, signal.get('confidence', 0.7) + ml_adjustment))
```

Then return the adjusted confidence in the gate's return value:
```python
return True, 'passed', confidence_adj
```

> **Safe to deploy immediately** — if the model file doesn't exist yet,
> `scorer.is_ready` is `False` and the gate passes with zero adjustment.

---

## Step 3 — Show ML Delta in Discord Alerts

In **`app/core/sniper.py`**, find `_format_discord_message()` (or wherever the
confidence line is built).  Add the ML delta line:

```python
# Existing confidence line
lines.append(f"Confidence : {signal['confidence']*100:.0f}%")

# Add after it:
if signal.get('ml_adjustment') and abs(signal['ml_adjustment']) >= 0.01:
    delta = signal['ml_adjustment']
    arrow = '📈' if delta > 0 else '📉'
    lines.append(
        f"ML Score   : {arrow} {delta*100:+.1f}pts  "
        f"({signal.get('ml_base_confidence',0)*100:.0f}% → {signal['confidence']*100:.0f}%)"
    )
```

Store `ml_adjustment` and `ml_base_confidence` on the signal dict in the
validation gate before returning (add two lines there):

```python
signal['ml_base_confidence'] = signal.get('confidence', 0.7)
signal['ml_adjustment']      = ml_adjustment
```

---

## Step 4 — EOD Auto-Retrain Hook

The EOD block in **`app/core/scanner.py`** already calls `ailearning`.  Add
the ML retrain immediately after:

```python
# ── EOD ML retrain (runs if 50+ new completed signals since last train) ──────
try:
    from app.ml.ml_trainer import should_retrain, train_model
    if should_retrain():
        logger.info("[EOD] Retraining ML model on live signal outcomes...")
        model, metrics = train_model()
        if model:
            logger.info(
                f"[EOD] ML retrain complete — "
                f"accuracy={metrics['accuracy']:.2%}  "
                f"n_train={metrics['n_train']}"
            )
            # Hot-reload: force MLSignalScorerV2 to pick up new weights
            try:
                from app.ml.ml_signal_scorer_v2 import MLSignalScorerV2
                MLSignalScorerV2._instance = None   # bust singleton cache
                logger.info("[EOD] MLSignalScorerV2 singleton reset — new model active")
            except Exception:
                pass
except Exception as exc:
    logger.warning(f"[EOD] ML retrain skipped: {exc}")
```

---

## Step 5 — Railway Deployment

Set the env var so Railway uses the pre-trained model:

```
ML_MODEL_FILE = ml_model_historical.pkl
```

Commit `models/ml_model_historical.pkl` to the repo so it deploys with the
container (it's ~2 MB).  Add this line to `.gitignore` to keep the live
retrained model out of Git (it lives on the Railway volume):

```
# Keep pre-trained seed model, ignore live-retrained models
models/ml_model.pkl
models/ml_model_*.pkl
!models/ml_model_historical.pkl
```

---

## Testing Checklist

Run each in sequence before deploying:

```powershell
# 1. Confirm model file exists and loads cleanly
python -c "
import pickle, pathlib
bundle = pickle.load(open('models/ml_model_historical.pkl','rb'))
print('Features :', len(bundle['feature_names']))
print('Trained  :', bundle['trained_at'])
print('Accuracy :', f\"{bundle['metrics']['accuracy']:.2%}\")
"

# 2. Confirm scorer returns a score without error
python -c "
from app.ml.ml_signal_scorer_v2 import MLSignalScorerV2
s = MLSignalScorerV2()
print('Ready:', s.is_ready)
test_signal = {
    'confidence': 0.72, 'rvol': 3.1, 'score': 72,
    'grade': 'B+', 'adx': 32, 'atr_pct': 0.015,
    'vwap_distance': 0.003, 'or_range_pct': 0.012,
    'direction': 'bull', 'signal_type': 'BREAKOUT',
    'hour': 10, 'rr_ratio': 2.1, 'explosive_mover': False,
    'mtf_convergence': True, 'mtf_convergence_count': 2,
    'mtf_boost': 0.05, 'ivr': 0.45,
    'gex_multiplier': 1.0, 'uoa_multiplier': 1.0, 'ivr_multiplier': 1.0,
}
result = s.score_signal(test_signal)
print('Adjustment:', result.get('confidence_adjustment'))
print('Version   :', result.get('model_version'))
"

# 3. Quick end-to-end validation gate test
python -c "
from app.validation import validate_signal
signal = {'ticker':'AAPL','confidence':0.70,'rvol':2.5,'score':70,'grade':'B'}
passed, reason, conf_adj = validate_signal(signal)
print(f'passed={passed}  reason={reason}  confidence={conf_adj:.2%}')
"
```

Expected output for test 2:
```
Ready: True
Adjustment: 0.06   ← or similar positive value for a quality signal
Version   : historical_v1
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `scorer.is_ready = False` | Model file not found | Run Step 0; check `ML_MODEL_FILE` env var |
| `Only N signals — need 50` | Not enough breakouts in history | `--interval d --months 36 --include-timeout` |
| `float() NoneType` | EODHD null volume field | Fixed in this commit; `git pull` |
| `422 Client Error` on interval=d | Intraday endpoint doesn't accept 'd' | Fixed in this commit; `git pull` |
| All signals WIN (78%+) | Daily RVOL too low, catching easy trends | Increase `--rvol-min 1.6` |
| `train_from_dataframe` feature mismatch | Custom signal has unexpected keys | Add missing key with neutral default |
| Model not hot-reloading after EOD retrain | Singleton not busted | Step 4 EOD hook resets `_instance = None` |

---

## What to Expect Live

Once wired in, every signal that passes Gates 1–4 goes through the ML scorer:

```
[VALIDATION] Gate 5 ML: TSLA adjustment=+0.09 source=historical_v1
[ML-BOOST]   TSLA 📈 | Conf: 68% → 77%  (+9pts)
```

Discord alert will show:
```
Confidence : 77%
ML Score   : 📈 +9pts  (68% → 77%)
```

Signals where the model has low conviction:
```
[ML-BOOST] META 📉 | Conf: 71% → 62%  (−9pts)
```

After 50+ live trades complete, EOD retraining automatically fine-tunes
the model on your own outcomes — at that point the historical seed is
replaced by a model calibrated to War Machine's exact signal style.
