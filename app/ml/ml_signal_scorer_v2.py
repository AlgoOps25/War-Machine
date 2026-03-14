"""
DEPRECATED NAME — ml_signal_scorer_v2 was never created as a separate file.
This shim re-exports the v1 scorer so sniper.py imports don't fail.

Real implementation: app/ml/ml_signal_scorer.py

Exported names expected by sniper.py:
    get_scorer_v2()  → returns the MLSignalScorerV1 singleton
    get_scorer()     → same
    score_signal()   → convenience wrapper
    MLSignalScorerV2 → alias for MLSignalScorerV1
"""
from app.ml.ml_signal_scorer import (  # noqa: F401
    MLSignalScorerV1 as MLSignalScorerV2,
    MLSignalScorerV1,
    get_scorer,
    score_signal,
)


def get_scorer_v2():
    """Return the ML scorer singleton (delegates to ml_signal_scorer.get_scorer)."""
    return get_scorer()


__all__ = ["MLSignalScorerV2", "MLSignalScorerV1", "get_scorer", "get_scorer_v2", "score_signal"]
