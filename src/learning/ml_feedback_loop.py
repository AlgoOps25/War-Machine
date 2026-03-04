"""
ML Feedback Loop for War Machine
Train models from past signal outcomes and adjust future confidence
"""

import psycopg2
import numpy as np
import pickle
from datetime import datetime
import logging
import os

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logging.warning("[ML] scikit-learn not available - ML features disabled")

class MLFeedbackLoop:
    def __init__(self, db_connection, model_path='models/signal_predictor.pkl'):
        self.db = db_connection
        self.model_path = model_path
        self.model = None
        self.feature_importance = {}
        
        # Create models directory if it doesn't exist
        os.makedirs(os.path.dirname(model_path) if os.path.dirname(model_path) else 'models', exist_ok=True)
        
        if ML_AVAILABLE:
            self.load_model()
            logging.info("[ML] Feedback loop initialized")
        else:
            logging.warning("[ML] ML features disabled - install scikit-learn")
    
    def load_model(self):
        """Load trained model from disk"""
        try:
            with open(self.model_path, 'rb') as f:
                self.model = pickle.load(f)
            logging.info(f"[ML] Model loaded from {self.model_path}")
        except FileNotFoundError:
            logging.info("[ML] No saved model found - will train on first run")
        except Exception as e:
            logging.error(f"[ML] Failed to load model: {e}")
    
    def save_model(self):
        """Save trained model to disk"""
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.model, f)
            logging.info(f"[ML] Model saved to {self.model_path}")
        except Exception as e:
            logging.error(f"[ML] Failed to save model: {e}")
    
    def train_model(self, min_samples=20):
        """
        Train ML model on closed signals
        Call this at market close or when sufficient new data exists
        """
        if not ML_AVAILABLE:
            return False
        
        try:
            cursor = self.db.cursor()
            # Fixed: JOIN with signal_outcomes to get signal_time
            cursor.execute("""
                SELECT 
                    ml.rvol, ml.vix, ml.score, 
                    EXTRACT(HOUR FROM so.signal_time) as hour,
                    EXTRACT(MINUTE FROM so.signal_time) as minute,
                    ml.confidence, 
                    CASE WHEN ml.regime = 'BULL' THEN 1 ELSE 0 END as is_bull,
                    ml.outcome,
                    ml.profit_r
                FROM ml_training_data ml
                JOIN signal_outcomes so ON ml.signal_id = so.id
                WHERE ml.outcome IS NOT NULL
                ORDER BY ml.created_at DESC
                LIMIT 500
            """)
            
            rows = cursor.fetchall()
            
            if len(rows) < min_samples:
                logging.warning(f"[ML] Insufficient data for training: {len(rows)} < {min_samples}")
                return False
            
            # Prepare features and labels
            X = []
            y = []
            
            for row in rows:
                rvol, vix, score, hour, minute, confidence, is_bull, outcome, profit_r = row
                
                # Feature engineering
                time_score = (hour * 60 + minute - 570) / 390  # Normalize market hours (9:30-16:00)
                features = [
                    rvol,
                    vix,
                    score,
                    time_score,
                    confidence,
                    is_bull
                ]
                
                X.append(features)
                y.append(1 if outcome else 0)  # 1 = WIN, 0 = LOSS
            
            X = np.array(X)
            y = np.array(y)
            
            # Train model
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                random_state=42
            )
            
            self.model.fit(X, y)
            
            # Calculate feature importance
            feature_names = ['rvol', 'vix', 'score', 'time', 'confidence', 'is_bull']
            self.feature_importance = dict(zip(feature_names, self.model.feature_importances_))
            
            # Save model
            self.save_model()
            
            # Calculate accuracy
            accuracy = self.model.score(X, y)
            
            logging.info(f"[ML] Model trained on {len(rows)} samples | Accuracy: {accuracy:.2%}")
            logging.info(f"[ML] Feature importance: {self.feature_importance}")
            
            return True
            
        except Exception as e:
            logging.error(f"[ML] Training failed: {e}")
            return False
    
    def predict_signal_quality(self, signal_data):
        """
        Predict if signal will win/loss
        Returns: (confidence_adjustment, win_probability)
        """
        if not ML_AVAILABLE or self.model is None:
            return 0, 0.5  # No adjustment if ML unavailable
        
        try:
            # Extract features
            signal_time = signal_data.get('signal_time', datetime.now())
            time_score = (signal_time.hour * 60 + signal_time.minute - 570) / 390
            
            features = np.array([[
                signal_data['rvol'],
                signal_data['vix_level'],
                signal_data['score'],
                time_score,
                signal_data['confidence'],
                1 if signal_data['regime'] == 'BULL' else 0
            ]])
            
            # Get prediction probability
            win_prob = self.model.predict_proba(features)[0][1]  # Probability of WIN
            
            # Adjust confidence based on ML prediction
            # High ML confidence (>0.65) = boost confidence
            # Low ML confidence (<0.35) = reduce confidence
            if win_prob >= 0.65:
                adjustment = min(15, int((win_prob - 0.5) * 30))  # Max +15%
            elif win_prob <= 0.35:
                adjustment = max(-15, int((win_prob - 0.5) * 30))  # Max -15%
            else:
                adjustment = 0  # Neutral zone
            
            logging.info(f"[ML] Signal quality: {win_prob:.2%} | Confidence adjustment: {adjustment:+d}%")
            
            return adjustment, win_prob
            
        except Exception as e:
            logging.error(f"[ML] Prediction failed: {e}")
            return 0, 0.5
    
    def get_feature_importance(self):
        """Return current feature importance scores"""
        return self.feature_importance
    
    def schedule_daily_training(self):
        """
        Schedule model retraining at market close (4:00 PM EST)
        Call this in your main loop
        """
        now = datetime.now()
        if now.hour == 16 and now.minute == 0:
            logging.info("[ML] Running scheduled daily training...")
            self.train_model()