"""
scanner.py — Intelligent Watchlist Builder & Scanner Loop v1.38e
Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, DB Cleanup.
WebSocket bar + quote feeds with candle cache (95%+ API reduction on redeploy).
See CHANGELOG.md for full phase history.

AUDIT S17 (2026-03-31): BUG-SC-1/2/3/4/5/6 addressed.
  SC-1: Standardized blank lines between all top-level definitions (PEP 8).
  SC-2: Documented future.cancel() limitation in _run_ticker_with_timeout.
  SC-3: Documented lambda tuple order / exception behavior in subscribe_and_prefetch_tickers.
  SC-4: Noted API_KEY[:8] slice is safe (Python slicing never raises IndexError).
  SC-5: Fixed startup Discord message — now correctly says 'Pre-market' vs 'OR window active'.
  SC-6: Added comment to _run_analytics explaining conn=None is required by _db_operation_safe.

AUDIT CORE-5 (2026-03-31): SC-A/B/C/E/F/G addressed.
  SC-A: Version bump docstring + banner + Discord message → v1.38e (sync with sniper.py).
  SC-B: Removed dead `metadata = watchlist_data['metadata']` in premarket first-build block.
  SC-C: watchlist_data['watchlist'] → .get('watchlist', []) in both premarket path blocks.
  SC-E: _get_stale_tickers silent except now logs warning before returning full list.
  SC-F: _REDEPLOY_RETRIES / _REDEPLOY_RETRY_WAIT moved to module-level constants.
  SC-G: metadata['stage'] / metadata['stage_description'] → .get() with '?' fallbacks.
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

REGIME_TICKERS         = ["SPY", "QQQ"]
TICKER_TIMEOUT_SECONDS = 45
# SC-F FIX (CORE-5): Moved from inside start_scanner_loop() to module-level.
# Constants belong at module scope — consistent with TICKER_TIMEOUT_SECONDS above.
_REDEPLOY_RETRIES      = 2
_REDEPLOY_RETRY_WAIT   = 3
_ticker_executor       = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker_watchdog")


def _run_ticker_with_timeout(process_ticker_fn, ticker: str) -> bool:
    future = _ticker_executor.submit(process_ticker_fn, ticker)
    try:
        future.result(timeout=TICKER_TIMEOUT_SECONDS)
        return True
    except FuturesTimeoutError:
        logger.error(f"[WATCHDOG] ⏰ {ticker} timed out after {TICKER_TIMEOUT_SECONDS}s — skipping")
        # BUG-SC-2 (documented): future.cancel() has NO effect on an already-running
        # ThreadPoolExecutor thread — Python threads cannot be forcibly interrupted.
        # cancel() always returns False here. The thread continues running in the
        # background until it completes naturally. This is a known Python limitation.
        # The scanner correctly moves on; resource impact is bounded by the executor's
        # max_workers=1 — the next ticker won't start until the timed-out thread finishes.
        future.cancel()
        return False
    except Exception as exc:
        logger.error(f"[WATCHDOG] ❌ {ticker} raised unhandled exception: {exc}")
        return False


# FIX #30: Removed raw module-level analytics_conn psycopg2 connection and
# _get_analytics_conn() reconnect helper. That connection was a parallel,
# unmanaged socket that bypassed the db_connection.py semaphore pool entirely.
# AnalyticsIntegration.__init__ accepts db_connection for API compatibility but
# ignores it — SignalTracker manages its own pooled connection internally.
# The old block also kept a bare psycopg2.connect() at import time which could
# block Railway startup and left an unclosed socket on any crash.
ANALYTICS_AVAILABLE = False
DATABASE_URL        = os.getenv('DATABASE_URL')

if DATABASE_URL:
    ANALYTICS_AVAILABLE = True
    logger.info("[DB] ✓ DATABASE_URL present - Analytics ONLINE")
else:
    logger.info("[DB] ✗ DATABASE_URL not set - Analytics DISABLED")


try:
    from app.signals.signal_analytics import signal_tracker
    LEGACY_ANALYTICS_ENABLED = True
    logger.info("[SCANNER] ✅ Legacy signal analytics enabled")
except ImportError:
    LEGACY_ANALYTICS_ENABLED = False
    signal_tracker = None

analytics = None
if ANALYTICS_AVAILABLE:
    try:
        from app.analytics import AnalyticsIntegration
        if AnalyticsIntegration is not None:
            analytics = AnalyticsIntegration(db_connection=None, enable_ml=True, enable_discord=True)
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
    except Exception as e:
        # SC-E FIX (CORE-5): Log warning before returning full list so the cause of
        # a full backfill on startup is visible in Railway logs instead of silent.
        logger.warning(f"[CACHE] Stale-check failed ({e}) — treating all {len(tickers)} tickers as stale")
        return list(tickers)
    return stale


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
        # BUG-SC-3 (documented): Lambda calls two backfill functions as a tuple expression.
        # Both are executed left-to-right: startup_backfill_with_cache first (30d history),
        # then startup_intraday_backfill_today (today's bars). Order is intentional —
        # historical context must be loaded before intraday bars are appended.
        # If startup_intraday_backfill_today raises, _fire_and_forget catches it as a
        # warning — historical backfill will have already completed successfully.
        _fire_and_forget(
            lambda: (
                data_manager.startup_backfill_with_cache(combined, days=30),
                data_manager.startup_intraday_backfill_today(combined),
            ),
            label=f"prefetch-{','.join(new_tickers[:3])}"
        )
    except Exception as e:
        logger.error(f"[WS-SUBSCRIBE] ⚠ Error subscribing tickers: {e}")
        logger.exception(e)


def start_scanner_loop():
    validate_required_env_vars()

    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals, clear_bos_alerts
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
    # SC-A FIX (CORE-5): Version bumped to v1.38e — synced with sniper.py post CORE-4.
    logger.info("WAR MACHINE CFW6 SCANNER v1.38e - STARTUP")
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
    # BUG-SC-4 (documented): API_KEY[:8] is safe — Python slice never raises IndexError.
    # If API_KEY is shorter than 8 chars (e.g. a stub), the full string is shown.
    # The ✗ branch is taken when API_KEY == "" so [:8] is only reached when a key exists.
    scrn_msg = ("EODHD API configured (" + API_KEY[:8] + "...)") if API_KEY else "EODHD_API_KEY not set"
    reg_msg  = "Regime channel active" if os.getenv('REGIME_WEBHOOK_URL') else "Set REGIME_WEBHOOK_URL"
    opts_msg = "Greeks analysis active" if OPTIONS_AVAILABLE else "NOT INTEGRATED"
    val_msg  = "CFW6 confirmation active" if VALIDATION_AVAILABLE else "NOT INTEGRATED"

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

    # BUG-SC-5 FIX (2026-03-31): Previous message showed "OR window active" for any
    # non-market-hours startup (including pre-market at 8:45 AM before the OR opens).
    # Now correctly distinguishes: live market hours vs pre-market vs after-hours.
    if _booting_into_market_hours:
        _startup_mode = "Resuming intraday"
    elif is_premarket():
        _startup_mode = "Pre-market build active"
    else:
        _startup_mode = "After-hours — awaiting market open"

    try:
        # SC-A FIX (CORE-5): Discord message version synced to v1.38e.
        send_simple_message(
            f"⚔️ WAR MACHINE ONLINE — CFW6 v1.38e | {_startup_mode}"
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
        list(EMERGENCY_FALLBACK) + REGIME_TICKERS
    ))

    logger.info("[WS-INIT] Starting WebSocket feed thread...")
    ws_thread = threading.Thread(target=lambda: start_ws_feed(startup_watchlist), daemon=True, name="start_ws_feed")
    ws_thread.start()
    time.sleep(2)
    ws_thread.join(timeout=5)
    logger.info("[WS] WebSocket feed started (or timed out gracefully)")

    quote_thread = threading.Thread(target=lambda: start_quote_feed(startup_watchlist), daemon=True, name="start_quote_feed")
    quote_thread.start()
    quote_thread.join(timeout=5)
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

    if _booting_into_market_hours:
        logger.info("[SCANNER] ⚡ Redeploy detected during market hours — loading locked watchlist")
        for attempt in range(1, _REDEPLOY_RETRIES + 1):
            try:
                watchlist_data      = get_watchlist_with_metadata(force_refresh=False)
                premarket_watchlist = watchlist_data.get('watchlist', [])
                if premarket_watchlist:
                    logger.info(
                        f"[SCANNER] ✅ Loaded locked watchlist: "
                        f"{len(premarket_watchlist)} tickers (attempt {attempt})"
                    )
                    break
                else:
                    logger.warning(
                        f"[SCANNER] ⚠️ Watchlist empty on attempt {attempt}/{_REDEPLOY_RETRIES} "
                        f"— {'retrying in ' + str(_REDEPLOY_RETRY_WAIT) + 's' if attempt < _REDEPLOY_RETRIES else 'giving up'}"
                    )
                    if attempt < _REDEPLOY_RETRIES:
                        time.sleep(_REDEPLOY_RETRY_WAIT)
            except Exception as e:
                logger.warning(
                    f"[SCANNER] ⚠️ Watchlist load error on attempt {attempt}/{_REDEPLOY_RETRIES}: {e}"
                )
                if attempt < _REDEPLOY_RETRIES:
                    time.sleep(_REDEPLOY_RETRY_WAIT)

        if not premarket_watchlist:
            premarket_watchlist = list(EMERGENCY_FALLBACK)
            logger.warning("[SCANNER] ⚠️ No locked watchlist found after retries — using emergency fallback")

        combined = list(dict.fromkeys(premarket_watchlist + REGIME_TICKERS))
        subscribe_tickers(combined)
        subscribe_quote_tickers(combined)
        last_subscribed_watchlist = set(combined)
        premarket_built = True

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
                        # SC-C FIX (CORE-5): Direct [] access → .get() with empty-list fallback.
                        # If get_watchlist_with_metadata() returns a partial dict, the old code
                        # raised a KeyError that was caught as "Funnel error: 'watchlist'" —
                        # misleading. .get() now falls through to the empty-watchlist warning below.
                        premarket_watchlist = watchlist_data.get('watchlist', [])
                        # SC-B FIX (CORE-5): Removed dead `metadata = watchlist_data['metadata']`
                        # that was assigned here but never read in this block. The only use of
                        # metadata in this function is in the refresh block below (logger.info).

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
                        logger.exception(e)
                        premarket_watchlist = list(EMERGENCY_FALLBACK)
                        premarket_built     = True
                else:
                    funnel = get_funnel()
                    if funnel.should_update():
                        logger.info(f"[PRE-MARKET] {current_time_str} - Refreshing Watchlist")
                        try:
                            watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                            # SC-C FIX (CORE-5): .get() fallback on watchlist key.
                            premarket_watchlist = watchlist_data.get('watchlist', [])
                            current_set = set(premarket_watchlist)
                            new_tickers = list(current_set - last_subscribed_watchlist)
                            if new_tickers:
                                subscribe_and_prefetch_tickers(new_tickers)
                            else:
                                combined = list(dict.fromkeys(premarket_watchlist + REGIME_TICKERS))
                                subscribe_tickers(combined)
                                subscribe_quote_tickers(combined)
                            last_subscribed_watchlist = current_set
                            metadata = watchlist_data.get('metadata', {})
                            # SC-G FIX (CORE-5): metadata['stage'] / metadata['stage_description']
                            # → .get() with '?' fallbacks. If metadata is partial or missing keys,
                            # the old code raised a KeyError caught as "Refresh error: 'stage'".
                            logger.info(
                                f"[FUNNEL] Stage: {metadata.get('stage', '?').upper()} "
                                f"— {metadata.get('stage_description', '?')}"
                            )
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
                    # BUG-SC-6 (documented): conn=None is REQUIRED here — _db_operation_safe
                    # calls _run_analytics(conn=<pooled_conn>) injecting a connection as a
                    # keyword argument. The function does not use it directly (SignalTracker
                    # manages its own pooled connections internally) but the parameter must
                    # exist to avoid a TypeError from the wrapper. See FIX #30 / FIX #26.
                    def _run_analytics(conn=None):
                        if analytics:
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
                        logger.exception(e)
                        continue

                scan_interval = get_adaptive_scan_interval()
                logger.debug(f"[SCANNER] Cycle #{cycle_count} complete — sleeping {scan_interval}s")
                time.sleep(scan_interval)

            else:
                if last_report_day != current_day:
                    last_report_day = current_day

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
                        logger.exception(e)

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
                    premarket_watchlist       = []
                    premarket_built           = False
                    cycle_count               = 0
                    loss_streak_alerted       = False
                    last_subscribed_watchlist = set()
                    _watchlist_lock_logged    = False

                    reset_funnel()
                    clear_armed_signals()
                    clear_watching_signals()
                    clear_bos_alerts()  # OBS-SC-2: public API from sniper.clear_bos_alerts()
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
            logger.exception(e)
            try:
                send_simple_message(f"⚠️ Scanner Error: {str(e)}")
            except Exception:
                pass
            time.sleep(30)


if __name__ == "__main__":
    start_scanner_loop()
