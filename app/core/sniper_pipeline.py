"""
sniper_pipeline.py — CFW6 Signal Pipeline
Extracted from sniper.py to keep that file under safe API size limits.
All gate logic lives here: cooldown → RVOL → options → volume profile →
confirmation → entry timing → VWAP → MTF bias → confidence → scorecard → arm.
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
from app.ai.ai_learning import compute_confidence
from app.options.dte_selector import get_ideal_dte
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

# ── Optional module flags (resolved at import time) ──────────────────────────
try:
    from app.signals.signal_analytics import signal_tracker
    from app.analytics.performance_monitor import performance_monitor
    PHASE_4_ENABLED = True
except ImportError:
    signal_tracker = None
    performance_monitor = None
    PHASE_4_ENABLED = False

try:
    from app.analytics.cooldown_tracker import cooldown_tracker
    from app.analytics.grade_gate_tracker import grade_gate_tracker
    TRACKERS_ENABLED = True
except ImportError:
    cooldown_tracker = None
    grade_gate_tracker = None
    TRACKERS_ENABLED = False

try:
    from app.validation.volume_profile import get_volume_analyzer
    VOLUME_PROFILE_ENABLED = True
except ImportError:
    VOLUME_PROFILE_ENABLED = False
    def get_volume_analyzer(): return None

try:
    from app.validation.entry_timing import get_entry_timing_validator
    ENTRY_TIMING_ENABLED = True
except ImportError:
    ENTRY_TIMING_ENABLED = False
    def get_entry_timing_validator(): return None

try:
    from app.filters.order_block_cache import (
        identify_order_block, cache_order_block, apply_ob_retest_boost,
    )
    ORDER_BLOCK_ENABLED = True
except ImportError:
    ORDER_BLOCK_ENABLED = False
    def identify_order_block(bars, bos_idx, direction): return None
    def cache_order_block(ticker, ob): pass
    def apply_ob_retest_boost(ticker, entry_price, direction, confidence): return confidence, None

try:
    from app.filters.liquidity_sweep import apply_sweep_boost
    LIQUIDITY_SWEEP_ENABLED = True
except ImportError:
    LIQUIDITY_SWEEP_ENABLED = False
    def apply_sweep_boost(ticker, bars, direction, or_high, or_low, confidence, vwap=0.0):
        return confidence, None

try:
    from app.filters.sd_zone_confluence import apply_sd_confluence_boost
    SD_ZONE_ENABLED = True
except ImportError:
    SD_ZONE_ENABLED = False
    def apply_sd_confluence_boost(ticker, entry_price, direction, confidence): return confidence, None

try:
    from app.mtf.mtf_integration import enhance_signal_with_mtf, run_mtf_trend_step
    MTF_ENABLED = True
    MTF_TREND_ENABLED = True
except ImportError:
    MTF_ENABLED = False
    MTF_TREND_ENABLED = False
    def enhance_signal_with_mtf(*a, **kw):
        return {'enabled': False, 'convergence': False, 'boost': 0.0, 'reason': 'MTF disabled', 'timeframes': []}
    def run_mtf_trend_step(ticker, direction, entry_price, confidence, signal_data):
        return confidence, signal_data

try:
    from app.mtf.smc_engine import enrich_signal_with_smc
    SMC_ENRICHMENT_ENABLED = True
except ImportError:
    SMC_ENRICHMENT_ENABLED = False
    def enrich_signal_with_smc(ticker, bars, signal_data): return signal_data

try:
    from app.filters.mtf_bias import mtf_bias_engine
    MTF_BIAS_ENABLED = True
except ImportError:
    MTF_BIAS_ENABLED = False
    mtf_bias_engine = None

try:
    from app.validation.hourly_gate import get_hourly_confidence_multiplier, get_current_hour_context
    HOURLY_GATE_ENABLED = True
except ImportError:
    HOURLY_GATE_ENABLED = False
    def get_hourly_confidence_multiplier(): return 1.0
    def get_current_hour_context():
        return {'hour': 0, 'win_rate': None, 'multiplier': 1.0, 'classification': 'no_data', 'trades': 0}

try:
    from app.core.gate_stats import _track_gate_result
except ImportError:
    def _track_gate_result(grade, signal_type, confidence, passed): pass

try:
    from app.core.sniper_log import _track_validation_call
except ImportError:
    def _track_validation_call(ticker, direction, price): return False

try:
    from utils.production_helpers import _fetch_data_safe
    PRODUCTION_HELPERS_ENABLED = True
except ImportError:
    PRODUCTION_HELPERS_ENABLED = False

# Resample helper (used by MTF bias gate)
from collections import defaultdict

def _resample_bars(bars_1m: list, minutes: int) -> list:
    buckets = defaultdict(list)
    for b in bars_1m:
        dt = b["datetime"]
        floored = dt.replace(minute=(dt.minute // minutes) * minutes, second=0, microsecond=0)
        buckets[floored].append(b)
    result = []
    for ts in sorted(buckets):
        bucket = buckets[ts]
        result.append({
            "datetime": ts,
            "open":     bucket[0]["open"],
            "high":     max(b["high"]   for b in bucket),
            "low":      min(b["low"]    for b in bucket),
            "close":    bucket[-1]["close"],
            "volume":   sum(b["volume"] for b in bucket),
        })
    return result


def _mult_to_adjustment(multiplier: float, base_conf: float) -> float:
    if multiplier >= 1.0:
        return min((multiplier - 1.0) * base_conf * 0.75, base_conf * 0.10)
    else:
        return max((multiplier - 1.0) * base_conf * 1.00, base_conf * -0.10)


def _run_signal_pipeline(
    ticker, direction, zone_low, zone_high,
    or_high_ref, or_low_ref, signal_type,
    bars_session, breakout_idx,
    bos_confirmation=None, bos_candle_type=None, spy_regime=None,
    skip_cfw6_confirmation=False,
    get_ticker_screener_metadata=None,
    state=None,
):
    """
    Full CFW6 signal pipeline. Called from sniper.py after BOS+FVG detection.

    Parameters
    ----------
    get_ticker_screener_metadata : callable
        Passed in from sniper.py so this module doesn't need to import it.
    state : ThreadSafeState
        Passed in from sniper.py to avoid circular import.
    """
    if get_ticker_screener_metadata is None:
        def get_ticker_screener_metadata(t): return {'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}

    # ── DB-persisted cooldown gate (restart-safe) ─────────────────────────────
    try:
        blocked, cooldown_reason = is_on_cooldown(ticker, direction)
        if blocked:
            logger.info(f"[{ticker}] 🚫 SIGNAL COOLDOWN: {cooldown_reason}")
            return False
        if direction == 'bear' and not config.BEAR_SIGNALS_ENABLED:
            logger.info(f"[{ticker}] 🚫 BEAR SUPPRESSED: BEAR_SIGNALS_ENABLED=False")
            return False
    except Exception as _cd_err:
        logger.info(f"[{ticker}] [COOLDOWN] Check error (non-fatal): {_cd_err}")

    # In-memory analytics cooldown (non-blocking, reporting only)
    if TRACKERS_ENABLED and cooldown_tracker:
        if cooldown_tracker.is_in_cooldown(ticker):
            remaining = cooldown_tracker.get_cooldown_remaining(ticker)
            logger.info(f"[{ticker}] 🚫 ANALYTICS COOLDOWN: {remaining:.0f}s remaining — signal dropped")
            return False

    # ── RVOL gate (Phase 1.36 + 1.38b ceiling) ───────────────────────────────
    _signal_rvol = 0.0
    _meta = get_ticker_screener_metadata(ticker)  # single call — reused below
    try:
        _signal_rvol = _meta.get('rvol', 0.0)
        if _signal_rvol < RVOL_SIGNAL_GATE and _signal_rvol < 3.0:
            logger.info(f"[{ticker}] 🚫 RVOL GATE: {_signal_rvol:.2f}x < {RVOL_SIGNAL_GATE}x minimum — signal dropped")
            return False
        logger.info(f"[{ticker}] ✅ RVOL GATE: {_signal_rvol:.2f}x — passed")
        if _signal_rvol >= RVOL_CEILING:
            logger.info(f"[{ticker}] 🚫 RVOL CEILING: {_signal_rvol:.2f}x >= {RVOL_CEILING}x — signal dropped")
            return False
    except Exception as _rvol_err:
        logger.info(f"[{ticker}] RVOL gate error (non-fatal): {_rvol_err}")

    # ── Options pre-gate (Step 6.5) ───────────────────────────────────────────
    _pre_options_data = None
    try:
        from app.validation.greeks_precheck import validate_signal_greeks
        _proxy_entry = bars_session[-1]["close"]
        greeks_valid, greeks_reason = validate_signal_greeks(ticker, direction, _proxy_entry)
        logger.info(f"[{ticker}] {'✅' if greeks_valid else '❌'} GREEKS-GATE: {greeks_reason}")
        if not greeks_valid:
            logger.info(f"[{ticker}] 🚫 Signal dropped: Greeks pre-check failed (HARD mode)")
            return False
        from app.validation.validation import get_options_filter
        options_filter = get_options_filter()
        _is_explosive = _meta.get('qualified', False)
        try:
            _vix = get_regime_filter().get_regime_state().vix
        except Exception:
            _vix = 20.0
        _ideal_dte = get_ideal_dte(vix=_vix, ticker=ticker)
        _tradeable, _opts_data, _reason = options_filter.validate_signal_for_options(
            ticker, direction, _proxy_entry, _proxy_entry * 1.05,
            explosive_mover=_is_explosive, ideal_dte=_ideal_dte
        )
        _pre_options_data = _opts_data
        if not _tradeable:
            logger.info(f"[{ticker}] ❌ OPTIONS-GATE [FULL]: {_reason} — signal dropped")
            return False
        logger.info(f"[{ticker}] ✅ OPTIONS-GATE [FULL]: passed → proceeding to confirmation")
    except Exception as _gate_err:
        logger.info(f"[{ticker}] OPTIONS-GATE error (non-fatal): {_gate_err}")
        _pre_options_data = None

    # ── Volume profile (Step 6.6) ─────────────────────────────────────────────
    vp_boost = 0.0
    vp_bias = 'NEUTRAL'
    if VOLUME_PROFILE_ENABLED:
        try:
            analyzer = get_volume_analyzer()
            if analyzer:
                fvg_midpoint = (zone_low + zone_high) / 2.0
                is_valid, vp_reason, vp_data = analyzer.validate_entry(
                    ticker=ticker, direction=direction,
                    entry_price=fvg_midpoint, bars=bars_session
                )
                logger.info(f"[{ticker}] {'✅' if is_valid else '❌'} VOLUME PROFILE: {vp_reason}")
                if vp_data:
                    vp_boost = vp_data.get('confidence_boost', 0.0)
                    vp_bias  = vp_data.get('options_bias', 'NEUTRAL')
                    logger.info(
                        f"[{ticker}] VP Details: POC=${vp_data.get('poc', 0):.2f} | "
                        f"Distance={vp_data.get('distance_from_poc_pct', 0):.1%} | "
                        f"Volume Rank={vp_data.get('volume_rank', 'N/A')} | "
                        f"Bias={vp_bias} | Boost={vp_boost:+.2f}"
                    )
                if not is_valid:
                    logger.info(f"[{ticker}] 🚫 Signal dropped: Volume profile validation failed")
                    return False
        except Exception as vp_err:
            logger.info(f"[{ticker}] Volume profile validation error (non-fatal): {vp_err}")

    # ── CFW6 Confirmation (Step 7) ────────────────────────────────────────────
    if skip_cfw6_confirmation:
        entry_price  = bars_session[-1]["close"]
        base_grade   = bos_confirmation if bos_confirmation in ("A+", "A", "A-", "B+", "B") else "A-"
        confirm_idx  = len(bars_session) - 1
        confirm_type = bos_candle_type or "BOS+FVG"
        logger.info(f"[{ticker}] ✅ BOS CONFIRMATION (pre-confirmed): {base_grade} grade @ ${entry_price:.2f}")
    else:
        result = wait_for_confirmation(
            ticker, direction, (zone_low, zone_high), bars_session[breakout_idx]["datetime"]
        )
        found, entry_price, base_grade, confirm_idx, confirm_type = result
        if not found or base_grade == "reject":
            logger.info(f"[{ticker}] — No confirmation (found={found}, grade={base_grade})")
            return False
        logger.info(f"[{ticker}] ✅ CONFIRMATION: {base_grade} grade @ ${entry_price:.2f}")

    # ── Entry timing (Step 6.7) ───────────────────────────────────────────────
    if ENTRY_TIMING_ENABLED:
        try:
            timing_validator = get_entry_timing_validator()
            if timing_validator:
                is_valid, timing_reason, timing_data = timing_validator.validate_entry_time(
                    current_time=_now_et(), signal_type=signal_type, grade=base_grade
                )
                logger.info(f"[{ticker}] {'✅' if is_valid else '❌'} ENTRY TIMING: {timing_reason}")
                if timing_data:
                    logger.info(
                        f"[{ticker}] Timing Details: Hour={timing_data.get('hour')}:00 | "
                        f"Win Rate={timing_data.get('hour_win_rate', 0):.1%} | "
                        f"Quality={timing_data.get('session_quality', 'unknown')}"
                    )
                if not is_valid:
                    logger.info(f"[{ticker}] 🚫 Signal dropped: Entry timing validation failed")
                    return False
        except Exception as timing_err:
            logger.info(f"[{ticker}] Entry timing validation error (non-fatal): {timing_err}")

    # ── Order block cache ─────────────────────────────────────────────────────
    if ORDER_BLOCK_ENABLED:
        _ob = identify_order_block(bars_session, breakout_idx, direction)
        if _ob:
            cache_order_block(ticker, _ob)
            logger.info(f"[{ticker}] 📦 OB cached: ${_ob['ob_low']:.2f}–${_ob['ob_high']:.2f}")

    # ── VWAP gate ─────────────────────────────────────────────────────────────
    _vwap_val = compute_vwap(bars_session)
    vwap_passes, vwap_reason = passes_vwap_gate(bars_session, direction, entry_price, vwap=_vwap_val)
    if not vwap_passes:
        logger.info(f"[{ticker}] 🚫 VWAP GATE: {vwap_reason}")
        return False
    logger.info(f"[{ticker}] ✅ VWAP GATE: {vwap_reason}")

    # ── MTF Bias gate (1H + 15m top-down) ────────────────────────────────────
    _mtf_bias_adj = 0.0
    if MTF_BIAS_ENABLED and mtf_bias_engine:
        try:
            _bars_1m_raw = data_manager.get_bars_from_memory(ticker, limit=390)
            _bars_15m    = _resample_bars(_bars_1m_raw, 15)
            _bars_1h     = _resample_bars(_bars_1m_raw, 60)
            _mtf = mtf_bias_engine.evaluate(
                direction=direction, bars_1h=_bars_1h, bars_15m=_bars_15m, current_price=entry_price,
            )
            logger.info(f"[{ticker}] {'✅' if _mtf['pass'] else '🚫'} MTF BIAS: {_mtf['reason']}")
            mtf_bias_engine.record_stat(ticker, direction, _mtf)
            if not _mtf["pass"]:
                return False
            _mtf_bias_adj = _mtf["confidence_adj"]
        except Exception as _mtf_err:
            logger.info(f"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}")

    # ── Confirmation layers → final grade ────────────────────────────────────
    conf_result = grade_signal_with_confirmations(
        ticker=ticker, direction=direction, bars=bars_session,
        current_price=entry_price, breakout_idx=breakout_idx, base_grade=base_grade
    )
    if conf_result["final_grade"] == "reject":
        logger.info(f"[{ticker}] — Rejected by confirmation layers")
        return False
    final_grade = conf_result["final_grade"]

    # ── MTF Trend step (Step 8.5) ─────────────────────────────────────────────
    _mtf_trend_signal_data = {}
    base_confidence, _mtf_trend_signal_data = run_mtf_trend_step(
        ticker, direction, entry_price,
        compute_confidence(final_grade, "5m", ticker), _mtf_trend_signal_data
    )
    _mtf_trend_boost = _mtf_trend_signal_data.get('mtf_trend', {}).get('boost', 0.0)

    # ── SMC Enrichment (Step 8.6) ─────────────────────────────────────────────
    _smc_signal_data = dict(_mtf_trend_signal_data)
    _smc_signal_data.update({
        'direction':  direction,
        'bos_idx':    breakout_idx,
        'bos_price':  zone_low if direction == 'bull' else zone_high,
        'entry_type': signal_type,
    })
    _smc_signal_data = enrich_signal_with_smc(ticker, bars_session, _smc_signal_data)
    _smc_delta   = _smc_signal_data.get('smc', {}).get('total_confidence_delta', 0.0)
    _smc_summary = _smc_signal_data.get('smc', {}).get('smc_summary', '')
    if _smc_summary:
        logger.info(f"[{ticker}] 🔬 SMC: {_smc_summary} | conf_delta={_smc_delta:+.3f}")

    # ── MTF Convergence boost ─────────────────────────────────────────────────
    mtf_result = enhance_signal_with_mtf(ticker=ticker, direction=direction, bars_session=bars_session)
    if mtf_result['convergence']:
        logger.info(
            f"[{ticker}] ✅ MTF CONVERGENCE: "
            f"{mtf_result.get('convergence_score', 0):.1%} across "
            f"{', '.join(mtf_result.get('timeframes', []))} | Boost: +{mtf_result['boost']:.2%}"
        )
    else:
        logger.info(f"[{ticker}] MTF: {mtf_result['reason']}")

    stop_price, t1, t2 = compute_stop_and_targets(
        bars_session, direction, or_high_ref, or_low_ref, entry_price, grade=final_grade
    )

    # Phase 4 — signal generated tracking
    if PHASE_4_ENABLED and signal_tracker:
        try:
            signal_tracker.record_signal_generated(
                ticker=ticker, signal_type=signal_type, direction=direction,
                grade=final_grade, confidence=compute_confidence(final_grade, "5m", ticker),
                entry_price=entry_price, stop_price=stop_price, t1_price=t1, t2_price=t2
            )
            logger.info(f"[PHASE 4] 📊 {ticker} signal GENERATED - {signal_type} {direction.upper()} {final_grade}")
        except Exception as e:
            logger.info(f"[PHASE 4] Signal tracking error: {e}")

    # ── Multi-indicator validator ─────────────────────────────────────────────
    latest_bar        = bars_session[-1]
    current_volume    = latest_bar.get("volume", 0)
    signal_direction  = "LONG" if direction == "bull" else "SHORT"
    original_confidence = compute_confidence(final_grade, "5m", ticker)
    base_confidence   = base_confidence  # already set from MTF trend step above

    validation_result = None
    try:
        is_duplicate = _track_validation_call(ticker, direction, entry_price)
        if is_duplicate:
            logger.info(f"[VALIDATOR] 🚫 {ticker} - Skipping duplicate validation")
            return False

        from app.validation.validation import get_validator
        validator = get_validator()
        should_pass, adjusted_conf, metadata = validator.validate_signal(
            ticker=ticker, signal_direction=signal_direction,
            current_price=entry_price, current_volume=current_volume,
            base_confidence=original_confidence
        )
        validation_result = {
            'should_take':         should_pass,
            'original_confidence': original_confidence * 100,
            'adjusted_confidence': adjusted_conf * 100,
            'checks_passed':       len(metadata['summary']['passed_checks']),
            'total_checks':        len(metadata['summary']['passed_checks']) + len(metadata['summary']['failed_checks']),
            'checks':              metadata['checks'],
            'failed_checks':       metadata['summary']['failed_checks'],
        }
        if state:
            state.increment_validator_stat('tested')
            if should_pass:
                state.increment_validator_stat('passed')
            else:
                state.increment_validator_stat('filtered')
            conf_change = validation_result['adjusted_confidence'] - validation_result['original_confidence']
            if conf_change > 0:
                state.increment_validator_stat('boosted')
            elif conf_change < 0:
                state.increment_validator_stat('penalized')

        conf_change = validation_result['adjusted_confidence'] - validation_result['original_confidence']
        logger.info(
            f"[VALIDATOR] {ticker} {'✅' if should_pass else '❌'} | "
            f"Conf: {validation_result['original_confidence']:.0f}% → "
            f"{validation_result['adjusted_confidence']:.0f}% ({conf_change:+.0f}%) | "
            f"Score: {validation_result['checks_passed']}/{validation_result['total_checks']}"
        )
        if not should_pass:
            failed = [k.upper() for k, v in validation_result['checks'].items()
                      if isinstance(v, dict) and not v.get('passed', True)]
            if failed:
                logger.info(f"[VALIDATOR]   Would filter: {', '.join(failed)}")

        if PHASE_4_ENABLED and signal_tracker:
            try:
                signal_tracker.record_validation_result(
                    ticker=ticker, passed=should_pass,
                    confidence_after=adjusted_conf,
                    ivr_multiplier=1.0, uoa_multiplier=1.0, gex_multiplier=1.0,
                    mtf_boost=mtf_result.get('boost', 0.0), ticker_multiplier=1.0,
                    checks_passed=[k for k, v in validation_result['checks'].items()
                                   if isinstance(v, dict) and v.get('passed', True)],
                    rejection_reason=", ".join(validation_result['failed_checks']) if not should_pass else ""
                )
                logger.info(f"[PHASE 4] ✅ {ticker} signal {'VALIDATED' if should_pass else 'REJECTED'}")
            except Exception as e:
                logger.info(f"[PHASE 4] Validation tracking error: {e}")

        if not should_pass:
            logger.info(f"[VALIDATOR] {ticker} FILTERED - {', '.join(validation_result['failed_checks'])}")
            return False
        base_confidence = adjusted_conf

    except Exception as e:
        logger.info(f"[VALIDATOR] Error validating {ticker}: {e}")
        import traceback; traceback.print_exc()

    # ── Confidence formula ────────────────────────────────────────────────────
    options_rec    = _pre_options_data or {}
    ml_boost       = 0.0  # ML scorer offline — hardcoded per cleanup Mar 16 2026
    ticker_multiplier = 1.0
    mtf_boost      = mtf_result.get('boost', 0.0)
    mode_decay     = 0.95 if signal_type == "CFW6_OR" else 1.0

    ivr_multiplier = options_rec.get("ivr_multiplier", 1.0)
    ivr_label      = options_rec.get("ivr_label", "IVR-N/A")
    uoa_multiplier = options_rec.get("uoa_multiplier", 1.0)
    uoa_label      = options_rec.get("uoa_label", "UOA-N/A")
    gex_multiplier = options_rec.get("gex_multiplier", 1.0)
    gex_label      = options_rec.get("gex_label", "GEX-N/A")

    ticker_adj = _mult_to_adjustment(ticker_multiplier, base_confidence)
    mode_adj   = _mult_to_adjustment(mode_decay,        base_confidence)
    ivr_adj    = _mult_to_adjustment(ivr_multiplier,    base_confidence)
    uoa_adj    = _mult_to_adjustment(uoa_multiplier,    base_confidence)
    gex_adj    = _mult_to_adjustment(gex_multiplier,    base_confidence)

    final_confidence = (
        base_confidence
        + ticker_adj + mode_adj + ivr_adj + uoa_adj + gex_adj
        + mtf_boost + ml_boost + vp_boost
        + _smc_delta + _mtf_bias_adj + _mtf_trend_boost
    )
    final_confidence = max(0.40, min(final_confidence, 0.95))

    if spy_regime:
        score_adj = spy_regime.get("score_adj", 0)
        spy_regime_adj = (max(0, score_adj) / 100.0 if direction == "bull"
                          else max(0, -score_adj) / 100.0)
        final_confidence = max(0.40, min(final_confidence + spy_regime_adj, 0.95))
        logger.info(f"[{ticker}] SPY EMA ADJ: {spy_regime_adj:+.3f} | Regime={spy_regime.get('label')}")

    # Liquidity sweep boost
    _sweep_result = None
    if LIQUIDITY_SWEEP_ENABLED:
        final_confidence, _sweep_result = apply_sweep_boost(
            ticker, bars_session, direction, or_high_ref, or_low_ref, final_confidence, vwap=_vwap_val
        )
        if _sweep_result is None:
            logger.info(f"[{ticker}] — No liquidity sweep detected")

    # Order block retest boost
    _ob_result = None
    if ORDER_BLOCK_ENABLED:
        final_confidence, _ob_result = apply_ob_retest_boost(ticker, entry_price, direction, final_confidence)
        if _ob_result is None:
            logger.info(f"[{ticker}] — No OB retest detected")

    # S/D zone confluence boost
    _sd_result = None
    if SD_ZONE_ENABLED:
        final_confidence, _sd_result = apply_sd_confluence_boost(ticker, entry_price, direction, final_confidence)
        if _sd_result is None:
            logger.info(f"[{ticker}] — No S/D zone confluence")

    # Post-3PM decay + per-grade confidence cap
    now_time = _now_et().time()
    if now_time >= time(15, 0):
        minutes_past_3 = (now_time.hour - 15) * 60 + now_time.minute
        decay = max(0.85, 1.0 - (minutes_past_3 / 30) * 0.15)
        final_confidence *= decay
        final_confidence = max(0.40, min(final_confidence, 0.95))
        logger.info(f"[{ticker}] ⏳ POST-3PM DECAY: {decay:.3f}x → confidence={final_confidence:.3f}")
    _conf_cap = config.CONFIDENCE_CAP_BY_GRADE.get(final_grade, 0.88)
    if final_confidence > _conf_cap:
        logger.info(f"[{ticker}] 📉 CONF CAP [{final_grade}]: {final_confidence:.3f} → {_conf_cap:.3f}")
        final_confidence = _conf_cap

    logger.info(
        f"[CONFIDENCE-v2] Base:{base_confidence:.2f} "
        f"+ MTF-Trend:{_mtf_trend_boost:+.3f} "
        f"+ SMC:{_smc_delta:+.3f} "
        f"+ MTFBias:{_mtf_bias_adj:+.3f} "
        f"+ Ticker:{ticker_adj:+.3f} "
        f"+ Mode:{mode_adj:+.3f} "
        f"+ IVR:{ivr_adj:+.3f}[{ivr_label}] "
        f"+ UOA:{uoa_adj:+.3f}[{uoa_label}] "
        f"+ GEX:{gex_adj:+.3f}[{gex_label}] "
        f"+ MTF:{mtf_boost:+.3f} + VP:{vp_boost:+.3f} "
        f"= {final_confidence:.2f}"
    )

    # ── Dynamic threshold + hourly gate ──────────────────────────────────────
    try:
        from app.risk.dynamic_thresholds import get_dynamic_threshold
        eff_min = get_dynamic_threshold(signal_type, final_grade, bars_session, ticker)
    except ImportError:
        min_type  = (config.MIN_CONFIDENCE_INTRADAY if signal_type == "CFW6_INTRADAY" else config.MIN_CONFIDENCE_OR)
        min_grade = config.MIN_CONFIDENCE_BY_GRADE.get(final_grade, min_type)
        eff_min   = max(min_type, min_grade, config.CONFIDENCE_ABSOLUTE_FLOOR)

    if HOURLY_GATE_ENABLED:
        try:
            hourly_mult = get_hourly_confidence_multiplier()
            hour_ctx    = get_current_hour_context()
            if hourly_mult != 1.0:
                original_eff_min = eff_min
                eff_min *= hourly_mult
                ctx_label = hour_ctx['classification'].upper()
                ctx_emoji = "🟢" if ctx_label == "STRONG" else ("🔴" if ctx_label == "WEAK" else "🟡")
                logger.info(
                    f"[HOURLY GATE] {ctx_emoji} {hour_ctx['hour']}:00 {ctx_label} "
                    f"(WR: {hour_ctx['win_rate']:.1f}% / {hour_ctx['trades']} trades) | "
                    f"Threshold: {original_eff_min:.2f} → {eff_min:.2f} ({hourly_mult:.2f}x)"
                )
        except Exception as hourly_err:
            logger.info(f"[HOURLY GATE] Error (non-fatal): {hourly_err}")

    # ── Confidence gate ───────────────────────────────────────────────────────
    if final_confidence < eff_min:
        _track_gate_result(final_grade, signal_type, final_confidence, passed=False)
        if TRACKERS_ENABLED and grade_gate_tracker:
            grade_gate_tracker.record_gate_rejection(
                ticker=ticker, grade=final_grade, confidence=final_confidence,
                threshold=eff_min, signal_type=signal_type
            )
        logger.info(
            f"[{ticker}] 🚫 GATED: confidence {final_confidence:.2f} < "
            f"dynamic threshold {eff_min:.2f} [{signal_type}/{final_grade}] — signal dropped"
        )
        if PHASE_4_ENABLED and signal_tracker:
            try:
                signal_tracker.record_signal_rejected(
                    ticker=ticker, stage='CONFIDENCE_GATE',
                    reason=f"conf {final_confidence:.2f} < threshold {eff_min:.2f} [{signal_type}/{final_grade}]"
                )
            except Exception:
                pass
        return False

    _track_gate_result(final_grade, signal_type, final_confidence, passed=True)
    if TRACKERS_ENABLED and grade_gate_tracker:
        grade_gate_tracker.record_gate_pass(
            ticker=ticker, grade=final_grade, confidence=final_confidence,
            threshold=eff_min, signal_type=signal_type
        )
    logger.info(f"[{ticker}] ✅ GATE PASSED: {final_confidence:.2f} >= {eff_min:.2f} (dynamic)")

    if PHASE_4_ENABLED and signal_tracker:
        try:
            bars_to_confirmation = len(bars_session) - confirm_idx if confirm_idx else 0
            signal_tracker.record_signal_armed(
                ticker=ticker, final_confidence=final_confidence,
                bars_to_confirmation=bars_to_confirmation,
                confirmation_type=confirm_type or 'retest'
            )
            logger.info(f"[PHASE 4] 🎯 {ticker} signal ARMED - confidence={final_confidence:.2f}")
        except Exception as e:
            logger.info(f"[PHASE 4] Armed tracking error: {e}")

    # ── Late-stage filters: dead zone, GEX pin ────────────────────────────────
    _dz_blocked, _dz_reason = is_dead_zone(direction, spy_regime)
    if _dz_blocked:
        logger.info(f"[{ticker}] 🚫 DEAD ZONE: {_dz_reason}")
        return False

    _pin_blocked, _pin_reason = is_in_gex_pin_zone(entry_price, _pre_options_data)
    if _pin_blocked:
        logger.info(f"[{ticker}] 🚫 GEX PIN GATE: {_pin_reason}")
        return False

    # ── Scorecard gate ────────────────────────────────────────────────────────
    _sc = build_scorecard(
        ticker=ticker, direction=direction, grade=final_grade,
        options_rec=options_rec,
        mtf_trend_boost=_mtf_trend_boost,
        smc_delta=_smc_delta,
        vwap_passed=vwap_passes,
        sweep_detected=(_sweep_result is not None),
        ob_detected=(_ob_result is not None),
        spy_regime=spy_regime,
        rvol=_signal_rvol,
    )
    if _sc.score < SCORECARD_GATE_MIN:
        logger.info(
            f"[{ticker}] 🚫 SCORECARD-GATE: {_sc.score:.1f} < {SCORECARD_GATE_MIN} "
            f"— signal dropped | {_sc.breakdown}"
        )
        return False

    # ── Arm the trade ─────────────────────────────────────────────────────────
    arm_ticker(
        ticker, direction, zone_low, zone_high,
        or_low_ref, or_high_ref,
        entry_price, stop_price, t1, t2,
        final_confidence, final_grade, options_rec,
        signal_type=signal_type,
        validation_result=validation_result,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type,
        mtf_result=mtf_result, metadata=_meta,
        vp_bias=vp_bias,
    )
    try:
        set_cooldown(ticker, direction, signal_type)
        logger.info(f"[{ticker}] ✅ Cooldown registered ({signal_type})")
    except Exception as _sc_err:
        logger.warning(f"[{ticker}] set_cooldown error (non-fatal): {_sc_err}")
