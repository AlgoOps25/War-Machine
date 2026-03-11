"""
test_ml_predictions.py — ML Prediction System Tests

CI-safe:
  - test_ml_src_importable  — checks if src.learning.ml_feedback_loop is importable

Integration (requires DATABASE_URL):
  - test_ml_train_and_predict  — trains model + runs predictions on mock signals

Run CI-safe only:
  pytest tests/test_ml_predictions.py -v -m "not integration"
"""
import os
import pytest
from datetime import datetime

try:
    from src.learning.ml_feedback_loop import MLFeedbackLoop
    _ML_AVAILABLE = True
except ImportError:
    _ML_AVAILABLE = False
    MLFeedbackLoop = None


def test_ml_src_importable():
    """src.learning.ml_feedback_loop must import cleanly."""
    assert _ML_AVAILABLE, (
        "src.learning.ml_feedback_loop failed to import. "
        "Check that the src/ directory exists and that all ML dependencies "
        "(scikit-learn, etc.) are installed."
    )


@pytest.mark.integration
@pytest.mark.skipif(not _ML_AVAILABLE, reason="src.learning not importable")
def test_ml_train_and_predict():
    """Train ML model (min 1 sample) and run predictions on mock signals."""
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")

    db = psycopg2.connect(db_url)
    ml = MLFeedbackLoop(db)

    # Train — may return False if not enough data; that's acceptable
    ml.train_model(min_samples=1)

    base_signal = {
        'ticker':            'TSLA',
        'signal_time':       datetime.now(),
        'pattern':           'GAP_MOVER',
        'confidence':        75,
        'entry_price':       250.00,
        'stop_loss':         248.00,
        'target_1':          253.00,
        'target_2':          255.00,
        'regime':            'BULL',
        'vix_level':         18.5,
        'spy_trend':         'UP',
        'rvol':              3.2,
        'score':             82,
        'explosive_override': False,
    }

    conf_adj, win_prob = ml.predict_signal_quality(base_signal)
    assert isinstance(conf_adj, (int, float)), "confidence_adj must be numeric"
    assert isinstance(win_prob, float),        "win_prob must be float"
    assert 0.0 <= win_prob <= 1.0,             f"win_prob out of range: {win_prob}"

    # Edge-case variants
    low_rvol = {**base_signal, 'rvol': 1.2}
    high_vix = {**base_signal, 'vix_level': 35.0}
    bear_sig = {**base_signal, 'regime': 'BEAR'}

    for variant_name, variant in [
        ('low_rvol', low_rvol),
        ('high_vix', high_vix),
        ('bear',     bear_sig),
    ]:
        adj, prob = ml.predict_signal_quality(variant)
        assert 0.0 <= prob <= 1.0, f"{variant_name}: win_prob {prob} out of range"

    db.close()
