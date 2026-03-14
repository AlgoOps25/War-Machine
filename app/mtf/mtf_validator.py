"""
MTF Trend Validator  (app.mtf.mtf_validator)  ← canonical location
====================================================================
Step 8.5 helper for sniper_mtf_trend_patch.py.

Validates multi-timeframe trend alignment using EMA 9/21 crossover state
across four timeframes: 1m, 5m, 15m, 30m.

Public API
----------
validate_signal_mtf(ticker, direction, entry_price) -> dict

Return dict schema:
    passes          bool    True if overall_score >= PASS_THRESHOLD
    confidence_boost float   Additive boost to apply if passes (0.0-0.08)
    overall_score   float   Weighted alignment score (0.0-10.0)
    divergences     list    Timeframes conflicting with direction
    tf_scores       dict    Per-timeframe score contribution
    summary         str     Human-readable one-liner
"""

from __future__ import annotations
from typing import Dict, Any

_TF_WEIGHTS: Dict[str, float] = {
    "30m": 3.5,
    "15m": 2.5,
    "5m":  2.5,
    "1m":  1.5,
}
_TOTAL_WEIGHT = sum(_TF_WEIGHTS.values())   # 10.0
PASS_THRESHOLD = 6.0
BOOST_SCALE    = 0.08


def _get_bars(ticker: str, timeframe: str) -> list:
    try:
        from app.data.data_manager import data_manager
        bars = data_manager.get_bars(ticker, timeframe, limit=40)
        return bars if bars else []
    except Exception:
        return []


def _ema(values: list, period: int) -> list:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _score_timeframe(bars: list, direction: str) -> tuple[float, str]:
    if len(bars) < 25:
        return 0.5, "insufficient_data"
    closes = [b["close"] for b in bars if "close" in b]
    if len(closes) < 25:
        return 0.5, "insufficient_data"
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    if not ema9 or not ema21:
        return 0.5, "insufficient_data"
    n = min(len(ema9), len(ema21))
    e9, e21 = ema9[-n:], ema21[-n:]
    if n < 3:
        return 0.5, "insufficient_data"
    latest_bull = e9[-1] > e21[-1]
    prev_bull   = e9[-3] > e21[-3]
    slope_9     = e9[-1] - e9[-3]
    price_above = closes[-1] > e21[-1]
    if direction == "bull":
        if latest_bull and prev_bull and slope_9 > 0 and price_above:
            return 1.0, "aligned"
        elif latest_bull and price_above:
            return 0.75, "partial"
        elif not latest_bull and not price_above:
            return 0.0, "divergent"
        else:
            return 0.5, "neutral"
    else:
        bear_align  = not latest_bull
        bear_prev   = not prev_bull
        price_below = closes[-1] < e21[-1]
        if bear_align and bear_prev and slope_9 < 0 and price_below:
            return 1.0, "aligned"
        elif bear_align and price_below:
            return 0.75, "partial"
        elif latest_bull and price_above:
            return 0.0, "divergent"
        else:
            return 0.5, "neutral"


def validate_signal_mtf(
    ticker: str,
    direction: str,
    entry_price: float,
) -> Dict[str, Any]:
    tf_scores: Dict[str, dict] = {}
    divergences: list[str] = []
    weighted_sum = 0.0
    for tf, weight in _TF_WEIGHTS.items():
        bars = _get_bars(ticker, tf)
        score_norm, status = _score_timeframe(bars, direction)
        weighted_sum += score_norm * weight
        tf_scores[tf] = {"score": round(score_norm, 3), "status": status, "weight": weight}
        if status == "divergent":
            divergences.append(tf)
    overall_score = weighted_sum
    passes = overall_score >= PASS_THRESHOLD
    if passes:
        boost = BOOST_SCALE * ((overall_score - PASS_THRESHOLD) / (10.0 - PASS_THRESHOLD))
        boost = round(min(boost, BOOST_SCALE), 4)
    else:
        boost = 0.0
    aligned_tfs = [tf for tf, d in tf_scores.items() if d["status"] == "aligned"]
    if passes:
        summary = (
            f"MTF aligned on {', '.join(aligned_tfs) or 'partial'} | "
            f"score={overall_score:.1f}/10 | boost=+{boost*100:.0f}%"
        )
    else:
        summary = (
            f"MTF weak alignment | score={overall_score:.1f}/10 | "
            f"divergent={divergences or 'none'}"
        )
    return {
        "passes":           passes,
        "confidence_boost": boost,
        "overall_score":    round(overall_score, 2),
        "divergences":      divergences,
        "tf_scores":        tf_scores,
        "summary":          summary,
    }
