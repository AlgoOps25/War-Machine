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


PHASE 1.18 (MAR 10, 2026):
  - FIXED: DB startup block now uses print() so status always visible in Railway logs


PHASE 1.18a (MAR 10, 2026):
  - FIXED: Cache dir uses os.getcwd() instead of __file__ relative path (Railway compat)


PHASE 1.19 (MAR 10, 2026):
  - FIX C5: start_health_server() called once at startup before WS init


PHASE 1.20 (MAR 10, 2026):
  - FIX H1: analytics_conn wrapped in reconnect helper


PHASE 1.21 (MAR 10, 2026):
  - FIX P0-3: Ticker timeout watchdog — 45-second hard timeout per ticker


PHASE 1.22 (MAR 10, 2026):
  - FIX: candle_cache EOD cleanup now runs alongside DB bar cleanup


PHASE 1.23 (MAR 12, 2026):
  - FIX OR WINDOW: Removed dead should_scan_now() guard blocking 9:30-9:40


PHASE 1.23a (MAR 12, 2026):
  - FIX: REGIME-FILTER banner check imports from correct module path


PHASE 1.24 (MAR 13, 2026):
  - FIX 1: Boot-time session guard on redeploy during market hours
  - FIX 2-6: Log noise, premarket guard, smart backfill improvements


PHASE 1.25 (MAR 13, 2026):
  - SPY+QQQ Market Regime — visual-only Discord, no hard blocks


PHASE 1.26 (MAR 13, 2026):
  - FIX REGIME FILTER: SPY and QQQ always included in WS subscription


PHASE 1.27 (MAR 14, 2026):
  - FIX HEALTHCHECK: start_health_server() moved to module level


PHASE 1.28 (MAR 16, 2026):
  - FIX #10: validate_required_env_vars() called at top of start_scanner_loop()
    Hard-fails on missing EODHD_API_KEY / DATABASE_URL / DISCORD_WEBHOOK_URL
    before any blocking DB/WS work begins. Surfaces config errors immediately
    in Railway logs with a clear table instead of a cryptic mid-boot crash.


PHASE 1.29 (MAR 16, 2026):
  - FIX #9: Eliminate redundant get_session_status() / get_loss_streak() DB
    checkouts in the main scan cycle.
    * get_session_status() called ONCE per cycle, result cached as `session`
    * loss_streak derived from session["daily_stats"] (no extra DB call)
    * monitor_open_positions() accepts optional pre-fetched session kwarg
    Net: 3 DB checkouts per cycle -> 1, preventing pool exhaustion at OR open.


PHASE 1.30 (MAR 16, 2026):
  - FIX: Remove dead sniper_stubs fallback. sniper_stubs was deprecated;
    the try/except was masking the real numpy/libstdc++ ImportError with
    a confusing ModuleNotFoundError. Hard raise now surfaces real error.


PHASE 1.31 (MAR 17, 2026):
  - FIX: Correct discord_helpers import path.
    Was: from app.discord_helpers import send_simple_message
    Now: from app.notifications.discord_helpers import send_simple_message


PHASE 1.32 (MAR 17, 2026):
  - EOD block refactored to call eod_reporter.run_eod_report().
    Removes 30-line inline Discord builder; all EOD Discord logic
    now lives in app/core/eod_reporter.py (single responsibility).
    signal_tracker.get_discord_eod_summary() is now sent every EOD.


PHASE 1.33 (MAR 17, 2026):
  - Remove dead _get_eod_summary_metrics() helper.
    Was only used by the old inline EOD block removed in Phase 1.32.
    No callers remain in the codebase.


PHASE 1.34 (MAR 19, 2026):
  - FIX: Wire reset_funnel() into EOD reset block.
    The WatchlistFunnel singleton (_funnel_instance) persisted across session
    boundaries on Railway (no restart between days). Yesterday's locked
    watchlist was returned all day on the following session.
    reset_funnel() sets _funnel_instance = None so the next premarket
    scan creates a fresh WatchlistFunnel() with no stale lock.


PHASE 1.35 (MAR 19, 2026):
  - FIX: start_health_server() moved to TRUE module level — before DB connect block.
    Phase 1.27 claimed this fix but the call was still inside start_scanner_loop().
    Railway's 30s healthcheck window was being consumed by psycopg2.connect()
    before /health ever came up, causing "Starting Container" hang on cold deploy.
  - Removed duplicate start_health_server() call inside start_scanner_loop().
  - connect_timeout lowered 10s -> 3s on module-level psycopg2.connect() so a
    slow Postgres cold-start cannot eat the Railway healthcheck window.
"""
from app.core.health_server import start_health_server, health_heartbeat

# ── PHASE 1.35: Start health server at TRUE module level ──────────────────────
# Must happen before ANY blocking work (DB connect, imports, etc.) so Railway's
# /health probe gets a 200 response within the 30s healthcheck window.
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
# Scanner optimizer caches
_last_logged_interval = None
_last_logged_watchlist_size = None
from app.data.data_manager import data_manager
from app.data.ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from app.data.ws_quote_feed import start_quote_feed, subscribe_quote_tickers
from app.screening.watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel,
    reset_funnel,          # PHASE 1.34: daily singleton reset
)
from app.risk.risk_manager import (
    get_loss_streak,
    get_session_status,
    get_eod_report,
    check_exits as risk_check_exits,
)
from app.risk.position_manager import position_manager as _pm


try:
    from app.filters.market_regime_context import send_regime_discord
    REGIME_DISCORD_AVAILABLE = True
except Exception:
    REGIME_DISCORD_AVAILABLE = False
    def send_regime_discord(regime=None, force=False): pass


logger = logging.getLogger(__name__)


REGIME_TICKERS = ["SPY", "QQQ"]


TICKER_TIMEOUT_SECONDS = 45
_ticker_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")



def _run_ticker_with_timeout(process_ticker_fn, ticker: str) -> bool:
    future = _ticker_executor.submit(process_ticker_fn, ticker)
    try:
        future.result(timeout=TICKER_TIMEOUT_SECONDS)
        return True
    except FuturesTimeoutError:
        logger.error(
            f"[WATCHDOG] ⏰ {ticker} timed out after {TICKER_TIMEOUT_SECONDS}s — skipping"
        )
        future.cancel()
        return False
    except Exception as exc:
        logger.error(f"[WATCHDOG] ❌ {ticker} raised unhandled exception: {exc}")
        return False



ANALYTICS_AVAILABLE = False
analytics_conn = None
_analytics_conn_lock = __import__('threading').Lock()
DATABASE_URL = os.getenv('DATABASE_URL')


if DATABASE_URL:
    try:
        import psycopg2
        # PHASE 1.35: connect_timeout 10s -> 3s so slow DB cold-start cannot
        # eat the Railway 30s healthcheck window before /health comes up.
        analytics_conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        analytics_conn.autocommit = True
        logger.info("[DB] ✓ Connected - Analytics ONLINE")
        ANALYTICS_AVAILABLE = True
    except Exception as e:
        logger.info(f"[DB] ✗ FAILED: {e}")
        logger.info("[DB] Analytics DISABLED - continuing without tracking")
        ANALYTICS_AVAILABLE = False
else:
    logger.info("[DB] ✗ DATABASE_URL not set - Analytics DISABLED")
    ANALYTICS_AVAILABLE = False


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
    """Return tickers that have no cached bar in the last 24 hours."""
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
    if dtime(9, 30) <= now < dtime(9, 40):
        interval = 5
        label = "OR Formation (BOS build)"
    elif dtime(9, 40) <= now < dtime(11, 0):
        interval = 45
        label = "Post-OR Morning"
    elif dtime(11, 0) <= now < dtime(14, 0):
        interval = 180
        label = "Midday Chop"
    elif dtime(14, 0) <= now < dtime(15, 30):
        interval = 60
        label = "Afternoon Activity"
    elif dtime(15, 30) <= now < dtime(16, 0):
        interval = 45
        label = "Power Hour"
    else:
        interval = 300
        label = "Outside Market Hours"
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
    if dtime(9, 30) <= now < dtime(9, 40):
        size = 30
    elif dtime(9, 40) <= now < dtime(10, 30):
        size = 30
    elif dtime(10, 30) <= now < dtime(15, 0):
        size = 50
    elif dtime(15, 0) <= now <= dtime(16, 0):
        size = 35
    else:
        size = 40
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
    """
    FIX #9 (PHASE 1.29): Accept optional pre-fetched session dict.
    When the caller already holds a session snapshot from this cycle,
    we skip the redundant get_session_status() DB checkout entirely.
    """
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
        logger.info(f"[WS-SUBSCRIBE] ✅ Subscribed {len(new_tickers)} tickers + regime ({', '.join(REGIME_TICKERS)}): {', '.join(new_tickers)}")
        _fire_and_forget(
            lambda: (
                data_manager.startup_backfill_with_cache(combined, days=30),
                data_manager.startup_intraday_backfill_today(combined),
            ),
            label=f"prefetch-{','.join(new_tickers[:3])}"
        )
        logger.info(f"[PREFETCH] 🔄 Background backfill started for {len(combined)} tickers")
    except Exception as e:
        logger.error(f"[WS-SUBSCRIBE] ⚠ Error subscribing tickers: {e}")
        import traceback
        traceback.print_exc()



def start_scanner_loop():
    # ── PHASE 1.28: Validate required env vars before any blocking work ────────────
    validate_required_env_vars()
    # NOTE: start_health_server() is intentionally NOT called here.
    # It was moved to true module level in Phase 1.35 so Railway's healthcheck
    # probe can reach /health before any blocking init runs.

    # ── PHASE 1.30: Hard import — no stubs fallback (sniper_stubs deprecated) ───
    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals, _orb_classifications
    logger.info("[SCANNER] ✅ process_ticker loaded from sniper.py (CFW6 engine active)")


    # ── PHASE 1.31: Correct import path for send_simple_message ─────────────────
    from app.notifications.discord_helpers import send_simple_message


    try:
        from app.ai.ai_learning import learning_engine
        HAS_AI_LEARNING = True
    except ImportError:
        learning_engine = None
        HAS_AI_LEARNING = False


    # ── STARTUP BANNER ────────────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("WAR MACHINE CFW6 SCANNER v1.38b - STARTUP")
    logger.info("=" * 60)
    logger.info("✓ REGIME-FILTER  VIX/SPY regime detection active")
    logger.info("=" * 60)
    logger.info("Risk Manager:    ✅ ENABLED (unified risk layer — Phase 1.15)")
    logger.info("✓ DATA-INGEST    WebSocket starting (tickers TBD)")


    try:
        cache_dir  = os.path.join(os.getcwd(), 'cache')
        os.makedirs(cache_dir, exist_ok=True)
        cache_files = len([f for f in os.listdir(cache_dir) if f.endswith('.parquet')])
        logger.info(f"✓ CACHE          {cache_files} cached ticker files, 30d history")
    except Exception as e:
        logger.info(f"? CACHE          Status unknown: {e}")


    db_icon = "✓" if ANALYTICS_AVAILABLE else "✗"
    db_msg  = "Connected - Analytics tracking enabled" if ANALYTICS_AVAILABLE else "OFFLINE - no volume/signal/P&L tracking"
    logger.info(f"✓ DATABASE        {db_msg}")


    discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
    disc_icon = "✓" if discord_webhook else "✗"
    disc_msg  = "Alert notifications ready" if discord_webhook else "NOT CONFIGURED - no alerts"
    logger.info(f"{disc_icon} DISCORD         {disc_msg}")


    screener_icon = "✓" if API_KEY else "✗"
    screener_msg  = ("EODHD API configured (" + API_KEY[:8] + "...)") if API_KEY else "EODHD_API_KEY not set"
    logger.info(f"{screener_icon} SCREENER       {screener_msg}")


    try:
        from app.validation.validation import get_regime_filter
        get_regime_filter()
        logger.info("✓ REGIME-FILTER  VIX/SPY regime detection active")
    except Exception:
        logger.info("? REGIME-FILTER  Module not found (may be inline)")


    regime_webhook = os.getenv('REGIME_WEBHOOK_URL')
    reg_icon = "✓" if regime_webhook else "✗"
    reg_msg  = "Regime channel active (SPY+QQQ visual)" if regime_webhook else "NOT CONFIGURED — set REGIME_WEBHOOK_URL"
    logger.info(f"{reg_icon} REGIME-DISCORD  {reg_msg}")


    opts_icon = "✓" if OPTIONS_AVAILABLE else "✗"
    opts_msg  = "Integrated - Greeks analysis active" if OPTIONS_AVAILABLE else "NOT INTEGRATED"
    logger.info(f"{opts_icon} OPTIONS-GATE    {opts_msg}")


    val_icon = "✓" if VALIDATION_AVAILABLE else "✗"
    val_msg  = "Integrated - CFW6 confirmation active" if VALIDATION_AVAILABLE else "NOT INTEGRATED"
    logger.info(f"{val_icon} VALIDATION      {val_msg}")


    logger.info("=" * 60)
    pm_mode = "Pre-market" if is_premarket() else "Live"
    logger.info("Trading session: 09:30 - 16:00 ET")
    logger.info(f"Scanner mode: {pm_mode}")
    logger.info("=" * 60)
    logger.info("Candle Cache:    ✅ ENABLED (95%+ API reduction on redeploy)")
    logger.info("WS Failover:     ✅ ENABLED (REST API fallback on disconnect)")
    logger.info("Spread Gate:     ✅ ENABLED (us-quote bid/ask filter active)")
    logger.info("Dynamic WS:      ✅ ENABLED (live session ticker subscription)")
    logger.info("CFW6 Engine:     ✅ ENABLED (sniper.py direct — Phase 1.16)")
    logger.info("BG Backfill:     ✅ ENABLED (fire-and-forget — Phase 1.17)")
    logger.info("Cache Dir Fix:   ✅ FIXED   (os.getcwd() — Phase 1.18a)")
    logger.info("Health HTTP:     ✅ ENABLED (GET /health → 200/503 — Phase 1.19 C5)")
    logger.info("Analytics Conn:  ✅ FIXED   (reconnect guard — Phase 1.20 H1)")
    logger.info(f"Ticker Watchdog:✅ ENABLED ({TICKER_TIMEOUT_SECONDS}s hard timeout — Phase 1.21 P0-3)")
    logger.info("Cache Cleanup:   ✅ ENABLED (30d candle_cache pruning EOD — Phase 1.22)")
    logger.info("OR Window:       ✅ FIXED   (9:30-9:40 scans every 5s — Phase 1.23)")
    logger.info("Regime Banner:   ✅ FIXED   (correct import path — Phase 1.23a)")
    logger.info("Session Guard:   ✅ FIXED   (skip premarket on redeploy — Phase 1.24)")
    logger.info("Log Noise:       ✅ REDUCED (no per-ticker banners, no lock spam — Phase 1.24)")
    logger.info("Smart Backfill:  ✅ ENABLED (skip warm cache tickers on redeploy — Phase 1.24)")
    logger.info("Market Regime:   ✅ VISUAL  (SPY+QQQ → REGIME_WEBHOOK_URL, no blocks — Phase 1.25)")
    logger.info(f"Regime WS Feed: ✅ FIXED   (SPY+QQQ always subscribed for regime bars — Phase 1.26)")
    logger.info("Health Boot Fix: ✅ FIXED   (start_health_server at module load — Phase 1.27/1.35)")
    logger.info("Env Var Guard:   ✅ ENABLED (validate_required_env_vars — Phase 1.28)")
    logger.info("DB Checkout Fix: ✅ FIXED   (single get_session_status per cycle — Phase 1.29)")
    logger.info("Sniper Import:   ✅ FIXED   (hard import, no dead stubs fallback — Phase 1.30)")
    logger.info("Discord Import:  ✅ FIXED   (app.notifications.discord_helpers — Phase 1.31)")
    logger.info("EOD Reporter:    ✅ ENABLED (eod_reporter.run_eod_report() — Phase 1.32)")
    logger.info("Dead Code:       ✅ REMOVED (_get_eod_summary_metrics deleted — Phase 1.33)")
    logger.info("Funnel Reset:    ✅ FIXED   (reset_funnel() at EOD — daily watchlist — Phase 1.34)")
    logger.info(f"  RVOL Signal Gate : ✅ ENABLED (MIN_RVOL={config.RVOL_SIGNAL_GATE}x hard floor — Phase 1.36)")
    logger.info("RVOL Signal Gate: ✅ ENABLED (MIN_RVOL=1.5x hard floor before options — Phase 1.36)")
    logger.info(f"  RVOL Ceiling   : ✅ ENABLED (MAX_RVOL={config.RVOL_CEILING}x hard cap — Phase 1.38b)")
    logger.info(f"  Bear Signals   : {'✅ ENABLED' if config.BEAR_SIGNALS_ENABLED else '🚫 DISABLED'} (Phase 1.38b — 267 trades -0.15R)")
    logger.info("=" * 60 + "\n")


    _booting_into_market_hours = is_market_hours()
    premarket_watchlist = []
    premarket_built     = False


    if _booting_into_market_hours:
        logger.info("[SCANNER] ⚡ Redeploy detected during market hours — skipping premarket, loading locked watchlist")
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
            f"⚔️ WAR MACHINE ONLINE — CFW6 v1.35 | "
            f"{'Resuming intraday' if _booting_into_market_hours else 'OR window active'} | Phase 1.35"
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
        (premarket_watchlist if premarket_watchlist else list(EMERGENCY_FALLBACK))
        + REGIME_TICKERS
    ))


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


    stale = _get_stale_tickers(startup_watchlist)
    if stale:
        logger.info(f"[BACKFILL] {len(stale)} stale tickers need backfill: {', '.join(stale)}")
        _fire_and_forget(
            lambda: data_manager.startup_backfill_with_cache(stale, days=30),
            label="startup_backfill"
        )
        _fire_and_forget(
            lambda: data_manager.startup_intraday_backfill_today(stale),
            label="intraday_backfill"
        )
    else:
        logger.info("[BACKFILL] ✅ All tickers have warm cache — skipping EODHD backfill")


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
                            combined = list(dict.fromkeys(premarket_watchlist + REGIME_TICKERS))
                            subscribe_tickers(combined)
                            subscribe_quote_tickers(combined)
                        last_subscribed_watchlist = current_set


                        logger.info(f"[WS] Subscribed premarket watchlist ({len(premarket_watchlist)} tickers)")


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


                # ── FIX #9 (PHASE 1.29): Single get_session_status() per cycle ──
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
                    if PRODUCTION_HELPERS_ENABLED:
                        def _run_analytics():
                            live_conn = _get_analytics_conn()
                            if live_conn and analytics:
                                def get_price(ticker):
                                    from app.data.ws_feed import get_current_bar_with_fallback
                                    bar = get_current_bar_with_fallback(ticker)
                                    return bar['close'] if bar else None
                                analytics.monitor_active_signals(get_price)
                                analytics.check_scheduled_tasks()
                        _db_operation_safe(_run_analytics, "analytics monitor")
                    else:
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
                        import traceback
                        traceback.print_exc()
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


                    # ── PHASE 1.32: Unified EOD reporting via eod_reporter ─────────────────
                    try:
                        from app.core.eod_reporter import run_eod_report
                        run_eod_report(current_day)
                    except Exception as e:
                        logger.error(f"[EOD] eod_reporter failed: {e}")
                        import traceback
                        traceback.print_exc()


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


                    # ── PHASE 1.34: Reset funnel singleton for fresh daily build ──
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
