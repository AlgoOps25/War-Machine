import logging
logger = logging.getLogger(__name__)
"""
arm_signal.py — Signal Arming & Discord Alert
Extracted from sniper.py

Provides:
    arm_ticker()  — validates stop, opens position via risk manager,
                    fires Discord alert only on confirmed position open,
                    persists armed signal state, sets cooldown.

All heavy imports are deferred inside the function to avoid circular imports.

FIXED (Mar 16 2026): Wire record_trade_executed() after position_id > 0 so the
  TRADED stage is recorded in signal_events and get_funnel_stats() shows real counts.

FIX P3 (2026-03-25): vp_bias now passed in the fallback (non-production-helpers)
  Discord alert path, matching the production-helpers path. Previously the fallback
  path omitted vp_bias so VP bias data was silently dropped from Discord alerts
  whenever production_helpers was not available.
"""


def arm_ticker(
    ticker, direction, zone_low, zone_high, or_low, or_high,
    entry_price, stop_price, t1, t2, confidence, grade,
    options_rec=None, signal_type="CFW6_OR", validation_result=None,
    bos_confirmation=None, bos_candle_type=None, mtf_result=None, metadata=None,
    vp_bias=None
):
    """Phase 4 Funnel Fix: Wire record_signal_armed() into arm_ticker() (FIX 19.C-1)
    Arm a confirmed signal:
      1. Hard-reject if stop is tighter than 0.1% of entry.
      2. Open position via position_manager (risk-gated).
          # Phase 4 Funnel: Record ARMED stage
    try:
        from app.signals.signal_analytics import signal_tracker
        bars = 0
        if metadata and isinstance(metadata, dict):
            bars = metadata.get('bars_to_confirmation', 0)
        
        signal_tracker.record_signal_armed(
            ticker=ticker,
            final_confidence=confidence,
            bars_to_confirmation=bars,
            confirmation_type=bos_confirmation or 'retest'
        )
        logger.info(f"[ANALYTICS] 🎯 {ticker} ARMED stage recorded")
    except Exception as _arm_err:
        logger.info(f"[ANALYTICS] record_signal_armed error (non-fatal): {_arm_err}")

      3. Fire Discord alert only if position_id > 0.
      4. Persist to armed_signals_persist DB table.
      5. Record TRADED stage in signal_analytics (FIX Mar 16 2026).
      6. Set per-ticker cooldown.
    """
    from app.risk.position_manager import position_manager
    from app.core.thread_safe_state import get_state
    from app.core.armed_signal_store import _persist_armed_signal
    from app.screening.screener_integration import get_ticker_screener_metadata
    from app.notifications.discord_helpers import send_options_signal_alert
    from app.core.sniper_log import log_proposed_trade

    _state = get_state()

    if abs(entry_price - stop_price) < entry_price * 0.001:
        logger.info(f"[ARM] ⚠️ {ticker} stop too tight — skipping")
        return

    mode_label = " [OR]" if signal_type == "CFW6_OR" else " [INTRADAY]"
    logger.info(
        f"✅ {ticker} ARMED{mode_label}: {direction.upper()} | "
        f"Entry:${entry_price:.2f} Stop:${stop_price:.2f} "
        f"T1:${t1:.2f} T2:${t2:.2f} | {confidence*100:.1f}% ({grade})"
    )

    log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade)

    metadata = metadata or get_ticker_screener_metadata(ticker)

    mtf_convergence_count = 0
    if mtf_result and mtf_result.get('convergence'):
        mtf_convergence_count = len(mtf_result.get('timeframes', []))

    # Open position FIRST — only alert Discord if it succeeds (FIX C2)
    position_id = position_manager.open_position(
        ticker=ticker, direction=direction,
        zone_low=zone_low, zone_high=zone_high,
        or_low=or_low, or_high=or_high,
        entry_price=entry_price, stop_price=stop_price,
        t1=t1, t2=t2, confidence=confidence, grade=grade, options_rec=options_rec
    )

    if position_id == -1:
        logger.info(f"[ARM] ❌ {ticker} position rejected by risk manager — Discord alert suppressed")
        return

    # ── FIX (Mar 16 2026): Record TRADED stage in signal_analytics ─────────────────────
    # Without this call get_funnel_stats()['traded'] was always 0.
    try:
        from app.signals.signal_analytics import signal_tracker
        signal_tracker.record_trade_executed(ticker, position_id)
        logger.info(f"[ANALYTICS] 📊 {ticker} TRADED stage recorded (position_id={position_id})")
    except Exception as _analytics_err:
        logger.info(f"[ANALYTICS] record_trade_executed error (non-fatal): {_analytics_err}")

    # ── Discord alert (production helper path) ──────────────────────────────────────
    try:
        from utils.production_helpers import _send_alert_safe
        PRODUCTION_HELPERS_ENABLED = True
    except ImportError:
        PRODUCTION_HELPERS_ENABLED = False

    if PRODUCTION_HELPERS_ENABLED:
        _send_alert_safe(
            send_options_signal_alert,
            ticker=ticker, direction=direction,
            entry=entry_price, stop=stop_price, t1=t1, t2=t2,
            confidence=confidence, timeframe="5m", grade=grade,
            options_data=options_rec,
            confirmation=bos_confirmation, candle_type=bos_candle_type,
            rvol=metadata.get('rvol'),
            volume_rank=None,
            composite_score=metadata.get('score'),
            mtf_convergence=mtf_convergence_count,
            explosive_mover=metadata.get('qualified', False),
            vp_bias=vp_bias
        )
    else:
        # FIX P3 (2026-03-25): vp_bias added to fallback path — was missing, causing
        # VP bias data to be silently dropped from Discord alerts in this branch.
        try:
            greeks_data = None
            if options_rec:
                try:
                    from app.validation.greeks_precheck import get_cached_greeks
                    greeks_list = get_cached_greeks(ticker, direction)
                    if greeks_list:
                        best_option = greeks_list[0]
                        greeks_data = {
                            'is_valid': True,
                            'reason': f"ATM {direction.upper()} options available with good Greeks",
                            'best_strike': best_option['strike'],
                            'details': {
                                'delta': best_option['delta'],
                                'iv': best_option['iv'],
                                'dte': best_option['dte'],
                                'spread_pct': best_option['spread_pct'],
                                'liquidity_ok': best_option['is_liquid']
                            }
                        }
                except Exception as greeks_err:
                    logger.info(f"[ARM] Greeks data extraction error (non-fatal): {greeks_err}")

            send_options_signal_alert(
                ticker=ticker, direction=direction,
                entry=entry_price, stop=stop_price, t1=t1, t2=t2,
                confidence=confidence, timeframe="5m", grade=grade,
                options_data=options_rec,
                confirmation=bos_confirmation, candle_type=bos_candle_type,
                greeks_data=greeks_data,
                rvol=metadata.get('rvol'),
                volume_rank=None,
                composite_score=metadata.get('score'),
                mtf_convergence=mtf_convergence_count,
                explosive_mover=metadata.get('qualified', False),
                vp_bias=vp_bias  # P3 FIX: was missing from fallback path
            )
        except Exception as e:
            logger.info(f"[DISCORD] ❌ Alert failed: {e}")

    # ── Persist armed signal state ───────────────────────────────────────────────────
    armed_signal_data = {
        "position_id":  position_id,
        "direction":    direction,
        "entry_price":  entry_price,
        "stop_price":   stop_price,
        "t1":           t1,
        "t2":           t2,
        "confidence":   confidence,
        "grade":        grade,
        "signal_type":  signal_type,
        "validation":   validation_result,
    }
    _state.set_armed_signal(ticker, armed_signal_data)
    _persist_armed_signal(ticker, armed_signal_data)

    logger.info(f"[ARMED] {ticker} ID:{position_id}")

    # ── Cooldown ──────────────────────────────────────────────────────────────────────────────
    try:
        from app.analytics.cooldown_tracker import set_cooldown as _set_cooldown
        _set_cooldown(ticker, direction, signal_type)
    except Exception as e:
        logger.info(f"[COOLDOWN] Warning: could not set cooldown for {ticker}: {e}")

    # ── Phase 4 alert check ───────────────────────────────────────────────────────────
    try:
        from app.analytics.performance_monitor import performance_monitor
        from app.notifications.discord_helpers import send_simple_message
        # alert_manager not available; skip
    except Exception:
        pass
