# Sniper Module - CFW6 Strategy Implementation
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers, Multi-Indicator Validator
# TWO-PATH SCANNING: OR-Anchored + Intraday BOS+FVG fallback
# TWO-PHASE ALERTS: Watch Alert (BOS detected) + Confirmed Signal (FVG+confirm)
# EARNINGS GUARD: Skips tickers with earnings within 2 days
# IV RANK: Confidence multiplier based on historical IV cheapness/expensiveness
# UOA: Confidence multiplier based on unusual options activity alignment
# GEX: Confidence multiplier based on gamma exposure environment + pin alignment
# VALIDATOR: Multi-indicator confirmation (ADX, Volume, DMI, CCI, Bollinger, VPVR) - TEST MODE
# CONFIDENCE GATE: Hard minimum floors by signal type + grade after all multipliers
# OR WIDTH FILTER: OR range < MIN_OR_RANGE_PCT skips OR path (choppy), falls to intraday BOS
# WATCH PERSISTENCE: watching_signals + armed_signals tables survive Railway redeploys;
#                    Smart expiration auto-cleans stale entries on load.
# OPTIONS PRE-GATE: Early options validation before confirmation — kills bad setups
#                   before CPU-heavy confirmation runs (Step 6.5, SOFT/HARD modes).
# PHASE 4 TRACKING: Signal funnel analytics for optimization visibility
# MTF CONVERGENCE: Multi-timeframe FVG alignment boost (5m + 3m convergence)
# CANDLE CONFIRMATION: 3-tier Nitro Trades candle quality model (A+/A/A- grading)
# MTF FVG PRIORITY: Highest timeframe FVG selection (5m > 3m > 2m > 1m)
# REGIME FILTER: VIX/SPY market condition detection — avoids bad tape
# EXPLOSIVE MOVER OVERRIDE: Score >=80 + RVOL >=4.0x bypasses regime filter for extreme opportunities
# PHASE 4 MONITORING: Live performance dashboard, risk alerts
# HOURLY GATE: Time-based confidence adjustment from historical win rates
# WIN RATE ENHANCEMENTS (Phase 2):
#   - 9:45 OR WINDOW: Widened from 9:30 to 9:40(3 bars) for better range capture
#   - VWAP DIRECTIONAL GATE: Price must be above/below VWAP for bull/bear signals
#   - HYBRID CONFIDENCE: Grade-based spread (A+: 92-95%, A-: 85-88%) instead of fixed values
#   - INTRADAY GRADE GATE REMOVED: A-, B+, B grades now flow through confidence gate
# VOLUME PROFILE (Step 6.6): Price must be near POC or high-volume nodes for valid entries
# ENTRY TIMING (Step 6.7): Time-based WR adjustment + session quality filtering
# MTF TREND (Step 8.5): Multi-timeframe trend alignment boost (1m/5m/15m/30m)
# SMC ENRICHMENT (Step 8.6): CHoCH / Inducement / Order Block / Trend Phase context + conf delta
# GATE DISTRIBUTION (Issue #23): EOD grade/signal-type/histogram report for gate analytics
# FUNNEL ANALYTICS: Upstream pre-detection funnel (SCREENED->BOS->FVG->ARMED) via log_bos/log_fvg
#
# RESTORE (Mar 10 2026): Full file recovered from commit 6a235067 after accidental truncation
# FIXED IMPORTS: signal_analytics, dynamic_thresholds, hourly_gate, production_helpers
# FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks
# FIXED C2 (Mar 10 2026): Discord alert now fires AFTER position open succeeds (position_id > 0)
#
# REFACTOR (Mar 14 2026):
#   - app/filters/vwap_gate.py      : compute_vwap, passes_vwap_gate, VWAP_GATE_ENABLED
#   - app/core/gate_stats.py        : _gate_stats, _track_gate_result, print_gate_distribution_stats
#   - app/core/confidence_model.py  : GRADE_CONFIDENCE_RANGES, compute_confidence
#   - app/core/arm_signal.py        : arm_ticker (position open + Discord + armed state)
#   - app/core/sniper_log.py        : log_proposed_trade
#
# FIX #15 (Mar 14 2026):
#   - Wired signal_generator_cooldown into _run_signal_pipeline.
#   - is_on_cooldown(ticker, direction) checked at entry — blocks duplicate signals
#     across Railway restarts (cooldown persisted to signal_cooldowns DB table).
#   - set_cooldown(ticker, direction, signal_type) called after arm_ticker() succeeds
#     so the 30-min same-direction / 15-min reversal window is registered in DB.
#
# CLEANUP (Mar 16 2026):
#   - Removed app.ml.ml_signal_scorer_v2 import + ML_SCORER_ENABLED flag (module deleted,
#     ml_signal_scorer.py was OFFLINE; scorer was never active in production).
#   - ml_boost stays hardcoded to 0.0 in confidence formula — no behavior change.
#
# IMPORT FIXES (Mar 16 2026):
#   - app.core.confidence_model -> app.ai.ai_learning (confidence_model.py is now a shim,
#     canonical compute_confidence lives in ai_learning with full 9-grade support).
#   - app.discord_helpers -> app.notifications.discord_helpers (root-level copy is legacy).
#
# FUNNEL ANALYTICS WIRE-IN (Mar 16 2026):
#   - app.signals.funnel_analytics: log_bos + log_fvg wired into process_ticker.
#   - log_bos() called after detect_breakout_after_or() on OR and secondary range paths.
#   - log_fvg() called after scan_bos_fvg() on INTRADAY_BOS path.
#
# FUNNEL ANALYTICS FIX (Mar 17 2026):
#   - Corrected import path: app.analytics.funnel_analytics (was app.signals.funnel_analytics
#     which does not exist — caused ImportError + FUNNEL_ANALYTICS_ENABLED = False every boot)
#   - Replaced log_bos(ticker, direction, price, signal_type=...) calls with thin wrappers
#     _log_bos_event() / _log_fvg_event() that map to funnel_tracker.record_stage() directly.
#     The old convenience functions only accept (ticker, passed, reason=None) — wrong sig.
#
# IMPORT STUBS (Mar 17 2026):
#   - app.core.eod_reporter: module deleted — wrapped in try/except, stub no-ops on missing.
#   - app.screening.screener_integration: module deleted — wrapped in try/except stub.
#   - app.core.gate_stats: module deleted — wrapped in try/except stub.
#   - app.core.sniper_log: module deleted — wrapped in try/except stub.
#
# SMC ENRICHMENT (Mar 17 2026):
#   - Step 8.6: enrich_signal_with_smc() wired into _run_signal_pipeline after run_mtf_trend_step.
#   - Detects CHoCH, Inducement, Order Blocks, OB Retests, Trend Phase.
#   - Applies confidence_delta from smc_context['total_confidence_delta'] before gate check.
#   - Non-fatal: ImportError falls back to no-op stub; all internal errors are caught.
#
# FIX (Mar 19 2026): UnboundLocalError '_is_watching' referenced before assignment.
#   - Root cause: orphaned DB-restore block used _is_watching before the assignment.
#   - Fix: removed orphaned first block; re-inserted DB-restore logic inside the
#     second _is_watching block, immediately after _is_watching is assigned.
#   - Also fixes silent bug: w["breakout_idx"] local dict was not updated after
#     state update, causing bars_since to compute against None on same cycle.
import traceback
from datetime import datetime, time, timedelta
from utils.time_helpers import _now_et, _bar_time, _strip_tz
from app.notifications.discord_helpers import send_simple_message
from app.validation.validation import get_validator, get_regime_filter
from app.validation.cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from app.data.data_manager import data_manager
from utils import config
from app.mtf.bos_fvg_engine import scan_bos_fvg, is_force_close_time, find_fvg_after_bos
from app.filters.early_session_disqualifier import should_skip_cfw6_or_early
try:
    from app.screening.screener_integration import get_ticker_screener_metadata
    print("[SNIPER] ✅ screener_integration loaded")
except ImportError:
    print("[SNIPER] ⚠️  screener_integration not found — using stub")
    def get_ticker_screener_metadata(ticker):
        return {'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}
from app.core.watch_signal_store import (
    _persist_watch, _remove_watch_from_db, _maybe_load_watches,
    send_bos_watch_alert, clear_watching_signals,
)
from app.core.armed_signal_store import (
    _persist_armed_signal, _remove_armed_from_db, _maybe_load_armed_signals,
    clear_armed_signals,
)
# ── Refactored modules ────────────────────────────────────────────────────────
try:
    from app.core.eod_reporter import run_eod_reports
    print("[SNIPER] ✅ eod_reporter loaded")
except ImportError:
    print("[SNIPER] ⚠️  eod_reporter not found — EOD reports disabled")
    def run_eod_reports(*args, **kwargs):
        print("[EOD] ⚠️  run_eod_reports stub called — module not installed")
from app.filters.vwap_gate import compute_vwap, passes_vwap_gate
try:
    from app.filters.mtf_bias import mtf_bias_engine
    MTF_BIAS_ENABLED = True
    print("[SNIPER] ✅ MTF bias engine enabled (Phase 1.34 — 1H/15m top-down)")
except ImportError:
    MTF_BIAS_ENABLED = False
    print("[SNIPER] ⚠️  MTF bias engine disabled")
    mtf_bias_engine = None
try:
    from app.core.gate_stats import _track_gate_result
    print("[SNIPER] ✅ gate_stats loaded")
except ImportError:
    print("[SNIPER] ⚠️  gate_stats not found — using stub")
    def _track_gate_result(grade, signal_type, confidence, passed): pass
from app.ai.ai_learning import compute_confidence
from app.core.arm_signal import arm_ticker
try:
    from app.core.sniper_log import _track_validation_call
    print("[SNIPER] ✅ sniper_log loaded")
except ImportError:
    print("[SNIPER] ⚠️  sniper_log not found — using stub")
    def _track_validation_call(ticker, direction, price): return False
# ── FIX #15: DB-persisted signal cooldown (survives Railway restarts) ─────────
from app.analytics.cooldown_tracker import is_on_cooldown, set_cooldown
print("[SNIPER] ✅ Signal cooldown gate loaded (DB-persisted, restart-safe)")

try:
    from app.validation.volume_profile import get_volume_analyzer
    VOLUME_PROFILE_ENABLED = True
    print("[SNIPER] ✅ Volume profile validation enabled")
except ImportError:
    VOLUME_PROFILE_ENABLED = False
    print("[SNIPER] ⚠️  Volume profile disabled")
    def get_volume_analyzer():
        return None
try:
    from app.filters.order_block_cache import (
        identify_order_block, cache_order_block, apply_ob_retest_boost, clear_ob_cache
    )
    ORDER_BLOCK_ENABLED = True
    print("[SNIPER] ✅ Order block retest cache enabled")
except ImportError:
    ORDER_BLOCK_ENABLED = False
    print("[SNIPER] ⚠️  Order block cache disabled")
    def identify_order_block(bars, bos_idx, direction): return None
    def cache_order_block(ticker, ob): pass
    def apply_ob_retest_boost(ticker, entry_price, direction, confidence): return confidence, None
    def clear_ob_cache(ticker=None): pass
try:
    from app.signals.opening_range import (
        or_detector,
        compute_opening_range_from_bars,
        compute_premarket_range,
        detect_breakout_after_or,
        detect_fvg_after_break,
)
    ORB_TRACKER_ENABLED = True
    print("[SNIPER] ✅ ORB Detector enabled")
except ImportError:
    ORB_TRACKER_ENABLED = False
    or_detector = None
    print("[SNIPER] ⚠️  ORB Detector disabled")
try:
    from app.signals.vwap_reclaim import detect_vwap_reclaim
    VWAP_RECLAIM_ENABLED = True
    print("[SNIPER] ✅ VWAP reclaim signal enabled")
except ImportError:
    VWAP_RECLAIM_ENABLED = False
    print("[SNIPER] ⚠️  VWAP reclaim signal disabled")
    def detect_vwap_reclaim(bars): return None

try:
    from app.validation.entry_timing import get_entry_timing_validator
    ENTRY_TIMING_ENABLED = True
    print("[SNIPER] ✅ Entry timing validation enabled")
except ImportError:
    ENTRY_TIMING_ENABLED = False
    print("[SNIPER] ⚠️  Entry timing disabled")
    def get_entry_timing_validator():
        return None

try:
    from app.filters.liquidity_sweep import apply_sweep_boost
    LIQUIDITY_SWEEP_ENABLED = True
    print("[SNIPER] ✅ Liquidity sweep detector enabled")
except ImportError:
    LIQUIDITY_SWEEP_ENABLED = False
    print("[SNIPER] ⚠️  Liquidity sweep detector disabled")
    def apply_sweep_boost(ticker, bars, direction, or_high, or_low, confidence, vwap=0.0):
        return confidence, None
try:
    from app.mtf.mtf_integration import run_mtf_trend_step
    MTF_TREND_ENABLED = True
    print("[SNIPER] ✅ MTF trend validator enabled (Step 8.5)")
except ImportError:
    MTF_TREND_ENABLED = False
    print("[SNIPER] ⚠️  MTF trend validator disabled")
    def run_mtf_trend_step(ticker, direction, entry_price, confidence, signal_data):
        return confidence, signal_data

# ── Step 8.6: SMC Enrichment — CHoCH / Inducement / OB / Trend Phase ─────────
try:
    from app.mtf.smc_engine import enrich_signal_with_smc
    SMC_ENRICHMENT_ENABLED = True
    print("[SNIPER] ✅ SMC enrichment enabled (Step 8.6 — CHoCH/Inducement/OB/Phase)")
except ImportError:
    SMC_ENRICHMENT_ENABLED = False
    print("[SNIPER] ⚠️  SMC enrichment disabled")
    def enrich_signal_with_smc(ticker, bars, signal_data):
        return signal_data

try:
    from app.filters.sd_zone_confluence import (
        cache_sd_zones, apply_sd_confluence_boost, clear_sd_cache
    )
    SD_ZONE_ENABLED = True
    print("[SNIPER] ✅ S/D zone confluence enabled")
except ImportError:
    SD_ZONE_ENABLED = False
    print("[SNIPER] ⚠️  S/D zone confluence disabled")
    def cache_sd_zones(ticker, bars): pass
    def apply_sd_confluence_boost(ticker, entry_price, direction, confidence): return confidence, None
    def clear_sd_cache(ticker=None): pass

# ── FUNNEL ANALYTICS: upstream pre-detection funnel visibility ────────────────
# FIX (Mar 17 2026): correct import path is app.analytics.funnel_analytics.
# app.signals.funnel_analytics does not exist — was causing ImportError every boot.
# Also: convenience log_bos/log_fvg only accept (ticker, passed, reason) — wrong
# for sniper call sites. Use thin wrappers below instead.
try:
    from app.analytics.funnel_analytics import funnel_tracker as _funnel_tracker
    FUNNEL_ANALYTICS_ENABLED = True
    print("[SNIPER] ✅ Funnel analytics enabled (log_bos + log_fvg)")
except ImportError:
    _funnel_tracker = None
    FUNNEL_ANALYTICS_ENABLED = False
    print("[SNIPER] ⚠️  Funnel analytics disabled")


def _log_bos_event(ticker: str, direction: str, bos_price: float, signal_type: str):
    """Thin wrapper: translate sniper BOS detection args → funnel_tracker.record_stage()."""
    if not FUNNEL_ANALYTICS_ENABLED or _funnel_tracker is None:
        return
    try:
        _funnel_tracker.record_stage(
            ticker, 'BOS', passed=True,
            reason=f"{direction.upper()} {signal_type} @ ${bos_price:.2f}"
        )
    except Exception as _e:
        print(f"[FUNNEL] _log_bos_event error (non-fatal): {_e}")


def _log_fvg_event(ticker: str, direction: str, fvg_low: float, fvg_high: float, signal_type: str):
    """Thin wrapper: translate sniper FVG detection args → funnel_tracker.record_stage()."""
    if not FUNNEL_ANALYTICS_ENABLED or _funnel_tracker is None:
        return
    try:
        _funnel_tracker.record_stage(
            ticker, 'FVG', passed=True,
            reason=f"{direction.upper()} {signal_type} zone=${fvg_low:.2f}-{fvg_high:.2f}"
        )
    except Exception as _e:
        print(f"[FUNNEL] _log_fvg_event error (non-fatal): {_e}")


from app.ml.metrics_cache import get_ticker_win_rates
_TICKER_WIN_CACHE = get_ticker_win_rates(days=30)
_orb_classifications = {}  # ticker -> OR classification dict, populated at 9:40
# BOS watch alert dedup — prevents repeat Discord pings for the same BOS
# across scanner cycles. Cleared at EOD alongside watching_signals.
_bos_watch_alerted: set = set()

# ══════════════════════════════════════════════════════════════════════════════
# SPY EMA CONTEXT — 5m EMA 9/21/50 regime filter
# ══════════════════════════════════════════════════════════════════════════════
try:
    from app.filters.market_regime_context import (
        get_market_regime, print_market_regime,
    )
    SPY_EMA_CONTEXT_ENABLED = True
    print("[SNIPER] ✅ SPY EMA context enabled (5m EMA 9/21/50)")
except ImportError as e:
    SPY_EMA_CONTEXT_ENABLED = False
    print(f"[SNIPER] ⚠️  SPY EMA context disabled: {e}")
    def get_market_regime(force_refresh=False): return {"label": "UNKNOWN", "score_adj": 0}
    def print_market_regime(r, ticker=""): pass

# ══════════════════════════════════════════════════════════════════════════════
# FIX #1: THREAD-SAFE STATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
from app.core.thread_safe_state import get_state

_state = get_state()
print("[SNIPER] ✅ Thread-safe state management enabled")
# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION POINT #1: IMPORT TRACKERS
# ══════════════════════════════════════════════════════════════════════════════
try:
    from app.analytics.cooldown_tracker import cooldown_tracker
    from app.analytics.explosive_tracker import explosive_tracker
    from app.analytics.grade_gate_tracker import grade_gate_tracker
    TRACKERS_ENABLED = True
    print("[SNIPER] ✅ Analytics trackers loaded (cooldown, explosive, grade gate)")
except ImportError as e:
    cooldown_tracker = None
    explosive_tracker = None
    grade_gate_tracker = None
    TRACKERS_ENABLED = False
    print(f"[SNIPER] ⚠️  Analytics trackers not available: {e}")

print("[SNIPER] ✅ VWAP directional gate enabled (app.filters.vwap_gate)")
print("[SNIPER] ✅ Confidence model loaded (app.ai.ai_learning)")
print("[SNIPER] ✅ Gate stats tracker loaded (app.core.gate_stats)")
print("[SNIPER] ✅ arm_ticker loaded (app.core.arm_signal)")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 INTEGRATION - Signal Analytics & Performance Monitoring
# ══════════════════════════════════════════════════════════════════════════════
try:
    from app.signals.signal_analytics import signal_tracker
    from app.analytics.performance_monitor import (
        performance_monitor,
        check_performance_dashboard,
        check_performance_alerts,
    )
    PHASE_4_ENABLED = True
    alert_manager = None
    print("[SIGNALS] ✅ Phase 4 monitoring enabled (analytics + performance)")
except ImportError as import_err:
    signal_tracker = None
    performance_monitor = None
    alert_manager = None
    PHASE_4_ENABLED = False
    print(f"[SIGNALS] ⚠️  Phase 4 monitoring disabled: {import_err}")

try:
    from utils.production_helpers import _send_alert_safe, _fetch_data_safe, _db_operation_safe
    PRODUCTION_HELPERS_ENABLED = True
    print("[SNIPER] ✅ Production hardening enabled")
except ImportError:
    PRODUCTION_HELPERS_ENABLED = False
    print("[SNIPER] ⚠️  Production helpers not available")

# ══════════════════════════════════════════════════════════════════════════════
# HOURLY CONFIDENCE GATE
# ══════════════════════════════════════════════════════════════════════════════
try:
    from app.validation.hourly_gate import get_hourly_confidence_multiplier, get_current_hour_context, print_hourly_gate_stats
    HOURLY_GATE_ENABLED = True
    print("[SIGNALS] ✅ Hourly confidence gate enabled (time-based WR adjustment)")
except ImportError:
    HOURLY_GATE_ENABLED = False
    print("[SIGNALS] ⚠️  Hourly gate disabled (module not found)")
    def get_hourly_confidence_multiplier():
        return 1.0
    def get_current_hour_context():
        return {'hour': 0, 'win_rate': None, 'multiplier': 1.0, 'classification': 'no_data', 'trades': 0}
    def print_hourly_gate_stats():
        pass

VALIDATOR_ENABLED = True
VALIDATOR_TEST_MODE = False
print("[SIGNALS] ✅ Multi-indicator validator ACTIVE (filtering enabled)")

OPTIONS_PRE_GATE_ENABLED = True
print("[SNIPER] ✅ Options pre-validation gate enabled (via validation.py)")

try:
    from app.mtf.mtf_integration import enhance_signal_with_mtf, print_mtf_stats
    MTF_ENABLED = True
    print("[SNIPER] ✅ MTF convergence boost enabled")
except ImportError:
    MTF_ENABLED = False
    print("[SNIPER] ⚠️  MTF system not available — single-timeframe mode")
    def enhance_signal_with_mtf(*args, **kwargs):
        return {'enabled': False, 'convergence': False, 'boost': 0.0, 'reason': 'MTF disabled', 'timeframes': []}
    def print_mtf_stats():
        pass

try:
    from app.mtf.mtf_fvg_priority import get_highest_priority_fvg, get_full_mtf_analysis, print_priority_stats
    MTF_PRIORITY_ENABLED = True
    print("[SNIPER] ✅ MTF FVG priority resolver enabled")
except ImportError:
    MTF_PRIORITY_ENABLED = False
    print("[SNIPER] ⚠️  MTF priority resolver not available — single-TF FVG mode")
    def get_highest_priority_fvg(*args, **kwargs):
        return None
    def get_full_mtf_analysis(*args, **kwargs):
        return {'primary_fvg': None, 'secondary_fvgs': [], 'confluence_count': 0, 'has_conflict': False}
    def print_priority_stats():
        pass

REGIME_FILTER_ENABLED = True
print("[SNIPER] ✅ Regime filter enabled (VIX/SPY market condition detection - via validation.py)")

EXPLOSIVE_SCORE_THRESHOLD = 80
EXPLOSIVE_RVOL_THRESHOLD = 3.0
print(f"[SNIPER] ✅ Explosive mover override enabled (score>={EXPLOSIVE_SCORE_THRESHOLD} + RVOL>={EXPLOSIVE_RVOL_THRESHOLD}x)")

MAX_WATCH_BARS = 12
OPTIONS_PRE_GATE_MODE = "HARD"

def _run_signal_pipeline(ticker, direction, zone_low, zone_high,
                          or_high_ref, or_low_ref, signal_type,
                          bars_session, breakout_idx,
                          bos_confirmation=None, bos_candle_type=None, spy_regime=None,
                          skip_cfw6_confirmation=False):

    # ── FIX #15: DB-persisted cooldown gate (restart-safe) ────────────────────
    # This is the primary deduplication guard — checks the signal_cooldowns table
    # which survives Railway restarts, unlike the in-memory analytics tracker below.
    try:
        blocked, cooldown_reason = is_on_cooldown(ticker, direction)
        if blocked:
            print(f"[{ticker}] 🚫 SIGNAL COOLDOWN: {cooldown_reason}")
            return False
    except Exception as _cd_err:
        print(f"[{ticker}] [COOLDOWN] Check error (non-fatal): {_cd_err}")

    # Analytics cooldown tracker (in-memory reporting, non-blocking)
    if TRACKERS_ENABLED and cooldown_tracker:
        if cooldown_tracker.is_in_cooldown(ticker):
            remaining = cooldown_tracker.get_cooldown_remaining(ticker)
            print(f"[{ticker}] 🚫 ANALYTICS COOLDOWN: {remaining:.0f}s remaining — signal dropped")
            return False

    _pre_options_data = None
    if OPTIONS_PRE_GATE_ENABLED:
        try:
            from app.validation.greeks_precheck import validate_signal_greeks
            _proxy_entry = bars_session[-1]["close"]
            greeks_valid, greeks_reason = validate_signal_greeks(ticker, direction, _proxy_entry)
            greeks_emoji = "✅" if greeks_valid else "❌"
            print(f"[{ticker}] {greeks_emoji} GREEKS-GATE: {greeks_reason}")
            if OPTIONS_PRE_GATE_MODE == "HARD" and not greeks_valid:
                print(f"[{ticker}] 🚫 Signal dropped: Greeks pre-check failed")
                return False
            if greeks_valid or OPTIONS_PRE_GATE_MODE == "SOFT":
                from app.validation.validation import get_options_filter
                options_filter = get_options_filter()
                _is_explosive = get_ticker_screener_metadata(ticker).get('qualified', False)
                _tradeable, _opts_data, _reason = options_filter.validate_signal_for_options(
                    ticker, direction, _proxy_entry, _proxy_entry * 1.05,
                    explosive_mover=_is_explosive
                )

                _pre_options_data = _opts_data
                if OPTIONS_PRE_GATE_MODE == "HARD":
                    if not _tradeable:
                        print(f"[{ticker}] ❌ OPTIONS-GATE [FULL]: {_reason} — signal dropped")
                        return False
                    print(f"[{ticker}] ✅ OPTIONS-GATE [FULL]: passed → proceeding to confirmation")
                else:
                    full_emoji = "✅" if _tradeable else "⚠️"
                    print(f"[{ticker}] {full_emoji} OPTIONS-GATE [FULL-SOFT]: {_reason}")
        except Exception as _gate_err:
            print(f"[{ticker}] OPTIONS-GATE error (non-fatal): {_gate_err}")
            _pre_options_data = None

    vp_boost = 0.0

    if VOLUME_PROFILE_ENABLED:
        try:
            analyzer = get_volume_analyzer()
            if analyzer:
                fvg_midpoint = (zone_low + zone_high) / 2.0
                is_valid, vp_reason, vp_data = analyzer.validate_entry(
                    ticker=ticker,
                    direction=direction,
                    entry_price=fvg_midpoint,
                    bars=bars_session
                )
                vp_emoji = "✅" if is_valid else "❌"
                print(f"[{ticker}] {vp_emoji} VOLUME PROFILE: {vp_reason}")
                if vp_data:
                    vp_boost = vp_data.get('confidence_boost', 0.0)
                    vp_bias  = vp_data.get('options_bias', 'NEUTRAL')
                    print(
                        f"[{ticker}] VP Details: POC=${vp_data.get('poc', 0):.2f} | "
                        f"Distance={vp_data.get('distance_from_poc_pct', 0):.1%} | "
                        f"Volume Rank={vp_data.get('volume_rank', 'N/A')} | "
                        f"Bias={vp_bias} | Boost={vp_boost:+.2f}"
                    )

                if not is_valid:
                    print(f"[{ticker}] 🚫 Signal dropped: Volume profile validation failed")
                    return False
        except Exception as vp_err:
            print(f"[{ticker}] Volume profile validation error (non-fatal): {vp_err}")

    if skip_cfw6_confirmation:
        # FIX #3 (MAR 15, 2026): use close of last confirmed bar, not open.
        # The bar's open is already stale by the time the signal fires.
        entry_price = bars_session[-1]["close"]
        base_grade  = bos_confirmation if bos_confirmation in ("A+", "A", "A-", "B+", "B") else "A-"
        confirm_idx = len(bars_session) - 1
        confirm_type = bos_candle_type or "BOS+FVG"
        print(f"[{ticker}] ✅ BOS CONFIRMATION (pre-confirmed): {base_grade} grade @ ${entry_price:.2f}")
    else:
        result = wait_for_confirmation(
            bars_session, direction, (zone_low, zone_high), breakout_idx + 1
        )
        found, entry_price, base_grade, confirm_idx, confirm_type = result
        if not found or base_grade == "reject":
            print(f"[{ticker}] — No confirmation (found={found}, grade={base_grade})")
            return False
        print(f"[{ticker}] ✅ CONFIRMATION: {base_grade} grade @ ${entry_price:.2f}")


    if ENTRY_TIMING_ENABLED:
        try:
            timing_validator = get_entry_timing_validator()
            if timing_validator:
                is_valid, timing_reason, timing_data = timing_validator.validate_entry_time(
                    current_time=_now_et(),
                    signal_type=signal_type,
                    grade=base_grade
                )
                timing_emoji = "✅" if is_valid else "❌"
                print(f"[{ticker}] {timing_emoji} ENTRY TIMING: {timing_reason}")
                if timing_data:
                    print(
                        f"[{ticker}] Timing Details: Hour={timing_data.get('hour')}:00 | "
                        f"Win Rate={timing_data.get('hour_win_rate', 0):.1%} | "
                        f"Quality={timing_data.get('session_quality', 'unknown')}"
                    )
                if not is_valid:
                    print(f"[{ticker}] 🚫 Signal dropped: Entry timing validation failed")
                    return False
        except Exception as timing_err:
            print(f"[{ticker}] Entry timing validation error (non-fatal): {timing_err}")

    if ORDER_BLOCK_ENABLED:
        _ob = identify_order_block(bars_session, breakout_idx, direction)
        if _ob:
            cache_order_block(ticker, _ob)
            print(f"[{ticker}] 📦 OB cached: ${_ob['ob_low']:.2f}–${_ob['ob_high']:.2f}")

    vwap_passes, vwap_reason = passes_vwap_gate(bars_session, direction, entry_price)
    if not vwap_passes:
        print(f"[{ticker}] 🚫 VWAP GATE: {vwap_reason}")
        return False
    else:
        print(f"[{ticker}] ✅ VWAP GATE: {vwap_reason}")
        # ── Phase 1.34: MTF Bias Gate (1H + 15m top-down, Nitro Trades) ──────────
    # ── Phase 1.34: MTF Bias Gate (1H + 15m top-down, Nitro Trades) ──────────
    if MTF_BIAS_ENABLED and mtf_bias_engine:
        try:
            from app.mtf.mtf_compression import compress_to_1m as _compress_1m
            def _resample_bars(bars_1m: list, minutes: int) -> list:
                """Delegate to mtf_compression for 15m/1h aggregation."""
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
                        "open":     bucket[0]["open"],
                        "high":     max(b["high"]   for b in bucket),
                        "low":      min(b["low"]    for b in bucket),
                        "close":    bucket[-1]["close"],
                        "volume":   sum(b["volume"] for b in bucket),
                    })
                return result

            _bars_1m_raw = data_manager.get_bars_from_memory(ticker, limit=390)
            _bars_15m = _resample_bars(_bars_1m_raw, 15)
            _bars_1h  = _resample_bars(_bars_1m_raw, 60)

            _mtf = mtf_bias_engine.evaluate(
                direction=direction,
                bars_1h=_bars_1h,
                bars_15m=_bars_15m,
                current_price=entry_price,
            )
            _mtf_emoji = "✅" if _mtf["pass"] else "🚫"
            print(f"[{ticker}] {_mtf_emoji} MTF BIAS: {_mtf['reason']}")
            mtf_bias_engine.record_stat(ticker, direction, _mtf)  # Phase 1.35
            if not _mtf["pass"]:
                return False
            _mtf_bias_adj = _mtf["confidence_adj"]

        except Exception as _mtf_err:
            print(f"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}")
            _mtf_bias_adj = 0.0
    else:
        _mtf_bias_adj = 0.0

    # ─────────────────────────────────────────────────────────────────────────

    conf_result = grade_signal_with_confirmations(
        ticker=ticker, direction=direction, bars=bars_session,
        current_price=entry_price, breakout_idx=breakout_idx, base_grade=base_grade
    )
    if conf_result["final_grade"] == "reject":
        print(f"[{ticker}] — Rejected by confirmation layers")
        return False
    final_grade = conf_result["final_grade"]

    _mtf_trend_signal_data = {}
    base_confidence_pre_mtf_trend = compute_confidence(final_grade, "5m", ticker)
    base_confidence_pre_mtf_trend, _mtf_trend_signal_data = run_mtf_trend_step(
        ticker, direction, entry_price,
        base_confidence_pre_mtf_trend, _mtf_trend_signal_data
    )
    _mtf_trend_boost = _mtf_trend_signal_data.get('mtf_trend', {}).get('boost', 0.0)

    # ── Step 8.6: SMC Enrichment ──────────────────────────────────────────────
    # Enrich signal with CHoCH / Inducement / Order Block / Trend Phase context.
    # Applies a capped confidence delta (+/- up to 0.10 / -0.05).
    # ADDITIVE ONLY — never blocks signals.
    _smc_signal_data = dict(_mtf_trend_signal_data)
    _smc_signal_data.update({
        'direction':  direction,
        'bos_idx':    breakout_idx,
        'bos_price':  zone_low if direction == 'bull' else zone_high,
        'entry_type': signal_type,
    })
    _smc_signal_data = enrich_signal_with_smc(ticker, bars_session, _smc_signal_data)
    _smc_delta = _smc_signal_data.get('smc', {}).get('total_confidence_delta', 0.0)
    _smc_summary = _smc_signal_data.get('smc', {}).get('smc_summary', '')
    if _smc_summary:
        print(f"[{ticker}] 🔬 SMC: {_smc_summary} | conf_delta={_smc_delta:+.3f}")

    mtf_result = enhance_signal_with_mtf(
        ticker=ticker,
        direction=direction,
        bars_session=bars_session
    )

    if mtf_result['convergence']:
        print(
            f"[{ticker}] ✅ MTF CONVERGENCE: "
            f"{mtf_result.get('convergence_score', 0):.1%} across "
            f"{', '.join(mtf_result.get('timeframes', []))} | "
            f"Boost: +{mtf_result['boost']:.2%}"
        )
    else:
        print(f"[{ticker}] MTF: {mtf_result['reason']}")

    stop_price, t1, t2 = compute_stop_and_targets(
        bars_session, direction, or_high_ref, or_low_ref, entry_price,
        grade=final_grade
    )

    if PHASE_4_ENABLED and signal_tracker:
        try:
            signal_tracker.record_signal_generated(
                ticker=ticker,
                signal_type=signal_type,
                direction=direction,
                grade=final_grade,
                confidence=compute_confidence(final_grade, "5m", ticker),
                entry_price=entry_price,
                stop_price=stop_price,
                t1_price=t1,
                t2_price=t2
            )
            print(f"[PHASE 4] 📊 {ticker} signal GENERATED - {signal_type} {direction.upper()} {final_grade}")
        except Exception as e:
            print(f"[PHASE 4] Signal tracking error: {e}")

    latest_bar = bars_session[-1]
    current_volume = latest_bar.get("volume", 0)
    signal_direction = "LONG" if direction == "bull" else "SHORT"
    base_confidence = base_confidence_pre_mtf_trend
    original_confidence = compute_confidence(final_grade, "5m", ticker)

    validation_result = None
    if VALIDATOR_ENABLED:
        is_duplicate = _track_validation_call(ticker, direction, entry_price)
        if is_duplicate:
            print(f"[VALIDATOR] 🚫 {ticker} - Skipping duplicate validation")
            return False

        try:
            validator = get_validator()
            should_pass, adjusted_conf, metadata = validator.validate_signal(
                ticker=ticker,
                signal_direction=signal_direction,
                current_price=entry_price,
                current_volume=current_volume,
                base_confidence=original_confidence
            )

            validation_result = {
                'should_take':           should_pass,
                'original_confidence':   original_confidence * 100,
                'adjusted_confidence':   adjusted_conf * 100,
                'checks_passed':         len(metadata['summary']['passed_checks']),
                'total_checks':          len(metadata['summary']['passed_checks']) + len(metadata['summary']['failed_checks']),
                'checks':                metadata['checks'],
                'failed_checks':         metadata['summary']['failed_checks']
            }

            _state.increment_validator_stat('tested')
            if validation_result['should_take']:
                _state.increment_validator_stat('passed')
            else:
                _state.increment_validator_stat('filtered')

            conf_change = validation_result['adjusted_confidence'] - validation_result['original_confidence']
            if conf_change > 0:
                _state.increment_validator_stat('boosted')
            elif conf_change < 0:
                _state.increment_validator_stat('penalized')

            status_emoji = "✅" if validation_result['should_take'] else "❌"
            trend_emoji = "📈" if conf_change > 0 else "📉" if conf_change < 0 else "➡️"

            print(
                f"[VALIDATOR] {ticker} {status_emoji} | "
                f"Conf: {validation_result['original_confidence']:.0f}% → "
                f"{validation_result['adjusted_confidence']:.0f}% {trend_emoji} "
                f"({conf_change:+.0f}%) | "
                f"Score: {validation_result['checks_passed']}/{validation_result['total_checks']}"
            )

            if not validation_result['should_take']:
                failed = [
                    k.upper() for k, v in validation_result['checks'].items()
                    if isinstance(v, dict) and not v.get('passed', True)
                ]
                if failed:
                    print(f"[VALIDATOR]   Would filter: {', '.join(failed)}")

            if PHASE_4_ENABLED and signal_tracker:
                try:
                    signal_tracker.record_validation_result(
                        ticker=ticker,
                        passed=validation_result['should_take'],
                        confidence_after=adjusted_conf,
                        ivr_multiplier=1.0,
                        uoa_multiplier=1.0,
                        gex_multiplier=1.0,
                        mtf_boost=mtf_result.get('boost', 0.0),
                        ticker_multiplier=1.0,
                        checks_passed=[k for k, v in validation_result['checks'].items()
                                     if isinstance(v, dict) and v.get('passed', True)],
                        rejection_reason=", ".join(validation_result['failed_checks']) if not validation_result['should_take'] else ""
                    )
                    status = "VALIDATED" if validation_result['should_take'] else "REJECTED"
                    print(f"[PHASE 4] ✅ {ticker} signal {status}")
                except Exception as e:
                    print(f"[PHASE 4] Validation tracking error: {e}")

            if VALIDATOR_TEST_MODE:
                base_confidence = adjusted_conf
            else:
                if not validation_result['should_take']:
                    print(f"[VALIDATOR] {ticker} FILTERED - {', '.join(validation_result['failed_checks'])}")
                    return False
                base_confidence = adjusted_conf

        except Exception as e:
            print(f"[VALIDATOR] Error validating {ticker}: {e}")
            traceback.print_exc()

    ml_boost = 0.0
    _meta = get_ticker_screener_metadata(ticker)

    options_rec = _pre_options_data
    if _pre_options_data and _pre_options_data.get("gex_data"):
        print(f"[{ticker}] [OPTIONS] GEX data reused from Step 6.5 cache")

    ticker_multiplier = 1.0
    mtf_boost = mtf_result.get('boost', 0.0)
    mode_decay = 0.95 if signal_type == "CFW6_OR" else 1.0

    ivr_multiplier = options_rec.get("ivr_multiplier", 1.0) if options_rec else 1.0
    ivr_label = options_rec.get("ivr_label", "IVR-N/A") if options_rec else "IVR-N/A"
    uoa_multiplier = options_rec.get("uoa_multiplier", 1.0) if options_rec else 1.0
    uoa_label = options_rec.get("uoa_label", "UOA-N/A") if options_rec else "UOA-N/A"
    gex_multiplier = options_rec.get("gex_multiplier", 1.0) if options_rec else 1.0
    gex_label = options_rec.get("gex_label", "GEX-N/A") if options_rec else "GEX-N/A"

    def mult_to_adjustment(multiplier, base_conf):
        if multiplier >= 1.0:
            return min((multiplier - 1.0) * base_conf * 0.75, base_conf * 0.10)
        else:
            return max((multiplier - 1.0) * base_conf * 1.00, base_conf * -0.10)

    ticker_adj = mult_to_adjustment(ticker_multiplier, base_confidence)
    mode_adj   = mult_to_adjustment(mode_decay, base_confidence)
    ivr_adj    = mult_to_adjustment(ivr_multiplier, base_confidence)
    uoa_adj    = mult_to_adjustment(uoa_multiplier, base_confidence)
    gex_adj    = mult_to_adjustment(gex_multiplier, base_confidence)

    final_confidence = (
        base_confidence
        + ticker_adj + mode_adj + ivr_adj + uoa_adj + gex_adj
        + mtf_boost + ml_boost + vp_boost
        + _smc_delta
        + _mtf_bias_adj   # Phase 1.34: 1H+15m alignment boost
    )
    final_confidence = max(0.40, min(final_confidence, 0.95))

    if SPY_EMA_CONTEXT_ENABLED and spy_regime:
        score_adj = spy_regime.get("score_adj", 0)
        spy_regime_adj = (max(0, score_adj) / 100.0 if direction == "bull"
                         else max(0, -score_adj) / 100.0)
        final_confidence = max(0.40, min(final_confidence + spy_regime_adj, 0.95))
        print(f"[{ticker}] SPY EMA ADJ: {spy_regime_adj:+.3f} | Regime={spy_regime.get('label')}")

    _sweep_result = None
    if LIQUIDITY_SWEEP_ENABLED:
        _sweep_vwap = compute_vwap(bars_session)
        final_confidence, _sweep_result = apply_sweep_boost(
            ticker, bars_session, direction,
            or_high_ref, or_low_ref,
            final_confidence,
            vwap=_sweep_vwap
        )
        if _sweep_result is None:
            print(f"[{ticker}] — No liquidity sweep detected")

    _ob_result = None
    if ORDER_BLOCK_ENABLED:
        final_confidence, _ob_result = apply_ob_retest_boost(
            ticker, entry_price, direction, final_confidence
        )
        if _ob_result is None:
            print(f"[{ticker}] — No OB retest detected")

    _sd_result = None
    if SD_ZONE_ENABLED:
        final_confidence, _sd_result = apply_sd_confluence_boost(
            ticker, entry_price, direction, final_confidence
        )
        if _sd_result is None:
            print(f"[{ticker}] — No S/D zone confluence")

    now_time = _now_et().time()
    if now_time >= time(15, 0):
        minutes_past_3 = (now_time.hour - 15) * 60 + now_time.minute
        decay = max(0.85, 1.0 - (minutes_past_3 / 30) * 0.15)
        final_confidence *= decay
        final_confidence = max(0.40, min(final_confidence, 0.95))
        print(f"[{ticker}] ⏳ POST-3PM DECAY: {decay:.3f}x → confidence={final_confidence:.3f}")

    print(
        f"[CONFIDENCE-v2] Base:{base_confidence:.2f} "
        f"+ MTF-Trend:{_mtf_trend_boost:+.3f} "
        f"+ SMC:{_smc_delta:+.3f} "
        f"+ MTFBias:{_mtf_bias_adj:+.3f} "
        f"+ Ticker:{ticker_adj:+.3f}({ticker_multiplier:.2f}) "
        f"+ Mode:{mode_adj:+.3f}({mode_decay:.2f}) "
        f"+ IVR:{ivr_adj:+.3f}[{ivr_label}] "
        f"+ UOA:{uoa_adj:+.3f}[{uoa_label}] "
        f"+ GEX:{gex_adj:+.3f}[{gex_label}] "
        f"+ MTF:{mtf_boost:+.3f} "
        f"+ ML:{ml_boost:+.3f} "
        f"+ VP:{vp_boost:+.3f} "
        f"+ Sweep:{(_sweep_result['boost'] if _sweep_result else 0.0):+.3f} "
        f"+ OB:{(0.03 if _ob_result else 0.0):+.3f} "
        f"+ SD:{(0.03 if _sd_result else 0.0):+.3f} "
        f"= {final_confidence:.2f}"
    )

    try:
        from app.risk.dynamic_thresholds import get_dynamic_threshold
        eff_min = get_dynamic_threshold(signal_type, final_grade)
    except ImportError:
        min_type = (
            config.MIN_CONFIDENCE_INTRADAY
            if signal_type == "CFW6_INTRADAY"
            else config.MIN_CONFIDENCE_OR
        )
        min_grade = config.MIN_CONFIDENCE_BY_GRADE.get(final_grade, min_type)
        eff_min = max(min_type, min_grade, config.CONFIDENCE_ABSOLUTE_FLOOR)

    if HOURLY_GATE_ENABLED:
        try:
            hourly_mult = get_hourly_confidence_multiplier()
            hour_ctx = get_current_hour_context()
            if hourly_mult != 1.0:
                original_eff_min = eff_min
                eff_min *= hourly_mult
                ctx_label = hour_ctx['classification'].upper()
                ctx_emoji = "🟢" if ctx_label == "STRONG" else ("🔴" if ctx_label == "WEAK" else "🟡")
                print(
                    f"[HOURLY GATE] {ctx_emoji} {hour_ctx['hour']}:00 {ctx_label} "
                    f"(WR: {hour_ctx['win_rate']:.1f}% / {hour_ctx['trades']} trades) | "
                    f"Threshold: {original_eff_min:.2f} → {eff_min:.2f} ({hourly_mult:.2f}x)"
                )
        except Exception as hourly_err:
            print(f"[HOURLY GATE] Error (non-fatal): {hourly_err}")

    if final_confidence < eff_min:
        _track_gate_result(final_grade, signal_type, final_confidence, passed=False)
        if TRACKERS_ENABLED and grade_gate_tracker:
            grade_gate_tracker.record_gate_rejection(
                ticker=ticker,
                grade=final_grade,
                confidence=final_confidence,
                threshold=eff_min,
                signal_type=signal_type
            )
        print(
            f"[{ticker}] 🚫 GATED: confidence {final_confidence:.2f} < "
            f"dynamic threshold {eff_min:.2f} "
            f"[{signal_type}/{final_grade}] — signal dropped"
        )
        if PHASE_4_ENABLED and signal_tracker:
            try:
                signal_tracker.record_signal_rejected(
                    ticker=ticker,
                    stage='CONFIDENCE_GATE',
                    reason=f"conf {final_confidence:.2f} < threshold {eff_min:.2f} [{signal_type}/{final_grade}]"
                )
            except Exception:
                pass
        return False

    _track_gate_result(final_grade, signal_type, final_confidence, passed=True)
    if TRACKERS_ENABLED and grade_gate_tracker:
        grade_gate_tracker.record_gate_pass(
            ticker=ticker,
            grade=final_grade,
            confidence=final_confidence,
            threshold=eff_min,
            signal_type=signal_type
        )

    print(f"[{ticker}] ✅ GATE PASSED: {final_confidence:.2f} >= {eff_min:.2f} (dynamic)")

    if PHASE_4_ENABLED and signal_tracker:
        try:
            bars_to_confirmation = len(bars_session) - confirm_idx if confirm_idx else 0
            signal_tracker.record_signal_armed(
                ticker=ticker,
                final_confidence=final_confidence,
                bars_to_confirmation=bars_to_confirmation,
                confirmation_type=confirm_type or 'retest'
            )
            print(f"[PHASE 4] 🎯 {ticker} signal ARMED - confidence={final_confidence:.2f}")
        except Exception as e:
            print(f"[PHASE 4] Armed tracking error: {e}")

    arm_ticker(
        ticker, direction, zone_low, zone_high,
        or_low_ref, or_high_ref,
        entry_price, stop_price, t1, t2,
        final_confidence, final_grade, options_rec,
        signal_type=signal_type,
        validation_result=validation_result,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type,
        mtf_result=mtf_result, metadata=_meta
    )

    return True

def _get_or_threshold(spy_regime) -> float:
    from app.validation.validation import get_regime_filter
    try:
        vix = get_regime_filter().get_regime_state().vix
    except Exception:
        vix = 20.0
    return config.get_vix_or_threshold(vix, spy_regime)

def process_ticker(ticker: str):
    try:
        _maybe_load_watches()
        _maybe_load_armed_signals()
        check_performance_dashboard(_state, PHASE_4_ENABLED)
        check_performance_alerts(_state, PHASE_4_ENABLED, alert_manager, send_simple_message)

        if REGIME_FILTER_ENABLED:
            regime_filter = get_regime_filter()
            if not regime_filter.is_favorable_regime():
                metadata = get_ticker_screener_metadata(ticker)
                if metadata['qualified']:
                    if TRACKERS_ENABLED and explosive_tracker:
                        explosive_tracker.record_override(
                            ticker=ticker,
                            score=metadata['score'],
                            rvol=metadata['rvol'],
                            tier=metadata['tier']
                        )
                    print(
                        f"[{ticker}] 🚀 EXPLOSIVE MOVER OVERRIDE: "
                        f"score={metadata['score']} rvol={metadata['rvol']:.1f}x "
                        f"tier={metadata['tier']} — regime filter bypassed"
                    )
                else:
                    state = regime_filter.get_regime_state()
                    print(
                        f"[{ticker}] 🚫 REGIME FILTER: {state.regime} "
                        f"(VIX:{state.vix:.1f}) — {state.reason}"
                    )
                    return

        if _state.ticker_is_armed(ticker):
            return

        if PRODUCTION_HELPERS_ENABLED:
            bars_session = _fetch_data_safe(
                ticker,
                lambda t: data_manager.get_today_session_bars(t),
                "session bars"
            )
            if bars_session is None:
                return
        else:
            try:
                bars_session = data_manager.get_today_session_bars(ticker)
                if not bars_session:
                    print(f"[{ticker}] No session bars")
                    return
            except Exception as e:
                print(f"[{ticker}] ❌ Data fetch failed: {e}")
                return

        print(
            f"[{ticker}] {_now_et().date()} ({len(bars_session)} bars) "
            f"{_bar_time(bars_session[0])} → {_bar_time(bars_session[-1])}"
        )

        if SD_ZONE_ENABLED:
            cache_sd_zones(ticker, bars_session)

        spy_regime = None
        if SPY_EMA_CONTEXT_ENABLED:
            try:
                spy_regime = get_market_regime()
                print_market_regime(spy_regime, ticker)
            except Exception as e:
                print(f"[{ticker}] SPY EMA context error (non-fatal): {e}")

        if is_force_close_time(bars_session[-1]):
            run_eod_reports(
                bars_session[-1],
                validator_enabled=VALIDATOR_ENABLED,
                validator_test_mode=VALIDATOR_TEST_MODE,
                sd_zone_enabled=SD_ZONE_ENABLED,
                trackers_enabled=TRACKERS_ENABLED,
                cooldown_tracker=cooldown_tracker,
                explosive_tracker=explosive_tracker,
                grade_gate_tracker=grade_gate_tracker,
                phase_4_enabled=PHASE_4_ENABLED,
                signal_tracker=signal_tracker,
                performance_monitor=performance_monitor,
                hourly_gate_enabled=HOURLY_GATE_ENABLED,
                regime_filter_enabled=REGIME_FILTER_ENABLED,
                order_block_enabled=ORDER_BLOCK_ENABLED,
            )
            return

        _is_watching = _state.ticker_is_watching(ticker)
        if _is_watching:
            w = _state.get_watching_signal(ticker)

            # ── DB-restore: resolve breakout_idx from breakout_bar_dt after restart ──
            # After a Railway restart, watching_signals are loaded from DB but
            # breakout_idx is not stored — only breakout_bar_dt is. Resolve it
            # by scanning today's bars for the matching datetime.
            if w.get("breakout_idx") is None:
                bar_dt_target = _strip_tz(w.get("breakout_bar_dt"))
                resolved_idx = None
                if bar_dt_target is not None:
                    for i, bar in enumerate(bars_session):
                        if _strip_tz(bar["datetime"]) == bar_dt_target:
                            resolved_idx = i
                            break
                if resolved_idx is None:
                    print(
                        f"[{ticker}] ⚠️ Watch DB entry: breakout bar "
                        f"{bar_dt_target} not found in today's session — discarding"
                    )
                    _state.remove_watching_signal(ticker)
                    _remove_watch_from_db(ticker)
                    return
                else:
                    _state.update_watching_signal_field(ticker, "breakout_idx", resolved_idx)
                    w["breakout_idx"] = resolved_idx  # keep local ref in sync
                    print(
                        f"[{ticker}] 📄 Watch restored from DB: "
                        f"breakout_idx={resolved_idx} ({bar_dt_target})"
                    )

            bars_since = len(bars_session) - w["breakout_idx"]
            if bars_since > MAX_WATCH_BARS:
                print(f"[{ticker}] ⏰ Watch expired — clearing")
                _state.remove_watching_signal(ticker)
                _remove_watch_from_db(ticker)
                return
            else:
                print(f"[{ticker}] 👁️ WATCHING [{bars_since}/{MAX_WATCH_BARS}]")
                fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
                fvg_result = find_fvg_after_bos(
                    bars_session, w["breakout_idx"], w["direction"],
                    min_pct=fvg_threshold
                )
                if fvg_result is None:
                    return
                zl, zh = fvg_result["fvg_low"], fvg_result["fvg_high"]
                _run_signal_pipeline(
                    ticker, w["direction"], zl, zh,
                    w["or_high"], w["or_low"], w["signal_type"],
                    bars_session, w["breakout_idx"],
                    spy_regime=spy_regime
                )
                _state.remove_watching_signal(ticker)
                _remove_watch_from_db(ticker)
                return

        direction = breakout_idx = zone_low = zone_high = None
        or_high_ref = or_low_ref = scan_mode = None
        bos_confirmation = bos_candle_type = None

        if _now_et().time() < time(9, 30):
            return

        or_high, or_low = compute_opening_range_from_bars(bars_session)
        if or_high is not None:
            or_range_pct = (or_high - or_low) / or_low
            or_threshold = _get_or_threshold(spy_regime)
            if or_range_pct < or_threshold:
                print(
                    f"[{ticker}] OR too narrow "
                    f"({or_range_pct:.2%} < {or_threshold:.2%}) "
                    f"— skipping OR path, trying intraday BOS"
                )
            else:
                print(f"[{ticker}] OR: ${or_low:.2f}—${or_high:.2f} ({or_range_pct:.2%})")

                now_et = _now_et()
                if should_skip_cfw6_or_early(or_range_pct, now_et):
                    print(
                        f"[{ticker}] EARLY SESSION GATE: CFW6_OR blocked before 9:45 AM "
                        f"(OR={or_range_pct:.2%} < {or_threshold:.2%})"
                    )
                    return

                direction, breakout_idx = detect_breakout_after_or(bars_session, or_high, or_low)

                if direction:
                    # ── FUNNEL ANALYTICS: log BOS detection on OR path ────────
                    _log_bos_event(ticker, direction,
                                   bars_session[breakout_idx]["close"],
                                   signal_type="CFW6_OR")

                    zone_low, zone_high = detect_fvg_after_break(
                        bars_session, breakout_idx, direction
                    )
                    if zone_low is not None:
                        # ── FUNNEL ANALYTICS: log FVG found on OR path ────────
                        _log_fvg_event(ticker, direction, zone_low, zone_high,
                                       signal_type="CFW6_OR")

                        scan_mode = "OR_ANCHORED"
                        or_high_ref, or_low_ref = or_high, or_low
                    else:
                        w_entry = {
                            "direction": direction,
                            "breakout_idx": breakout_idx,
                            "breakout_bar_dt": _strip_tz(bars_session[breakout_idx]["datetime"]),
                            "or_high": or_high,
                            "or_low": or_low,
                            "signal_type": "CFW6_OR",
                        }
                        _state.set_watching_signal(ticker, w_entry)
                        _persist_watch(ticker, w_entry)
                        _bos_key = f"{ticker}:{direction}:{bars_session[breakout_idx]['datetime']}"
                        if _bos_key not in _bos_watch_alerted:
                            _bos_watch_alerted.add(_bos_key)
                            send_bos_watch_alert(
                                ticker, direction,
                                bars_session[breakout_idx]["close"],
                                or_high, or_low, "CFW6_OR"
                            )
                        else:
                            print(f"[{ticker}] 🔕 BOS watch alert suppressed (already sent)")
                        return
                else:
                    print(f"[{ticker}] No ORB")

                if scan_mode is None and _now_et().time() >= time(10, 30):
                    from app.signals.opening_range import get_secondary_range_levels
                    sr = get_secondary_range_levels(ticker)
                    if sr:
                        sr_direction, sr_idx = detect_breakout_after_or(
                            bars_session, sr["sr_high"], sr["sr_low"]
                        )
                        if sr_direction:
                            # ── FUNNEL ANALYTICS: log BOS on secondary range path ──
                            _log_bos_event(ticker, sr_direction,
                                           bars_session[sr_idx]["close"],
                                           signal_type="CFW6_OR")

                            zone_low, zone_high = detect_fvg_after_break(
                                bars_session, sr_idx, sr_direction
                            )
                            if zone_low is not None:
                                # ── FUNNEL ANALYTICS: log FVG on secondary range path ──
                                _log_fvg_event(ticker, sr_direction, zone_low, zone_high,
                                               signal_type="CFW6_OR")

                                scan_mode    = "OR_ANCHORED"
                                or_high_ref  = sr["sr_high"]
                                or_low_ref   = sr["sr_low"]
                                direction    = sr_direction
                                breakout_idx = sr_idx
                            else:
                                w_entry = {
                                    "direction":       sr_direction,
                                    "breakout_idx":    sr_idx,
                                    "breakout_bar_dt": _strip_tz(bars_session[sr_idx]["datetime"]),
                                    "or_high":         sr["sr_high"],
                                    "or_low":          sr["sr_low"],
                                    "signal_type":     "CFW6_OR",
                                }
                                _state.set_watching_signal(ticker, w_entry)
                                _persist_watch(ticker, w_entry)
                                _bos_key = f"{ticker}:{sr_direction}:{bars_session[sr_idx]['datetime']}"
                                if _bos_key not in _bos_watch_alerted:
                                    _bos_watch_alerted.add(_bos_key)
                                    send_bos_watch_alert(
                                        ticker, sr_direction,
                                        bars_session[sr_idx]["close"],
                                        sr["sr_high"], sr["sr_low"], "CFW6_OR"
                                    )
                                else:
                                    print(f"[{ticker}] 🔕 BOS watch alert suppressed (already sent)")
                                return

        else:
            print(f"[{ticker}] No OR bars")

        if scan_mode is None:
            if len(bars_session) < 15:
                return

            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
            if bos_signal is None:
                print(f"[{ticker}] — No BOS+FVG signal")
                return

            direction = bos_signal["direction"]
            breakout_idx = bos_signal["bos_idx"]
            bos_confirmation = bos_signal.get("confirmation")
            bos_candle_type = bos_signal.get("candle_type")

            # ── FUNNEL ANALYTICS: log BOS + FVG on INTRADAY_BOS path ─────────
            _log_bos_event(ticker, direction,
                           bos_signal.get("bos_price", bars_session[breakout_idx]["close"]),
                           signal_type="CFW6_INTRADAY")
            _log_fvg_event(ticker, direction,
                           bos_signal["fvg_low"], bos_signal["fvg_high"],
                           signal_type="CFW6_INTRADAY")

            if MTF_PRIORITY_ENABLED:
                try:
                    mtf_analysis = get_full_mtf_analysis(
                        ticker=ticker,
                        direction=direction,
                        bars_5m=bars_session,
                        min_pct=fvg_threshold
                    )
                    primary_fvg = mtf_analysis['primary_fvg']
                    if primary_fvg is None:
                        print(f"[{ticker}] — No FVGs found on any timeframe (MTF scan)")
                        return
                    zone_low = primary_fvg['fvg_low']
                    zone_high = primary_fvg['fvg_high']
                    if mtf_analysis['has_conflict']:
                        print(
                            f"[{ticker}] 🎯 MTF PRIORITY: {primary_fvg['timeframe']} FVG selected | "
                            f"Confluence: {mtf_analysis['confluence_count']} timeframe(s) | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                    else:
                        print(
                            f"[{ticker}] 🔍 Single FVG on {primary_fvg['timeframe']} | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                except Exception as priority_err:
                    print(f"[{ticker}] MTF priority error (falling back to 5m): {priority_err}")
                    zone_low = bos_signal["fvg_low"]
                    zone_high = bos_signal["fvg_high"]
            else:
                zone_low = bos_signal["fvg_low"]
                zone_high = bos_signal["fvg_high"]

            if direction == "bull":
                or_high_ref = bos_signal["bos_price"]
                or_low_ref = zone_low
            else:
                or_high_ref = zone_high
                or_low_ref = bos_signal["bos_price"]

            scan_mode = "INTRADAY_BOS"

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        print(f"[{ticker}] {scan_mode} | FVG ${zone_low:.2f}—${zone_high:.2f}")
        _run_signal_pipeline(
            ticker, direction, zone_low, zone_high,
            or_high_ref, or_low_ref, signal_type,
            bars_session, breakout_idx,
            bos_confirmation=bos_confirmation,
            bos_candle_type=bos_candle_type,
            spy_regime=spy_regime,
            skip_cfw6_confirmation=(scan_mode == "INTRADAY_BOS")
        )

        if ORB_TRACKER_ENABLED and or_detector and scan_mode is not None:
            try:
                or_data = or_detector.classify_or(ticker)
                if or_data:
                    _orb_classifications[ticker] = or_data
                    print(
                        f"[{ticker}] 📊 OR: {or_data['classification']} | "
                        f"${or_data['or_low']:.2f}—${or_data['or_high']:.2f} | "
                        f"ATR Ratio: {or_data['or_range_atr']:.2f}x"
                    )
            except Exception as orb_err:
                print(f"[{ticker}] ORB classify error (non-fatal): {orb_err}")

        # AFTER
        if scan_mode is None and VWAP_RECLAIM_ENABLED:
            _vwap_val = compute_vwap(bars_session)
            for _vr_dir in ("bull", "bear"):
                vr = detect_vwap_reclaim(ticker, bars_session, _vr_dir, _vwap_val)
                if vr:
                    break
            if vr:
                print(
                    f"[{ticker}] 🔵 VWAP RECLAIM: {vr['direction'].upper()} "
                    f"@ ${vr['entry_price']:.2f} | VWAP=${vr['vwap']:.2f}"
                )
                vr_zone_low  = vr["zone_low"]
                vr_zone_high = vr["zone_high"]
                vr_or_high   = vr["entry_price"] * 1.005
                vr_or_low    = vr["entry_price"] * 0.995
                _run_signal_pipeline(
                    ticker,
                    vr["direction"],
                    vr_zone_low,
                    vr_zone_high,
                    vr_or_high,
                    vr_or_low,
                    "CFW6_INTRADAY",
                    bars_session,
                    vr["reclaim_bar_idx"],
                    spy_regime=spy_regime,
                    skip_cfw6_confirmation=True,
                )
            else:
                print(f"[{ticker}] — No VWAP reclaim signal")

    except Exception as e:
        print(f"process_ticker error {ticker}:", e)
        traceback.print_exc()
