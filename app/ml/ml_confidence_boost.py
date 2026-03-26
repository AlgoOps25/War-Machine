"""
ML Confidence Booster - XGBoost model for signal quality prediction.

NOTE (#43): This is a SEPARATE model from ml_trainer.py.
  - This file: XGBClassifier, saved to /app/models/confidence_booster.pkl
  - ml_trainer.py: HistGradientBoostingClassifier, saved to ml_model.joblib
  Do NOT swap or merge these two model files — they use different feature sets
  and serve different purposes in the signal pipeline.

Design:
- Binary classification: 1 = profitable trade, 0 = loss/scratch
- Outputs probability [0.0, 1.0] mapped to confidence adjustment [-15%, +15%]
- Wide feature set initially, pruned by importance after training
- Weekly retrain on Railway via cron (Sunday 2 AM ET)
- Model saved as .pkl in /app/models/ directory

FIX (Mar 26 2026) — issues #41 / #42:
  #41: train() print() → logger.info() for training metrics output.
  #42: save_model() trained_at timestamp naive/UTC → datetime.now(ET).
"""

import os
import pickle
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

MODEL_PATH = "/app/models/confidence_booster.pkl"
IMPORTANCE_PATH = "/app/models/feature_importance.csv"

class MLConfidenceBooster:
    def __init__(self):
        self.model: Optional[XGBClassifier] = None
        self.feature_names: list = []
        self.is_trained = False
        self._load_model()

    def _load_model(self):
        """Load trained model from disk if available."""
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, 'rb') as f:
                    data = pickle.load(f)
                    self.model = data['model']
                    self.feature_names = data['feature_names']
                    self.is_trained = True
                logger.info(f"[ML] Loaded model from {MODEL_PATH}")
            except Exception as e:
                logger.info(f"[ML] Model load error: {e}")
        else:
            logger.info("[ML] No pre-trained model found - will use default confidence")

    def predict_confidence_adjustment(self, features: Dict[str, float]) -> float:
        """
        Predict confidence adjustment for a signal.

        Args:
            features: Dictionary of feature name -> value

        Returns:
            Adjustment factor in range [-15%, +15%] as decimal (e.g., 0.15)
        """
        if not self.is_trained or self.model is None:
            return 0.0

        try:
            X = np.array([[features.get(f, 0.0) for f in self.feature_names]])
            prob = self.model.predict_proba(X)[0, 1]
            # Map [0.0, 1.0] -> [-0.15, +0.15]  (prob=0.5 -> 0.0 neutral)
            adjustment = (prob - 0.5) * 0.30
            return np.clip(adjustment, -0.15, 0.15)
        except Exception as e:
            logger.info(f"[ML] Prediction error: {e}")
            return 0.0

    def train(self, X: pd.DataFrame, y: pd.Series, test_size: float = 0.25) -> Dict:
        """
        Train XGBoost model on labeled trade data.

        Args:
            X: Feature DataFrame
            y: Binary labels (1=profit, 0=loss)
            test_size: Validation split ratio

        Returns:
            Training metrics dict
        """
        logger.info(f"[ML-TRAIN] Starting training with {len(X)} samples, {len(X.columns)} features")

        self.feature_names = list(X.columns)

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        self.model = XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=len(y_train[y_train == 0]) / len(y_train[y_train == 1]),
            random_state=42,
            eval_metric='logloss',
            early_stopping_rounds=20
        )

        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )

        self.is_trained = True

        y_pred = self.model.predict(X_val)
        y_prob = self.model.predict_proba(X_val)[:, 1]

        report = classification_report(y_val, y_pred, output_dict=True)
        auc = roc_auc_score(y_val, y_prob)

        metrics = {
            'accuracy':  report['accuracy'],
            'precision': report['1']['precision'],
            'recall':    report['1']['recall'],
            'f1':        report['1']['f1-score'],
            'auc':       auc,
            'train_samples': len(X_train),
            'val_samples':   len(X_val)
        }

        # FIX #41: print() → logger.info()
        logger.info(
            f"[ML-TRAIN] Validation metrics: Acc={metrics['accuracy']:.3f}, "
            f"Prec={metrics['precision']:.3f}, Rec={metrics['recall']:.3f}, AUC={auc:.3f}"
        )

        self._save_feature_importance()

        return metrics

    def save_model(self):
        """Save trained model to disk."""
        if not self.is_trained:
            logger.info("[ML] No trained model to save")
            return

        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

        # FIX #42: datetime.now() naive/UTC → datetime.now(ET)
        data = {
            'model':        self.model,
            'feature_names': self.feature_names,
            'trained_at':   datetime.now(ET).isoformat()
        }

        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(data, f)

        logger.info(f"[ML] Model saved to {MODEL_PATH}")

    def _save_feature_importance(self):
        """Save feature importance scores to CSV."""
        if not self.is_trained or self.model is None:
            return

        importance = self.model.feature_importances_
        df = pd.DataFrame({
            'feature':    self.feature_names,
            'importance': importance
        }).sort_values('importance', ascending=False)

        os.makedirs(os.path.dirname(IMPORTANCE_PATH), exist_ok=True)
        df.to_csv(IMPORTANCE_PATH, index=False)

        logger.info(f"[ML] Feature importance saved to {IMPORTANCE_PATH}")
        logger.info("[ML] Top 10 features:")
        for idx, row in df.head(10).iterrows():
            logger.info(f"  {row['feature']}: {row['importance']:.4f}")
