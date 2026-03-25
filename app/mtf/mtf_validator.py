"""
MTF Trend Validator  (app.mtf.mtf_validator)  ← canonical location
====================================================================
Step 8.5 helper. Validates multi-timeframe trend alignment using
EMA 9/21 crossover state across 1m / 5m / 15m / 30m.

Exports expected by app/mtf/__init__.py:
    MTFTrendValidator        class
    MTFValidator             alias for MTFTrendValidator
    get_mtf_trend_validator  factory → returns singleton
    mtf_validator            module-level singleton instance
    validate_signal_mtf      convenience function

PHASE 41.H-3 (Mar 19, 2026):
  - FIX: validate_signal_mtf() re-fetched bars from DB for all 4 timeframes
    on every pipeline call (3 extra DB reads per signal).
    Fix: accept optional bars_by_tf dict {"5m": [...], "15m": [...], ...}.
    When a timeframe is present in bars_by_tf the DB fetch is skipped.
    Callers that already hold 5m bars can pass {"5m": bars} and save
    the two most-expensive reads (5m + 15m). Falls back to _get_bars()
    for any timeframe not supplied.
"""
from __future__ import annotations
from typing import Dict, Any, Optional

_TF_WEIGHTS: Dict[str, float] = {"30m": 3.5, "15m": 2.5, "5m": 2.5, "1m": 1.5}
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
        return 0.5, "neutral"
    else:
        price_below = closes[-1] < e21[-1]
        if not latest_bull and not prev_bull and slope_9 < 0 and price_below:
            return 1.0, "aligned"
        elif not latest_bull and price_below:
            return 0.75, "partial"
        elif latest_bull and price_above:
            return 0.0, "divergent"
        return 0.5, "neutral"


def validate_signal_mtf(
    ticker: str,
    direction: str,
    entry_price: float = 0.0,
    bars_by_tf: Optional[Dict[str, list]] = None,
) -> Dict[str, Any]:
    """
    Validate MTF trend alignment. Returns passes/boost/score dict.

    Args:
        ticker:      Stock symbol.
        direction:   "bull" or "bear".
        entry_price: Optional entry price (unused internally, kept for callers).
        bars_by_tf:  Optional pre-fetched bars keyed by timeframe string
                     e.g. {"5m": [...], "15m": [...]}.
                     Any timeframe present here skips the DB fetch entirely.
                     Missing timeframes fall back to _get_bars() as before.
    """
    if bars_by_tf is None:
        bars_by_tf = {}

    tf_scores: Dict[str, dict] = {}
    divergences: list = []
    weighted_sum = 0.0
    for tf, weight in _TF_WEIGHTS.items():
        # 41.H-3: use caller-supplied bars when available, else fetch from DB
        bars = bars_by_tf.get(tf) or _get_bars(ticker, tf)
        score_norm, status = _score_timeframe(bars, direction)
        weighted_sum += score_norm * weight
        tf_scores[tf] = {"score": round(score_norm, 3), "status": status, "weight": weight}
        if status == "divergent":
            divergences.append(tf)
    overall_score = weighted_sum
    passes = overall_score >= PASS_THRESHOLD
    if passes:
        boost = round(min(BOOST_SCALE * ((overall_score - PASS_THRESHOLD) / (10.0 - PASS_THRESHOLD)), BOOST_SCALE), 4)
    else:
        boost = 0.0
    aligned = [tf for tf, d in tf_scores.items() if d["status"] == "aligned"]
    summary = (
        f"MTF aligned on {', '.join(aligned) or 'partial'} | score={overall_score:.1f}/10 | boost=+{boost*100:.0f}%"
        if passes else
        f"MTF weak alignment | score={overall_score:.1f}/10 | divergent={divergences or 'none'}"
    )
    return {
        "passes": passes, "confidence_boost": boost,
        "overall_score": round(overall_score, 2),
        "divergences": divergences, "tf_scores": tf_scores, "summary": summary,
    }


class MTFTrendValidator:
    """Class wrapper around validate_signal_mtf for OOP consumers."""

    def validate(
        self,
        ticker: str,
        direction: str,
        entry_price: float = 0.0,
        bars_by_tf: Optional[Dict[str, list]] = None,
    ) -> Dict[str, Any]:
        return validate_signal_mtf(ticker, direction, entry_price, bars_by_tf=bars_by_tf)

    def is_aligned(self, ticker: str, direction: str) -> bool:
        return validate_signal_mtf(ticker, direction)["passes"]

    def get_boost(self, ticker: str, direction: str) -> float:
        return validate_signal_mtf(ticker, direction)["confidence_boost"]


# Alias for legacy imports
MTFValidator = MTFTrendValidator


_instance: Optional[MTFTrendValidator] = None

def get_mtf_trend_validator() -> MTFTrendValidator:
    """Return the module-level singleton."""
    global _instance
    if _instance is None:
        _instance = MTFTrendValidator()
    return _instance


# Module-level singleton — satisfies: from app.mtf.mtf_validator import mtf_validator
mtf_validator = MTFTrendValidator()
