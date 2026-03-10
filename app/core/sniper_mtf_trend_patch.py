"""
MTF Trend Validator — sniper.py integration patch (Step 8.5)

This module is imported by sniper.py to wire in the MTF trend layer
between Steps 8 (confirmation layers) and 9 (MTF FVG boost).

Usage in sniper.py _run_signal_pipeline():

    from app.core.sniper_mtf_trend_patch import run_mtf_trend_step

    # Between Step 8 and Step 9:
    confidence, signal_data = run_mtf_trend_step(
        ticker, direction, entry_price, confidence, signal_data
    )

Behaviour:
  - If MTF trend passes  (score >= 6.0): applies confidence_boost additively
  - If MTF trend fails   (score <  6.0): no boost, logs warning — does NOT
    hard-kill signal (validator is additive, not a gate, to preserve throughput
    while trend data is calibrated)
  - If import fails or exception raised: logs warning, passes through unchanged
"""
from typing import Tuple, Dict

try:
    from app.signals.mtf_validator import validate_signal_mtf
    MTF_TREND_ENABLED = True
    print("[SNIPER] \u2705 MTF trend validator wired (Step 8.5)")
except ImportError as e:
    MTF_TREND_ENABLED = False
    print(f"[SNIPER] \u26a0\ufe0f  MTF trend validator not available: {e}")
    def validate_signal_mtf(ticker, direction, entry_price):
        return {'passes': True, 'confidence_boost': 0.0, 'overall_score': 0.0,
                'divergences': [], 'summary': 'MTF trend disabled'}


def run_mtf_trend_step(
    ticker: str,
    direction: str,
    entry_price: float,
    confidence: float,
    signal_data: Dict
) -> Tuple[float, Dict]:
    """
    Step 8.5 — MTF trend alignment check.

    Returns updated (confidence, signal_data).
    Never raises — all exceptions are caught and logged.
    """
    if not MTF_TREND_ENABLED:
        return confidence, signal_data

    try:
        result = validate_signal_mtf(ticker, direction, entry_price)
        boost  = result.get('confidence_boost', 0.0)

        # Attach metadata for Discord alert / DB logging
        signal_data['mtf_trend'] = {
            'score':      result.get('overall_score', 0.0),
            'passes':     result.get('passes', True),
            'boost':      boost,
            'divergences': result.get('divergences', []),
            'summary':    result.get('summary', ''),
            'tf_scores':  result.get('tf_scores', {})
        }

        if result.get('passes', True) and boost > 0:
            confidence = min(0.99, confidence + boost)
            print(f"[STEP-8.5] {ticker} MTF trend \u2705 score={result['overall_score']:.1f} "
                  f"boost=+{boost*100:.0f}% new_conf={confidence:.3f}")
        elif not result.get('passes', True):
            print(f"[STEP-8.5] {ticker} MTF trend \u26a0\ufe0f  score={result['overall_score']:.1f} "
                  f"(below threshold, no boost) | {result.get('summary', '')}")
        else:
            print(f"[STEP-8.5] {ticker} MTF trend neutral score={result['overall_score']:.1f}")

    except Exception as exc:
        print(f"[STEP-8.5] {ticker} MTF trend error (non-fatal): {exc}")

    return confidence, signal_data
