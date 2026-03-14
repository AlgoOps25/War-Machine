"""
DEPRECATED NAME — ml_signal_scorer_v2 was never created as a separate file.
This shim re-exports the v1 scorer so sniper.py imports don't fail.

Real implementation: app/ml/ml_signal_scorer.py
"""
from app.ml.ml_signal_scorer import (  # noqa: F401
    MLSignalScorerV1 as MLSignalScorerV2,
    MLSignalScorerV1,
    get_scorer,
    score_signal,
)

# Alias so `from app.ml.ml_signal_scorer_v2 import MLSignalScorerV2` works
__all__ = ["MLSignalScorerV2", "MLSignalScorerV1", "get_scorer", "score_signal"]
