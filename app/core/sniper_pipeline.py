# Phase 1.38d-fix-4 — March 30 2026
"""
app/core/sniper_pipeline.py — CFW6 Signal Pipeline

FIX HISTORY (2026-04-01):

  P3-3: Wired CONFIDENCE_ABSOLUTE_FLOOR into confidence gate (gate 12).
    CONFIDENCE_ABSOLUTE_FLOOR was defined in utils/config.py (0.55) but
    never imported or referenced in this file. The confidence mapping at
    gate 12 used a hardcoded max(0.60, ...) — making the config value a
    dead constant and applying a stricter floor (0.60) than intended (0.55).
    Fixed: import CONFIDENCE_ABSOLUTE_FLOOR from utils.config and replace
    the hardcoded 0.60 with max(CONFIDENCE_ABSOLUTE_FLOOR, ...) so the
    floor is tunable in one place and reflects the documented intent.

  BUG-GEX-1: Gate 7 called is_in_gex_pin_zone(ticker) with a ticker string.
    is_in_gex_pin_zone() signature is (entry_price, options_rec) — passing
    ticker caused a silent type mismatch: abs(str - float) raises TypeError
    which was swallowed by the except-pass inside the gate, so it always
    returned (False, "gex_pin_gate error") and NEVER blocked a signal.
    Fixed: is_in_gex_pin_zone(entry_price, options_rec) with correct args.
    Both were already in scope (entry_price computed at gate 5,
    options_rec is a pipeline parameter).

  BUG-DZ-1: Gate 6 called is_dead_zone(now_et) with a timestamp argument.
    is_dead_zone() signature is (direction, spy_regime) — the timestamp arg
    caused a silent type mismatch: 'direction' received a datetime object,
    the string comparisons always failed, and the gate NEVER fired.
    Fixed: is_dead_zone(direction, spy_regime) with correct args.
    spy_regime was already available in scope — it just was not forwarded.

FIX HISTORY (2026-03-31):

  BUG-SP-3: Removed unused `BEAR_SIGNALS_ENABLED` import.
    Was imported at module scope but never referenced anywhere in the file.
    Dead import removed — keeps the import block clean and avoids confusion
    about whether bear-signal gating is active here (it is not; it lives in
    sniper.py at the process_ticker() call site).

FIX HISTORY (2026-03-30):

  BUG-SP-1: TIME gate moved above RVOL fetch.
    RVOL was fetched from data_manager before the TIME gate ran, meaning
    every post-11am signal attempt wasted a data_manager.get_rvol() call
    before being killed. TIME gate now runs first — zero DB/cache work
    on rejected time-window signals. Gate order comment updated to match.

  BUG-SP-2: confidence_base from grade_signal_with_confirmations() wired
    into build_scorecard() as cfw6_confidence_base parameter.
    Previously, confidence_base was computed and immediately discarded —
    the final confidence used by arm_ticker() was derived solely from the
    scorecard score (min 0.60, max 0.85). CFW6 confirmation quality now
    contributes to scoring. signal_scorecard.py updated to accept and
    score the new parameter (max +10pts for confidence_base >= 0.80,
    scaled linearly down to 0pts for confidence_base <= 0.50).

FIX HISTORY (2026-03-27):

  FIX #53: Removed local _resample_bars() duplicate.
    utils/bar_utils.py already defines resample_bars() (the canonical version,
    added in Issue #3). sniper.py had its own _resample_bars() and
    sniper_pipeline.py had another copy — three identical implementations.
    Both now import from utils.bar_utils. The local copy here is removed.

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
from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING, CONFIDENCE_ABSOLUTE_FLOOR
from utils.time_helpers import _now_et
from utils.bar_utils import resample_bars as _resample_bars  # FIX #53: was a local duplicate
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

    Gate order (BUG-SP-1 fix: TIME gate runs before any data fetch):
      1. TIME gate (< 11:00 AM ET)          <- runs first, no data fetch wasted
      2. RVOL fetch
      3. RVOL floor gate
      4. RVOL ceiling gate
      5. VWAP gate
      6. Dead zone gate  (BUG-DZ-1 fix: was passing now_et instead of direction+spy_regime)
      7. GEX pin gate    (BUG-GEX-1 fix: was passing ticker instead of entry_price+options_rec)
      8. Cooldown gate
      9. CFW6 confirmation (skipped for INTRADAY / VWAP-reclaim paths)
     10. MTF trend bias (counter-trend rejected if RVOL < 1.8x)
     11. SMC delta / Sweep / OB enrichment
     12. SignalScorecard (gate: 60 pts) — now includes CFW6 confidence_base (BUG-SP-2)
     13. compute_stop_and_targets() — None return drops signal cleanly
     14. arm_ticker() — all required args supplied
    """
    # -- 1. TIME gate (BUG-SP-1: moved above RVOL fetch) ----------------------
    now_et = _now_et()
    if now_et.time() > time(11, 0):
        logger.info(
            f"[{ticker}] TIME GATE: {now_et.strftime('%H:%M')} > 11:00 AM — signal dropped"
        )
        return False

    # -- 2. RVOL fetch --------------------------------------------------------
    try:
        rvol = data_manager.get_rvol(ticker) or 1.0
    except Exception:
        rvol = 1.0

    # -- 3. RVOL floor --------------------------------------------------------
    if rvol < RVOL_SIGNAL_GATE:
        logger.info(
            f"[{ticker}] RVOL GATE: {rvol:.2f}x < {RVOL_SIGNAL_GATE}x floor — signal dropped"
        )
        return False

    # -- 4. RVOL ceiling ------------------------------------------------------
    if rvol >= RVOL_CEILING:
        logger.info(
            f"[{ticker}] RVOL CEILING: {rvol:.2f}x >= {RVOL_CEILING}x — signal dropped"
        )
        return False

    # -- 5. VWAP gate ---------------------------------------------------------
    vwap_val    = compute_vwap(bars_session)
    entry_price = bars_session[-1]["close"]
    vwap_passed = passes_vwap_gate(entry_price, vwap_val, direction)
    if not vwap_passed:
        logger.info(
            f"[{ticker}] VWAP GATE: price ${entry_price:.2f} failed vwap=${vwap_val:.2f}"
        )
        return False

    # -- 6. Dead zone (BUG-DZ-1: was is_dead_zone(now_et) — wrong signature) --
    _dz_blocked, _dz_reason = is_dead_zone(direction, spy_regime or {})
    if _dz_blocked:
        logger.info(f"[{ticker}] DEAD ZONE: {_dz_reason} — signal dropped")
        return False

    # -- 7. GEX pin zone (BUG-GEX-1: was is_in_gex_pin_zone(ticker)) ---------
    # entry_price computed at gate 5; options_rec is a pipeline parameter.
    _gex_blocked, _gex_reason = is_in_gex_pin_zone(entry_price, options_rec or {})
    if _gex_blocked:
        logger.info(f"[{ticker}] GEX PIN ZONE: {_gex_reason} — signal dropped")
        return False

    # -- 8. Cooldown ----------------------------------------------------------
    _cd_blocked, _cd_reason = is_on_cooldown(ticker, direction)
    if _cd_blocked:
        logger.info(f"[{ticker}] COOLDOWN: {_cd_reason} — signal dropped")
        return False

    # -- 9. CFW6 confirmation -------------------------------------------------
    if not skip_cfw6_confirmation:
        confirmed, confirmation_meta = wait_for_confirmation(
            ticker, bars_session, breakout_idx, direction, zone_low, zone_high
        )
        if not confirmed:
            logger.warning(f"[{ticker}] CFW6 confirmation failed")
            return False
        grade, confidence_base = grade_signal_with_confirmations(confirmation_meta)
    else:
        grade             = "A"
        confidence_base   = 0.65
        confirmation_meta = {}

    # -- 10. MTF trend bias ---------------------------------------------------
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
                        logger.info(f"[{ticker}] MTF-TREND: Aligned — +5% bias")
                    else:
                        if rvol < 1.8:
                            logger.info(
                                f"[{ticker}] MTF-RVOL GATE: Counter-trend "
                                f"rvol {rvol:.2f}x < 1.8x required — signal dropped"
                            )
                            return False
                        logger.info(
                            f"[{ticker}] MTF-TREND: Counter-trend — "
                            f"High RVOL {rvol:.2f}x overrides"
                        )
        except Exception as _mtf_err:
            logger.warning(f"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}")

    # -- 11a. SMC enrichment --------------------------------------------------
    try:
        from app.filters.sd_zone_confluence import get_smc_delta
        smc_delta = get_smc_delta(ticker, direction)
    except Exception:
        smc_delta = None

    # -- 11b. Liquidity sweep -------------------------------------------------
    try:
        from app.filters.liquidity_sweep import has_sweep
        sweep_detected = has_sweep(ticker, bars_session, direction)
    except Exception:
        sweep_detected = False

    # -- 11c. Order block retest ----------------------------------------------
    try:
        from app.filters.order_block_cache import has_ob_retest
        ob_detected = has_ob_retest(ticker, bars_session, direction)
    except Exception:
        ob_detected = False

    # -- 12. SignalScorecard --------------------------------------------------
    # BUG-SP-2: confidence_base from CFW6 now passed in — no longer discarded
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
        cfw6_confidence_base=confidence_base,  # BUG-SP-2: was silently discarded
    )

    if _sc.score < SCORECARD_GATE_MIN:
        logger.info(
            f"[{ticker}] SCORECARD-GATE: {_sc.score:.1f} "
            f"< {SCORECARD_GATE_MIN} — signal dropped"
        )
        return False

    # P3-3: floor from config.CONFIDENCE_ABSOLUTE_FLOOR (0.55), not hardcoded 0.60.
    # Previously max(0.60, ...) was inconsistent with the config value and made
    # CONFIDENCE_ABSOLUTE_FLOOR a dead constant. Now tunable in one place.
    _confidence = min(0.85, max(CONFIDENCE_ABSOLUTE_FLOOR, _sc.score / 100.0))
    logger.info(
        f"[{ticker}] SCORECARD PASS: {_sc.score:.1f}pts "
        f"confidence={_confidence:.2f} grade={grade} cfw6_base={confidence_base:.2f}"
    )

    # -- 13. Stop / Targets ---------------------------------------------------
    stop_price, t1, t2 = compute_stop_and_targets(
        bars=bars_session,
        direction=direction,
        or_high=or_high_ref or 0.0,
        or_low=or_low_ref or 0.0,
        entry_price=entry_price,
        grade=grade,
    )

    if stop_price is None:
        logger.info(
            f"[{ticker}] STOP-INVALID: compute_stop_and_targets returned None "
            f"(entry=${entry_price:.2f} grade={grade} direction={direction}) — signal dropped"
        )
        return False

    # -- 14. Arm --------------------------------------------------------------
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
