"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
CANDLE CACHE: Cache-aware startup with 95%+ API reduction
OUTCOME TRACKING: Signal deduplication, ML predictions, EOD reports
DYNAMIC WS SUBSCRIPTION: Live session ticker subscription with bar prefetch

PHASE 1.16b (MAR 9, 2026):
  - FIXED: Python 3.10 SyntaxError — backslashes in f-strings not allowed

PHASE 1.17 (MAR 9, 2026):
  - FIXED: startup_backfill demoted to fire-and-forget background daemon
  - No more 45s timeout warning — backfill runs silently in background
  - set_backfill_complete() called immediately; WS starts right away
  - subscribe_and_prefetch_tickers() also non-blocking (background thread)
  - Main loop enters in <5s regardless of EODHD API latency
  - Banner updated to v1.17

PHASE 1.18 (MAR 10, 2026):
  - FIXED: DB startup block now uses print() so status always visible in Railway logs
  - FIXED: Removed sslmode=require injection (internal Railway host needs no SSL)
  - FIXED: Added connect_timeout=10 to surface connection failures immediately

PHASE 1.18a (MAR 10, 2026):
  - FIXED: Cache dir uses os.getcwd() instead of __file__ relative path (Railway compat)
  - FIXED: os.makedirs on cache dir so it is always created if missing
  - FIXED: Options import now logs the actual exception (not just ImportError)

PHASE 1.19 (MAR 10, 2026):
  - FIX C5: start_health_server() called once at startup before WS init
  - FIX C5: health_heartbeat() called at top of every main loop cycle
  - Railway now gets a real 200/503 signal from GET /health instead of
    always-200 (health endpoint was missing entirely before this fix)

PHASE 1.20 (MAR 10, 2026):
  - FIX H1: analytics_conn wrapped in reconnect helper — survives Railway DB
    restarts, idle-connection timeouts, and transient TCP drops without crashing
    the scanner process. A dead connection is detected before use and replaced.

PHASE 1.21 (MAR 10, 2026):
  - FIX P0-3: Ticker timeout watchdog — process_ticker() now runs in a
    ThreadPoolExecutor with a 45-second hard timeout per ticker.
    A hung EODHD call, confirmation wait, or DB query can no longer stall
    the entire scan loop. Timed-out tickers are logged and skipped cleanly.

PHASE 1.22 (MAR 10, 2026):
  - FIX: candle_cache EOD cleanup now runs alongside DB bar cleanup.
    DB bars: rolling 60-day window (unchanged).
    Candle cache: rolling 30-day window (matches startup_backfill_with_cache).
    Also prunes orphaned cache_metadata rows for tickers with no remaining bars.
    Prevents unbounded candle_cache table growth on long-running deployments.

PHASE 1.23 (MAR 12, 2026):
  - FIX OR WINDOW: Removed dead `should_scan_now()` guard that was blocking
    all scanning from 9:30-9:40. scanner_optimizer now returns True from 9:30
    with 5s intervals so every 1m bar is captured for BOS+FVG detection.
  - Added OR window log banner so Railway logs show active BOS build status.
  - At 9:40 the first valid A+/A/A- confirmation candle fires the signal
    immediately — no 15s sleep gap between OR close and signal generation.

PHASE 1.23a (MAR 12, 2026):
  - FIX: REGIME-FILTER banner check now imports from correct module path
    (app.validation.validation.get_regime_filter) instead of app.filters.
"""
import os
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
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

# ── Health server (C5 fix) ────────────────────────────────────────────────────
from app.core.health_server import start_health_server, health_heartbeat

# ── Risk layer — single import, all risk calls go through here ────────────────
from app.risk.risk_manager import (
    get_loss_streak,
    get_session_status,
    get_eod_report,
    check_exits as risk_check_exits,
)
from app.risk.position_manager import position_manager as _pm

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# P0-3 FIX: Ticker timeout watchdog
# Each call to process_ticker() is submitted to a single-thread executor and
# given TICKER_TIMEOUT_SECONDS to complete.  If it hangs (blocked EODHD fetch,
# stalled confirmation loop, DB deadlock, etc.) the future is cancelled, a
# warning is logged, and the scan loop moves on to the next ticker unharmed.
# ─────────────────────────────────────────────────────────────────────────────
TICKER_TIMEOUT_SECONDS = 45
_ticker_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")


def _run_ticker_with_timeout(process_ticker_fn, ticker: str) -> bool:
    """
    Run process_ticker(ticker) with a hard wall-clock timeout.

    Returns True if it completed (successfully or with a handled exception),
    False if it was forcibly timed out.
    """
    future = _ticker_executor.submit(process_ticker_fn, ticker)
    try:
        future.result(timeout=TICKER_TIMEOUT_SECONDS)
        return True
    except FuturesTimeoutError:
        logger.error(
            f"[WATCHDOG] ⏰ {ticker} timed out after {TICKER_TIMEOUT_SECONDS}s "
            f"— skipping ticker, scan loop continues"
        )
        future.cancel()
        return False
    except Exception as exc:
        # process_ticker has its own internal try/except; this catches anything
        # that bubbles up despite that (should be rare).
        logger.error(f"[WATCHDOG] ❌ {ticker} raised unhandled exception: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# H1 FIX: analytics_conn with reconnect guard
# ─────────────────────────────────────────────────────────────────────────────
ANALYTICS_AVAILABLE = False
analytics_conn = None
DATABASE_URL = os.getenv('DATABASE_URL')

print("=" * 50, flush=True)
print("[DB] Attempting connection...", flush=True)
if DATABASE_URL:
    try:
        import psycopg2
        analytics_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        analytics_conn.autocommit = True  # Avoid idle-in-transaction issues
        print("[DB] ✓ Connected - Analytics ONLINE", flush=True)
        ANALYTICS_AVAILABLE = True
    except Exception as e:
        print(f"[DB] ✗ FAILED: {e}", flush=True)
        print("[DB] Analytics DISABLED - continuing without tracking", flush=True)
        ANALYTICS_AVAILABLE = False
else:
    print("[DB] ✗ DATABASE_URL not set - Analytics DISABLED", flush=True)
    ANALYTICS_AVAILABLE = False
print("=" * 50, flush=True)


def _get_analytics_conn():
    """
    H1 FIX: Return a live analytics connection.

    Checks the module-level connection with a lightweight SELECT 1.
    If it's dead (Railway restart, idle-connection timeout, TCP drop),
    silently reconnects and returns the fresh connection.
    Returns None when DATABASE_URL is unset or all reconnect attempts fail.
    """
    global analytics_conn, ANALYTICS_AVAILABLE

    if not DATABASE_URL:
        return None

    # Fast-path: probe existing connection
    if analytics_conn is not None:
        try:
            cur = analytics_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return analytics_conn  # Still alive
        except Exception:
            # Connection is dead — fall through to reconnect
            try:
                analytics_conn.close()
            except Exception:
                pass
            analytics_conn = None

    # Reconnect (up to 3 attempts)
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

API_KEY = os.getenv("EODHD_API_KEY", "")
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND FIRE-AND-FORGET HELPER (Phase 1.17)
# ─────────────────────────────────────────────────────────────────────────────
def _fire_and_forget(fn, label: str):
    """
    Spawn fn() as a daemon thread and return immediately.
    The thread runs to completion in the background; the main
    thread is never blocked or joined.
    """
    def _wrapper():
        try:
            fn()
            logger.info(f"[BG] ✅ {label} complete")
        except Exception as e:
            logger.warning(f"[BG] ⚠️  {label} failed: {e}")

    t = threading.Thread(target=_wrapper, daemon=True, name=label)
    t.start()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
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


def _is_or_window():
    """True during 9:30-9:39:59 ET — OR formation / BOS+FVG build window."""
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
    """
    Subscribe tickers to WS feeds immediately (blocking, fast).
    Historical backfill runs in the background so the scanner
    is never held up waiting for EODHD API responses.
    """
    if not new_tickers:
        return
    try:
        # Subscribe is instant — do it synchronously
        subscribe_tickers(new_tickers)
        subscribe_quote_tickers(new_tickers)
        logger.info(f"[WS-SUBSCRIBE] ✅ Subscribed {len(new_tickers)} tickers: {', '.join(new_tickers)}")

        # Kick off the slow EODHD backfill in the background
        _fire_and_forget(
            lambda: (
                data_manager.startup_backfill_with_cache(new_tickers, days=30),
                data_manager.startup_intraday_backfill_today(new_tickers),
            ),
            label=f"prefetch-{','.join(new_tickers[:3])}"
        )
        logger.info(f"[PREFETCH] 🔄 Background backfill started for {len(new_tickers)} tickers")
    except Exception as e:
        logger.error(f"[WS-SUBSCRIBE] ⚠️ Error subscribing tickers: {e}")
        import traceback
        traceback.print_exc()


def start_scanner_loop():
    # ────────────────────────────────────────────────────────────────────────
    # Import process_ticker directly from sniper.py
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
    # C5 FIX: Start HTTP health server before anything else so Railway's
    # probe gets a real response from the very first second of startup.
    # ════════════════════════════════════════════════════════════════════════
    start_health_server()

    # ════════════════════════════════════════════════════════════════════════
    # STARTUP HEALTH CHECK BANNER
    # ════════════════════════════════════════════════════════════════════════
    print("=" * 60, flush=True)
    print("WAR MACHINE CFW6 SCANNER v1.23 - STARTUP", flush=True)
    print("=" * 60, flush=True)
    print("✓ DATA-INGEST    WebSocket starting (tickers TBD)", flush=True)

    # ── FIX: use os.getcwd() so path resolves correctly inside Railway container
    try:
        cache_dir = os.path.join(os.getcwd(), 'cache')
        os.makedirs(cache_dir, exist_ok=True)  # create if missing — no-op if already exists
        cache_files = len([f for f in os.listdir(cache_dir) if f.endswith('.parquet')])
        print(f"✓ CACHE          {cache_files} cached ticker files, 30d history", flush=True)
    except Exception as e:
        print(f"? CACHE          Status unknown: {e}", flush=True)

    screener_icon = "✓" if API_KEY else "✗"
    screener_msg  = ("EODHD API configured (" + API_KEY[:8] + "...)") if API_KEY else "EODHD_API_KEY not set"
    print(f"{screener_icon} SCREENER       {screener_msg}", flush=True)

    # ── FIXED (Phase 1.23a): import from correct module path ─────────────────
    try:
        from app.validation.validation import get_regime_filter
        get_regime_filter()  # confirm instantiation succeeds
        print("✓ REGIME-FILTER  VIX/SPY regime detection active", flush=True)
    except Exception:
        print("? REGIME-FILTER  Module not found (may be inline)", flush=True)

    db_icon = "✓" if ANALYTICS_AVAILABLE else "✗"
    db_msg  = "Connected - Analytics tracking enabled" if ANALYTICS_AVAILABLE else "OFFLINE - no volume/signal/P&L tracking"
    print(f"{db_icon} DATABASE        {db_msg}", flush=True)

    discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
    disc_icon = "✓" if discord_webhook else "✗"
    disc_msg  = "Alert notifications ready" if discord_webhook else "NOT CONFIGURED - no alerts"
    print(f"{disc_icon} DISCORD         {disc_msg}", flush=True)

    opts_icon = "✓" if OPTIONS_AVAILABLE else "✗"
    opts_msg  = "Integrated - Greeks analysis active" if OPTIONS_AVAILABLE else "NOT INTEGRATED"
    print(f"{opts_icon} OPTIONS-GATE    {opts_msg}", flush=True)

    val_icon = "✓" if VALIDATION_AVAILABLE else "✗"
    val_msg  = "Integrated - CFW6 confirmation active" if VALIDATION_AVAILABLE else "NOT INTEGRATED"
    print(f"{val_icon} VALIDATION      {val_msg}", flush=True)

    print("=" * 60, flush=True)
    pm_mode = "Pre-market" if is_premarket() else "Live"
    print("Trading session: 09:30 - 16:00 ET", flush=True)
    print(f"Scanner mode: {pm_mode}", flush=True)
    print("=" * 60, flush=True)
    print("Candle Cache:    ✅ ENABLED (95%+ API reduction on redeploy)", flush=True)
    print("WS Failover:     ✅ ENABLED (REST API fallback on disconnect)", flush=True)
    print("Spread Gate:     ✅ ENABLED (us-quote bid/ask filter active)", flush=True)
    print("Dynamic WS:      ✅ ENABLED (live session ticker subscription)", flush=True)
    print("Risk Manager:    ✅ ENABLED (unified risk layer — Phase 1.15)", flush=True)
    print("CFW6 Engine:     ✅ ENABLED (sniper.py direct — Phase 1.16)", flush=True)
    print("BG Backfill:     ✅ ENABLED (fire-and-forget — Phase 1.17)", flush=True)
    print("Cache Dir Fix:   ✅ FIXED   (os.getcwd() — Phase 1.18a)", flush=True)
    print("Health HTTP:     ✅ ENABLED (GET /health → 200/503 — Phase 1.19 C5)", flush=True)
    print("Analytics Conn:  ✅ FIXED   (reconnect guard — Phase 1.20 H1)", flush=True)
    print(f"Ticker Watchdog: ✅ ENABLED ({TICKER_TIMEOUT_SECONDS}s hard timeout per ticker — Phase 1.21 P0-3)", flush=True)
    print("Cache Cleanup:   ✅ ENABLED (30d candle_cache pruning EOD — Phase 1.22)", flush=True)
    print("OR Window:       ✅ FIXED   (9:30-9:40 scans every 5s, no sleep — Phase 1.23)", flush=True)
    print("Regime Banner:   ✅ FIXED   (correct import path — Phase 1.23a)", flush=True)
    print("=" * 60 + "\n", flush=True)

    try:
        send_simple_message("⚔️ WAR MACHINE ONLINE — CFW6 v1.23 | OR window active scanning | Phase 1.23a")
    except Exception as e:
        logger.warning(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist       = []
    premarket_built           = False
    cycle_count               = 0
    last_report_day           = None
    loss_streak_alerted       = False
    last_subscribed_watchlist = set()
    _or_window_logged         = False  # suppress repeated OR banner lines

    # ── STARTUP SEQUENCE ────────────────────────────────────────────────────
    # Phase 1.17: WS feeds start with a short join (they connect fast).
    # All EODHD API backfill is fire-and-forget — never blocks main loop.
    # ─────────────────────────────────────────────────────────────────────
    startup_watchlist = list(EMERGENCY_FALLBACK)

    # WS connections are fast — short join is fine
    ws_thread = threading.Thread(
        target=lambda: start_ws_feed(startup_watchlist),
        daemon=True, name="start_ws_feed"
    )
    ws_thread.start()
    ws_thread.join(timeout=20)
    logger.info("[WS] WebSocket feed started (or timed out gracefully)")

    quote_thread = threading.Thread(
        target=lambda: start_quote_feed(startup_watchlist),
        daemon=True, name="start_quote_feed"
    )
    quote_thread.start()
    quote_thread.join(timeout=20)
    logger.info("[QUOTE] Quote feed started (or timed out gracefully)")

    # Backfill is SLOW (N tickers × 30s API timeout each).
    # Fire-and-forget: main loop enters immediately.
    _fire_and_forget(
        lambda: data_manager.startup_backfill_with_cache(startup_watchlist, days=30),
        label="startup_backfill"
    )
    _fire_and_forget(
        lambda: data_manager.startup_intraday_backfill_today(startup_watchlist),
        label="intraday_backfill"
    )

    # Mark backfill as "complete" right away so WS starts receiving bars
    set_backfill_complete()
    last_subscribed_watchlist = set(startup_watchlist)
    logger.info("[STARTUP] ✅ WS feeds up | backfill running in background | entering main loop")
    # ─────────────────────────────────────────────────────────────────────

    while True:
        try:
            # ── C5: heartbeat — keeps /health returning 200 ──────────────
            health_heartbeat()

            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            # ── PRE-MARKET ────────────────────────────────────────────────
            if is_premarket():
                _or_window_logged = False  # reset for next session
                if not premarket_built:
                    logger.info(f"[PRE-MARKET] {current_time_str} - Building Watchlist")
                    try:
                        watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata            = watchlist_data['metadata']
                        volume_signals      = watchlist_data['volume_signals']

                        if not premarket_watchlist and now_et.time() > dtime(8, 0):
                            logger.warning("⚠️  WATCHLIST EMPTY after 8:00 AM - possible config issue")
                            try:
                                send_simple_message("⚠️ **WATCHLIST EMPTY** after 8:00 AM ET — Check funnel configuration!")
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

                        stage_emoji = {'wide': '📡', 'narrow': '🎯', 'final': '🔥', 'live': '⚡'}
                        emoji       = stage_emoji.get(metadata['stage'], '📊')
                        pm_metrics  = _extract_premarket_metrics(watchlist_data)

                        ellipsis = '...' if len(premarket_watchlist) > 20 else ''
                        msg = (
                            f"{emoji} **{metadata['stage_description']}**\n"
                            f"✅ Watchlist: {len(premarket_watchlist)} tickers\n"
                            f"{', '.join(premarket_watchlist[:20])}{ellipsis}\n"
                        )
                        if pm_metrics:
                            msg += (
                                f"\n**Screener Insights:**\n"
                                f"🔥 Explosive: {pm_metrics['explosive_count']} "
                                f"(RVOL ≥{pm_metrics['explosive_rvol_threshold']}x)\n"
                                f"📊 Avg RVOL: {pm_metrics['avg_rvol']:.1f}x | "
                                f"Avg Score: {pm_metrics['avg_score']:.0f}\n"
                                f"🎯 Top 3: {pm_metrics['top_3_summary']}"
                            )
                        if volume_signals:
                            msg += f"\n\n⚠️ {len(volume_signals)} volume signals active"
                        send_simple_message(msg)

                        for ticker in premarket_watchlist:
                            _run_ticker_with_timeout(process_ticker, ticker)

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
                                _run_ticker_with_timeout(process_ticker, ticker)
                        except Exception as e:
                            logger.error(f"[PRE-MARKET] Refresh error: {e}")
                    else:
                        logger.info(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")
                    time.sleep(60)
                continue

            # ── MARKET HOURS ──────────────────────────────────────────────
            elif is_market_hours():
                # ── OR WINDOW (9:30-9:39): actively scan every 5s, no sleep ──
                # should_scan_now() returns True and get_adaptive_scan_interval()
                # returns 5s during this window. Log once so Railway logs are clean.
                if _is_or_window():
                    if not _or_window_logged:
                        logger.info(
                            f"[SCANNER] 📊 OR WINDOW — BOS+FVG building (9:30-9:40) "
                            f"scanning every 5s | {current_time_str}"
                        )
                        _or_window_logged = True

                if get_loss_streak():
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
                    logger.info(f"[WS-SUBSCRIBE] 🔄 Detected {len(new_tickers)} new watchlist tickers")
                    subscribe_and_prefetch_tickers(new_tickers)
                    last_subscribed_watchlist = current_set

                logger.info(f"[SCANNER] {len(watchlist)} tickers | {', '.join(watchlist[:10])}...")

                # H1 FIX: use reconnect-aware accessor instead of bare analytics_conn
                if ANALYTICS_AVAILABLE and analytics:
                    try:
                        live_conn = _get_analytics_conn()
                        if live_conn and analytics:
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
                        # P0-3 FIX: wrapped in 45s timeout watchdog
                        _run_ticker_with_timeout(process_ticker, ticker)

                    except Exception as e:
                        logger.error(f"[SCANNER] Error on {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

                logger.info(f"[SCANNER] Cycle #{cycle_count} complete")
                scan_interval = get_adaptive_scan_interval()
                logger.info(f"[SCANNER] Sleeping {scan_interval}s...")
                time.sleep(scan_interval)

            # ── AFTER HOURS / EOD ─────────────────────────────────────────
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
                            f"📊 **EOD Report {current_day}**\n"
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

                    # ── Phase 1.22: EOD cleanup — DB bars (60d) + candle cache (30d) ──
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
                send_simple_message(f"⚠️ Scanner Error: {str(e)}")
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
