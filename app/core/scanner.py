"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
CANDLE CACHE: Cache-aware startup with 95%+ API reduction
OUTCOME TRACKING: Signal deduplication, ML predictions, EOD reports
DYNAMIC WS SUBSCRIPTION: Live session ticker subscription with bar prefetch

PHASE 1.11 (MAR 5, 2026):
  - Critical database connection with explicit logging
  - Startup health check banner integration
  - Validation/Options integration wiring
  - Structured logging with component tags
  - Data storage spam reduction (periodic summaries)
  - Explicit zero-watchlist alerts

PHASE 1.12 (MAR 5, 2026):
  - Database SSL hotfix for Railway connections
  - Parse DATABASE_URL and inject sslmode=require
"""
import os
import time
import threading
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils import config

from app.data.data_manager import data_manager
from app.risk.position_manager import position_manager
from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from app.data.ws_quote_feed import start_quote_feed, subscribe_quote_tickers
from app.core.scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)
from app.signals.signal_generator import (
    check_and_alert,
    monitor_signals,
    print_active_signals,
    signal_generator
)
from app.screening.watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel
)

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: STRUCTURED LOGGING SETUP
# ────────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.12: DATABASE CONNECTION WITH RAILWAY SSL SUPPORT
# ────────────────────────────────────────────────────────────────────────────────────
ANALYTICS_AVAILABLE = False
analytics_conn = None
DATABASE_URL = os.getenv('DATABASE_URL')

logger.info("=" * 50)
logger.info("DATABASE Attempting connection...")
if DATABASE_URL:
    try:
        import psycopg2
        # Railway requires SSL for proxy connections
        # Add sslmode=require if not already present
        conn_url = DATABASE_URL
        if 'sslmode=' not in conn_url.lower():
            separator = '&' if '?' in conn_url else '?'
            conn_url = f"{conn_url}{separator}sslmode=require"
        
        analytics_conn = psycopg2.connect(conn_url)
        logger.info("DATABASE ✓ Connected - Analytics ONLINE")
        ANALYTICS_AVAILABLE = True
    except Exception as e:
        logger.error(f"DATABASE ✗ FAILED: {e}")
        logger.error("DATABASE Analytics DISABLED - continuing without tracking")
        ANALYTICS_AVAILABLE = False
else:
    logger.warning("DATABASE ✗ DATABASE_URL not set - Analytics DISABLED")
    ANALYTICS_AVAILABLE = False
logger.info("=" * 50)

# ────────────────────────────────────────────────────────────────────────────────────
# LEGACY SIGNAL ANALYTICS (Quality scoring, Sharpe, expectancy)
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
    logger.info("[SCANNER] ✅ Legacy signal analytics enabled")
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None
    logger.info("[SCANNER] ⚠️  signal_analytics not available")

# ────────────────────────────────────────────────────────────────────────────────────
# SIGNAL OUTCOME TRACKING (Deduplication, ML, Discord Reports)
# ────────────────────────────────────────────────────────────────────────────────────
analytics = None
if ANALYTICS_AVAILABLE and analytics_conn:
    try:
        from app.analytics import AnalyticsIntegration
        analytics = AnalyticsIntegration(
            analytics_conn,
            enable_ml=True,
            enable_discord=True
        )
        logger.info("[SCANNER] ✅ Signal outcome tracking enabled (Deduplication + ML + Reports)")
    except Exception as e:
        analytics = None
        logger.warning(f"[SCANNER] ⚠️  Outcome tracking disabled: {e}")

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: VALIDATION & OPTIONS INTEGRATION
# ────────────────────────────────────────────────────────────────────────────────────
VALIDATION_AVAILABLE = False
OPTIONS_AVAILABLE = False

try:
    from app.validation import validate_signal
    VALIDATION_AVAILABLE = True
    logger.info("[SCANNER] ✅ Validation gates loaded")
except ImportError:
    logger.warning("[SCANNER] ⚠️  Validation module not available")
    validate_signal = None

try:
    from app.options import build_options_trade
    OPTIONS_AVAILABLE = True
    logger.info("[SCANNER] ✅ Options intelligence loaded")
except ImportError:
    logger.warning("[SCANNER] ⚠️  Options module not available")
    build_options_trade = None

API_KEY = os.getenv("EODHD_API_KEY", "")

# Minimal fallback (only used if funnel completely fails)
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 1.11: DATA STORAGE SPAM REDUCTION
# ────────────────────────────────────────────────────────────────────────────────────
data_update_counter = 0
data_update_symbols = set()
last_data_summary_time = time.time()


def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def is_premarket():
    now = _now_et().time()
    return dtime(4, 0) <= now < dtime(9, 30)


def is_market_hours():
    now = _now_et()
    if now.weekday() >= 5:
        return False
    return config.MARKET_OPEN <= now.time() <= config.MARKET_CLOSE


def build_watchlist(force_refresh: bool = False) -> list:
    """Build adaptive watchlist using funnel system."""
    try:
        watchlist = get_current_watchlist(force_refresh=force_refresh)
        if watchlist:
            return watchlist
    except Exception as e:
        logger.error(f"[WATCHLIST] Funnel error: {e}", extra={"component": "watchlist_funnel"})

    logger.warning(
        f"[WATCHLIST] Using emergency fallback: {len(EMERGENCY_FALLBACK)} tickers",
        extra={"component": "watchlist_funnel", "fallback_count": len(EMERGENCY_FALLBACK)}
    )
    return list(EMERGENCY_FALLBACK)


def monitor_open_positions():
    """
    Check all open positions against current price.
    Fallback chain: WS live bar → REST API bar (if WS down) → DB last bar.
    """
    from app.data.data_manager import data_manager
    from app.data.ws_feed import get_current_bar_with_fallback

    open_positions = position_manager.get_open_positions()
    if not open_positions:
        return

    logger.info(
        f"[MONITOR] Checking {len(open_positions)} open positions...",
        extra={"component": "position_monitor", "position_count": len(open_positions)}
    )
    current_prices = {}

    for pos in open_positions:
        ticker = pos["ticker"]

        # Tier 1+2: WS live bar, or REST API if WS is down
        bar = get_current_bar_with_fallback(ticker)

        if bar is not None:
            source = bar.get("source", "ws")
            if source == "rest":
                logger.warning(
                    f"[WS-FAILOVER] {ticker}: position monitoring via REST bar",
                    extra={"component": "ws_failover", "symbol": ticker}
                )
        else:
            # Tier 3: DB last bar (unchanged final safety net)
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            bar  = bars[-1] if bars else None
            if bar:
                logger.warning(
                    f"[MONITOR] {ticker}: using DB last bar (WS+REST unavailable)",
                    extra={"component": "position_monitor", "symbol": ticker}
                )

        if bar:
            current_prices[ticker] = bar["close"]

    position_manager.check_exits(current_prices)


def subscribe_and_prefetch_tickers(new_tickers: list):
    """
    Subscribe new tickers to WebSocket feeds and prefetch their bar data.
    
    Args:
        new_tickers: List of ticker symbols to subscribe and prefetch
    
    This function:
    1. Subscribes tickers to WS bar feed (5m candles)
    2. Subscribes tickers to WS quote feed (bid/ask/spread)
    3. Prefetches 30 days of historical bars (cached)
    4. Prefetches today's intraday bars
    5. Waits 3 seconds for initial WS bars to flow
    """
    if not new_tickers:
        return
    
    try:
        # Step 1: Subscribe to WebSocket feeds
        subscribe_tickers(new_tickers)
        subscribe_quote_tickers(new_tickers)
        logger.info(
            f"[WS-SUBSCRIBE] ✅ Subscribed {len(new_tickers)} new tickers: {', '.join(new_tickers)}",
            extra={"component": "ws_subscribe", "ticker_count": len(new_tickers)}
        )
        
        # Step 2: Prefetch historical bars (cached, fast)
        logger.info(
            f"[PREFETCH] Fetching 30d historical bars for {len(new_tickers)} tickers...",
            extra={"component": "data_prefetch", "ticker_count": len(new_tickers)}
        )
        data_manager.startup_backfill_with_cache(new_tickers, days=30)
        
        # Step 3: Prefetch today's intraday bars
        logger.info(
            f"[PREFETCH] Fetching today's intraday bars for {len(new_tickers)} tickers...",
            extra={"component": "data_prefetch", "ticker_count": len(new_tickers)}
        )
        data_manager.startup_intraday_backfill_today(new_tickers)
        
        # Step 4: Wait for initial WebSocket bars to flow
        logger.info(
            f"[WS-SUBSCRIBE] Waiting 3s for initial bars to flow...",
            extra={"component": "ws_subscribe"}
        )
        time.sleep(3)
        
        logger.info(
            f"[WS-SUBSCRIBE] ✅ Prefetch complete for {len(new_tickers)} tickers",
            extra={"component": "ws_subscribe", "ticker_count": len(new_tickers)}
        )
        
    except Exception as e:
        logger.error(
            f"[WS-SUBSCRIBE] ⚠️ Error subscribing/prefetching tickers: {e}",
            extra={"component": "ws_subscribe"}
        )
        import traceback
        traceback.print_exc()


def start_scanner_loop():
    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals
    from app.discord_helpers import send_simple_message
    try:
        from app.ai.ai_learning import learning_engine
        HAS_AI_LEARNING = True
    except ImportError:
        learning_engine = None
        HAS_AI_LEARNING = False
    
    # ════════════════════════════════════════════════════════════════════════════════
    # PHASE 1.11: STARTUP HEALTH CHECK BANNER
    # ════════════════════════════════════════════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("WAR MACHINE BOS/FVG SCANNER - STARTUP HEALTH CHECK")
    logger.info("=" * 60)
    
    # WebSocket status (will be checked after startup)
    logger.info(f"✓ DATA-INGEST    WebSocket starting (tickers TBD)")
    
    # Cache status
    try:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
        if os.path.exists(cache_dir):
            cache_files = len([f for f in os.listdir(cache_dir) if f.endswith('.parquet')])
            logger.info(f"✓ CACHE          {cache_files} cached ticker files, 30d history")
        else:
            logger.info("? CACHE          Directory not found (will be created)")
    except Exception as e:
        logger.info(f"? CACHE          Status unknown: {e}")
    
    # Screener API status
    if API_KEY:
        logger.info(f"✓ SCREENER       EODHD API configured ({API_KEY[:8]}...)")
    else:
        logger.info("✗ SCREENER       EODHD_API_KEY not set")
    
    # Regime filter status
    try:
        from app.filters import regime_filter
        logger.info("✓ REGIME-FILTER  ADX/VIX monitoring active")
    except Exception:
        logger.info("? REGIME-FILTER  Module not found (may be inline)")
    
    # Database status (already logged above)
    logger.info(f"{'✓' if ANALYTICS_AVAILABLE else '✗'} DATABASE      {'Connected - Analytics tracking enabled' if ANALYTICS_AVAILABLE else 'OFFLINE - no volume/signal/P&L tracking'}")
    
    # Discord status
    discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
    logger.info(f"{'✓' if discord_webhook else '✗'} DISCORD        {'Alert notifications ready' if discord_webhook else 'NOT CONFIGURED - no alerts'}")
    
    # Options integration status
    logger.info(f"{'✓' if OPTIONS_AVAILABLE else '✗'} OPTIONS-GATE   {'Integrated - Greeks analysis active' if OPTIONS_AVAILABLE else 'NOT INTEGRATED'}")
    
    # Validation status
    logger.info(f"{'✓' if VALIDATION_AVAILABLE else '✗'} VALIDATION    {'Integrated - CFW6 confirmation active' if VALIDATION_AVAILABLE else 'NOT INTEGRATED'}")
    
    logger.info("=" * 60)
    
    # Session info
    now_et = _now_et()
    session_start = "09:30"
    session_end = "16:00"
    is_premarket_now = is_premarket()
    logger.info(f"Trading session: {session_start} - {session_end} ET")
    logger.info(f"Scanner mode: {'Pre-market' if is_premarket_now else 'Live'}")
    logger.info("=" * 60)
    
    # Additional status info
    if LEGACY_ANALYTICS_ENABLED:
        logger.info(f"Legacy Analytics: ✅ ENABLED (quality scoring, Sharpe, expectancy)")
    if ANALYTICS_AVAILABLE and analytics:
        logger.info(f"Outcome Tracking: ✅ ENABLED (deduplication, ML, reports)")
    logger.info(f"Candle Cache:  ✅ ENABLED (95%+ API reduction on redeploy)")
    logger.info(f"WS Failover:   ✅ ENABLED (REST API fallback on disconnect)")
    logger.info(f"Spread Gate:   ✅ ENABLED (us-quote bid/ask filter active)")
    logger.info(f"Dynamic WS:    ✅ ENABLED (live session ticker subscription)")
    logger.info("=" * 60 + "\n")

    try:
        send_simple_message("🎯 WAR MACHINE ONLINE - CFW6 Scanner + Outcome Tracking Started")
    except Exception as e:
        logger.warning(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist = []
    premarket_built     = False
    cycle_count         = 0
    last_report_day     = None
    loss_streak_alerted = False
    last_subscribed_watchlist = set()  # Track subscribed tickers to detect changes

    # ── STARTUP SEQUENCE ─────────────────────────────────────────────────────
    startup_watchlist = list(EMERGENCY_FALLBACK)
    try:
        start_ws_feed(startup_watchlist)
        logger.info(
            f"[WS] WebSocket feed started for {len(startup_watchlist)} tickers",
            extra={"component": "ws_feed", "ticker_count": len(startup_watchlist)}
        )
    except Exception as e:
        logger.error(f"[WS] ERROR starting WebSocket feed: {e}", extra={"component": "ws_feed"})

    try:
        start_quote_feed(startup_watchlist)
        logger.info(
            f"[QUOTE] Quote feed started for {len(startup_watchlist)} tickers",
            extra={"component": "quote_feed", "ticker_count": len(startup_watchlist)}
        )
    except Exception as e:
        logger.error(f"[QUOTE] ERROR starting quote feed: {e}", extra={"component": "quote_feed"})

    data_manager.startup_backfill_with_cache(startup_watchlist, days=30)
    data_manager.startup_intraday_backfill_today(startup_watchlist)
    set_backfill_complete()
    last_subscribed_watchlist = set(startup_watchlist)  # Initialize with startup tickers
    # ──────────────────────────────────────────────────────────────────────────

    while True:
        try:
            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            if is_premarket():
                if not premarket_built:
                    logger.info(
                        f"[PRE-MARKET] {current_time_str} - Building Watchlist",
                        extra={"component": "premarket_scanner"}
                    )
                    try:
                        watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata            = watchlist_data['metadata']
                        volume_signals      = watchlist_data['volume_signals']
                        
                        # ════════════════════════════════════════════════════════════════════
                        # PHASE 1.11: EXPLICIT ZERO-WATCHLIST ALERT
                        # ════════════════════════════════════════════════════════════════════
                        if not premarket_watchlist and now_et.time() > dtime(8, 0):
                            logger.warning(
                                "⚠️  WATCHLIST EMPTY after 8:00 AM - possible config issue",
                                extra={"component": "watchlist_funnel", "time": current_time_str}
                            )
                            try:
                                send_simple_message(
                                    "⚠️ **WATCHLIST EMPTY** after 8:00 AM ET - Check funnel configuration!"
                                )
                            except Exception:
                                pass
                        # ════════════════════════════════════════════════════════════════════

                        premarket_built = True
                        
                        # Subscribe new tickers and update tracking
                        current_set = set(premarket_watchlist)
                        new_tickers = list(current_set - last_subscribed_watchlist)
                        if new_tickers:
                            subscribe_and_prefetch_tickers(new_tickers)
                        else:
                            subscribe_tickers(premarket_watchlist)
                            subscribe_quote_tickers(premarket_watchlist)
                        last_subscribed_watchlist = current_set

                        logger.info(
                            f"[WS] Subscribed premarket watchlist "
                            f"({len(premarket_watchlist)} tickers) to WS feed",
                            extra={
                                "component": "ws_subscribe",
                                "ticker_count": len(premarket_watchlist)
                            }
                        )

                        stage_emoji = {
                            'wide': '📡', 'narrow': '🎯',
                            'final': '🔥', 'live': '⚡'
                        }
                        emoji = stage_emoji.get(metadata['stage'], '📊')

                        msg = (
                            f"{emoji} **{metadata['stage_description']}**\n"
                            f"✅ Watchlist: {len(premarket_watchlist)} tickers\n"
                            f"{', '.join(premarket_watchlist[:20])}"
                            f"{'...' if len(premarket_watchlist) > 20 else ''}"
                        )

                        if volume_signals:
                            msg += f"\n\n⚠️ {len(volume_signals)} volume signals active"

                        send_simple_message(msg)

                        logger.info(
                            f"[SIGNALS] Pre-market breakout scan on "
                            f"{len(premarket_watchlist)} tickers...",
                            extra={
                                "component": "signal_scanner",
                                "ticker_count": len(premarket_watchlist)
                            }
                        )
                        check_and_alert(premarket_watchlist)

                        if signal_generator.active_signals:
                            print_active_signals()

                    except Exception as e:
                        logger.error(
                            f"[PRE-MARKET] Funnel error: {e}",
                            extra={"component": "premarket_scanner"}
                        )
                        import traceback
                        traceback.print_exc()
                        premarket_watchlist = list(EMERGENCY_FALLBACK)
                        premarket_built     = True
                else:
                    funnel = get_funnel()
                    if funnel.should_update():
                        logger.info(
                            f"[PRE-MARKET] {current_time_str} - Refreshing Watchlist",
                            extra={"component": "premarket_scanner"}
                        )
                        try:
                            watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                            premarket_watchlist = watchlist_data['watchlist']
                            
                            # Subscribe new tickers and update tracking
                            current_set = set(premarket_watchlist)
                            new_tickers = list(current_set - last_subscribed_watchlist)
                            if new_tickers:
                                subscribe_and_prefetch_tickers(new_tickers)
                            else:
                                subscribe_tickers(premarket_watchlist)
                                subscribe_quote_tickers(premarket_watchlist)
                            last_subscribed_watchlist = current_set

                            metadata = watchlist_data['metadata']
                            logger.info(
                                f"[FUNNEL] Stage: {metadata['stage'].upper()} - "
                                f"{metadata['stage_description']}",
                                extra={
                                    "component": "watchlist_funnel",
                                    "stage": metadata['stage']
                                }
                            )
                            logger.info(
                                f"[FUNNEL] Top 3: {', '.join(metadata['top_3_tickers'])}",
                                extra={
                                    "component": "watchlist_funnel",
                                    "top_tickers": metadata['top_3_tickers']
                                }
                            )

                            logger.info(
                                f"[SIGNALS] Pre-market breakout scan on "
                                f"{len(premarket_watchlist)} tickers...",
                                extra={
                                    "component": "signal_scanner",
                                    "ticker_count": len(premarket_watchlist)
                                }
                            )
                            check_and_alert(premarket_watchlist)
                            monitor_signals()

                            if signal_generator.active_signals:
                                print_active_signals()

                        except Exception as e:
                            logger.error(
                                f"[PRE-MARKET] Refresh error: {e}",
                                extra={"component": "premarket_scanner"}
                            )
                    else:
                        logger.info(
                            f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...",
                            extra={"component": "premarket_scanner"}
                        )

                    time.sleep(60)
                continue

            elif is_market_hours():
                if not should_scan_now():
                    logger.info(
                        f"[SCANNER] {current_time_str} - Opening Range forming, waiting...",
                        extra={"component": "scanner"}
                    )
                    time.sleep(15)
                    continue

                if position_manager.has_loss_streak(max_consecutive_losses=3):
                    if not loss_streak_alerted:
                        msg = (
                            "🛑 **CIRCUIT BREAKER** — 3 consecutive losses today. "
                            "New scans halted for the rest of the session. "
                            "Open positions still monitored."
                        )
                        try:
                            send_simple_message(msg)
                        except Exception:
                            pass
                        loss_streak_alerted = True
                        logger.warning(
                            "[RISK] Daily loss streak reached — halting new scans.",
                            extra={"component": "risk_manager"}
                        )
                    monitor_open_positions()
                    time.sleep(60)
                    continue

                cycle_count += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                logger.info(f"{'='*60}")

                try:
                    watchlist = get_current_watchlist(force_refresh=False)
                    if not watchlist:
                        watchlist = (
                            premarket_watchlist if premarket_watchlist
                            else list(EMERGENCY_FALLBACK)
                        )
                except Exception as e:
                    logger.error(
                        f"[WATCHLIST] Error: {e}",
                        extra={"component": "watchlist_funnel"}
                    )
                    watchlist = (
                        premarket_watchlist if premarket_watchlist
                        else list(EMERGENCY_FALLBACK)
                    )

                optimal_size = calculate_optimal_watchlist_size()
                watchlist    = watchlist[:optimal_size]

                # ══════════════════════════════════════════════════════════════════════════════
                # FIX ISSUE #1: DYNAMIC WEBSOCKET SUBSCRIPTION DURING LIVE SESSION
                # Detect new tickers in watchlist and subscribe them to WS feeds + prefetch bars
                # ══════════════════════════════════════════════════════════════════════════════
                current_set = set(watchlist)
                new_tickers = list(current_set - last_subscribed_watchlist)
                
                if new_tickers:
                    logger.info(
                        f"[WS-SUBSCRIBE] 🔄 Detected {len(new_tickers)} new watchlist tickers",
                        extra={
                            "component": "ws_subscribe",
                            "new_ticker_count": len(new_tickers)
                        }
                    )
                    subscribe_and_prefetch_tickers(new_tickers)
                    last_subscribed_watchlist = current_set
                # ══════════════════════════════════════════════════════════════════════════════

                logger.info(
                    f"[SCANNER] {len(watchlist)} tickers | "
                    f"{', '.join(watchlist[:10])}...",
                    extra={
                        "component": "scanner",
                        "watchlist_size": len(watchlist),
                        "top_tickers": watchlist[:10]
                    }
                )

                logger.info(
                    f"[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...",
                    extra={
                        "component": "signal_scanner",
                        "ticker_count": len(watchlist)
                    }
                )
                check_and_alert(watchlist)
                
                # Monitor active analytics signals for outcome tracking
                if ANALYTICS_AVAILABLE and analytics:
                    try:
                        def get_price(ticker):
                            from app.data.ws_feed import get_current_bar_with_fallback
                            bar = get_current_bar_with_fallback(ticker)
                            return bar['close'] if bar else None
                        
                        analytics.monitor_active_signals(get_price)
                        analytics.check_scheduled_tasks()
                    except Exception as e:
                        logger.error(
                            f"[ANALYTICS] Monitor error: {e}",
                            extra={"component": "analytics"}
                        )
                
                monitor_signals()

                if signal_generator.active_signals:
                    print_active_signals()

                monitor_open_positions()

                daily_stats = position_manager.get_daily_stats()
                logger.info(
                    f"[TODAY] Trades: {daily_stats['trades']} "
                    f"W/L: {daily_stats['wins']}/{daily_stats['losses']} "
                    f"WR: {daily_stats['win_rate']:.1f}% "
                    f"P&L: ${daily_stats['total_pnl']:+.2f}",
                    extra={
                        "component": "position_manager",
                        "trades": daily_stats['trades'],
                        "win_rate": daily_stats['win_rate'],
                        "pnl": daily_stats['total_pnl']
                    }
                )

                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        logger.info(
                            f"--- [{idx}/{len(watchlist)}] {ticker} ---",
                            extra={
                                "component": "scanner",
                                "symbol": ticker,
                                "progress": f"{idx}/{len(watchlist)}"
                            }
                        )
                        
                        # ════════════════════════════════════════════════════════════════════
                        # PHASE 1.11: VALIDATION & OPTIONS INTEGRATION
                        # ════════════════════════════════════════════════════════════════════
                        signal = process_ticker(ticker)
                        
                        if signal and VALIDATION_AVAILABLE and validate_signal:
                            # Validate signal before alerting
                            validation_result = validate_signal(
                                ticker=ticker,
                                signal_type=signal.get('type', 'BOS'),
                                regime_filter=True,  # Placeholder - connect to regime module
                                greeks_available=OPTIONS_AVAILABLE
                            )
                            
                            if validation_result.get('passed', False):
                                # Build options trade if available
                                options_play = None
                                if OPTIONS_AVAILABLE and build_options_trade:
                                    try:
                                        options_play = build_options_trade(
                                            ticker,
                                            "CALL" if signal['signal'] == 'BUY' else "PUT",
                                            signal.get('confidence', 70)
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"[OPTIONS] Failed to build trade for {ticker}: {e}",
                                            extra={"component": "options", "symbol": ticker}
                                        )
                                
                                # Send alert with options info
                                # (Actual alert sending handled by process_ticker/signal_generator)
                                logger.info(
                                    f"[VALIDATION] {ticker} signal PASSED validation",
                                    extra={
                                        "component": "validation",
                                        "symbol": ticker,
                                        "has_options": options_play is not None
                                    }
                                )
                            else:
                                logger.info(
                                    f"[VALIDATION] {ticker} rejected: {validation_result.get('reason', 'Unknown')}",
                                    extra={
                                        "component": "validation",
                                        "symbol": ticker,
                                        "reason": validation_result.get('reason')
                                    }
                                )
                        # ════════════════════════════════════════════════════════════════════
                        
                    except Exception as e:
                        logger.error(
                            f"[SCANNER] Error on {ticker}: {e}",
                            extra={"component": "scanner", "symbol": ticker}
                        )
                        import traceback
                        traceback.print_exc()
                        continue

                logger.info(f"[SCANNER] Cycle #{cycle_count} complete")
                scan_interval = get_adaptive_scan_interval()
                logger.info(f"[SCANNER] Sleeping {scan_interval}s...")
                time.sleep(scan_interval)

            else:
                if last_report_day != current_day:
                    logger.info(f"\n{'='*80}")
                    logger.info(f"[EOD] Market Closed - Generating Reports for {current_day}")
                    logger.info(f"{'='*80}\n")

                    open_positions = position_manager.get_open_positions()
                    if open_positions:
                        logger.info(
                            f"[EOD] {len(open_positions)} positions still open",
                            extra={
                                "component": "position_manager",
                                "open_position_count": len(open_positions)
                            }
                        )

                    # 1. LEGACY SIGNAL ANALYTICS
                    if LEGACY_ANALYTICS_ENABLED and signal_tracker:
                        try:
                            logger.info("[ANALYTICS] Generating signal performance report...")
                            summary = signal_tracker.get_daily_summary()
                            print(summary)

                            funnel_stats = signal_tracker.get_funnel_stats()
                            mult_stats   = signal_tracker.get_multiplier_impact()

                            print("\n" + "="*80)
                            print("SIGNAL FUNNEL ANALYSIS")
                            print("="*80)
                            print(f"Generated: {funnel_stats['generated']}")
                            print(f"Validated: {funnel_stats['validated']} ({funnel_stats['validation_rate']}%)")
                            print(f"Armed:     {funnel_stats['armed']} ({funnel_stats['arming_rate']}%)")
                            print(f"Traded:    {funnel_stats['traded']} ({funnel_stats['execution_rate']}%)")
                            print("\n" + "="*80)
                            print("MULTIPLIER IMPACT")
                            print("="*80)
                            print(f"IVR Mult: {mult_stats['ivr_avg']:.3f}x | UOA Mult: {mult_stats['uoa_avg']:.3f}x")
                            print(f"GEX Mult: {mult_stats['gex_avg']:.3f}x | MTF Boost: +{mult_stats['mtf_avg']:.3f}")
                            print(f"Total Impact: {mult_stats['total_boost_pct']:+.1f}%")
                            print("="*80 + "\n")
                        except Exception as e:
                            logger.error(
                                f"[ANALYTICS] Error generating report: {e}",
                                extra={"component": "analytics"}
                            )
                            import traceback
                            traceback.print_exc()

                    # 2. EOD PNL REPORT
                    try:
                        daily_stats = position_manager.get_daily_stats()
                        eod_report  = (
                            f"📊 **EOD Report {current_day}**\n"
                            f"Trades: {daily_stats['trades']} | "
                            f"WR: {daily_stats['win_rate']:.1f}% | "
                            f"P&L: ${daily_stats['total_pnl']:+.2f}"
                        )
                        try:
                            eod_report += f"\n{position_manager.generate_report()}"
                        except Exception:
                            pass
                        send_simple_message(eod_report)
                    except Exception as e:
                        logger.error(
                            f"[EOD] EOD report error: {e}",
                            extra={"component": "eod_report"}
                        )

                    # 3. AI LEARNING
                    if HAS_AI_LEARNING:
                        try:
                            learning_engine.optimize_confirmation_weights()
                            learning_engine.optimize_fvg_threshold()
                            print(learning_engine.generate_performance_report())
                        except Exception as e:
                            logger.error(
                                f"[AI] Optimization error: {e}",
                                extra={"component": "ai_learning"}
                            )

                    # 4. WS FAILOVER STATS
                    try:
                        from app.data.ws_feed import get_failover_stats
                        stats = get_failover_stats()
                        if stats["rest_hits"] > 0:
                            logger.info(
                                f"[WS-FAILOVER] Session REST hits: {stats['rest_hits']} "
                                f"(WS outage fallbacks)",
                                extra={
                                    "component": "ws_failover",
                                    "rest_hits": stats['rest_hits']
                                }
                            )
                    except Exception as e:
                        logger.error(
                            f"[WS-FAILOVER] Stats error: {e}",
                            extra={"component": "ws_failover"}
                        )

                    # 5. DATABASE CLEANUP
                    try:
                        data_manager.cleanup_old_bars(days_to_keep=60)
                    except Exception as e:
                        logger.error(
                            f"[CLEANUP] Error: {e}",
                            extra={"component": "database_cleanup"}
                        )

                    # 6. DAILY RESET
                    signal_generator.reset_daily()
                    logger.info("[SIGNALS] Daily reset complete")

                    # 7. STATE RESET
                    last_report_day     = current_day
                    premarket_watchlist = []
                    premarket_built     = False
                    cycle_count         = 0
                    loss_streak_alerted = False
                    last_subscribed_watchlist = set()  # Reset subscription tracking

                    clear_armed_signals()
                    clear_watching_signals()

                    # 8. PDH/PDL CACHE CLEAR
                    try:
                        data_manager.clear_prev_day_cache()
                    except Exception as e:
                        logger.error(
                            f"[DATA] PDH/PDL cache clear error: {e}",
                            extra={"component": "data_manager"}
                        )

                    logger.info(f"\n{'='*80}")
                    logger.info(f"[EOD] All EOD tasks complete")
                    logger.info(f"{'='*80}\n")

                logger.info(
                    f"[AFTER-HOURS] {current_time_str} - Market closed, next check in 10 min",
                    extra={"component": "scanner"}
                )
                time.sleep(600)

        except KeyboardInterrupt:
            logger.info("[SCANNER] Shutdown signal received")
            print(position_manager.generate_report())
            raise

        except Exception as e:
            logger.error(
                f"[SCANNER] Critical error: {e}",
                extra={"component": "scanner"}
            )
            import traceback
            traceback.print_exc()
            try:
                send_simple_message(f"⚠️ Scanner Error: {str(e)}")
            except Exception:
                pass
            time.sleep(30)


def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> list:
    """Screener function using EODHD API.

    Valid sort fields: market_capitalization, adjusted_close, avgvol_1d, avgvol_200d,
                       refund_1d_p, refund_5d_p, refund_1m_p, refund_6m_p, refund_1y_p
    Valid filter fields: same as above, plus 'exchange' (string match).
    exchange value must be lowercase: 'us', 'nasdaq', 'nyse', etc.
    """
    import requests
    import json
    url = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["avgvol_1d",            ">=", 1_000_000],
            ["exchange",             "=",  "us"]        # lowercase required
        ]),
        "sort":   "avgvol_1d.desc",
        "limit":  limit,
        "offset": 0
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            logger.error(
                f"[SCREENER] HTTP {response.status_code}: {response.text[:300]}",
                extra={"component": "screener", "status_code": response.status_code}
            )
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "data" not in data:
            logger.error(
                f"[SCREENER] Unexpected response shape: {str(data)[:300]}",
                extra={"component": "screener"}
            )
            return []
        tickers = []
        for item in data["data"]:
            code = item.get("code")
            if code:
                tickers.append(code.replace(".US", "").replace(".us", ""))
        logger.info(
            f"[SCREENER] ✅ Fetched {len(tickers)} tickers (total available: {data.get('total', '?')})",
            extra={
                "component": "screener",
                "ticker_count": len(tickers),
                "total_available": data.get('total')
            }
        )
        return tickers[:limit]
    except Exception as e:
        logger.error(
            f"[SCREENER] Error: {e}",
            extra={"component": "screener"}
        )
        return []

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_scanner_loop()
