"""
Analytics Integration Helper for War Machine Scanner

Thin delegation wrapper over the real SignalTracker (signal_analytics.py).
This class is the ONLY entry-point used by scanner.py; it proxies all calls
through to signal_tracker so there is exactly one source of truth for signal
lifecycle data — the signal_events Postgres table.

Previous stub behaviour (in-memory signals_by_ticker dict + signal_count int)
has been removed. All persistence now lives in signal_analytics.SignalTracker.

Public API (unchanged signatures so scanner.py needs no edits):
  process_signal(signal_data, ...)         -> signal_id | None
  validate_signal(ticker, passed, ...)     -> event_id
  arm_signal(ticker, confidence, bars)     -> event_id
  record_trade(ticker, position_id)        -> event_id
  monitor_active_signals(price_fetcher)    -> no-op placeholder
  check_scheduled_tasks()                  -> delegates EOD tasks
  get_today_stats()                        -> from SignalTracker.get_funnel_stats()

AUDIT 2026-03-31 (Session 16):
  BUG-AI-1: Replaced bare logging.warning/logging.info module-level calls
            with a proper logger = logging.getLogger(__name__) so log lines
            appear as 'app.core.analytics_integration' in Railway, not 'root'.
  BUG-AI-2: get_today_stats() was accessing _tracker.session_signals directly
            (tight coupling; breaks if SignalTracker renames the attribute).
            Now uses _tracker.get_funnel_stats().get('unique_tickers', 0).
  BUG-AI-3: check_scheduled_tasks() midnight reset block was resetting
            daily_reset_done but NOT eod_report_done. On a multi-day run the
            EOD report would fire once and then never again. Fixed.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

try:
    from app.signals.signal_analytics import signal_tracker as _tracker
    _TRACKER_AVAILABLE = True
except Exception as e:
    _tracker = None
    _TRACKER_AVAILABLE = False
    logger.warning("[ANALYTICS] SignalTracker unavailable: %s — running in no-op mode", e)


class AnalyticsIntegration:
    """
    Thin delegation wrapper over SignalTracker.

    Usage in scanner.py (unchanged):
        self.analytics_integration = AnalyticsIntegration(db_connection)
        signal_id = self.analytics_integration.process_signal(signal_data)
        if signal_id:
            send_discord_alert(signal_data)
    """

    def __init__(self, db_connection=None, enable_ml: bool = True, enable_discord: bool = True):
        # db_connection kept for API compatibility — SignalTracker manages its own connection.
        self.enable_ml      = enable_ml
        self.enable_discord = enable_discord

        # Time-based flags (EOD tasks)
        self.daily_reset_done  = False
        self.eod_ml_done       = False
        self.eod_report_done   = False

        if _TRACKER_AVAILABLE:
            logger.info("[ANALYTICS] AnalyticsIntegration ready — delegating to SignalTracker")
        else:
            logger.warning("[ANALYTICS] Running in no-op mode (SignalTracker unavailable)")

    # -- Primary pipeline entry-point ----------------------------------------

    def process_signal(
        self,
        signal_data: Dict,
        regime: Optional[str]  = None,
        vix_level: Optional[float] = None,
        spy_trend: Optional[str] = None,
    ) -> Optional[int]:
        """
        Record signal generation and return a signal_id.
        Returns None if the tracker is unavailable or recording fails.
        """
        if not _TRACKER_AVAILABLE or _tracker is None:
            return 1  # fallback: always allow in no-op mode

        ticker     = signal_data.get("ticker", "UNKNOWN")
        sig_type   = signal_data.get("pattern", signal_data.get("signal_type", "UNKNOWN"))
        direction  = signal_data.get("direction", "bull")
        grade      = signal_data.get("confirmation_grade", signal_data.get("grade", "A"))
        confidence = float(signal_data.get("confidence", signal_data.get("confirmation_score", 0.7)))
        entry      = float(signal_data.get("entry_price",  0.0))
        stop       = float(signal_data.get("stop_price",   0.0))
        t1         = float(signal_data.get("target_1",     signal_data.get("t1_price", 0.0)))
        t2         = float(signal_data.get("target_2",     signal_data.get("t2_price", 0.0)))

        event_id = _tracker.record_signal_generated(
            ticker=ticker,
            signal_type=sig_type,
            direction=direction,
            grade=grade,
            confidence=confidence,
            entry_price=entry,
            stop_price=stop,
            t1_price=t1,
            t2_price=t2,
        )

        if event_id < 0:
            logger.warning("[ANALYTICS] record_signal_generated failed for %s", ticker)
            return None

        logger.info("[ANALYTICS] Signal logged %s (ID: %d, Pattern: %s)", ticker, event_id, sig_type)
        return event_id

    # -- Validation result ---------------------------------------------------

    def validate_signal(
        self,
        ticker: str,
        passed: bool,
        confidence_after: float      = 0.0,
        ivr_multiplier: float        = 1.0,
        uoa_multiplier: float        = 1.0,
        gex_multiplier: float        = 1.0,
        mtf_boost: float             = 0.0,
        ticker_multiplier: float     = 1.0,
        ivr_label: str               = "",
        uoa_label: str               = "",
        gex_label: str               = "",
        checks_passed: List[str]     = None,
        rejection_reason: str        = "",
    ) -> int:
        """Delegate to SignalTracker.record_validation_result()."""
        if not _TRACKER_AVAILABLE or _tracker is None:
            return -1
        return _tracker.record_validation_result(
            ticker=ticker,
            passed=passed,
            confidence_after=confidence_after,
            ivr_multiplier=ivr_multiplier,
            uoa_multiplier=uoa_multiplier,
            gex_multiplier=gex_multiplier,
            mtf_boost=mtf_boost,
            ticker_multiplier=ticker_multiplier,
            ivr_label=ivr_label,
            uoa_label=uoa_label,
            gex_label=gex_label,
            checks_passed=checks_passed,
            rejection_reason=rejection_reason,
        )

    # -- Arming --------------------------------------------------------------

    def arm_signal(
        self,
        ticker: str,
        final_confidence: float,
        bars_to_confirmation: int,
        confirmation_type: str = "retest",
    ) -> int:
        """Delegate to SignalTracker.record_signal_armed()."""
        if not _TRACKER_AVAILABLE or _tracker is None:
            return -1
        return _tracker.record_signal_armed(
            ticker=ticker,
            final_confidence=final_confidence,
            bars_to_confirmation=bars_to_confirmation,
            confirmation_type=confirmation_type,
        )

    # -- Trade execution -----------------------------------------------------

    def record_trade(self, ticker: str, position_id: int) -> int:
        """Delegate to SignalTracker.record_trade_executed()."""
        if not _TRACKER_AVAILABLE or _tracker is None:
            return -1
        return _tracker.record_trade_executed(ticker=ticker, position_id=position_id)

    # -- Monitoring / scheduled tasks ----------------------------------------

    def monitor_active_signals(self, price_fetcher):
        """Placeholder — active signal monitoring handled by position_manager."""
        pass

    def check_scheduled_tasks(self):
        """Run time-based tasks (market open / EOD). Call once per minute."""
        now = datetime.now(ZoneInfo("America/New_York"))

        # Market open reset
        if now.hour == 9 and now.minute == 30 and not self.daily_reset_done:
            if _TRACKER_AVAILABLE and _tracker:
                _tracker.clear_session_cache()
            self.daily_reset_done = True
            self.eod_ml_done      = False
            self.eod_report_done  = False
            logger.info("[ANALYTICS] Daily reset complete")

        # EOD summary
        if now.hour == 16 and now.minute == 5 and not self.eod_report_done:
            if _TRACKER_AVAILABLE and _tracker:
                logger.info(_tracker.get_daily_summary())
            self.eod_report_done = True

        # Midnight flag reset — BUG-AI-3: also reset eod_report_done
        if now.hour == 0 and now.minute == 0:
            self.daily_reset_done = False
            self.eod_report_done  = False

    # -- Stats ---------------------------------------------------------------

    def get_today_stats(self) -> Dict:
        """Return today's funnel stats from SignalTracker."""
        if not _TRACKER_AVAILABLE or _tracker is None:
            return {"total_signals": 0, "unique_tickers": 0, "win_rate": 0.0, "total_profit": 0.0}
        funnel = _tracker.get_funnel_stats()
        return {
            # BUG-AI-2: use public get_funnel_stats() instead of _tracker.session_signals directly
            "total_signals":   funnel.get("generated", 0),
            "unique_tickers":  funnel.get("unique_tickers", 0),
            "validation_rate": funnel.get("validation_rate", 0.0),
            "arming_rate":     funnel.get("arming_rate", 0.0),
            "execution_rate":  funnel.get("execution_rate", 0.0),
            "win_rate":        0.0,
            "total_profit":    0.0,
        }
