"""
ML Feedback Loop for War Machine
Trains model on signal outcomes and adjusts confidence scoring
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import joblib
import logging
from datetime import datetime

class MLFeedbackLoop:
    def __init__(self, db_connection):
        self.db = db_connection
        self.model = None
        self.label_encoders = {}
        self.feature_importance = None
        logging.info("[ML] Feedback loop initialized")
    
    def load_training_data(self, min_samples=20):
        """
        Load training data from database
        Returns: (X, y) dataframes or None if insufficient data
        """
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT 
                    rvol, vix, score, time_of_day, confidence, regime,
                    outcome, profit_r
                FROM ml_training_data
                WHERE outcome IS NOT NULL
                ORDER BY created_at DESC
            """)
            
            rows = cursor.fetchall()
            
            if len(rows) < min_samples:
                logging.warning(f"[ML] Insufficient training data: {len(rows)} samples (need {min_samples})")
                return None, None
            
            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=[
                'rvol', 'vix', 'score', 'time_of_day', 'confidence', 'regime',
                'outcome', 'profit_r'
            ])
            
            # Separate features and targets
            X = df[['rvol', 'vix', 'score', 'time_of_day', 'confidence', 'regime']]
            y = df['outcome']
            
            logging.info(f"[ML] Loaded {len(df)} training samples | Win Rate: {y.mean()*100:.1f}%")
            return X, y
            
        except Exception as e:
            logging.error(f"[ML] Failed to load training data: {e}")
            return None, None
    
    def train_model(self, X, y):
        """
        Train Random Forest model on signal outcomes
        """
        try:
            # Encode categorical features
            X_encoded = X.copy()
            
            for col in ['time_of_day', 'regime']:
                if col not in self.label_encoders:
                    self.label_encoders[col] = LabelEncoder()
                    X_encoded[col] = self.label_encoders[col].fit_transform(X[col])
                else:
                    X_encoded[col] = self.label_encoders[col].transform(X[col])
            
            # Train Random Forest
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=5,
                min_samples_split=5,
                random_state=42
            )
            
            self.model.fit(X_encoded, y)
            
            # Calculate feature importance
            self.feature_importance = dict(zip(
                X.columns,
                self.model.feature_importances_
            ))
            
            # Log results
            train_acc = self.model.score(X_encoded, y)
            logging.info(f"[ML] ✅ Model trained | Accuracy: {train_acc*100:.1f}%")
            logging.info(f"[ML] Top features: {sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)[:3]}")
            
            return True
            
        except Exception as e:
            logging.error(f"[ML] Training failed: {e}")
            return False
    
    def predict_signal_quality(self, signal_features):
        """
        Predict win probability for a new signal
        Returns: (win_probability, confidence_adjustment)
        """
        if self.model is None:
            return 0.5, 1.0  # Default: 50% win rate, no adjustment
        
        try:
            # Prepare features
            X = pd.DataFrame([signal_features])
            X_encoded = X.copy()
            
            for col in ['time_of_day', 'regime']:
                if col in self.label_encoders:
                    X_encoded[col] = self.label_encoders[col].transform(X[col])
            
            # Predict
            win_prob = self.model.predict_proba(X_encoded)[0][1]
            
            # Confidence adjustment (boost/penalize based on ML prediction)
            if win_prob >= 0.7:
                confidence_adj = 1.10  # +10% confidence boost
            elif win_prob >= 0.6:
                confidence_adj = 1.05  # +5% confidence boost
            elif win_prob <= 0.4:
                confidence_adj = 0.85  # -15% confidence penalty
            elif win_prob <= 0.5:
                confidence_adj = 0.95  # -5% confidence penalty
            else:
                confidence_adj = 1.0  # No adjustment
            
            logging.info(f"[ML] Signal quality: {win_prob*100:.1f}% win prob | Confidence adj: {confidence_adj:.2f}x")
            return win_prob, confidence_adj
            
        except Exception as e:
            logging.error(f"[ML] Prediction failed: {e}")
            return 0.5, 1.0
    
    def save_model(self, filepath='models/war_machine_ml.pkl'):
        """Save trained model to disk"""
        try:
            joblib.dump({
                'model': self.model,
                'label_encoders': self.label_encoders,
                'feature_importance': self.feature_importance
            }, filepath)
            logging.info(f"[ML] ✅ Model saved to {filepath}")
        except Exception as e:
            logging.error(f"[ML] Failed to save model: {e}")
    
    def load_model(self, filepath='models/war_machine_ml.pkl'):
        """Load trained model from disk"""
        try:
            data = joblib.load(filepath)
            self.model = data['model']
            self.label_encoders = data['label_encoders']
            self.feature_importance = data['feature_importance']
            logging.info(f"[ML] ✅ Model loaded from {filepath}")
            return True
        except Exception as e:
            logging.warning(f"[ML] No saved model found: {e}")
            return False
    
    def retrain_daily(self):
        """
        Daily retraining routine (call at market close)
        """
        logging.info("[ML] 🔄 Starting daily retrain...")
        
        X, y = self.load_training_data()
        if X is None:
            logging.warning("[ML] Skipping retrain - insufficient data")
            return False
        
        success = self.train_model(X, y)
        if success:
            self.save_model()
            logging.info("[ML] ✅ Daily retrain complete")
        
        return success
