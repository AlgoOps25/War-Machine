"""
Day 6: ML Confidence Boosting

Machine learning module for signal confidence adjustment using LightGBM.
Predicts win probability based on 40+ features and adjusts confidence ±15%.
"""

__all__ = [
    'confidence_booster',
    'build_feature_vector',
    'train_confidence_booster',
    'bootstrap_training_data'
]
