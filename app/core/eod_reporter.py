"""
eod_reporter.py — End-of-day report dispatcher
Extracted from sniper.py process_ticker() EOD block.
Call run_eod_reports() when is_force_close_time() is True.
"""


def run_eod_reports(
    last_bar,
    *,
    validator_enabled=True,
    validator_test_mode=False,
    sd_zone_enabled=False,
    trackers_enabled=False,
    cooldown_tracker=None,
    explosive_tracker=None,
    grade_gate_tracker=None,
    phase_4_enabled=False,
    signal_tracker=None,
    performance_monitor=None,
    hourly_gate_enabled=False,
    regime_filter_enabled=False,
    order_block_enabled=False,
):
    """Fire all EOD reports and caches clears. Call once per ticker at force-close time."""
    from app.risk.position_manager import position_manager
    from app.core.sniper_log import print_validation_stats, print_validation_call_stats
    from app.core.gate_stats import print_gate_distribution_stats

    ticker_price = last_bar["close"]
    # Use a single-key dict — position_manager.close_all_eod expects {ticker: price}
    # Caller should pass the full prices dict if available; this is a safe fallback.
    position_manager.close_all_eod({"__eod__": ticker_price})

    print_validation_stats(validator_enabled, validator_test_mode)
    print_validation_call_stats()

    try:
        from app.mtf.mtf_integration import print_mtf_stats
        print_mtf_stats()
    except Exception as e:
        print(f"[EOD] MTF stats error: {e}")

    try:
        from app.mtf.mtf_fvg_priority import print_priority_stats
        print_priority_stats()
    except Exception as e:
        print(f"[EOD] MTF priority stats error: {e}")

    print_gate_distribution_stats()

    if sd_zone_enabled:
        try:
            from app.filters.sd_zone_confluence import clear_sd_cache
            clear_sd_cache()
            print("[SD-CACHE] 🧹 EOD clear — all S/D zones flushed")
        except Exception as e:
            print(f"[EOD] SD cache clear error: {e}")

    if trackers_enabled:
        if cooldown_tracker:
            try:
                cooldown_tracker.print_eod_report()
            except Exception as e:
                print(f"[EOD] Cooldown tracker report error: {e}")
        if explosive_tracker:
            try:
                from app.analytics.explosive_mover_tracker import print_explosive_override_summary
                print_explosive_override_summary()
            except Exception as e:
                print(f"[EOD] Explosive tracker report error: {e}")
        if grade_gate_tracker:
            try:
                grade_gate_tracker.print_eod_report()
            except Exception as e:
                print(f"[EOD] Grade gate tracker report error: {e}")

    if phase_4_enabled:
        try:
            if signal_tracker:
                print(signal_tracker.get_daily_summary())
            if performance_monitor:
                print(performance_monitor.get_daily_performance_report())
        except Exception as e:
            print(f"[PHASE 4] EOD report error: {e}")

    if hourly_gate_enabled:
        try:
            from app.validation.hourly_gate import print_hourly_gate_stats
            print_hourly_gate_stats()
        except Exception as e:
            print(f"[HOURLY GATE] EOD stats error: {e}")

    if regime_filter_enabled:
        try:
            from app.validation.validation import get_regime_filter
            get_regime_filter().print_regime_summary()
        except Exception as e:
            print(f"[EOD] Regime summary error: {e}")

    if order_block_enabled:
        try:
            from app.filters.order_block_cache import clear_ob_cache
            clear_ob_cache()
            print("[OB-CACHE] 🧹 EOD clear — all order blocks flushed")
        except Exception as e:
            print(f"[EOD] OB cache clear error: {e}")
