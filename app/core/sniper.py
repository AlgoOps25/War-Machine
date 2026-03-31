"""
sniper.py — CFW6 Strategy Engine v1.38d
Two-path scanning: OR-Anchored + Intraday BOS+FVG fallback.
Signal pipeline lives in app/core/sniper_pipeline.py.
See CHANGELOG.md for full phase history.

AUDIT 2026-03-31 (Session 18):
  BUG-SN-1 (non-crashing): import logging / logger were placed after all optional
    try/except import blocks (~40 lines in). Moved to immediately after the hard
    imports so logger is available from the first line of execution. Previously,
    any exception raised inside the optional try/except blocks before logger was
    assigned would produce an unlogged silent failure.
  BUG-SN-2 (structural note): VWAP reclaim block at bottom of process_ticker is
    structurally unreachable — scan_mode is always set to OR_ANCHORED or
    INTRADAY_BOS before _run_signal_pipeline() is called, so the `if scan_mode
    is None` guard never passes. Added comment to document intent vs. reality.
    Not fixed (would require architectural change) but documented to prevent
    future confusion.
  BUG-SN-3 (non-crashing): _log_bos_event and _log_fvg_event were defined before
    logger was assigned (same root as BUG-SN-1). Resolved by BUG-SN-1 fix.
  All other checks CONFIRMED CLEAN — see AUDIT_REGISTRY.md Session 18.
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
from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING, BEAR_SIGNALS_ENABLED
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone
from app.filters.early_session_disqualifier import should_skip_cfw6_or_early

# Pipeline lives in sniper_pipeline.py (extracted to keep this file small)
from app.core.sniper_pipeline import _run_signal_pipeline as _pipeline

# BUG-SN-1 FIX: logger moved here — before all optional try/except blocks so
# any import-time exception is loggable immediately.
import logging
logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")  # FIX: was NameError in process_ticker regime_age calc

# ── Constants ──────────────────────────────────────────────────────────
EXPLOSIVE_SCORE_THRESHOLD = 80
EXPLOSIVE_RVOL_THRESHOLD  = 3.0
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
            for t in wl.get('all_tickers_with_scores', []):
                if t.get('ticker') == ticker:
                    score = t.get('score', 0)
                    rvol  = t.get('rvol', 0.0)
                    tier  = t.get('tier', None)
                    return {
                        'qualified': score >= EXPLOSIVE_SCORE_THRESHOLD and rvol >= EXPLOSIVE_RVOL_THRESHOLD,
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

try:
    from app.signals.opening_range import (
        or_detector, compute_opening_range_from_bars, compute_premarket_range,
        detect_breakout_after_or, detect_fvg_after_break,
    )
    ORB_TRACKER_ENABLED = True
    logger.info("[SNIPER] ✅ ORB Detector enabled")
except ImportError:
    ORB_TRACKER_ENABLED = False
    or_detector = None
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
                         skip_cfw6_confirmation=False):
    """
    Thin dispatcher — delegates to sniper_pipeline._run_signal_pipeline.
    Kept here so scanner.py import surface stays unchanged.

    FIX E (2026-03-26): Removed get_ticker_screener_metadata= and state= kwargs.
      Those were part of the old all-in-one sniper.py signature before the pipeline
      was extracted. sniper_pipeline absorbed them via **_unused_kwargs but passing
      them is dead weight — removed to keep the call surface clean.
    """
    return _pipeline(
        ticker, direction, zone_low, zone_high,
        or_high_ref, or_low_ref, signal_type,
        bars_session, breakout_idx,
        bos_confirmation=bos_confirmation,
        bos_candle_type=bos_candle_type,
        spy_regime=spy_regime,
        skip_cfw6_confirmation=skip_cfw6_confirmation,
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
                        f"[{ticker}] \U0001f680 EXPLOSIVE MOVER OVERRIDE: "
                        f"score={metadata['score']} rvol={metadata['rvol']:.1f}x "
                        f"tier={metadata['tier']} — regime filter bypassed"
                    )
                else:
                    state_r = regime_filter.get_regime_state()
                    logger.info(
                        f"[{ticker}] \U0001f6ab REGIME FILTER: {state_r.regime} "
                        f"(VIX:{state_r.vix:.1f}) — {state_r.reason}"
                    )
                    return

        if _state.ticker_is_armed(ticker):
            return

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
                logger.warning(f"[{ticker}] \u274c Data fetch failed: {e}")
                return

        logger.info(
            f"[{ticker}] {_now_et().date()} ({len(bars_session)} bars) "
            f"{_bar_time(bars_session[0])} \u2192 {_bar_time(bars_session[-1])}"
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
                        f"[{ticker}] \u26a0\ufe0f Watch DB entry: breakout bar "
                        f"{bar_dt_target} not found in today's session \u2014 discarding"
                    )
                    _state.remove_watching_signal(ticker)
                    _remove_watch_from_db(ticker)
                    return
                else:
                    _state.update_watching_signal_field(ticker, "breakout_idx", resolved_idx)
                    w["breakout_idx"] = resolved_idx
                    logger.info(
                        f"[{ticker}] \U0001f4c4 Watch restored from DB: "
                        f"breakout_idx={resolved_idx} ({bar_dt_target})"
                    )

            bars_since = len(bars_session) - w["breakout_idx"]
            if bars_since > MAX_WATCH_BARS:
                logger.info(f"[{ticker}] \u23f0 Watch expired \u2014 clearing")
                _state.remove_watching_signal(ticker)
                _remove_watch_from_db(ticker)
                return

            logger.info(f"[{ticker}] \U0001f441\ufe0f WATCHING [{bars_since}/{MAX_WATCH_BARS}]")
            fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
            fvg_result = find_fvg_after_bos(
                bars_session, w["breakout_idx"], w["direction"], min_pct=fvg_threshold
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
            or_range_pct  = (or_high - or_low) / or_low
            or_threshold  = _get_or_threshold(spy_regime)
            if or_range_pct < or_threshold:
                logger.info(
                    f"[{ticker}] OR too narrow "
                    f"({or_range_pct:.2%} < {or_threshold:.2%}) "
                    f"\u2014 skipping OR path, trying intraday BOS"
                )
            else:
                logger.info(f"[{ticker}] OR: ${or_low:.2f}\u2014${or_high:.2f} ({or_range_pct:.2%})")

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
                            logger.info(f"[{ticker}] \U0001f515 BOS watch alert suppressed (already sent)")
                        return
                else:
                    logger.info(f"[{ticker}] No ORB")

                # Secondary range fallback (after 10:30)
                if scan_mode is None and _now_et().time() >= time(10, 30):
                    from app.signals.opening_range import get_secondary_range_levels
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
                                    logger.info(f"[{ticker}] \U0001f515 BOS watch alert suppressed (already sent)")
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
                logger.info(f"[{ticker}] \u2014 No BOS+FVG signal")
                return

            direction    = bos_signal["direction"]
            breakout_idx = bos_signal["bos_idx"]
            bos_confirmation = bos_signal.get("confirmation")
            bos_candle_type  = bos_signal.get("candle_type")

            _log_bos_event(ticker, direction,
                           bos_signal.get("bos_price", bars_session[breakout_idx]["close"]),
                           "CFW6_INTRADAY")
            _log_fvg_event(ticker, direction, bos_signal["fvg_low"], bos_signal["fvg_high"],
                           "CFW6_INTRADAY")

            if MTF_PRIORITY_ENABLED:
                try:
                    mtf_analysis = get_full_mtf_analysis(
                        ticker=ticker, direction=direction,
                        bars_5m=bars_session, min_pct=fvg_threshold
                    )
                    primary_fvg = mtf_analysis['primary_fvg']
                    if primary_fvg is None:
                        logger.info(f"[{ticker}] \u2014 No FVGs found on any timeframe (MTF scan)")
                        return
                    zone_low  = primary_fvg['fvg_low']
                    zone_high = primary_fvg['fvg_high']
                    if mtf_analysis['has_conflict']:
                        logger.info(
                            f"[{ticker}] \U0001f3af MTF PRIORITY: {primary_fvg['timeframe']} FVG selected | "
                            f"Confluence: {mtf_analysis['confluence_count']} timeframe(s) | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                    else:
                        logger.info(
                            f"[{ticker}] \U0001f50d Single FVG on {primary_fvg['timeframe']} | "
                            f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                        )
                except Exception as priority_err:
                    logger.warning(f"[{ticker}] MTF priority error (falling back to 5m): {priority_err}")
                    zone_low  = bos_signal["fvg_low"]
                    zone_high = bos_signal["fvg_high"]
            else:
                zone_low  = bos_signal["fvg_low"]
                zone_high = bos_signal["fvg_high"]

            if direction == "bull":
                or_high_ref = bos_signal["bos_price"]
                or_low_ref  = zone_low
            else:
                or_high_ref = zone_high
                or_low_ref  = bos_signal["bos_price"]

            scan_mode = "INTRADAY_BOS"

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        logger.info(f"[{ticker}] {scan_mode} | FVG ${zone_low:.2f}\u2014${zone_high:.2f}")
        _run_signal_pipeline(
            ticker, direction, zone_low, zone_high,
            or_high_ref, or_low_ref, signal_type,
            bars_session, breakout_idx,
            bos_confirmation=bos_confirmation,
            bos_candle_type=bos_candle_type,
            spy_regime=spy_regime,
            skip_cfw6_confirmation=(scan_mode == "INTRADAY_BOS")
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
                    f"[{ticker}] \U0001f535 VWAP RECLAIM: {vr['direction'].upper()} "
                    f"@ ${vr['entry_price']:.2f} | VWAP=${vr['vwap']:.2f}"
                )
                _run_signal_pipeline(
                    ticker, vr["direction"],
                    vr["zone_low"], vr["zone_high"],
                    0.0, 0.0,
                    "CFW6_INTRADAY",
                    bars_session, vr["reclaim_bar_idx"],
                    spy_regime=spy_regime,
                    skip_cfw6_confirmation=True,
                )
            else:
                logger.info(f"[{ticker}] \u2014 No VWAP reclaim signal")

    except Exception as e:
        logger.error(f"process_ticker error {ticker}: {e}", exc_info=True)
