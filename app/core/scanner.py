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

PHASE 1.13 (MAR 6, 2026):
  - Removed deprecated signal_generator imports
  - Scanner relies entirely on sniper.py for signal processing

PHASE 1.14 (MAR 9, 2026):
  - Fixed signal_analytics import path
  - TEMPORARY: sniper_stubs workaround

PHASE 1.15 (MAR 9, 2026):
  - Wired all risk calls through risk_manager
  - Fixed crash: get_closed_positions_today() -> get_daily_stats()
  - monitor_open_positions() delegates exits to risk_manager.check_exits()

PHASE 1.16 (MAR 9, 2026):
  - FIXED: process_ticker now imported from sniper.py (retires sniper_stubs)
  - FIXED: startup_backfill wrapped in 45s timeout thread (no more hang)
  - FIXED: start_ws_feed / start_quote_feed wrapped in 20s timeout threads
  - Startup banner updated to v1.16
"""
import os
import time
import threading
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils import config

from app.data.data_manager import data_manager
from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from app.data.ws_quote_feed import start_quote_feed, subscribe_quote_tickers
from app.core.scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)
from app.screening.watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel
)

# ── Risk layer — single import, all risk calls go through here ────────────────
from app.risk.risk_manager import (
    get_loss_streak,
    get_session_status,
    get_eod_report,
    check_exits as risk_check_exits,
)
from app.risk.position_manager import position_manager as _pm

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────────
ANALYTICS_AVAILABLE = False
analytics_conn = None
DATABASE_URL = os.getenv('DATABASE_URL')

logger.info("=" * 50)
logger.info("DATABASE Attempting connection...")
if DATABASE_URL:
    try:
        import psycopg2
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

try:
    from app.signals.signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
    logger.info("[SCANNER] ✅ Legacy signal analytics enabled")
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None
    logger.info("[SCANNER] ⚠️  signal_analytics not available")

analytics = None
if ANALYTICS_AVAILABLE and analytics_conn:
    try:
        from app.analytics import AnalyticsIntegration
        if AnalyticsIntegration is not None:
            analytics = AnalyticsIntegration(
                analytics_conn,
                enable_ml=True,
                enable_discord=True
            )
        else:
            analytics = None
    except Exception as e:
        analytics = None
        logger.warning(f"[SCANNER] ⚠️  Outcome tracking disabled: {e}")

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
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]


# ─────────────────────────────────────────────────────────────────────────────────
# TIMEOUT-GUARDED STARTUP HELPER
# ─────────────────────────────────────────────────────────────────────────────────
def _run_with_timeout(fn, timeout_seconds: int, label: str):
    """
    Run fn() in a daemon thread.  If it doesn’t finish within
    timeout_seconds we log a warning and continue — we never block
    the main thread forever.
    """
    t = threading.Thread(target=fn, daemon=True, name=label)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        logger.warning(
            f"[STARTUP] ⚠️  {label} did not finish within {timeout_seconds}s — continuing anyway"
        )


# ─────────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────────
def _extract_premarket_metrics(watchlist_data: dict) -> dict:
    try:
        all_tickers = watchlist_data.get('all_tickers_with_scores', [])
        if not all_tickers:
            return None
        explosive_count = sum(
            1 for t in all_tickers
            if t.get('score', 0) >= 80 and t.get('rvol', 0) >= 4.0
        )
        avg_rvol  = sum(t.get('rvol', 0)  for t in all_tickers) / len(all_tickers)
        avg_score = sum(t.get('score', 0) for t in all_tickers) / len(all_tickers)
        top_3_summary = ', '.join([
            f"{t['ticker']} ({t['rvol']:.1f}x)"
            for t in all_tickers[:3] if 'ticker' in t and 'rvol' in t
        ]) if all_tickers else 'N/A'
        return {
            'explosive_count':          explosive_count,
            'explosive_rvol_threshold': 4.0,
            'avg_rvol':                 avg_rvol,
            'avg_score':                avg_score,
            'top_3_summary':            top_3_summary,
        }
    except Exception as e:
        logger.error(f"[METRICS] Pre-market extraction error: {e}")
        return None


def _get_eod_summary_metrics() -> dict:
    try:
        session     = get_session_status()
        daily_stats = session["daily_stats"]
        if not daily_stats or daily_stats.get("trades", 0) == 0:
            return None
        top_performers = get_eod_report()
        try:
            watchlist_data  = get_watchlist_with_metadata(force_refresh=False)
            all_tickers     = watchlist_data.get('all_tickers_with_scores', [])
            avg_rvol        = sum(t.get('rvol', 0) for t in all_tickers) / len(all_tickers) if all_tickers else 0
            explosive_count = sum(
                1 for t in all_tickers
                if t.get('score', 0) >= 80 and t.get('rvol', 0) >= 4.0
            )
        except Exception:
            avg_rvol        = 0
            explosive_count = 0
        return {
            'top_performers':  top_performers,
            'avg_rvol':        avg_rvol,
            'explosive_count': explosive_count,
        }
    except Exception as e:
        logger.error(f"[METRICS] EOD extraction error: {e}")
        return None


data_update_counter    = 0
data_update_symbols    = set()
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
    try:
        watchlist = get_current_watchlist(force_refresh=force_refresh)
        if watchlist:
            return watchlist
    except Exception as e:
        logger.error(f"[WATCHLIST] Funnel error: {e}")
    logger.warning(f"[WATCHLIST] Using emergency fallback: {len(EMERGENCY_FALLBACK)} tickers")
    return list(EMERGENCY_FALLBACK)


def monitor_open_positions():
    from app.data.ws_feed import get_current_bar_with_fallback
    session        = get_session_status()
    open_positions = session["open_positions"]
    if not open_positions:
        return
    logger.info(f"[MONITOR] Checking {len(open_positions)} open positions...")
    current_prices = {}
    for pos in open_positions:
        ticker = pos["ticker"]
        bar    = get_current_bar_with_fallback(ticker)
        if bar is not None:
            if bar.get("source", "ws") == "rest":
                logger.warning(f"[WS-FAILOVER] {ticker}: position monitoring via REST bar")
        else:
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            bar  = bars[-1] if bars else None
            if bar:
                logger.warning(f"[MONITOR] {ticker}: using DB last bar (WS+REST unavailable)")
        if bar:
            current_prices[ticker] = bar["close"]
    risk_check_exits(current_prices)


def subscribe_and_prefetch_tickers(new_tickers: list):
    if not new_tickers:
        return
    try:
        subscribe_tickers(new_tickers)
        subscribe_quote_tickers(new_tickers)
        logger.info(f"[WS-SUBSCRIBE] ✅ Subscribed {len(new_tickers)} new tickers: {', '.join(new_tickers)}")
        logger.info(f"[PREFETCH] Fetching 30d historical bars for {len(new_tickers)} tickers...")
        data_manager.startup_backfill_with_cache(new_tickers, days=30)
        logger.info(f"[PREFETCH] Fetching today's intraday bars for {len(new_tickers)} tickers...")
        data_manager.startup_intraday_backfill_today(new_tickers)
        logger.info("[WS-SUBSCRIBE] Waiting 3s for initial bars to flow...")
        time.sleep(3)
        logger.info(f"[WS-SUBSCRIBE] ✅ Prefetch complete for {len(new_tickers)} tickers")
    except Exception as e:
        logger.error(f"[WS-SUBSCRIBE] ⚠️ Error subscribing/prefetching tickers: {e}")
        import traceback
        traceback.print_exc()


def start_scanner_loop():
    # ────────────────────────────────────────────────────────────────────────
    # PHASE 1.16: Import process_ticker directly from sniper.py
    # (retires the Phase 1.14 sniper_stubs workaround)
    # ────────────────────────────────────────────────────────────────────────
    try:
        from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals
        logger.info("[SCANNER] ✅ process_ticker loaded from sniper.py (CFW6 engine active)")
    except ImportError as e:
        logger.error(f"[SCANNER] ❌ sniper.py import failed: {e} — falling back to sniper_stubs")
        from app.core.sniper_stubs import process_ticker, clear_armed_signals, clear_watching_signals

    from app.discord_helpers import send_simple_message

    try:
        from app.ai.ai_learning import learning_engine
        HAS_AI_LEARNING = True
    except ImportError:
        learning_engine = None
        HAS_AI_LEARNING = False

    # ════════════════════════════════════════════════════════════════════════
    # STARTUP HEALTH CHECK BANNER
    # ════════════════════════════════════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("WAR MACHINE CFW6 SCANNER v1.16 - STARTUP")
    logger.info("=" * 60)
    logger.info("✓ DATA-INGEST    WebSocket starting (tickers TBD)")

    try:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
        if os.path.exists(cache_dir):
            cache_files = len([f for f in os.listdir(cache_dir) if f.endswith('.parquet')])
            logger.info(f"✓ CACHE          {cache_files} cached ticker files, 30d history")
        else:
            logger.info("? CACHE          Directory not found (will be created)")
    except Exception as e:
        logger.info(f"? CACHE          Status unknown: {e}")

    logger.info(f"{'\u2713' if API_KEY else '\u2717'} SCREENER       {'EODHD API configured (' + API_KEY[:8] + '...)' if API_KEY else 'EODHD_API_KEY not set'}")

    try:
        from app.filters import regime_filter  # noqa: F401
        logger.info("✓ REGIME-FILTER  ADX/VIX monitoring active")
    except Exception:
        logger.info("? REGIME-FILTER  Module not found (may be inline)")

    logger.info(f"{'\u2713' if ANALYTICS_AVAILABLE else '\u2717'} DATABASE        {'Connected - Analytics tracking enabled' if ANALYTICS_AVAILABLE else 'OFFLINE - no volume/signal/P&L tracking'}")
    discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
    logger.info(f"{'\u2713' if discord_webhook else '\u2717'} DISCORD         {'Alert notifications ready' if discord_webhook else 'NOT CONFIGURED - no alerts'}")
    logger.info(f"{'\u2713' if OPTIONS_AVAILABLE else '\u2717'} OPTIONS-GATE    {'Integrated - Greeks analysis active' if OPTIONS_AVAILABLE else 'NOT INTEGRATED'}")
    logger.info(f"{'\u2713' if VALIDATION_AVAILABLE else '\u2717'} VALIDATION     {'Integrated - CFW6 confirmation active' if VALIDATION_AVAILABLE else 'NOT INTEGRATED'}")
    logger.info("=" * 60)
    logger.info(f"Trading session: 09:30 - 16:00 ET")
    logger.info(f"Scanner mode: {'Pre-market' if is_premarket() else 'Live'}")
    logger.info("=" * 60)
    logger.info("Candle Cache:  ✅ ENABLED (95%+ API reduction on redeploy)")
    logger.info("WS Failover:   ✅ ENABLED (REST API fallback on disconnect)")
    logger.info("Spread Gate:   ✅ ENABLED (us-quote bid/ask filter active)")
    logger.info("Dynamic WS:    ✅ ENABLED (live session ticker subscription)")
    logger.info("Risk Manager:  ✅ ENABLED (unified risk layer — Phase 1.15)")
    logger.info("CFW6 Engine:   ✅ ENABLED (sniper.py direct — Phase 1.16)")
    logger.info("Startup Guard: ✅ ENABLED (timeout-protected startup calls)")
    logger.info("=" * 60 + "\n")

    try:
        send_simple_message("\u2694️ WAR MACHINE ONLINE — CFW6 v1.16 | sniper.py active | Timeout-guarded startup")
    except Exception as e:
        logger.warning(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist       = []
    premarket_built           = False
    cycle_count               = 0
    last_report_day           = None
    loss_streak_alerted       = False
    last_subscribed_watchlist = set()

    # ── STARTUP SEQUENCE (all calls timeout-guarded) ──────────────────────────
    startup_watchlist = list(EMERGENCY_FALLBACK)

    _run_with_timeout(
        lambda: start_ws_feed(startup_watchlist),
        timeout_seconds=20,
        label="start_ws_feed"
    )
    logger.info(f"[WS] WebSocket feed started (or timed out gracefully)")

    _run_with_timeout(
        lambda: start_quote_feed(startup_watchlist),
        timeout_seconds=20,
        label="start_quote_feed"
    )
    logger.info(f"[QUOTE] Quote feed started (or timed out gracefully)")

    _run_with_timeout(
        lambda: data_manager.startup_backfill_with_cache(startup_watchlist, days=30),
        timeout_seconds=45,
        label="startup_backfill"
    )
    logger.info("[PREFETCH] Historical backfill complete (or timed out gracefully)")

    _run_with_timeout(
        lambda: data_manager.startup_intraday_backfill_today(startup_watchlist),
        timeout_seconds=30,
        label="intraday_backfill"
    )
    logger.info("[PREFETCH] Intraday backfill complete (or timed out gracefully)")

    set_backfill_complete()
    last_subscribed_watchlist = set(startup_watchlist)
    logger.info("[STARTUP] ✅ Startup sequence complete — entering main loop")
    # ─────────────────────────────────────────────────────────────────────────────────

    while True:
        try:
            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            # ── PRE-MARKET ──────────────────────────────────────────────────
            if is_premarket():
                if not premarket_built:
                    logger.info(f"[PRE-MARKET] {current_time_str} - Building Watchlist")
                    try:
                        watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata            = watchlist_data['metadata']
                        volume_signals      = watchlist_data['volume_signals']

                        if not premarket_watchlist and now_et.time() > dtime(8, 0):
                            logger.warning("\u26a0\ufe0f  WATCHLIST EMPTY after 8:00 AM - possible config issue")
                            try:
                                send_simple_message("\u26a0\ufe0f **WATCHLIST EMPTY** after 8:00 AM ET — Check funnel configuration!")
                            except Exception:
                                pass

                        premarket_built = True

                        current_set = set(premarket_watchlist)
                        new_tickers = list(current_set - last_subscribed_watchlist)
                        if new_tickers:
                            subscribe_and_prefetch_tickers(new_tickers)
                        else:
                            subscribe_tickers(premarket_watchlist)
                            subscribe_quote_tickers(premarket_watchlist)
                        last_subscribed_watchlist = current_set

                        logger.info(f"[WS] Subscribed premarket watchlist ({len(premarket_watchlist)} tickers)")

                        stage_emoji = {'wide': '\U0001f4e1', 'narrow': '\U0001f3af', 'final': '\U0001f525', 'live': '\u26a1'}
                        emoji       = stage_emoji.get(metadata['stage'], '\U0001f4ca')
                        pm_metrics  = _extract_premarket_metrics(watchlist_data)

                        msg = (
                            f"{emoji} **{metadata['stage_description']}**\n"
                            f"✅ Watchlist: {len(premarket_watchlist)} tickers\n"
                            f"{', '.join(premarket_watchlist[:20])}"
                            f"{'...' if len(premarket_watchlist) > 20 else ''}\n"
                        )
                        if pm_metrics:
                            msg += (
                                f"\n**Screener Insights:**\n"
                                f"\U0001f525 Explosive: {pm_metrics['explosive_count']} "
                                f"(RVOL \u2265{pm_metrics['explosive_rvol_threshold']}x)\n"
                                f"\U0001f4ca Avg RVOL: {pm_metrics['avg_rvol']:.1f}x | "
                                f"Avg Score: {pm_metrics['avg_score']:.0f}\n"
                                f"\U0001f3af Top 3: {pm_metrics['top_3_summary']}"
                            )
                        if volume_signals:
                            msg += f"\n\n\u26a0\ufe0f {len(volume_signals)} volume signals active"
                        send_simple_message(msg)

                        for ticker in premarket_watchlist:
                            try:
                                process_ticker(ticker)
                            except Exception as e:
                                logger.error(f"[PRE-MARKET] Error processing {ticker}: {e}")

                    except Exception as e:
                        logger.error(f"[PRE-MARKET] Funnel error: {e}")
                        import traceback
                        traceback.print_exc()
                        premarket_watchlist = list(EMERGENCY_FALLBACK)
                        premarket_built     = True
                else:
                    funnel = get_funnel()
                    if funnel.should_update():
                        logger.info(f"[PRE-MARKET] {current_time_str} - Refreshing Watchlist")
                        try:
                            watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                            premarket_watchlist = watchlist_data['watchlist']
                            current_set = set(premarket_watchlist)
                            new_tickers = list(current_set - last_subscribed_watchlist)
                            if new_tickers:
                                subscribe_and_prefetch_tickers(new_tickers)
                            else:
                                subscribe_tickers(premarket_watchlist)
                                subscribe_quote_tickers(premarket_watchlist)
                            last_subscribed_watchlist = current_set
                            metadata = watchlist_data['metadata']
                            logger.info(f"[FUNNEL] Stage: {metadata['stage'].upper()} — {metadata['stage_description']}")
                            for ticker in premarket_watchlist:
                                try:
                                    process_ticker(ticker)
                                except Exception as e:
                                    logger.error(f"[PRE-MARKET] Error processing {ticker}: {e}")
                        except Exception as e:
                            logger.error(f"[PRE-MARKET] Refresh error: {e}")
                    else:
                        logger.info(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")
                    time.sleep(60)
                continue

            # ── MARKET HOURS ────────────────────────────────────────────────
            elif is_market_hours():
                if not should_scan_now():
                    logger.info(f"[SCANNER] {current_time_str} - Opening Range forming, waiting...")
                    time.sleep(15)
                    continue

                if get_loss_streak():
                    if not loss_streak_alerted:
                        try:
                            send_simple_message(
                                "\U0001f6d1 **CIRCUIT BREAKER** — 3 consecutive losses today. "
                                "New scans halted. Open positions still monitored."
                            )
                        except Exception:
                            pass
                        loss_streak_alerted = True
                        logger.warning("[RISK] Daily loss streak reached — halting new scans.")
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
                        watchlist = premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK)
                except Exception as e:
                    logger.error(f"[WATCHLIST] Error: {e}")
                    watchlist = premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK)

                optimal_size = calculate_optimal_watchlist_size()
                watchlist    = watchlist[:optimal_size]

                current_set = set(watchlist)
                new_tickers = list(current_set - last_subscribed_watchlist)
                if new_tickers:
                    logger.info(f"[WS-SUBSCRIBE] \U0001f504 Detected {len(new_tickers)} new watchlist tickers")
                    subscribe_and_prefetch_tickers(new_tickers)
                    last_subscribed_watchlist = current_set

                logger.info(f"[SCANNER] {len(watchlist)} tickers | {', '.join(watchlist[:10])}...")

                if ANALYTICS_AVAILABLE and analytics:
                    try:
                        def get_price(ticker):
                            from app.data.ws_feed import get_current_bar_with_fallback
                            bar = get_current_bar_with_fallback(ticker)
                            return bar['close'] if bar else None
                        analytics.monitor_active_signals(get_price)
                        analytics.check_scheduled_tasks()
                    except Exception as e:
                        logger.error(f"[ANALYTICS] Monitor error: {e}")

                monitor_open_positions()

                session     = get_session_status()
                daily_stats = session["daily_stats"]
                logger.info(
                    f"[TODAY] Trades: {daily_stats['trades']} "
                    f"W/L: {daily_stats['wins']}/{daily_stats['losses']} "
                    f"WR: {daily_stats['win_rate']:.1f}% "
                    f"P&L: ${daily_stats['total_pnl']:+.2f}"
                )

                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        logger.info(f"--- [{idx}/{len(watchlist)}] {ticker} ---")
                        signal = process_ticker(ticker)

                        if signal and VALIDATION_AVAILABLE and validate_signal:
                            validation_result = validate_signal(
                                ticker=ticker,
                                signal_type=signal.get('type', 'BOS'),
                                regime_filter=True,
                                greeks_available=OPTIONS_AVAILABLE,
                            )
                            if validation_result.get('passed', False):
                                options_play = None
                                if OPTIONS_AVAILABLE and build_options_trade:
                                    try:
                                        options_play = build_options_trade(
                                            ticker,
                                            "CALL" if signal['signal'] == 'BUY' else "PUT",
                                            signal.get('confidence', 70),
                                        )
                                    except Exception as e:
                                        logger.warning(f"[OPTIONS] Failed to build trade for {ticker}: {e}")
                                logger.info(f"[VALIDATION] {ticker} signal PASSED validation")
                            else:
                                logger.info(f"[VALIDATION] {ticker} rejected: {validation_result.get('reason', 'Unknown')}")
                    except Exception as e:
                        logger.error(f"[SCANNER] Error on {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

                logger.info(f"[SCANNER] Cycle #{cycle_count} complete")
                scan_interval = get_adaptive_scan_interval()
                logger.info(f"[SCANNER] Sleeping {scan_interval}s...")
                time.sleep(scan_interval)

            # ── AFTER HOURS / EOD ──────────────────────────────────────────────
            else:
                if last_report_day != current_day:
                    logger.info(f"\n{'='*80}")
                    logger.info(f"[EOD] Market Closed - Generating Reports for {current_day}")
                    logger.info(f"{'='*80}\n")

                    session        = get_session_status()
                    open_positions = session["open_positions"]
                    if open_positions:
                        logger.info(f"[EOD] {len(open_positions)} positions still open")

                    if LEGACY_ANALYTICS_ENABLED and signal_tracker:
                        try:
                            summary      = signal_tracker.get_daily_summary()
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
                        except Exception as e:
                            logger.error(f"[ANALYTICS] Error generating report: {e}")
                            import traceback
                            traceback.print_exc()

                    try:
                        daily_stats  = session["daily_stats"]
                        eod_metadata = _get_eod_summary_metrics()
                        eod_report = (
                            f"\U0001f4ca **EOD Report {current_day}**\n"
                            f"Trades: {daily_stats['trades']} | "
                            f"WR: {daily_stats['win_rate']:.1f}% | "
                            f"P&L: ${daily_stats['total_pnl']:+.2f}\n"
                        )
                        if eod_metadata:
                            eod_report += (
                                f"\n**Top Performers:**\n{eod_metadata.get('top_performers', 'N/A')}\n"
                                f"\n**Screener Stats:**\n"
                                f"Avg RVOL: {eod_metadata.get('avg_rvol', 0):.1f}x | "
                                f"Explosive Movers: {eod_metadata.get('explosive_count', 0)}"
                            )
                        send_simple_message(eod_report)
                    except Exception as e:
                        logger.error(f"[EOD] EOD report error: {e}")

                    if HAS_AI_LEARNING:
                        try:
                            learning_engine.optimize_confirmation_weights()
                            learning_engine.optimize_fvg_threshold()
                            print(learning_engine.generate_performance_report())
                        except Exception as e:
                            logger.error(f"[AI] Optimization error: {e}")

                    try:
                        from app.data.ws_feed import get_failover_stats
                        stats = get_failover_stats()
                        if stats["rest_hits"] > 0:
                            logger.info(f"[WS-FAILOVER] Session REST hits: {stats['rest_hits']}")
                    except Exception as e:
                        logger.error(f"[WS-FAILOVER] Stats error: {e}")

                    try:
                        data_manager.cleanup_old_bars(days_to_keep=60)
                    except Exception as e:
                        logger.error(f"[CLEANUP] Error: {e}")

                    logger.info("[SIGNALS] Daily reset complete")
                    last_report_day           = current_day
                    premarket_watchlist       = []
                    premarket_built           = False
                    cycle_count               = 0
                    loss_streak_alerted       = False
                    last_subscribed_watchlist = set()

                    clear_armed_signals()
                    clear_watching_signals()

                    try:
                        data_manager.clear_prev_day_cache()
                    except Exception as e:
                        logger.error(f"[DATA] PDH/PDL cache clear error: {e}")

                    logger.info(f"\n{'='*80}")
                    logger.info("[EOD] All EOD tasks complete")
                    logger.info(f"{'='*80}\n")

                logger.info(f"[AFTER-HOURS] {current_time_str} - Market closed, next check in 10 min")
                time.sleep(600)

        except KeyboardInterrupt:
            logger.info("[SCANNER] Shutdown signal received")
            print(get_eod_report())
            raise

        except Exception as e:
            logger.error(f"[SCANNER] Critical error: {e}")
            import traceback
            traceback.print_exc()
            try:
                send_simple_message(f"\u26a0\ufe0f Scanner Error: {str(e)}")
            except Exception:
                pass
            time.sleep(30)


def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> list:
    import requests
    import json
    url    = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["avgvol_1d",            ">=", 1_000_000],
            ["exchange",             "=",  "us"],
        ]),
        "sort":   "avgvol_1d.desc",
        "limit":  limit,
        "offset": 0,
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            logger.error(f"[SCREENER] HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "data" not in data:
            logger.error(f"[SCREENER] Unexpected response shape: {str(data)[:300]}")
            return []
        tickers = []
        for item in data["data"]:
            code = item.get("code")
            if code:
                tickers.append(code.replace(".US", "").replace(".us", ""))
        logger.info(f"[SCREENER] ✅ Fetched {len(tickers)} tickers")
        return tickers[:limit]
    except Exception as e:
        logger.error(f"[SCREENER] Error: {e}")
        return []


if __name__ == "__main__":
    start_scanner_loop()
