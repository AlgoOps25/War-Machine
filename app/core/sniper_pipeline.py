# Audit fixes applied March 26, 2026 — Phase 1.38d-fix
"""
sniper_pipeline.py - CFW6 Signal Pipeline
Phase 1.38d-fix: Corrected build_scorecard call (all required args), removed
orphan run_signal_pipeline stub, fixed _sc.confidence AttributeError.
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
from app.analytics.cooldown_tracker import is_on_cooldown, set_cooldown
from app.options.dte_selector import get_ideal_dte
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


def _resample_bars(bars_1m: list, minutes: int) -> list:
    """Resample 1m bars into a higher timeframe bucket (Hoisted: 19.H-6)."""
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
            "open": bucket[0]["open"],
            "high": max(b["high"] for b in bucket),
            "low": min(b["low"] for b in bucket),
            "close": bucket[-1]["close"],
            "volume": sum(b["volume"] for b in bucket),
        })
    return result


def _run_signal_pipeline(
    ticker, direction, zone_low, zone_high,
    or_high_ref, or_low_ref, signal_type,
    bars_session, breakout_idx,
    bos_confirmation=None, bos_candle_type=None, spy_regime=None,
    skip_cfw6_confirmation=False,
    get_ticker_screener_metadata=None,
    state=None,
    options_rec=None,
):
    """
    Core CFW6 signal pipeline — Phase 1.38d-fix.

    FIX 1: build_scorecard now receives all required args (smc_delta,
            vwap_passed, sweep_detected, ob_detected, spy_regime, rvol).
    FIX 2: Removed _sc.confidence access — SignalScorecard has no confidence
            field; confidence is derived from scorecard score.
    FIX 3: grade passed from grade_signal_with_confirmations, not hardcoded.
    FIX 4: bars_1m_raw guard before MTF resample (None / empty check).
    FIX 5: is_on_cooldown returns (bool, reason) tuple — unpack correctly
            and pass direction arg. set_cooldown also requires direction.
    """
    # ── RVOL fetch ───────────────────────────────────────────────────────────
    try:
        rvol = data_manager.get_rvol(ticker) or 1.0
    except Exception:
        rvol = 1.0

    # ── Hard filters (Phase 1.38c/d) ────────────────────────────────────────
    now_et = _now_et()
    if now_et.time() > time(11, 0):
        logger.info(f"[{ticker}] 🚫 TIME GATE: {now_et.strftime('%H:%M')} > 11:00 AM — signal dropped")
        return False

    if rvol < RVOL_SIGNAL_GATE:
        logger.info(f"[{ticker}] 🚫 RVOL GATE: {rvol:.2f}x < {RVOL_SIGNAL_GATE}x floor — signal dropped")
        return False

    if rvol >= RVOL_CEILING:
        logger.info(f"[{ticker}] 🚫 RVOL CEILING: {rvol:.2f}x >= {RVOL_CEILING}x — signal dropped")
        return False

    # ── VWAP gate ────────────────────────────────────────────────────────────
    vwap_val = compute_vwap(bars_session)
    entry_price = bars_session[-1]["close"]
    vwap_passed = passes_vwap_gate(entry_price, vwap_val, direction)
    if not vwap_passed:
        logger.info(f"[{ticker}] 🚫 VWAP GATE: price ${entry_price:.2f} failed vwap=${vwap_val:.2f}")
        return False

    # ── Dead zone / GEX pin gate ──────────────────────────────────────────────
    if is_dead_zone(now_et):
        logger.info(f"[{ticker}] 🚫 DEAD ZONE: {now_et.strftime('%H:%M')} — signal dropped")
        return False

    if is_in_gex_pin_zone(ticker):
        logger.info(f"[{ticker}] 🚫 GEX PIN ZONE — signal dropped")
        return False

    # ── Cooldown (FIX 5: unpack tuple, pass direction) ────────────────────────
    _cd_blocked, _cd_reason = is_on_cooldown(ticker, direction)
    if _cd_blocked:
        logger.info(f"[{ticker}] 🚫 COOLDOWN: {_cd_reason} — signal dropped")
        return False

    # ── CFW6 confirmation ──────────────────────────────────────────────────────
    if not skip_cfw6_confirmation:
        confirmed, confirmation_meta = wait_for_confirmation(
            ticker, bars_session, breakout_idx, direction, zone_low, zone_high
        )
        if not confirmed:
            logger.info(f"[{ticker}] 🚫 CFW6 confirmation failed")
            return False
        grade, confidence_base = grade_signal_with_confirmations(confirmation_meta)
    else:
        grade = "A"
        confidence_base = 0.65
        confirmation_meta = {}

    # ── MTF trend bias (Phase 1.38d) ──────────────────────────────────────────
    _mtf_bias_adj = 0.0
    if getattr(config, "MTF_TREND_ENABLED", True):
        try:
            bars_1m_raw = data_manager.get_1m_bars(ticker) if hasattr(data_manager, 'get_1m_bars') else []
            if bars_1m_raw:  # FIX 4: guard None/empty
                _bars_15m = _resample_bars(bars_1m_raw, 15)
                if len(_bars_15m) >= 2:
                    _is_aligned = (
                        (direction == 'bull' and _bars_15m[-1]['close'] > _bars_15m[-1]['open']) or
                        (direction == 'bear' and _bars_15m[-1]['close'] < _bars_15m[-1]['open'])
                    )
                    if _is_aligned:
                        _mtf_bias_adj = 0.05
                        logger.info(f"[{ticker}] ✅ MTF-TREND: Aligned — +5% bias")
                    else:
                        if rvol < 1.8:
                            logger.info(
                                f"[{ticker}] 🚫 MTF-RVOL GATE: Counter-trend "
                                f"rvol {rvol:.2f}x < 1.8x required — signal dropped"
                            )
                            return False
                        else:
                            logger.info(
                                f"[{ticker}] ⚠️ MTF-TREND: Counter-trend — "
                                f"High RVOL {rvol:.2f}x overrides"
                            )
        except Exception as _mtf_err:
            logger.warning(f"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}")

    # ── SMC enrichment delta ─────────────────────────────────────────────────
    try:
        from app.filters.sd_zone_confluence import get_smc_delta
        smc_delta = get_smc_delta(ticker, direction)
    except Exception:
        smc_delta = None

    # ── Sweep / OB detection ─────────────────────────────────────────────────
    try:
        from app.filters.liquidity_sweep import has_sweep
        sweep_detected = has_sweep(ticker, bars_session, direction)
    except Exception:
        sweep_detected = False

    try:
        from app.filters.order_block_cache import has_ob_retest
        ob_detected = has_ob_retest(ticker, bars_session, direction)
    except Exception:
        ob_detected = False

    # ── Scorecard (Phase 1.38d — FIX 1: all required args supplied) ──────────
    _sc = build_scorecard(
        ticker=ticker,
        direction=direction,
        grade=grade,              # FIX 3: real grade, not hardcoded "A"
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
            f"[{ticker}] 🚫 SCORECARD-GATE: {_sc.score:.1f} "
            f"< {SCORECARD_GATE_MIN} — signal dropped"
        )
        return False

    # ── Confidence from scorecard score (FIX 2: no .confidence attr) ─────────
    # Map 60-85+ pts linearly to 0.60-0.85 confidence
    _confidence = min(0.85, max(0.60, _sc.score / 100.0))

    logger.info(
        f"[{ticker}] ✅ SCORECARD PASS: {_sc.score:.1f}pts "
        f"confidence={_confidence:.2f} grade={grade}"
    )

    # ── Arm the ticker ────────────────────────────────────────────────────────
    armed = arm_ticker(
        ticker=ticker,
        direction=direction,
        zone_low=zone_low,
        zone_high=zone_high,
        entry_price=entry_price,
        confidence=_confidence,
        options_rec=options_rec,
    )
    if armed:
        set_cooldown(ticker, direction)  # FIX 5: pass direction
    return armed
