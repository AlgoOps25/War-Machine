#!/usr/bin/env python3
"""
Test ML Prediction System
Run: python tests/test_ml_predictions.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.learning.ml_feedback_loop import MLFeedbackLoop
from datetime import datetime
import psycopg2

def main():
    print("=" * 60)
    print("ML PREDICTION SYSTEM TEST")
    print("=" * 60)
    print()
    
    # Connect to database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ ERROR: DATABASE_URL not set")
        print("Set it: $env:DATABASE_URL=\"postgresql://...\"")
        return
    
    db = psycopg2.connect(db_url)
    ml = MLFeedbackLoop(db)
    
    # Try to train (needs 20+ samples, we only have 1 NVDA)
    print("🧠 Training ML model...")
    success = ml.train_model(min_samples=1)  # Lower threshold for testing
    print(f"ML Training: {'✅ Success' if success else '⚠️ Insufficient data (need 20 samples)'}")
    print()
    
    # Test prediction on a new signal
    print("📊 Testing prediction on mock TSLA signal...")
    test_signal = {
        'ticker': 'TSLA',
        'signal_time': datetime.now(),
        'pattern': 'GAP_MOVER',
        'confidence': 75,
        'entry_price': 250.00,
        'stop_loss': 248.00,
        'target_1': 253.00,
        'target_2': 255.00,
        'regime': 'BULL',
        'vix_level': 18.5,
        'spy_trend': 'UP',
        'rvol': 3.2,
        'score': 82,
        'explosive_override': False
    }
    
    confidence_adj, win_prob = ml.predict_signal_quality(test_signal)
    print()
    print(f'📊 ML Prediction for TSLA:')
    print(f'   Win Probability: {win_prob:.1%}')
    print(f'   Confidence Adjustment: {confidence_adj:+d}%')
    print(f'   Original Confidence: {test_signal["confidence"]}%')
    print(f'   New Confidence: {test_signal["confidence"] + confidence_adj}%')
    print()
    
    # Test with different scenarios
    print("📊 Testing edge cases...")
    
    # Low RVOL signal
    low_rvol = test_signal.copy()
    low_rvol['rvol'] = 1.2
    adj, prob = ml.predict_signal_quality(low_rvol)
    print(f"   Low RVOL (1.2): {prob:.1%} win prob, {adj:+d}% adj")
    
    # High VIX signal
    high_vix = test_signal.copy()
    high_vix['vix_level'] = 35.0
    adj, prob = ml.predict_signal_quality(high_vix)
    print(f"   High VIX (35): {prob:.1%} win prob, {adj:+d}% adj")
    
    # Bear regime signal
    bear = test_signal.copy()
    bear['regime'] = 'BEAR'
    adj, prob = ml.predict_signal_quality(bear)
    print(f"   Bear Regime: {prob:.1%} win prob, {adj:+d}% adj")
    
    print()
    print("✅ ML prediction test complete!")
    print()
    print("Next: Add more signals to database for better ML training")
    print("ML needs 20+ completed trades to train effectively")
    
    db.close()

if __name__ == "__main__":
    main()
