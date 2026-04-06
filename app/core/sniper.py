"""
sniper.py — CFW6 Strategy Engine v1.38f
Two-path scanning: OR-Anchored + Intraday BOS+FVG fallback.
Signal pipeline lives in app/core/sniper_pipeline.py.
See CHANGELOG.md for full phase history.

AUDIT 2026-04-06 (SN-11):
  FIX-SN-11 (screener fallback key path): get_watchlist_with_metadata()
    returns a nested dict:
      {'watchlist': [...], 'metadata': {'all_tickers_with_scores': [...]}, ...}
    The ImportError fallback stub was calling wl.get('all_tickers_with_scores', [])
    on the top-level dict, which always resolves to []. Every lookup therefore
    fell through to the default return {'qualified': False, 'score': 0,
    'rvol': 0.0, 'tier': None}, meaning the explosive-mover override was
    permanently disabled when screener_integration was absent — even for
    tickers that were fully scored and present in the watchlist funnel.
    Fix: changed the lookup to wl.get('metadata', {}).get('all_tickers_with_scores', [])
    so the loop iterates the actual scored-ticker list.

AUDIT 2026-04-06 (SN-10):
  SN-10 (source of truth): EXPLOSIVE_RVOL_THRESHOLD was hardcoded to 3.0
    locally while config.EXPLOSIVE_RVOL_THRESHOLD is 4.0. Two values in
    production meant the explosive-mover override fired at a lower threshold
    than intended, potentially bypassing the regime filter for marginal RVOL
    movers. Fixed: removed local constant; all references now use
    config.EXPLOSIVE_RVOL_THRESHOLD directly.

AUDIT 2026-04-03:
  BUG-SN-7 (dead import): BEAR_SIGNALS_ENABLED was imported from utils.config
    but never referenced anywhere in this file. Same class as BUG-SP-3 which
    removed the same dead import from sniper_pipeline.py. Import removed.

  BUG-SN-9 (real bug): options_rec was never fetched or forwarded in
    process_ticker. Gate 7 (GEX pin) and Gate 12 (IVR/GEX scorecard) in
    sniper_pipeline.py always received options_rec=None, making both gates
    permanently neutral regardless of config. Fix (Option A): call
    get_ticker_screener_metadata(ticker) once early in process_ticker
    (after armed-signal guard, before bars fetch) and forward options_rec
    to all three _run_signal_pipeline call sites. Failure is non-fatal —
    options_rec falls back to None on any exception.

AUDIT 2026-03-31 (Session CORE-4):
  BUG-SN-4 (clarity): _run_signal_pipeline local wrapper shadowed the _pipeline
    alias from the module-level import. Added explicit docstring note clarifying
    the intentional aliasing pattern so future developers don't mistake it for
    a naming collision or circular call.
  BUG-SN-5 (consistency): get_secondary_range_levels was imported inline via a
    deferred `from app.signals.opening_range import ...` inside the secondary
    range fallback block. All other opening_range symbols are imported at module
    top in the ORB_TRACKER_ENABLED try/except block. Moved get_secondary_range_levels
    into that block so all opening_range imports are in one place. The inline
    import is removed — it was structurally safe (only reachable when OR data
    exists, which requires ORB_TRACKER_ENABLED=True) but inconsistent.
  BUG-SN-6 (defensive): bos_signal["fvg_low"], bos_signal["fvg_high"], and
    bos_signal["bos_price"] in the intraday path were direct key access with no
    .get() fallback. scan_bos_fvg() contract guarantees these keys but a
    malformed return would raise an unlogged KeyError inside process_ticker's
    outer try/except. Replaced with .get() + safe defaults (0.0) so any
    unexpected dict shape produces a logged warning and a graceful skip rather
    than a silent error swallow.

Prior audit notes (Session 18 / v1.38d):
  BUG-SN-1: logger moved before optional try/except blocks.
  BUG-SN-2: VWAP reclaim block documented as structurally unreachable.
  BUG-SN-3: resolved by BUG-SN-1 fix.
  All other checks CONFIRMED CLEAN — see AUDIT_REGISTRY.md.
"""
import traceback
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from utils.time_helpers import _now_et, _bar_time, _strip_tz
from utils.bar_utils import resample_bars as _resample_bars  # FIX #53: was a local duplicate
from app.notifications.discord_helpers import send_simple_message
from app.validation.validation import get_validator, get_regime_filter
from app.validation.cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from app.data.data_manager import data_manager
from utils import config
from app.mtf.bos_fvg_engine import scan_bos_fvg, is_force_close_time, find_fvg_after_bos
from app.core.signal_scorecard import build_scorecard, SCORECARD_GATE_MIN
# BUG-SN-7 FIX: BEAR_SIGNALS_ENABLED removed — was imported but never referenced
# anywhere in this file (same dead import as BUG-SP-3 in sniper_pipeline.py).
from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone
from app.filters.early_session_disqualifier import should_skip_cfw6_or_early

# Pipeline lives in sniper_pipeline.py (extracted to keep this file small).
# BUG-SN-4 NOTE: imported as _pipeline to avoid name collision with the local
# _run_signal_pipeline dispatcher defined below. The dispatcher is the public
# surface used by process_ticker and scanner.py; _pipeline is the implementation.
from app.core.sniper_pipeline import _run_signal_pipeline as _pipeline

# BUG-SN-1 FIX: logger moved here — before all optional try/except blocks so
# any import-time exception is loggable immediately.
import logging
logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")  # FIX: was NameError in process_ticker regime_age calc

# ── Constants ──────────────────────────────────────────────────────────
EXPLOSIVE_SCORE_THRESHOLD = 80
# SN-10 FIX: removed local EXPLOSIVE_RVOL_THRESHOLD = 3.0 — was diverging from
# config.EXPLOSIVE_RVOL_THRESHOLD (4.0). All references below use config directly
# so there is a single source of truth.
MIN_RVOL_TO_SIGNAL         = config.RVOL_SIGNAL_GATE
MAX_WATCH_BARS             = 12
REGIME_FILTER_ENABLED      = True

# ── Optional: screener metadata ────────────────────────────────────────────────────────
try:
    from app.screening.screener_integration import get_ticker_screener_metadata
    logger.info("[SNIPER] ✅ screener_integration loaded")
except ImportError:
    logger.info("[SNIPER] ⚠️  screener_integration not found — using watchlist fallback")
    def get_ticker_screener_metadata(ticker):
        try:
            from app.screening.watchlist_funnel import get_watchlist_with_metadata
            wl = get_watchlist_with_metadata(force_refresh=False)
            # FIX SN-11: get_watchlist_with_metadata() nests scored tickers under
            # wl['metadata']['all_tickers_with_scores'], not at the top level.
            # The old wl.get('all_tickers_with_scores', []) always returned []
            # so every ticker fell through to qualified=False.
            scored = wl.get('metadata', {}).get('all_tickers_with_scores', [])
            for t in scored:
                if t.get('ticker') == ticker:
                    score = t.get('score', 0) or t.get('composite_score', 0)
                    rvol  = t.get('rvol', 0.0)
                    tier  = t.get('tier', None) or t.get('rvol_tier', None)
                    return {
                        'qualified': score >= EXPLOSIVE_SCORE_THRESHOLD and rvol >= config.EXPLOSIVE_RVOL_THRESHOLD,
                        'score': score, 'rvol': rvol, 'tier': tier,
                    }
        except Exception as _e:
            logger.warning(f"[SNIPER] screener_metadata fallback error ({ticker}): {_e}")
        return {'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}

# ── Watch / armed signal stores ───────────────────────────────────────────
from app.core.watch_signal_store import (
    _persist_watch, _remove_watch_from_db, _maybe_load_watches,
    send_bos_watch_alert, clear_watching_signals,
)
from app.core.armed_signal_store import (
    _persist_armed_signal, _remove_armed_from_db, _maybe_load_armed_signals,
    clear_armed_signals,
)

# ── Optional modules (non-fatal stubs on missing) ──────────────────────────
try:
    from app.core.eod_reporter import run_eod_report
    logger.info("[SNIPER] ✅ eod_reporter loaded")
except ImportError:
    logger.info("[SNIPER] ⚠️  eod_reporter not found — EOD reports disabled")
    def run_eod_report(*args, **kwargs):
        logger.info("[EOD] ⚠️  run_eod_report stub called — module not installed")

from app.filters.vwap_gate import compute_vwap, passes_vwap_gate

try:
    from app.filters.mtf_bias import mtf_bias_engine
    MTF_BIAS_ENABLED = True
    logger.info("[SNIPER] ✅ MTF bias engine enabled")
except ImportError:
    MTF_BIAS_ENABLED = False
    mtf_bias_engine = None

# BUG-SN-5 FIX: get_secondary_range_levels moved into this block so all
# opening_range imports live in one place. Previously it was imported inline
# via a deferred `from app.signals.opening_range import get_secondary_range_levels`
# inside the secondary range fallback block — inconsistent with every other
# opening_range symbol imported here at module top.
try:
    from app.signals.opening_range import (
        or_detector, compute_opening_range_from_bars, compute_premarket_range,
        detect_breakout_after_or, detect_fvg_after_break,
        get_secondary_range_levels,
    )
    ORB_TRACKER_ENABLED = True
    logger.info("[SNIPER] ✅ ORB Detector enabled")
except ImportError:
    ORB_TRACKER_ENABLED = False
    or_detector = None
    get_secondary_range_levels = None
    logger.info("[SNIPER] ⚠️  ORB Detector disabled")

try:
    from app.signals.vwap_reclaim import detect_vwap_reclaim
    VWAP_RECLAIM_ENABLED = True
    logger.info("[SNIPER] ✅ VWAP reclaim signal enabled")
except ImportError:
    VWAP_RECLAIM_ENABLED = False
    def detect_vwap_reclaim(*a, **kw): return None

try:
    from app.mtf.mtf_fvg_priority import get_highest_priority_fvg, get_full_mtf_analysis, print_priority_stats
    MTF_PRIORITY_ENABLED = True
    logger.info("[SNIPER] ✅ MTF FVG priority resolver enabled")
except ImportError:
    MTF_PRIORITY_ENABLED = False
    def get_full_mtf_analysis(*a, **kw):
        return {'primary_fvg': None, 'secondary_fvgs': [], 'confluence_count': 0, 'has_conflict': False}

try:
    from app.filters.sd_zone_confluence import cache_sd_zones, apply_sd_confluence_boost, clear_sd_cache
    SD_ZONE_ENABLED = True
    logger.info("[SNIPER] ✅ S/D zone confluence enabled")
except ImportError:
    SD_ZONE_ENABLED = False
    def cache_sd_zones(ticker, bars): pass
    def clear_sd_cache(ticker=None): pass

try:
    from app.filters.order_block_cache import clear_ob_cache
    ORDER_BLOCK_ENABLED = True
except ImportError:
    ORDER_BLOCK_ENABLED = False
    def clear_ob_cache(ticker=None): pass

try:
    from app.filters.market_regime_context import get_market_regime, print_market_regime
    SPY_EMA_CONTEXT_ENABLED = True
    logger.info("[SNIPER] ✅ SPY EMA context enabled")
except ImportError:
    SPY_EMA_CONTEXT_ENABLED = False
    def get_market_regime(force_refresh=False): return {"label": "UNKNOWN", "score_adj": 0}
    def print_market_regime(r, ticker=""): pass

try:
    from app.analytics.funnel_analytics import funnel_tracker as _funnel_tracker
    FUNNEL_ANALYTICS_ENABLED = True
    logger.info("[SNIPER] ✅ Funnel analytics enabled")
except ImportError:
    _funnel_tracker = None
    FUNNEL_ANALYTICS_ENABLED = False

try:
    from app.signals.signal_analytics import signal_tracker
    from app.analytics.performance_monitor import (
        performance_monitor, check_performance_dashboard, check_performance_alerts,
    )
    PHASE_4_ENABLED = True
    logger.info("[SIGNALS] ✅ Phase 4 monitoring enabled")
except ImportError:
    signal_tracker = None
    performance_monitor = None
    PHASE_4_ENABLED = False
    def check_performance_dashboard(*a, **kw): pass
    def check_performance_alerts(*a, **kw): pass

try:
    from app.analytics.cooldown_tracker import cooldown_tracker
    from app.analytics.explosive_tracker import (  # noqa: F401
        explosive_tracker,
        track_explosive_override,
    )
    from app.analytics.grade_gate_tracker import grade_gate_tracker
    TRACKERS_ENABLED = True
    logger.info("[SNIPER] ✅ Analytics trackers loaded")
except ImportError:
    cooldown_tracker = None
    explosive_tracker = None
    track_explosive_override = None
    grade_gate_tracker = None
    TRACKERS_ENABLED = False

try:
    from utils.production_helpers import _send_alert_safe, _fetch_data_safe, _db_operation_safe
    PRODUCTION_HELPERS_ENABLED = True
    logger.info("[SNIPER] ✅ Production hardening enabled")
except ImportError:
    PRODUCTION_HELPERS_ENABLED = False

# ── Thread-safe state ───────────────────────────────────────────────────
from app.core.thread_safe_state import get_state
_state = get_state()

# BOS watch alert dedup — cleared EOD via clear_bos_alerts()
_bos_watch_alerted: set = set()


def clear_bos_alerts():
    """EOD reset — called by scanner.py to clear BOS watch alert dedup set."""
    _bos_watch_alerted.clear()


def _log_bos_event(ticker: str, direction: str, bos_price: float, signal_type: str):
    if not FUNNEL_ANALYTICS_ENABLED or _funnel_tracker is None:
        return
    try:
        _funnel_tracker.record_stage(
            ticker, 'BOS', passed=True,
            reason=f"{direction.upper()} {signal_type} @ ${bos_price:.2f}"
        )
    except Exception as _e:
        logger.warning(f"[FUNNEL] _log_bos_event error (non-fatal): {_e}")


def _log_fvg_event(ticker: str, direction: str, fvg_low: float, fvg_high: float, signal_type: str):
    if not FUNNEL_ANALYTICS_ENABLED or _funnel_tracker is None:
        return
    try:
        _funnel_tracker.record_stage(
            ticker, 'FVG', passed=True,
            reason=f"{direction.upper()} {signal_type} zone=${fvg_low:.2f}-{fvg_high:.2f}"
        )
    except Exception as _e:
        logger.warning(f"[FUNNEL] _log_fvg_event error (non-fatal): {_e}")


def _get_or_threshold(spy_regime) -> float:
    try:
        vix = get_regime_filter().get_regime_state().vix
    except Exception:
        vix = 20.0
    return config.get_vix_or_threshold(vix, spy_regime)


def _run_signal_pipeline(ticker, direction, zone_low, zone_high,
                         or_high_ref, or_low_ref, signal_type,
                         bars_session, breakout_idx,
                         bos_confirmation=None, bos_candle_type=None, spy_regime=None,
                         skip_cfw6_confirmation=False, options_rec=None):
    """
    Thin dispatcher — delegates to sniper_pipeline._run_signal_pipeline.
    Kept here so scanner.py import surface stays unchanged.

    BUG-SN-4 NOTE: This function intentionally has the same name as the symbol
      imported from sniper_pipeline (imported as _pipeline to avoid collision).
      This is not a recursive call — _pipeline is the implementation, this
      wrapper is the public surface. scanner.py imports _run_signal_pipeline
      from this module, not from sniper_pipeline directly.

    FIX E (2026-03-26): Removed get_ticker_screener_metadata= and state= kwargs.
      Those were part of the old all-in-one sniper.py signature before the pipeline
      was extracted. sniper_pipeline absorbed them via **_unused_kwargs but passing
      them is dead weight — removed to keep the call surface clean.

    BUG-SN-9 FIX (2026-04-03): options_rec parameter added. process_ticker now
      fetches screener metadata early and passes options_rec here so Gate 7
      (GEX pin) and Gate 12 (IVR/GEX scorecard) in sniper_pipeline.py receive
      real data instead of always-None.
    """
    return _pipeline(
        ticker, direction, zone_low, zone_high,
        or_high_ref, or_low_ref, signal_type,
        bars_session, breakout_idx,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type,
        spy_regime=spy_regime,
        skip_cfw6_confirmation=skip_cfw6_confirmation,
        options_rec=options_rec,
    )


def process_ticker(ticker: str):
    try:
        _maybe_load_watches()
        _maybe_load_armed_signals()
        check_performance_dashboard(_state, PHASE_4_ENABLED)
        check_performance_alerts(_state, PHASE_4_ENABLED, None, send_simple_message)

        if REGIME_FILTER_ENABLED:
            regime_filter = get_regime_filter()
            if not regime_filter.is_favorable_regime():
                metadata = get_ticker_screener_metadata(ticker)
                if metadata['qualified']:
                    if TRACKERS_ENABLED and track_explosive_override is not None:
                        state_r = regime_filter.get_regime_state()
                        track_explosive_override(
                            ticker=ticker,
                            direction="pre-scan",
                            score=metadata['score'],
                            rvol=metadata['rvol'],
                            tier=metadata['tier'] or "N/A",
                            regime_type=state_r.regime,
                            vix_level=state_r.vix,
                            entry_price=0.0,
                            grade="N/A",
                            confidence=0.0,
                        )
                    logger.info(
                        f"[{ticker}] 🚀 EXPLOSIVE MOVER OVERRIDE: "
                        f"score={metadata['score']} rvol={metadata['rvol']:.1f}x "
                        f"tier={metadata['tier']} — regime filter bypassed"
                    )
                else:
                    state_r = regime_filter.get_regime_state()
                    logger.info(
                        f"[{ticker}] 🚫 REGIME FILTER: {state_r.regime} "
                        f"(VIX:{state_r.vix:.1f}) — {state_r.reason}"
                    )
                    return

        if _state.ticker_is_armed(ticker):
            return

        # BUG-SN-9 FIX: Fetch screener metadata once here, unconditionally, so
        # options_rec is available for Gate 7 (GEX pin) and Gate 12 (IVR/GEX
        # scorecard) on every signal path — including normal-regime days where
        # the regime block above is skipped entirely. Non-fatal: failure falls
        # back to options_rec=None (same as the old always-None behaviour).
        options_rec = None
        try:
            _meta = get_ticker_screener_metadata(ticker)
            options_rec = _meta.get('options_rec') or _meta.get('options') or None
        except Exception as _meta_err:
            logger.warning(f"[{ticker}] options_rec fetch failed (non-fatal): {_meta_err}")

        if PRODUCTION_HELPERS_ENABLED:
            bars_session = _fetch_data_safe(
                ticker, lambda t: data_manager.get_today_session_bars(t), "session bars"
            )
            if bars_session is None:
                return
        else:
            try:
                bars_session = data_manager.get_today_session_bars(ticker)
                if not bars_session:
                    logger.info(f"[{ticker}] No session bars")
                    return
            except Exception as e:
                logger.warning(f"[{ticker}] ❌ Data fetch failed: {e}")
                return

        logger.info(
            f"[{ticker}] {_now_et().date()} ({len(bars_session)} bars) "
            f"{_bar_time(bars_session[0])} → {_bar_time(bars_session[-1])}"
        )

        if SD_ZONE_ENABLED:
            cache_sd_zones(ticker, bars_session)

        spy_regime = None
        if SPY_EMA_CONTEXT_ENABLED:
            try:
                spy_regime = get_market_regime()
                regime_age = (datetime.now(_ET) - spy_regime.get("ts", datetime.now(_ET))).total_seconds()
                if regime_age < 2:
                    print_market_regime(spy_regime)
            except Exception as e:
                logger.warning(f"[{ticker}] SPY EMA context error: {e}")

        # FIX v1.38d: run_eod_report() only accepts session_date (str|None).
        if is_force_close_time(bars_session[-1]):
            run_eod_report()
            return

        _is_watching = _state.ticker_is_watching(ticker)
        if _is_watching:
            w = _state.get_watching_signal(ticker)

            # DB-restore: resolve breakout_idx from breakout_bar_dt after restart
            if w.get("breakout_idx") is None:
                bar_dt_target = _strip_tz(w.get("breakout_bar_dt"))
                resolved_idx  = None
                if bar_dt_target is not None:
                    for i, bar in enumerate(bars_session):
                        if _strip_tz(bar["datetime"]) == bar_dt_target:
                            resolved_idx = i
                            break
                if resolved_idx is None:
                    logger.info(
                        f"[{ticker}] ⚠️ Watch DB entry: breakout bar "
                        f"{bar_dt_target} not found in today's session — discarding"
                    )
                    _state.remove_watching_signal(ticker)
                    _remove_watch_from_db(ticker)
                    return
                else:
                    _state.update_watching_signal_field(ticker, "breakout_idx", resolved_idx)
                    w["breakout_idx"] = resolved_idx
                    logger.info(
                        f"[{ticker}] 📄 Watch restored from DB: "
                        f"breakout_idx={resolved_idx} ({bar_dt_target})"
                    )

            bars_since = len(bars_session) - w["breakout_idx"]
            if bars_since > MAX_WATCH_BARS:
                logger.info(f"[{ticker}] ⏰ Watch expired — clearing")
                _state.remove_watching_signal(ticker)
                _remove_watch_from_db(ticker)
                return

            logger.info(f"[{ticker}] 👁️ WATCHING [{bars_since}/{MAX_WATCH_BARS}]")
            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            fvg_result = find_fvg_after_bos(
                bars_session, w["breakout_idx"], w["direction"], min_pct=fvg_threshold
            )
            if fvg_result is None:
                return
            zl, zh = fvg_result["fvg_low"], fvg_result["fvg_high"]
            # BUG-SN-9 FIX: options_rec forwarded (call site 1 — watch path)
            _run_signal_pipeline(
                ticker, w["direction"], zl, zh,
                w["or_high"], w["or_low"], w["signal_type"],
                bars_session, w["breakout_idx"],
                spy_regime=spy_regime,
                options_rec=options_rec,
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
            or_range_pct  = (or_high - or_low) / or_low
            or_threshold  = _get_or_threshold(spy_regime)
            if or_range_pct < or_threshold:
                logger.info(
                    f"[{ticker}] OR too narrow "
                    f"({or_range_pct:.2%} < {or_threshold:.2%}) "
                    f"— skipping OR path, trying intraday BOS"
                )
            else:
                logger.info(f"[{ticker}] OR: ${or_low:.2f}—${or_high:.2f} ({or_range_pct:.2%})")

                if should_skip_cfw6_or_early(or_range_pct, _now_et(), or_threshold):
                    logger.info(
                        f"[{ticker}] EARLY SESSION GATE: CFW6_OR blocked before 9:45 AM "
                        f"(OR={or_range_pct:.2%} < {or_threshold:.2%})"
                    )
                    return

                direction, breakout_idx = detect_breakout_after_or(bars_session, or_high, or_low)

                if direction:
                    _log_bos_event(ticker, direction, bars_session[breakout_idx]["close"], "CFW6_OR")
                    zone_low, zone_high = detect_fvg_after_break(bars_session, breakout_idx, direction)
                    if zone_low is not None:
                        _log_fvg_event(ticker, direction, zone_low, zone_high, "CFW6_OR")
                        scan_mode    = "OR_ANCHORED"
                        or_high_ref  = or_high
                        or_low_ref   = or_low
                    else:
                        w_entry = {
                            "direction":       direction,
                            "breakout_idx":    breakout_idx,
                            "breakout_bar_dt": _strip_tz(bars_session[breakout_idx]["datetime"]),
                            "or_high":         or_high,
                            "or_low":          or_low,
                            "signal_type":     "CFW6_OR",
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
                            logger.info(f"[{ticker}] 🔕 BOS watch alert suppressed (already sent)")
                        return
                else:
                    logger.info(f"[{ticker}] No ORB")

                # Secondary range fallback (after 10:30).
                # BUG-SN-5 FIX: get_secondary_range_levels is now imported at module
                # top in the ORB_TRACKER_ENABLED block — no longer deferred inline here.
                if scan_mode is None and _now_et().time() >= time(10, 30):
                    if get_secondary_range_levels is not None:
                        sr = get_secondary_range_levels(ticker)
                        if sr:
                            sr_direction, sr_idx = detect_breakout_after_or(
                                bars_session, sr["sr_high"], sr["sr_low"]
                            )
                            if sr_direction:
                                _log_bos_event(ticker, sr_direction,
                                               bars_session[sr_idx]["close"], "CFW6_OR")
                                zone_low, zone_high = detect_fvg_after_break(
                                    bars_session, sr_idx, sr_direction
                                )
                                if zone_low is not None:
                                    _log_fvg_event(ticker, sr_direction, zone_low, zone_high, "CFW6_OR")
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
                                        logger.info(f"[{ticker}] 🔕 BOS watch alert suppressed (already sent)")
                                    return
        else:
            logger.info(f"[{ticker}] No OR bars")

        # ── Intraday BOS+FVG fallback ─────────────────────────────────────────────
        if scan_mode is None:
            if len(bars_session) < 15:
                return

            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
            if bos_signal is None:
                logger.info(f"[{ticker}] — No BOS+FVG signal")
                return

            direction    = bos_signal.get("direction")
            breakout_idx = bos_signal.get("bos_idx")
            bos_confirmation = bos_signal.get("confirmation")
            bos_candle_type  = bos_signal.get("candle_type")

            # BUG-SN-6 FIX: fvg_low, fvg_high, and bos_price now use .get() with
            # safe 0.0 defaults. scan_bos_fvg() contract guarantees these keys but
            # a malformed return would previously raise an unlogged KeyError swallowed
            # by the outer try/except. Guard + warn so any shape deviation is surfaced.
            _fvg_low  = bos_signal.get("fvg_low",  0.0)
            _fvg_high = bos_signal.get("fvg_high", 0.0)
            _bos_price = bos_signal.get("bos_price", bars_session[breakout_idx]["close"] if breakout_idx is not None else 0.0)

            if not direction or breakout_idx is None or _fvg_low == 0.0 or _fvg_high == 0.0:
                logger.warning(f"[{ticker}] BUG-SN-6: bos_signal missing required keys — skipping: {bos_signal}")
                return

            _log_bos_event(ticker, direction, _bos_price, "CFW6_INTRADAY")
            _log_fvg_event(ticker, direction, _fvg_low, _fvg_high, "CFW6_INTRADAY")

            if MTF_PRIORITY_ENABLED:
                try:
                    mtf_analysis = get_full_mtf_analysis(
                        ticker=ticker, direction=direction,
                        bars_5m=bars_session, min_pct=fvg_threshold
                    )
                    primary_fvg = mtf_analysis['primary_fvg']
                    if primary_fvg is None:
                        logger.info(f"[{ticker}] — No FVGs found on any timeframe (MTF scan)")
                        return
                    zone_low  = primary_fvg['fvg_low']
                    zone_high = primary_fvg['fvg_high']
                    if mtf_analysis['has_conflict']:
                        logger.info(
                            f"[{ticker}] 🎯 MTF PRIORITY: {primary_fvg['timeframe']} FVG selected | "
                            f"Confluence: {mtf_analysis['confluence_count']} timeframe(s) | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                    else:
                        logger.info(
                            f"[{ticker}] 🔍 Single FVG on {primary_fvg['timeframe']} | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                except Exception as priority_err:
                    logger.warning(f"[{ticker}] MTF priority error (falling back to 5m): {priority_err}")
                    zone_low  = _fvg_low
                    zone_high = _fvg_high
            else:
                zone_low  = _fvg_low
                zone_high = _fvg_high

            if direction == "bull":
                or_high_ref = _bos_price
                or_low_ref  = zone_low
            else:
                or_high_ref = zone_high
                or_low_ref  = _bos_price

            scan_mode = "INTRADAY_BOS"

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        logger.info(f"[{ticker}] {scan_mode} | FVG ${zone_low:.2f}—${zone_high:.2f}")
        # BUG-SN-9 FIX: options_rec forwarded (call site 2 — OR-anchored + intraday BOS)
        _run_signal_pipeline(
            ticker, direction, zone_low, zone_high,
            or_high_ref, or_low_ref, signal_type,
            bars_session, breakout_idx,
            bos_confirmation=bos_confirmation,
            bos_candle_type=bos_candle_type,
            spy_regime=spy_regime,
            skip_cfw6_confirmation=(scan_mode == "INTRADAY_BOS"),
            options_rec=options_rec,
        )

        # BUG-SN-2 NOTE: VWAP reclaim block below is structurally unreachable.
        # scan_mode is always OR_ANCHORED or INTRADAY_BOS by this point, so the
        # `if scan_mode is None` guard never passes. Keeping the code in place
        # as documented intent — if VWAP reclaim is to be activated it needs its
        # own execution path, not a fallback on scan_mode==None.
        if scan_mode is None and VWAP_RECLAIM_ENABLED:
            _vwap_val = compute_vwap(bars_session)
            vr = None
            for _vr_dir in ("bull", "bear"):
                vr = detect_vwap_reclaim(ticker, bars_session, _vr_dir, _vwap_val)
                if vr:
                    break
            if vr:
                logger.info(
                    f"[{ticker}] 🔵 VWAP RECLAIM: {vr['direction'].upper()} "
                    f"@ ${vr['entry_price']:.2f} | VWAP=${vr['vwap']:.2f}"
                )
                # BUG-SN-9 FIX: options_rec forwarded (call site 3 — VWAP reclaim)
                _run_signal_pipeline(
                    ticker, vr["direction"],
                    vr["zone_low"], vr["zone_high"],
                    0.0, 0.0,
                    "CFW6_INTRADAY",
                    bars_session, vr["reclaim_bar_idx"],
                    spy_regime=spy_regime,
                    skip_cfw6_confirmation=True,
                    options_rec=options_rec,
                )
            else:
                logger.info(f"[{ticker}] — No VWAP reclaim signal")

    except Exception as e:
        logger.error(f"process_ticker error {ticker}: {e}", exc_info=True)
