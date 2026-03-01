"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
CANDLE CACHE: Cache-aware startup with 95%+ API reduction
"""
import os
import time
import threading
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
# OPTIONAL: SIGNAL ANALYTICS
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    ANALYTICS_ENABLED = True
    print("[SCANNER] ✅ Signal analytics enabled")
except ImportError:
    ANALYTICS_ENABLED = False
    signal_tracker = None
    print("[SCANNER] ⚠️  signal_analytics not available — analytics disabled")

API_KEY = os.getenv("EODHD_API_KEY", "")

# Minimal fallback (only used if funnel completely fails)
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]


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
        print(f"[WATCHLIST] Funnel error: {e}")

    print(f"[WATCHLIST] Using emergency fallback: {len(EMERGENCY_FALLBACK)} tickers")
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

    print(f"\n[MONITOR] Checking {len(open_positions)} open positions...")
    current_prices = {}

    for pos in open_positions:
        ticker = pos["ticker"]

        # Tier 1+2: WS live bar, or REST API if WS is down
        bar = get_current_bar_with_fallback(ticker)

        if bar is not None:
            source = bar.get("source", "ws")
            if source == "rest":
                print(f"[WS-FAILOVER] {ticker}: position monitoring via REST bar")
        else:
            # Tier 3: DB last bar (unchanged final safety net)
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            bar  = bars[-1] if bars else None
            if bar:
                print(f"[MONITOR] {ticker}: using DB last bar (WS+REST unavailable)")

        if bar:
            current_prices[ticker] = bar["close"]

    position_manager.check_exits(current_prices)


def start_scanner_loop():
    from app.core.sniper import process_ticker, clear_armed_signals, clear_watching_signals
    from app.discord_helpers import send_simple_message
    try:
        from app.ai.ai_learning import learning_engine
        HAS_AI_LEARNING = True
    except ImportError:
        learning_engine = None
        HAS_AI_LEARNING = False
    print(f"\n{'='*60}")
    print("WAR MACHINE - CFW6 SCANNER + BREAKOUT DETECTOR")
    print(f"{'='*60}")
    print(f"Market Hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
    print(f"Adaptive intervals + watchlist funnel + breakout signals active")
    if ANALYTICS_ENABLED:
        print(f"Analytics:     ✅ ENABLED (quality scoring, Sharpe, expectancy)")
    print(f"Candle Cache:  ✅ ENABLED (95%+ API reduction on redeploy)")
    print(f"WS Failover:   ✅ ENABLED (REST API fallback on disconnect)")
    print(f"Spread Gate:   ✅ ENABLED (us-quote bid/ask filter active)")
    print(f"{'='*60}\n")

    try:
        send_simple_message("🎯 WAR MACHINE ONLINE - CFW6 Scanner + Breakout Detector Started")
    except Exception as e:
        print(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist = []
    premarket_built     = False
    cycle_count         = 0
    last_report_day     = None
    loss_streak_alerted = False

    # ── STARTUP SEQUENCE ─────────────────────────────────────────────────────
    startup_watchlist = list(EMERGENCY_FALLBACK)
    try:
        start_ws_feed(startup_watchlist)
        print(f"[WS] WebSocket feed started for {len(startup_watchlist)} tickers")
    except Exception as e:
        print(f"[WS] ERROR starting WebSocket feed: {e}")

    try:
        start_quote_feed(startup_watchlist)
        print(f"[QUOTE] Quote feed started for {len(startup_watchlist)} tickers")
    except Exception as e:
        print(f"[QUOTE] ERROR starting quote feed: {e}")

    data_manager.startup_backfill_with_cache(startup_watchlist, days=30)
    data_manager.startup_intraday_backfill_today(startup_watchlist)
    set_backfill_complete()
    # ──────────────────────────────────────────────────────────────────────────

    while True:
        try:
            now_et           = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day      = now_et.strftime('%Y-%m-%d')

            if is_premarket():
                if not premarket_built:
                    print(f"\n[PRE-MARKET] {current_time_str} - Building Watchlist\n")
                    try:
                        watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                        premarket_watchlist = watchlist_data['watchlist']
                        metadata            = watchlist_data['metadata']
                        volume_signals      = watchlist_data['volume_signals']

                        premarket_built = True
                        subscribe_tickers(premarket_watchlist)
                        subscribe_quote_tickers(premarket_watchlist)

                        print(
                            f"[WS] Subscribed premarket watchlist "
                            f"({len(premarket_watchlist)} tickers) to WS feed"
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

                        print(
                            f"\n[SIGNALS] Pre-market breakout scan on "
                            f"{len(premarket_watchlist)} tickers..."
                        )
                        check_and_alert(premarket_watchlist)

                        if signal_generator.active_signals:
                            print_active_signals()

                    except Exception as e:
                        print(f"[PRE-MARKET] Funnel error: {e}")
                        import traceback
                        traceback.print_exc()
                        premarket_watchlist = list(EMERGENCY_FALLBACK)
                        premarket_built     = True
                else:
                    funnel = get_funnel()
                    if funnel.should_update():
                        print(f"[PRE-MARKET] {current_time_str} - Refreshing Watchlist\n")
                        try:
                            watchlist_data      = get_watchlist_with_metadata(force_refresh=True)
                            premarket_watchlist = watchlist_data['watchlist']
                            subscribe_tickers(premarket_watchlist)
                            subscribe_quote_tickers(premarket_watchlist)

                            metadata = watchlist_data['metadata']
                            print(
                                f"[FUNNEL] Stage: {metadata['stage'].upper()} - "
                                f"{metadata['stage_description']}"
                            )
                            print(f"[FUNNEL] Top 3: {', '.join(metadata['top_3_tickers'])}\n")

                            print(
                                f"[SIGNALS] Pre-market breakout scan on "
                                f"{len(premarket_watchlist)} tickers..."
                            )
                            check_and_alert(premarket_watchlist)
                            monitor_signals()

                            if signal_generator.active_signals:
                                print_active_signals()

                        except Exception as e:
                            print(f"[PRE-MARKET] Refresh error: {e}")
                    else:
                        print(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")

                    time.sleep(60)
                continue

            elif is_market_hours():
                if not should_scan_now():
                    print(f"[SCANNER] {current_time_str} - Opening Range forming, waiting...")
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
                        print("[RISK] Daily loss streak reached — halting new scans.")
                    monitor_open_positions()
                    time.sleep(60)
                    continue

                cycle_count += 1
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}")

                try:
                    watchlist = get_current_watchlist(force_refresh=False)
                    if not watchlist:
                        watchlist = (
                            premarket_watchlist if premarket_watchlist
                            else list(EMERGENCY_FALLBACK)
                        )
                except Exception as e:
                    print(f"[WATCHLIST] Error: {e}")
                    watchlist = (
                        premarket_watchlist if premarket_watchlist
                        else list(EMERGENCY_FALLBACK)
                    )

                optimal_size = calculate_optimal_watchlist_size()
                watchlist    = watchlist[:optimal_size]

                print(
                    f"[SCANNER] {len(watchlist)} tickers | "
                    f"{', '.join(watchlist[:10])}...\n"
                )

                print(f"[SIGNALS] Scanning {len(watchlist)} tickers for breakouts...")
                check_and_alert(watchlist)
                monitor_signals()

                if signal_generator.active_signals:
                    print_active_signals()

                monitor_open_positions()

                daily_stats = position_manager.get_daily_stats()
                print(
                    f"[TODAY] Trades: {daily_stats['trades']} "
                    f"W/L: {daily_stats['wins']}/{daily_stats['losses']} "
                    f"WR: {daily_stats['win_rate']:.1f}% "
                    f"P&L: ${daily_stats['total_pnl']:+.2f}\n"
                )

                for idx, ticker in enumerate(watchlist, 1):
                    try:
                        print(f"\n--- [{idx}/{len(watchlist)}] {ticker} ---")
                        process_ticker(ticker)
                    except Exception as e:
                        print(f"[SCANNER] Error on {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

                print(f"\n[SCANNER] Cycle #{cycle_count} complete")
                scan_interval = get_adaptive_scan_interval()
                print(f"[SCANNER] Sleeping {scan_interval}s...\n")
                time.sleep(scan_interval)

            else:
                if last_report_day != current_day:
                    print(f"\n{'='*80}")
                    print(f"[EOD] Market Closed - Generating Reports for {current_day}")
                    print(f"{'='*80}\n")

                    open_positions = position_manager.get_open_positions()
                    if open_positions:
                        print(f"[EOD] {len(open_positions)} positions still open")

                    # 1. SIGNAL ANALYTICS
                    if ANALYTICS_ENABLED and signal_tracker:
                        try:
                            print("\n[ANALYTICS] Generating signal performance report...\n")
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
                            print(f"[ANALYTICS] Error generating report: {e}")
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
                        print(f"[EOD] EOD report error: {e}")

                    # 3. AI LEARNING
                    try:
                        learning_engine.optimize_confirmation_weights()
                        learning_engine.optimize_fvg_threshold()
                        print(learning_engine.generate_performance_report())
                    except Exception as e:
                        print(f"[AI] Optimization error: {e}")

                    # 4. WS FAILOVER STATS
                    try:
                        from app.data.ws_feed import get_failover_stats
                        stats = get_failover_stats()
                        if stats["rest_hits"] > 0:
                            print(
                                f"[WS-FAILOVER] Session REST hits: {stats['rest_hits']} "
                                f"(WS outage fallbacks)"
                            )
                    except Exception as e:
                        print(f"[WS-FAILOVER] Stats error: {e}")

                    # 5. DATABASE CLEANUP
                    try:
                        data_manager.cleanup_old_bars(days_to_keep=60)
                    except Exception as e:
                        print(f"[CLEANUP] Error: {e}")

                    # 6. DAILY RESET
                    signal_generator.reset_daily()
                    print("[SIGNALS] Daily reset complete")

                    # 7. STATE RESET
                    last_report_day     = current_day
                    premarket_watchlist = []
                    premarket_built     = False
                    cycle_count         = 0
                    loss_streak_alerted = False

                    clear_armed_signals()
                    clear_watching_signals()

                    # 8. PDH/PDL CACHE CLEAR
                    try:
                        data_manager.clear_prev_day_cache()
                    except Exception as e:
                        print(f"[DATA] PDH/PDL cache clear error: {e}")

                    print(f"\n{'='*80}")
                    print(f"[EOD] All EOD tasks complete")
                    print(f"{'='*80}\n")

                print(f"[AFTER-HOURS] {current_time_str} - Market closed, next check in 10 min")
                time.sleep(600)

        except KeyboardInterrupt:
            print("\n[SCANNER] Shutdown signal received")
            print(position_manager.generate_report())
            raise

        except Exception as e:
            print(f"[SCANNER] Critical error: {e}")
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
            print(f"[SCREENER] HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "data" not in data:
            print(f"[SCREENER] Unexpected response shape: {str(data)[:300]}")
            return []
        tickers = []
        for item in data["data"]:
            code = item.get("code")
            if code:
                tickers.append(code.replace(".US", "").replace(".us", ""))
        print(f"[SCREENER] ✅ Fetched {len(tickers)} tickers (total available: {data.get('total', '?')})")
        return tickers[:limit]
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_scanner_loop()
