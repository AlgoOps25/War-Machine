# Phase 1.38d-fix-2 — March 26 2026
"""
app/core/sniper_pipeline.py — CFW6 Signal Pipeline

FIX HISTORY (2026-03-26, session 2):

  FIX A: **_unused_kwargs added to _run_signal_pipeline() signature.
    sniper.py's thin dispatcher (_run_signal_pipeline) calls _pipeline() and
    passes get_ticker_screener_metadata= and state= as keyword args. Those
    kwargs exist on the OLD all-in-one sniper.py signature but are not needed
    by this extracted pipeline. Without **_unused_kwargs every pipeline call
    from sniper.py raised TypeError: unexpected keyword argument.

  FIX B: options_rec parameter default changed from <required> to None.
    All current callers in sniper.py call _run_signal_pipeline() without
    passing options_rec. The missing arg caused TypeError on every call.
    options_rec=None is the correct default — scorecard and arm_ticker
    both handle None gracefully (IVR/GEX fallback to neutral score).

  FIX C: Removed duplicate set_cooldown() call after arm_ticker().
    arm_signal.arm_ticker() already calls set_cooldown() internally at the
    bottom of its execution. The extra call here wrote the cooldown twice
    with identical args (wasteful DB write) and emitted a duplicate log line.
    The 'if armed:' block and the set_cooldown import are both removed.

  FIX D: arm_ticker() has no return statement — it returns None implicitly.
    The old 'if armed: set_cooldown()' was therefore dead code. The pipeline
    now always returns True after arm_ticker() completes (arm_ticker guards
    its own failure paths and logs them), and False on any gate rejection.
    This gives callers a meaningful bool to log/track pipeline outcome.

FIX HISTORY (2026-03-26, session 1 / Issue #1):
  FIX 1-6: arm_ticker() TypeError — all 13 required args now supplied.
  compute_stop_and_targets() called before arm_ticker() to derive stop/targets.
  See CHANGELOG.md 2026-03-26 for full detail.
"""
from __future__ import annotations
import logging
from datetime import time
from zoneinfo import ZoneInfo
from utils import config
from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING, BEAR_SIGNALS_ENABLED
from utils.time_helpers import _now_et
from app.data.data_manager import data_manager
from app.validation.validation import get_regime_filter
from app.validation.cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from app.filters.vwap_gate import compute_vwap, passes_vwap_gate
from app.core.arm_signal import arm_ticker
from app.core.signal_scorecard import build_scorecard, SCORECARD_GATE_MIN
from app.analytics.cooldown_tracker import is_on_cooldown  # set_cooldown removed — arm_ticker handles it
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


def _resample_bars(bars_1m: list, minutes: int) -> list:
    """Resample 1m bars into higher-timeframe buckets."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for b in bars_1m:
        dt = b["datetime"]
        floored = dt.replace(
            minute=(dt.minute // minutes) * minutes,
            second=0, microsecond=0
        )
        buckets[floored].append(b)
    result = []
    for ts in sorted(buckets):
        bucket = buckets[ts]
        result.append({
            "datetime": ts,
            "open":   bucket[0]["open"],
            "high":   max(b["high"] for b in bucket),
            "low":    min(b["low"]  for b in bucket),
            "close":  bucket[-1]["close"],
            "volume": sum(b["volume"] for b in bucket),
        })
    return result


def _run_signal_pipeline(
    ticker, direction, zone_low, zone_high,
    or_high_ref, or_low_ref, signal_type,
    bars_session, breakout_idx,
    bos_confirmation=None,
    bos_candle_type=None,
    spy_regime=None,
    skip_cfw6_confirmation=False,
    options_rec=None,           # FIX B: was required; all callers omit it
    **_unused_kwargs,           # FIX A: absorb legacy kwargs (state=, get_ticker_screener_metadata=)
):
    """
    Core CFW6 signal pipeline.

    Returns:
        True  — pipeline ran to completion and arm_ticker() was called
        False — signal was dropped by any upstream gate

    Gate order:
      1. TIME gate (< 11:00 AM ET)
      2. RVOL floor gate
      3. RVOL ceiling gate
      4. VWAP gate
      5. Dead zone gate
      6. GEX pin gate
      7. Cooldown gate
      8. CFW6 confirmation (skipped for INTRADAY / VWAP-reclaim paths)
      9. MTF trend bias (counter-trend rejected if RVOL < 1.8x)
     10. SMC delta / Sweep / OB enrichment
     11. SignalScorecard (gate: 60 pts)
     12. compute_stop_and_targets() — None return drops signal cleanly
     13. arm_ticker() — all 13 required args supplied
    """
    # ── 1. RVOL fetch ──────────────────────────────────────────────────────────
    try:
        rvol = data_manager.get_rvol(ticker) or 1.0
    except Exception:
        rvol = 1.0

    # ── 2. TIME gate ───────────────────────────────────────────────────────────
    now_et = _now_et()
    if now_et.time() > time(11, 0):
        logger.info(
            f"[{ticker}] ⛔ TIME GATE: {now_et.strftime('%H:%M')} > 11:00 AM — signal dropped"
        )
        return False

    # ── 3. RVOL floor ──────────────────────────────────────────────────────────
    if rvol < RVOL_SIGNAL_GATE:
        logger.info(
            f"[{ticker}] ⛔ RVOL GATE: {rvol:.2f}x < {RVOL_SIGNAL_GATE}x floor — signal dropped"
        )
        return False

    # ── 4. RVOL ceiling ────────────────────────────────────────────────────────
    if rvol >= RVOL_CEILING:
        logger.info(
            f"[{ticker}] ⛔ RVOL CEILING: {rvol:.2f}x >= {RVOL_CEILING}x — signal dropped"
        )
        return False

    # ── 5. VWAP gate ───────────────────────────────────────────────────────────
    vwap_val    = compute_vwap(bars_session)
    entry_price = bars_session[-1]["close"]
    vwap_passed = passes_vwap_gate(entry_price, vwap_val, direction)
    if not vwap_passed:
        logger.info(
            f"[{ticker}] ⛔ VWAP GATE: price ${entry_price:.2f} failed vwap=${vwap_val:.2f}"
        )
        return False

    # ── 6. Dead zone ───────────────────────────────────────────────────────────
    if is_dead_zone(now_et):
        logger.info(f"[{ticker}] ⛔ DEAD ZONE: {now_et.strftime('%H:%M')} — signal dropped")
        return False

    # ── 7. GEX pin zone ────────────────────────────────────────────────────────
    if is_in_gex_pin_zone(ticker):
        logger.info(f"[{ticker}] ⛔ GEX PIN ZONE — signal dropped")
        return False

    # ── 8. Cooldown ────────────────────────────────────────────────────────────
    _cd_blocked, _cd_reason = is_on_cooldown(ticker, direction)
    if _cd_blocked:
        logger.info(f"[{ticker}] ⛔ COOLDOWN: {_cd_reason} — signal dropped")
        return False

    # ── 9. CFW6 confirmation ───────────────────────────────────────────────────
    if not skip_cfw6_confirmation:
        confirmed, confirmation_meta = wait_for_confirmation(
            ticker, bars_session, breakout_idx, direction, zone_low, zone_high
        )
        if not confirmed:
            logger.info(f"[{ticker}] ⛔ CFW6 confirmation failed")
            return False
        grade, confidence_base = grade_signal_with_confirmations(confirmation_meta)
    else:
        grade            = "A"
        confidence_base  = 0.65
        confirmation_meta = {}

    # ── 10. MTF trend bias ────────────────────────────────────────────────────
    _mtf_bias_adj = 0.0
    if getattr(config, "MTF_TREND_ENABLED", True):
        try:
            bars_1m_raw = (
                data_manager.get_1m_bars(ticker)
                if hasattr(data_manager, "get_1m_bars") else []
            )
            if bars_1m_raw:  # guard None / empty
                _bars_15m = _resample_bars(bars_1m_raw, 15)
                if len(_bars_15m) >= 2:
                    _is_aligned = (
                        (direction == "bull" and _bars_15m[-1]["close"] > _bars_15m[-1]["open"])
                        or (direction == "bear" and _bars_15m[-1]["close"] < _bars_15m[-1]["open"])
                    )
                    if _is_aligned:
                        _mtf_bias_adj = 0.05
                        logger.info(f"[{ticker}] ✅ MTF-TREND: Aligned — +5% bias")
                    else:
                        if rvol < 1.8:
                            logger.info(
                                f"[{ticker}] ⛔ MTF-RVOL GATE: Counter-trend "
                                f"rvol {rvol:.2f}x < 1.8x required — signal dropped"
                            )
                            return False
                        logger.info(
                            f"[{ticker}] ⚠️ MTF-TREND: Counter-trend — "
                            f"High RVOL {rvol:.2f}x overrides"
                        )
        except Exception as _mtf_err:
            logger.warning(f"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}")

    # ── 11a. SMC enrichment ────────────────────────────────────────────────────
    try:
        from app.filters.sd_zone_confluence import get_smc_delta
        smc_delta = get_smc_delta(ticker, direction)
    except Exception:
        smc_delta = None

    # ── 11b. Liquidity sweep ───────────────────────────────────────────────────
    try:
        from app.filters.liquidity_sweep import has_sweep
        sweep_detected = has_sweep(ticker, bars_session, direction)
    except Exception:
        sweep_detected = False

    # ── 11c. Order block retest ────────────────────────────────────────────────
    try:
        from app.filters.order_block_cache import has_ob_retest
        ob_detected = has_ob_retest(ticker, bars_session, direction)
    except Exception:
        ob_detected = False

    # ── 12. SignalScorecard ────────────────────────────────────────────────────
    _sc = build_scorecard(
        ticker=ticker,
        direction=direction,
        grade=grade,
        options_rec=options_rec,
        mtf_trend_boost=_mtf_bias_adj,
        smc_delta=smc_delta,
        vwap_passed=vwap_passed,
        sweep_detected=sweep_detected,
        ob_detected=ob_detected,
        spy_regime=spy_regime,
        rvol=rvol,
    )

    if _sc.score < SCORECARD_GATE_MIN:
        logger.info(
            f"[{ticker}] ⛔ SCORECARD-GATE: {_sc.score:.1f} "
            f"< {SCORECARD_GATE_MIN} — signal dropped"
        )
        return False

    # Confidence mapped linearly from scorecard score (60–85+ → 0.60–0.85)
    _confidence = min(0.85, max(0.60, _sc.score / 100.0))
    logger.info(
        f"[{ticker}] ✅ SCORECARD PASS: {_sc.score:.1f}pts "
        f"confidence={_confidence:.2f} grade={grade}"
    )

    # ── 13. Stop / Targets ────────────────────────────────────────────────────
    # Passing or_high=0 / or_low=0 is safe — trade_calculator M8 fix skips
    # the OR boundary comparison when the range has not formed.
    stop_price, t1, t2 = compute_stop_and_targets(
        bars=bars_session,
        direction=direction,
        or_high=or_high_ref or 0.0,
        or_low=or_low_ref or 0.0,
        entry_price=entry_price,
        grade=grade,
    )

    if stop_price is None:
        # trade_calculator FIX 10.C-4: stop at/above entry (bull) or at/below
        # entry (bear) — A+ high-vol tight-OR tape. Drop cleanly.
        logger.info(
            f"[{ticker}] ⛔ STOP-INVALID: compute_stop_and_targets returned None "
            f"(entry=${entry_price:.2f} grade={grade} direction={direction}) — signal dropped"
        )
        return False

    # ── 14. Arm ───────────────────────────────────────────────────────────────
    # arm_ticker() guards all its own failure paths (stop tightness, position
    # manager rejection, Discord errors) and logs them. It also calls
    # set_cooldown() internally — do NOT call it here (FIX C).
    # arm_ticker() has no return statement (returns None implicitly) —
    # we return True to signal pipeline completion to the caller (FIX D).
    arm_ticker(
        ticker=ticker,
        direction=direction,
        zone_low=zone_low,
        zone_high=zone_high,
        or_low=or_low_ref or 0.0,
        or_high=or_high_ref or 0.0,
        entry_price=entry_price,
        stop_price=stop_price,
        t1=t1,
        t2=t2,
        confidence=_confidence,
        grade=grade,
        options_rec=options_rec,
        signal_type=signal_type,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type,
    )
    return True  # FIX D: arm_ticker returns None; pipeline completion = True
