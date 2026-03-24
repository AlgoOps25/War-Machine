# app/core/signal_scorecard.py
# Sprint 1 — 47.P1-1: SignalScorecard
#
# PURPOSE:
#   Replaces the ad-hoc float confidence arithmetic in _run_signal_pipeline
#   with a structured 0-100 scorecard.  Every contributor is scored
#   independently, summed, and a hard gate (score < SCORECARD_GATE_MIN)
#   kills the signal before arm_ticker() fires.
#
# INTEGRATION (sniper.py):
#   from app.core.signal_scorecard import build_scorecard, SCORECARD_GATE_MIN
#   scorecard = build_scorecard(inputs)
#   if scorecard.score < SCORECARD_GATE_MIN:
#       logger.info(f"[{ticker}] 🚫 SCORECARD-GATE: {scorecard.score:.1f} < {SCORECARD_GATE_MIN}")
#       return False
#
# SCORE BREAKDOWN (max 85):
#   Grade quality          0-15   (A+ = 15, A = 13, A- = 11, B+ = 11, B = 10)
#                          NOTE: grade weight intentionally flattened — backtest shows
#                          B+ / B grades outperform A+ when RVOL ≥ 1.2x. Old 25pt
#                          A+ weight was blocking winning setups below the gate.
#   IVR environment        0-15   (IVR 20-50 = 15, IVR 50-80 = 10, else = 5)
#   GEX zone               0-15   (neg_gex_zone = 15, pos = 8)
#   MTF trend alignment    0-15   (boost > 0.05 = 15, boost > 0 = 10, else = 5)
#   SMC enrichment         0-10   (delta >= 0.05 = 10, delta > 0 = 7, else = 3)
#   VWAP gate pass         0-5    (pass = 5, else gate blocks before here)
#   Liquidity sweep        0-5    (detected = 5, else = 0)
#   OB retest              0-5    (detected = 5, else = 0)
#   SPY regime             0-5    (STRONG_BULL/BEAR aligned = 5, BULL/BEAR = 3, else = 1)
#
# GATE: score < 60 → signal dropped.
# (Lowered from 72 to pass B-grade setups validated by grid search data.)

from dataclasses import dataclass, field
from typing import Optional
import logging
logger = logging.getLogger(__name__)

SCORECARD_GATE_MIN = 60   # lowered from 72 — grid search shows B-grade setups win at RVOL≥1.2x


@dataclass
class SignalScorecard:
    # Raw contributor scores
    grade_score:     float = 0.0
    ivr_score:       float = 0.0
    gex_score:       float = 0.0
    mtf_trend_score: float = 0.0
    smc_score:       float = 0.0
    vwap_score:      float = 0.0
    sweep_score:     float = 0.0
    ob_score:        float = 0.0
    regime_score:    float = 0.0

    # Computed total
    score: float = 0.0

    # Metadata for Discord / logging
    grade:     str = ""
    direction: str = ""
    ticker:    str = ""
    breakdown: str = ""

    def compute(self) -> "SignalScorecard":
        self.score = (
            self.grade_score
            + self.ivr_score
            + self.gex_score
            + self.mtf_trend_score
            + self.smc_score
            + self.vwap_score
            + self.sweep_score
            + self.ob_score
            + self.regime_score
        )
        self.breakdown = (
            f"grade={self.grade_score:.0f} "
            f"ivr={self.ivr_score:.0f} "
            f"gex={self.gex_score:.0f} "
            f"mtf={self.mtf_trend_score:.0f} "
            f"smc={self.smc_score:.0f} "
            f"vwap={self.vwap_score:.0f} "
            f"sweep={self.sweep_score:.0f} "
            f"ob={self.ob_score:.0f} "
            f"regime={self.regime_score:.0f} "
            f"= {self.score:.1f}"
        )
        return self


def _score_grade(grade: str) -> float:
    # Intentionally flattened — grid search shows grade is NOT a reliable
    # win predictor. B+ / B outperform A+ when RVOL ≥ 1.2x.
    # Old mapping: A+=25, A=22, A-=18, B+=14, B=10
    return {"A+": 15, "A": 13, "A-": 11, "B+": 11, "B": 10}.get(grade, 8)


def _score_ivr(options_rec: Optional[dict]) -> float:
    if not options_rec:
        return 5.0
    ivr = options_rec.get("ivr", None)
    if ivr is None:
        return 5.0
    if 20 <= ivr <= 50:
        return 15.0
    if 50 < ivr <= 80:
        return 10.0
    return 5.0


def _score_gex(options_rec: Optional[dict]) -> float:
    if not options_rec:
        return 8.0
    gex_data = options_rec.get("gex_data", {})
    if not gex_data or not gex_data.get("has_data"):
        return 8.0
    return 15.0 if gex_data.get("neg_gex_zone") else 8.0


def _score_mtf_trend(mtf_trend_boost: float) -> float:
    if mtf_trend_boost > 0.05:
        return 15.0
    if mtf_trend_boost > 0.0:
        return 10.0
    return 5.0


def _score_smc(smc_delta: float) -> float:
    if smc_delta >= 0.05:
        return 10.0
    if smc_delta > 0.0:
        return 7.0
    return 3.0


def _score_regime(spy_regime: Optional[dict], direction: str) -> float:
    if not spy_regime:
        return 1.0
    label = spy_regime.get("label", "UNKNOWN")
    is_bull = direction == "bull"
    aligned_strong = (is_bull and label == "STRONG_BULL") or (not is_bull and label == "STRONG_BEAR")
    aligned = (is_bull and label in ("BULL", "NEUTRAL_BULL")) or (not is_bull and label in ("BEAR", "NEUTRAL_BEAR"))
    if aligned_strong:
        return 5.0
    if aligned:
        return 3.0
    return 1.0


def _check_confidence_inversion(ticker: str, grade: str, rvol: Optional[float]) -> None:
    """
    Warn when A+ grade + low RVOL — the exact combo that inverts confidence vs P&L.
    Grid search finding: RVOL < 1.2x → 40% WR / -0.101 avg R regardless of grade.
    A+ grade at low RVOL scores 15pts toward the gate but should be treated as noise.
    """
    if grade == "A+" and rvol is not None and rvol < 1.2:
        logger.warning(
            f"[{ticker}] ⚠️  CONFIDENCE-INVERSION: A+ grade but RVOL={rvol:.2f}x < 1.2x — "
            f"high scorecard score does NOT predict profitability at this volume level. "
            f"Consider RVOL gate enforcement upstream."
        )


def build_scorecard(
    ticker: str,
    direction: str,
    grade: str,
    options_rec: Optional[dict],
    mtf_trend_boost: float,
    smc_delta: float,
    vwap_passed: bool,
    sweep_detected: bool,
    ob_detected: bool,
    spy_regime: Optional[dict],
    rvol: Optional[float] = None,   # added for inversion warning
) -> "SignalScorecard":
    """
    Build and return a computed SignalScorecard from all pipeline contributors.
    Non-fatal: any exception returns a pass-through scorecard at score=60.
    """
    try:
        # Fire inversion warning before scoring
        _check_confidence_inversion(ticker, grade, rvol)

        sc = SignalScorecard(
            ticker=ticker,
            direction=direction,
            grade=grade,
            grade_score=_score_grade(grade),
            ivr_score=_score_ivr(options_rec),
            gex_score=_score_gex(options_rec),
            mtf_trend_score=_score_mtf_trend(mtf_trend_boost),
            smc_score=_score_smc(smc_delta),
            vwap_score=5.0 if vwap_passed else 0.0,
            sweep_score=5.0 if sweep_detected else 0.0,
            ob_score=5.0 if ob_detected else 0.0,
            regime_score=_score_regime(spy_regime, direction),
        )
        sc.compute()
        logger.info(f"[{ticker}] 📊 SCORECARD: {sc.breakdown}")
        return sc
    except Exception as e:
        logger.info(f"[SCORECARD] build_scorecard error (non-fatal, pass-through): {e}")
        sc = SignalScorecard(ticker=ticker, direction=direction, grade=grade)
        sc.score = SCORECARD_GATE_MIN  # pass-through on error
        return sc
