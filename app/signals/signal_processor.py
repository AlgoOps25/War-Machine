"""
Signal Processor with Analytics Integration
Wraps existing signal generation to add deduplication, tracking, and ML
"""
import logging
from datetime import datetime

try:
    from app.core.analytics_integration import AnalyticsIntegration
    from app.data.database import get_db_connection
    
    # Initialize analytics
    db_connection = get_db_connection()
    analytics = AnalyticsIntegration(
        db_connection,
        enable_ml=True,
        enable_discord=True
    )
    ANALYTICS_ENABLED = True
    logging.info("[SIGNAL_PROCESSOR] Analytics integration enabled")
except Exception as e:
    analytics = None
    ANALYTICS_ENABLED = False
    logging.warning(f"[SIGNAL_PROCESSOR] Analytics disabled: {e}")


def process_signal_with_analytics(signal_data, regime='NEUTRAL', vix_level=20.0, spy_trend='NEUTRAL'):
    """
    Process a signal through analytics before sending Discord alert
    
    Args:
        signal_data: Dict with ticker, pattern, confidence, entry, stop, t1, t2, rvol, score
        regime: Current market regime (BULL/BEAR/NEUTRAL)
        vix_level: Current VIX level
        spy_trend: SPY trend direction
        
    Returns:
        signal_id if signal should fire (and was logged), None if blocked by deduplication
    """
    if not ANALYTICS_ENABLED or not analytics:
        # Analytics disabled - allow signal through
        return True
    
    try:
        # Process through analytics (deduplication + ML + logging)
        signal_id = analytics.process_signal(
            signal_data=signal_data,
            regime=regime,
            vix_level=vix_level,
            spy_trend=spy_trend
        )
        
        return signal_id  # Returns ID if logged, None if blocked
        
    except Exception as e:
        logging.error(f"[SIGNAL_PROCESSOR] Analytics error: {e}")
        # On error, allow signal through (fail-safe)
        return True


def monitor_active_signals_with_analytics(price_fetcher):
    """
    Monitor active signals for T1/T2/Stop hits
    
    Args:
        price_fetcher: Function that takes ticker and returns current price
    """
    if not ANALYTICS_ENABLED or not analytics:
        return
    
    try:
        analytics.monitor_active_signals(price_fetcher=price_fetcher)
    except Exception as e:
        logging.error(f"[SIGNAL_PROCESSOR] Monitoring error: {e}")


def check_scheduled_tasks_with_analytics():
    """
    Run scheduled analytics tasks (market open/close routines)
    Call this once per minute in scanner loop
    """
    if not ANALYTICS_ENABLED or not analytics:
        return
    
    try:
        analytics.check_scheduled_tasks()
    except Exception as e:
        logging.error(f"[SIGNAL_PROCESSOR] Scheduled tasks error: {e}")


def get_today_analytics_stats():
    """
    Get today's analytics performance summary
    Returns: dict with total, wins, losses, etc. or None
    """
    if not ANALYTICS_ENABLED or not analytics:
        return None
    
    try:
        return analytics.get_today_stats()
    except Exception as e:
        logging.error(f"[SIGNAL_PROCESSOR] Stats error: {e}")
        return None
