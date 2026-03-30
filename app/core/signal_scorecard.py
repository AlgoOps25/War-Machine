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
# SCORE BREAKDOWN (max 95 + RVOL ceiling deduction):
#   Grade quality          0-15   (A+ = 15, A = 13, A- = 11, B+ = 11, B = 10)
#                          NOTE: grade weight intentionally flattened — backtest shows
#                          B+ / B grades outperform A+ when RVOL ≥ 1.2x. Old 25pt
#                          A+ weight was blocking winning setups below the gate.
#   IVR environment        0-15   (IVR 20-50 = 15, IVR 50-80 = 10, no-data = 10)
#   GEX zone               0-15   (neg_gex_zone = 15, pos = 8, no-data = 10)
#   MTF trend alignment    0-15   (boost > 0.05 = 15, boost > 0 = 10, no-data = 8)
#   SMC enrichment         0-10   (delta >= 0.05 = 10, delta > 0 = 7, else = 3)
#   VWAP gate pass         0-5    (pass = 5, else gate blocks before here)
#   Liquidity sweep        0-5    (detected = 5, else = 0)
#   OB retest              0-5    (detected = 5, else = 0)
#   SPY regime             0-5    (STRONG_BULL/BEAR aligned = 5, BULL/BEAR = 3, else = 1)
#   CFW6 confidence base   0-10   (BUG-SP-2 fix 2026-03-30)
#                                  confidence_base >= 0.80 = 10, >= 0.70 = 7,
#                                  >= 0.60 = 5, >= 0.50 = 3, else = 0.
#                                  skip_cfw6=True path uses default 0.65 → 5pts.
#   RVOL ceiling penalty   -20    (RVOL >= config.RVOL_CEILING → deduct 20 pts)
#                                  Enforces config.RVOL_CEILING (3.0x) at scorecard layer.
#
# GATE: score < 60 → signal dropped.
# (Lowered from 72 to pass B-grade setups validated by grid search data.)
#
# Phase 1.38c — Fallback score calibration:
#   IVR/GEX/MTF fallbacks raised so missing enrichment data does not
#   block valid signals. Gate stays at 60.
#   Typical no-enrichment signal: 38 → 48 after this fix.
#
# FIX P2 (2026-03-25): exception handler now scores SCORECARD_GATE_MIN - 1
#   instead of exactly SCORECARD_GATE_MIN, so a scorer crash blocks the signal
#   rather than silently passing through at the gate boundary. Upgraded to
#   logger.warning so errors surface in Railway logs.
#
# FIX P4 (2026-03-25): _score_rvol_ceiling() added. RVOL >= RVOL_CEILING (3.0x)
#   deducts 20pts from scorecard total — enough to push any signal below the
#   60-pt gate. Enforces backtest finding that RVOL >= 3.0x destroys P&L
#   (-32.23 Total R combined across 3.0–4.0x and 4.0x+ cohorts).
#
# BUG-SP-2 FIX (2026-03-30): cfw6_confidence_base parameter added.
#   Previously confidence_base from grade_signal_with_confirmations() was
#   computed in sniper_pipeline.py and immediately discarded — it never
#   influenced the scorecard or final confidence value. Now scored 0-10pts
#   and included in the breakdown string.

from dataclasses import dataclass, field
from typing import Optional
import logging
logger = logging.getLogger(__name__)

SCORECARD_GATE_MIN = 60   # lowered from 72 — grid search shows B-grade setups win at RVOL≥1.2x


@dataclass
class SignalScorecard:
    # Raw contributor scores
    grade_score:          float = 0.0
    ivr_score:            float = 0.0
    gex_score:            float = 0.0
    mtf_trend_score:      float = 0.0
    smc_score:            float = 0.0
    vwap_score:           float = 0.0
    sweep_score:          float = 0.0
    ob_score:             float = 0.0
    regime_score:         float = 0.0
    cfw6_score:           float = 0.0   # BUG-SP-2: CFW6 confidence_base contributor
    rvol_ceiling_score:   float = 0.0   # P4: 0 normally, -20 when RVOL >= RVOL_CEILING

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
            + self.cfw6_score
            + self.rvol_ceiling_score
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
            f"cfw6={self.cfw6_score:.0f} "
            f"rvol_ceil={self.rvol_ceiling_score:.0f} "
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
        return 10.0  # Phase 1.38c: raised from 5 — missing data ≠ bad signal
    ivr = options_rec.get("ivr", None)
    if ivr is None:
        return 10.0  # Phase 1.38c: raised from 5
    if 20 <= ivr <= 50:
        return 15.0
    if 50 < ivr <= 80:
        return 10.0
    return 5.0


def _score_gex(options_rec: Optional[dict]) -> float:
    if not options_rec:
        return 10.0  # Phase 1.38c: raised from 8 — missing data ≠ bad signal
    gex_data = options_rec.get("gex_data", {})
    if not gex_data or not gex_data.get("has_data"):
        return 10.0  # Phase 1.38c: raised from 8
    return 15.0 if gex_data.get("neg_gex_zone") else 8.0


def _score_mtf_trend(mtf_trend_boost: float) -> float:
    if mtf_trend_boost > 0.05:
        return 15.0
    if mtf_trend_boost > 0.0:
        return 10.0
    return 8.0  # Phase 1.38c: raised from 5 — no MTF data ≠ bad signal


def _score_smc(smc_delta: Optional[float]) -> float:
    if smc_delta is None: return 7.0
    if smc_delta >= 0.05:
        return 10.0
    if smc_delta > 0.0:
        return 7.0
    return 3.0


def _score_cfw6_confidence(confidence_base: Optional[float]) -> float:
    """
    BUG-SP-2 fix (2026-03-30): Score CFW6 confirmation quality (0-10pts).
    confidence_base comes from grade_signal_with_confirmations() in
    cfw6_confirmation.py. Was previously computed and discarded.
    skip_cfw6=True path defaults confidence_base=0.65 → 5pts.
    """
    if confidence_base is None:
        return 5.0  # neutral fallback — no confirmation data ≠ bad signal
    if confidence_base >= 0.80:
        return 10.0
    if confidence_base >= 0.70:
        return 7.0
    if confidence_base >= 0.60:
        return 5.0
    if confidence_base >= 0.50:
        return 3.0
    return 0.0


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


def _score_rvol_ceiling(rvol: Optional[float]) -> float:
    """
    P4 (2026-03-25): Enforce config.RVOL_CEILING at scorecard layer.
    Backtest finding: RVOL >= 3.0x destroys P&L (-32.23 Total R combined
    across 3.0–4.0x and 4.0x+ cohorts, 582-trade audit 2026-03-24).
    Deducts 20pts — enough to drop any valid signal below the 60-pt gate.
    No penalty when rvol is None (missing data does not penalise).
    """
    if rvol is None:
        return 0.0
    try:
        from utils import config as _cfg
        ceiling = getattr(_cfg, "RVOL_CEILING", 3.0)
    except Exception:
        ceiling = 3.0
    if rvol >= ceiling:
        logger.warning(
            f"[SCORECARD] ⛔ RVOL={rvol:.2f}x >= RVOL_CEILING={ceiling:.1f}x — "
            f"deducting 20pts (backtest: RVOL≥3.0x cohort is -32.23R)"
        )
        return -20.0
    return 0.0


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
    rvol: Optional[float] = None,
    cfw6_confidence_base: Optional[float] = None,  # BUG-SP-2 fix
) -> "SignalScorecard":
    """
    Build and return a computed SignalScorecard from all pipeline contributors.

    FIX P2 (2026-03-25): Any exception now returns score = SCORECARD_GATE_MIN - 1
    (59) so a scorer crash blocks the signal rather than silently passing at exactly
    the gate boundary. Logged at WARNING level so errors surface in Railway logs.

    FIX P4 (2026-03-25): rvol parameter now passed to _score_rvol_ceiling() to
    enforce config.RVOL_CEILING at the scorecard layer.

    BUG-SP-2 FIX (2026-03-30): cfw6_confidence_base now scored 0-10pts via
    _score_cfw6_confidence(). Previously was computed in sniper_pipeline.py
    and silently discarded before this function was called.
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
            cfw6_score=_score_cfw6_confidence(cfw6_confidence_base),  # BUG-SP-2
            rvol_ceiling_score=_score_rvol_ceiling(rvol),  # P4
        )
        sc.compute()
        logger.info(f"[{ticker}] 📊 SCORECARD: {sc.breakdown}")
        return sc
    except Exception as e:
        # P2 FIX: score below gate (59) so a crash blocks rather than passes the signal
        logger.warning(f"[SCORECARD] ⚠️ build_scorecard error — blocking signal as precaution: {e}")
        sc = SignalScorecard(ticker=ticker, direction=direction, grade=grade)
        sc.score = SCORECARD_GATE_MIN - 1  # 59 — fails gate, does not pass through
        return sc
