"""
scanner.py — Intelligent Watchlist Builder & Scanner Loop v1.38b
Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, DB Cleanup.
WebSocket bar + quote feeds with candle cache (95%+ API reduction on redeploy).
See CHANGELOG.md for full phase history.
"""
from app.core.health_server import start_health_server, health_heartbeat

# Start health server at TRUE module level so Railway /health probe gets a
# 200 response within the 30s healthcheck window before any blocking init runs.
start_health_server()

import os
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils import config
from utils.config import validate_required_env_vars
try:
    from utils.production_helpers import _db_operation_safe
    PRODUCTION_HELPERS_ENABLED = True
except ImportError:
    PRODUCTION_HELPERS_ENABLED = False
    def _db_operation_safe(fn, label=""): fn()

_last_logged_interval       = None
_last_logged_watchlist_size = None

from app.data.data_manager import data_manager
from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from app.data.ws_quote_feed import start_quote_feed, subscribe_quote_tickers
from app.screening.watchlist_funnel import (
    get_current_watchlist, get_watchlist_with_metadata, get_funnel, reset_funnel,
)
from app.risk.risk_manager import (
    get_loss_streak, get_session_status, get_eod_report, check_exits as risk_check_exits,
)
from app.risk.position_manager import position_manager as _pm

try:
    from app.filters.market_regime_context import send_regime_discord
    REGIME_DISCORD_AVAILABLE = True
except Exception:
    REGIME_DISCORD_AVAILABLE = False
    def send_regime_discord(regime=None, force=False): pass

logger = logging.getLogger(__name__)

REGIME_TICKERS          = ["SPY", "QQQ"]
TICKER_TIMEOUT_SECONDS  = 45
_ticker_executor        = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")



def _run_ticker_with_timeout(process_ticker_fn, ticker: str) -> bool:
    future = _ticker_executor.submit(process_ticker_fn, ticker)
    try:
        future.result(timeout=TICKER_TIMEOUT_SECONDS)
        return True
    except FuturesTimeoutError:
        logger.error(f"[WATCHDOG] ⏰ {ticker} timed out after {TICKER_TIMEOUT_SECONDS}s — skipping")
        future.cancel()
        return False
    except Exception as exc:
        logger.error(f"[WATCHDOG] ❌ {ticker} raised unhandled exception: {exc}")
        return False



ANALYTICS_AVAILABLE = False
analytics_conn      = None
_analytics_conn_lock = __import__('threading').Lock()
DATABASE_URL        = os.getenv('DATABASE_URL')

if DATABASE_URL:
    try:
        import psycopg2
        analytics_conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        analytics_conn.autocommit = True
        logger.info("[DB] ✓ Connected - Analytics ONLINE")
        ANALYTICS_AVAILABLE = True
    except Exception as e:
        logger.info(f"[DB] ✗ FAILED: {e}")
        ANALYTICS_AVAILABLE = False
else:
    logger.info("[DB] ✗ DATABASE_URL not set - Analytics DISABLED")


def _get_analytics_conn():
    global analytics_conn, ANALYTICS_AVAILABLE
    if not DATABASE_URL:
        return None
    with _analytics_conn_lock:
        if analytics_conn is not None:
            try:
                cur = analytics_conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return analytics_conn
            except Exception:
                try:
                    analytics_conn.close()
                except Exception:
                    pass
                analytics_conn = None
        for attempt in range(1, 4):
            try:
                import psycopg2
                analytics_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
                analytics_conn.autocommit = True
                ANALYTICS_AVAILABLE = True
                logger.info(f"[DB] Reconnected analytics connection (attempt {attempt})")
                return analytics_conn
            except Exception as e:
                logger.warning(f"[DB] Reconnect attempt {attempt}/3 failed: {e}")
                time.sleep(1)
        logger.error("[DB] All reconnect attempts failed — analytics disabled for this cycle")
        ANALYTICS_AVAILABLE = False
        return None


try:
    from app.signals.signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
    logger.info("[SCANNER] ✅ Legacy signal analytics enabled")
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None

analytics = None
if ANALYTICS_AVAILABLE and analytics_conn:
    try:
        from app.analytics import AnalyticsIntegration
        if AnalyticsIntegration is not None:
            analytics = AnalyticsIntegration(analytics_conn, enable_ml=True, enable_discord=True)
    except Exception as e:
        logger.warning(f"[SCANNER] ⚠️  Outcome tracking disabled: {e}")

VALIDATION_AVAILABLE = False
OPTIONS_AVAILABLE    = False

try:
    from app.validation import validate_signal
    VALIDATION_AVAILABLE = True
    logger.info("[SCANNER] ✅ Validation gates loaded")
except Exception as e:
    logger.warning(f"[SCANNER] ⚠️  Validation module not available: {e}")
    validate_signal = None

try:
    from app.options import build_options_trade
    OPTIONS_AVAILABLE = True
    logger.info("[SCANNER] ✅ Options intelligence loaded")
except Exception as e:
    logger.warning(f"[SCANNER] ⚠️  Options module not available: {e}")
    build_options_trade = None

API_KEY            = os.getenv("EODHD_API_KEY", "")
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]



def _fire_and_forget(fn, label: str):
    def _wrapper():
        try:
            fn()
            logger.info(f"[BG] ✅ {label} complete")
        except Exception as e:
            logger.warning(f"[BG] ⚠️  {label} failed: {e}")
    t = threading.Thread(target=_wrapper, daemon=True, name=label)
    t.start()
    return t



def _get_stale_tickers(tickers: list) -> list:
    stale = []
    try:
        from app.data.candle_cache import candle_cache
        from datetime import timedelta
        cutoff = datetime.now(ZoneInfo("America/New_York")) - timedelta(hours=24)
        for ticker in tickers:
            bars = candle_cache.get_bars(ticker, limit=1) if hasattr(candle_cache, 'get_bars') else []
            if not bars:
                stale.append(ticker)
            else:
                last_bar_time = bars[-1].get("datetime")
                if last_bar_time is None or last_bar_time < cutoff:
                    stale.append(ticker)
    except Exception:
        return list(tickers)
    return stale



def _extract_premarket_metrics(watchlist_data: dict) -> dict:
    try:
        all_tickers = watchlist_data.get('all_tickers_with_scores', [])
        if not all_tickers:
            return None
        explosive_count = sum(
            1 for t in all_tickers if t.get('score', 0) >= 80 and t.get('rvol', 0) >= 4.0
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


def get_adaptive_scan_interval() -> int:
    global _last_logged_interval
    now = datetime.now(ZoneInfo("America/New_York")).time()
    if   dtime(9, 30)  <= now < dtime(9, 40):  interval, label = 5,   "OR Formation (BOS build)"
    elif dtime(9, 40)  <= now < dtime(11, 0):  interval, label = 45,  "Post-OR Morning"
    elif dtime(11, 0)  <= now < dtime(14, 0):  interval, label = 180, "Midday Chop"
    elif dtime(14, 0)  <= now < dtime(15, 30): interval, label = 60,  "Afternoon Activity"
    elif dtime(15, 30) <= now < dtime(16, 0):  interval, label = 45,  "Power Hour"
    else:                                       interval, label = 300, "Outside Market Hours"
    if interval != _last_logged_interval:
        logger.info(f"[SCANNER] {label} -> Scanning every {interval}s")
        _last_logged_interval = interval
    return interval


def should_scan_now() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


def calculate_optimal_watchlist_size() -> int:
    global _last_logged_watchlist_size
    now = datetime.now(ZoneInfo("America/New_York")).time()
    if   dtime(9, 30)  <= now < dtime(9, 40):  size = 30
    elif dtime(9, 40)  <= now < dtime(10, 30): size = 30
    elif dtime(10, 30) <= now < dtime(15, 0):  size = 50
    elif dtime(15, 0)  <= now <= dtime(16, 0): size = 35
    else:                                       size = 40
    if size != _last_logged_watchlist_size:
        logger.info(f"[SCANNER] Watchlist size adjusted to {size} tickers")
        _last_logged_watchlist_size = size
    return size


def _is_or_window():
    now = _now_et().time()
    return dtime(9, 30) <= now < dtime(9, 40)


def build_watchlist(force_refresh: bool = False) -> list:
    try:
        watchlist = get_current_watchlist(force_refresh=force_refresh)
        if watchlist:
            return watchlist
    except Exception as e:
        logger.error(f"[WATCHLIST] Funnel error: {e}")
    logger.warning(f"[WATCHLIST] Using emergency fallback: {len(EMERGENCY_FALLBACK)} tickers")
    return list(EMERGENCY_FALLBACK)


def monitor_open_positions(session: dict = None):
    from app.data.ws_feed import get_current_bar_with_fallback
    if session is None:
        session = get_session_status()
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
        combined = list(dict.fromkeys(new_tickers + REGIME_TICKERS))
        subscribe_tickers(combined)
        subscribe_quote_tickers(combined)
        logger.info(f"[WS-SUBSCRIBE] ✅ Subscribed {len(new_tickers)} tickers + regime: {', '.join(new_tickers)}")
        _fire_and_forget(
            lambda: (
                data_manager.startup_backfill_with_cache(combined, days=30),
                data_manager.startup_intraday_backfill_today(combined),
            ),
            label=f"prefetch-{','.join(new_tickers[:3])}"
        )
    except Exception as e:
        logger.error(f"[WS-SUBSCRIBE] ⚠ Error subscribing tickers: {e}")
        import traceback; traceback.print_exc()



def start_scanner_loop():
    validate_required_env_vars()

    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals, _orb_classifications
    logger.info("[SCANNER] ✅ process_ticker loaded from sniper.py (CFW6 engine active)")

    from app.notifications.discord_helpers import send_simple_message

    try:
        from app.ai.ai_learning import learning_engine
        HAS_AI_LEARNING = True
    except ImportError:
        learning_engine = None
        HAS_AI_LEARNING = False

    # ── Startup banner (status only — see CHANGELOG.md for phase history) ─────
    logger.info("=" * 60)
    logger.info("WAR MACHINE CFW6 SCANNER v1.38b - STARTUP")
    logger.info("=" * 60)

    try:
        cache_dir   = os.path.join(os.getcwd(), 'cache')
        os.makedirs(cache_dir, exist_ok=True)
        cache_files = len([f for f in os.listdir(cache_dir) if f.endswith('.parquet')])
        logger.info(f"✓ CACHE          {cache_files} cached ticker files (30d history)")
    except Exception as e:
        logger.info(f"? CACHE          Status unknown: {e}")

    db_msg   = "Connected — Analytics tracking enabled" if ANALYTICS_AVAILABLE else "OFFLINE — no tracking"
    disc_msg = "Alert notifications ready" if os.getenv('DISCORD_WEBHOOK_URL') else "NOT CONFIGURED"
    scrn_msg = ("EODHD API configured (" + API_KEY[:8] + "...)") if API_KEY else "EODHD_API_KEY not set"
    reg_msg  = "Regime channel active" if os.getenv('REGIME_WEBHOOK_URL') else "Set REGIME_WEBHOOK_URL"
    opts_msg = "Greeks analysis active" if OPTIONS_AVAILABLE else "NOT INTEGRATED"
    val_msg  = "CFW6 confirmation active" if VALIDATION_AVAILABLE else "NOT INTEGRATED"

    # FIX: Pre-compute ternary labels — backslashes inside f-string expressions
    # are a SyntaxError on Python 3.10 (Railway runtime). Same fix as position_manager FIX #7.
    db_tick   = "\u2713" if ANALYTICS_AVAILABLE else "\u2717"
    disc_tick = "\u2713" if os.getenv('DISCORD_WEBHOOK_URL') else "\u2717"
    scrn_tick = "\u2713" if API_KEY else "\u2717"
    reg_tick  = "\u2713" if os.getenv('REGIME_WEBHOOK_URL') else "\u2717"
    opts_tick = "\u2713" if OPTIONS_AVAILABLE else "\u2717"
    val_tick  = "\u2713" if VALIDATION_AVAILABLE else "\u2717"

    logger.info(f"{db_tick} DATABASE        {db_msg}")
    logger.info(f"{disc_tick} DISCORD         {disc_msg}")
    logger.info(f"{scrn_tick} SCREENER        {scrn_msg}")
    logger.info(f"{reg_tick} REGIME-DISCORD  {reg_msg}")
    logger.info(f"{opts_tick} OPTIONS-GATE    {opts_msg}")
    logger.info(f"{val_tick} VALIDATION      {val_msg}")
    logger.info(f"  RVOL Signal Gate : MIN={config.RVOL_SIGNAL_GATE}x  Ceiling={config.RVOL_CEILING}x")
    logger.info(f"  Bear Signals     : {'ENABLED' if config.BEAR_SIGNALS_ENABLED else 'DISABLED'}")
    logger.info(f"  Ticker Watchdog  : {TICKER_TIMEOUT_SECONDS}s hard timeout per ticker")
    logger.info("=" * 60)
    logger.info(f"Session: 09:30–16:00 ET | Mode: {'Pre-market' if is_premarket() else 'Live'}")
    logger.info("=" * 60 + "\n")

    _booting_into_market_hours = is_market_hours()
    premarket_watchlist = []
    premarket_built     = False

    if _booting_into_market_hours:
        logger.info("[SCANNER] ⚡ Redeploy detected during market hours — loading locked watchlist")
        try:
            watchlist_data      = get_watchlist_with_metadata(force_refresh=False)
            premarket_watchlist = watchlist_data.get('watchlist', [])
            if premarket_watchlist:
                logger.info(f"[SCANNER] ✅ Loaded locked watchlist: {len(premarket_watchlist)} tickers")
            else:
                premarket_watchlist = list(EMERGENCY_FALLBACK)
                logger.warning("[SCANNER] ⚠️ No locked watchlist found — using emergency fallback")
        except Exception as e:
            premarket_watchlist = list(EMERGENCY_FALLBACK)
            logger.warning(f"[SCANNER] ⚠️ Could not load locked watchlist ({e}) — using emergency fallback")
        premarket_built = True

    try:
        send_simple_message(
            f"⚔️ WAR MACHINE ONLINE — CFW6 v1.38b | "
            f"{'Resuming intraday' if _booting_into_market_hours else 'OR window active'}"
        )
    except Exception as e:
        logger.warning(f"[SCANNER] Discord unavailable: {e}")

    cycle_count               = 0
    last_report_day           = None
    loss_streak_alerted       = False
    last_subscribed_watchlist = set()
    _or_window_logged         = False
    _watchlist_lock_logged    = False

    startup_watchlist = list(dict.fromkeys(
        (premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK)) + REGIME_TICKERS
    ))

    ws_thread = threading.Thread(target=lambda: start_ws_feed(startup_watchlist), daemon=True, name="start_ws_feed")
    ws_thread.start()
    ws_thread.join(timeout=20)
    logger.info("[WS] WebSocket feed started (or timed out gracefully)")

    quote_thread = threading.Thread(target=lambda: start_quote_feed(startup_watchlist), daemon=True, name="start_quote_feed")
    quote_thread.start()
    quote_thread.join(timeout=20)
    logger.info("[QUOTE] Quote feed started (or timed out gracefully)")

    stale = _get_stale_tickers(startup_watchlist)
    if stale:
        logger.info(f"[BACKFILL] {len(stale)} stale tickers need backfill: {', '.join(stale)}")
        _fire_and_forget(lambda: data_manager.startup_backfill_with_cache(stale, days=30), label="startup_backfill")
        _fire_and_forget(lambda: data_manager.startup_intraday_backfill_today(stale), label="intraday_backfill")
    else:
        logger.info("[BACKFILL] ✅ All tickers warm — skipping EODHD backfill")

    set_backfill_complete()
    last_subscribed_watchlist = set(startup_watchlist)
    logger.info("[STARTUP] ✅ WS feeds up | backfill running in background | entering main loop")

    while True:
        try:
            health_heartbeat()

            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            if is_premarket():
                _or_window_logged      = False
                _watchlist_lock_logged = False
                if not premarket_built:
                    logger.info(f"[PRE-MARKET] {current_time_str} - Building Watchlist")
                    try:
                        watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata            = watchlist_data['metadata']

                        if not premarket_watchlist and now_et.time() > dtime(8, 0):
                            logger.warning("⚠️  WATCHLIST EMPTY after 8:00 AM - possible config issue")
                            try:
                                send_simple_message("⚠️ **WATCHLIST EMPTY** after 8:00 AM ET — Check funnel!")
                            except Exception:
                                pass

                        premarket_built = True
                        current_set = set(premarket_watchlist)
                        new_tickers = list(current_set - last_subscribed_watchlist)
                        if new_tickers:
                            subscribe_and_prefetch_tickers(new_tickers)
                        else:
                            combined = list(dict.fromkeys(premarket_watchlist + REGIME_TICKERS))
                            subscribe_tickers(combined)
                            subscribe_quote_tickers(combined)
                        last_subscribed_watchlist = current_set
                        logger.info(f"[WS] Subscribed premarket watchlist ({len(premarket_watchlist)} tickers)")
                    except Exception as e:
                        logger.error(f"[PRE-MARKET] Funnel error: {e}")
                        import traceback; traceback.print_exc()
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
                                combined = list(dict.fromkeys(premarket_watchlist + REGIME_TICKERS))
                                subscribe_tickers(combined)
                                subscribe_quote_tickers(combined)
                            last_subscribed_watchlist = current_set
                            metadata = watchlist_data['metadata']
                            logger.info(f"[FUNNEL] Stage: {metadata['stage'].upper()} — {metadata['stage_description']}")
                        except Exception as e:
                            logger.error(f"[PRE-MARKET] Refresh error: {e}")
                    else:
                        logger.info(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")
                    time.sleep(60)
                continue

            elif is_market_hours():
                if _is_or_window():
                    if not _or_window_logged:
                        logger.info(
                            f"[SCANNER] 📊 OR WINDOW — BOS+FVG building (9:30-9:40) "
                            f"scanning every 5s | {current_time_str}"
                        )
                        _or_window_logged = True

                session     = get_session_status()
                daily_stats = session["daily_stats"]

                _has_loss_streak = (
                    (daily_stats.get("losses", 0) >= 3 and daily_stats.get("wins", 0) == 0)
                    or _pm.has_loss_streak(max_consecutive_losses=3)
                )

                if _has_loss_streak:
                    if not loss_streak_alerted:
                        try:
                            send_simple_message(
                                "🛑 **CIRCUIT BREAKER** — 3 consecutive losses today. "
                                "New scans halted. Open positions still monitored."
                            )
                        except Exception:
                            pass
                        loss_streak_alerted = True
                        logger.warning("[RISK] Daily loss streak reached — halting new scans.")
                    monitor_open_positions(session=session)
                    time.sleep(60)
                    continue

                cycle_count += 1
                send_regime_discord()

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
                    logger.info(f"[WS-SUBSCRIBE] 🔄 Detected {len(new_tickers)} new watchlist tickers")
                    subscribe_and_prefetch_tickers(new_tickers)
                    last_subscribed_watchlist = current_set

                if not _watchlist_lock_logged:
                    logger.info(f"[SCANNER] Cycle #{cycle_count} | {len(watchlist)} tickers | {current_time_str}")
                    _watchlist_lock_logged = True
                else:
                    logger.debug(f"[SCANNER] Cycle #{cycle_count} | {len(watchlist)} tickers | {current_time_str}")

                if ANALYTICS_AVAILABLE and analytics:
                    def _run_analytics(conn=None):
                        live_conn = _get_analytics_conn()
                        if live_conn and analytics:
                            def get_price(t):
                                from app.data.ws_feed import get_current_bar_with_fallback
                                bar = get_current_bar_with_fallback(t)
                                return bar['close'] if bar else None
                            analytics.monitor_active_signals(get_price)
                            analytics.check_scheduled_tasks()
                    if PRODUCTION_HELPERS_ENABLED:
                        _db_operation_safe(_run_analytics, "analytics monitor")
                    else:
                        try:
                            _run_analytics()
                        except Exception as e:
                            logger.error(f"[ANALYTICS] Monitor error: {e}")

                monitor_open_positions(session=session)

                logger.info(
                    f"[TODAY] Trades: {daily_stats['trades']} "
                    f"W/L: {daily_stats['wins']}/{daily_stats['losses']} "
                    f"WR: {daily_stats['win_rate']:.1f}% "
                    f"P&L: ${daily_stats['total_pnl']:+.2f}"
                )

                for ticker in watchlist:
                    try:
                        _run_ticker_with_timeout(process_ticker, ticker)
                    except Exception as e:
                        logger.error(f"[SCANNER] Error on {ticker}: {e}")
                        import traceback; traceback.print_exc()
                        continue

                scan_interval = get_adaptive_scan_interval()
                logger.debug(f"[SCANNER] Cycle #{cycle_count} complete — sleeping {scan_interval}s")
                time.sleep(scan_interval)

            else:
                if last_report_day != current_day:
                    logger.info(f"[EOD] Market Closed — Generating Reports for {current_day}")

                    session        = get_session_status()
                    open_positions = session["open_positions"]
                    if open_positions:
                        logger.info(f"[EOD] {len(open_positions)} positions still open")

                    try:
                        from app.core.eod_reporter import run_eod_report
                        run_eod_report(current_day)
                    except Exception as e:
                        logger.error(f"[EOD] eod_reporter failed: {e}")
                        import traceback; traceback.print_exc()

                    if HAS_AI_LEARNING:
                        try:
                            learning_engine.optimize_confirmation_weights()
                            learning_engine.optimize_fvg_threshold()
                            logger.info(learning_engine.generate_performance_report())
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
                        logger.error(f"[CLEANUP] DB bar cleanup error: {e}")

                    try:
                        from app.data.candle_cache import candle_cache
                        candle_cache.cleanup_old_cache(days_to_keep=30)
                    except Exception as e:
                        logger.error(f"[CLEANUP] Candle cache cleanup error: {e}")

                    logger.info("[SIGNALS] Daily reset complete")
                    last_report_day           = current_day
                    premarket_watchlist       = []
                    premarket_built           = False
                    cycle_count               = 0
                    loss_streak_alerted       = False
                    last_subscribed_watchlist = set()
                    _watchlist_lock_logged    = False

                    reset_funnel()
                    clear_armed_signals()
                    clear_watching_signals()
                    from app.core.sniper import _bos_watch_alerted; _bos_watch_alerted.clear()
                    try:
                        data_manager.clear_prev_day_cache()
                    except Exception as e:
                        logger.error(f"[DATA] PDH/PDL cache clear error: {e}")

                    logger.info("[EOD] All EOD tasks complete")

                logger.info(f"[AFTER-HOURS] {current_time_str} - Market closed, next check in 10 min")
                time.sleep(600)

        except KeyboardInterrupt:
            logger.info("[SCANNER] Shutdown signal received")
            logger.info(get_eod_report())
            raise

        except Exception as e:
            logger.error(f"[SCANNER] Critical error: {e}")
            import traceback; traceback.print_exc()
            try:
                send_simple_message(f"⚠️ Scanner Error: {str(e)}")
            except Exception:
                pass
            time.sleep(30)



if __name__ == "__main__":
    start_scanner_loop()
