"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Adaptive Watchlist Funnel, Pre-Market Scanner, Position Monitoring, Database Cleanup
OPTIONS LAYER: Cache-based watchlist scoring, background prefetch, per-cycle context logging
PHASE 2A: Signal Analytics & PnL Digest EOD integration
PHASE 2B: Daily Bias Engine - ICT top-down analysis pre-market
CANDLE CACHE: Cache-aware startup with 95%+ API reduction
"""
import os
import time
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import config

# ════════════════════════════════════════════════════════════════════════════════════
# CRITICAL: DATABASE SCHEMA MIGRATION MUST RUN FIRST
# ════════════════════════════════════════════════════════════════════════════════════
print("\n[STARTUP] ⚙️  Checking database schema...")
try:
    from apply_schema_migration import apply_positions_pnl_migration
    apply_positions_pnl_migration()
    print("[STARTUP] ✅ Schema migration complete\n")
except ImportError:
    print("[STARTUP] ⚠️  apply_schema_migration.py not found - skipping migration")
except Exception as e:
    print(f"[STARTUP] ⚠️  Schema migration failed (non-fatal): {e}")
    print("[STARTUP] System will continue but performance_monitor may fail\n")

# ────────────────────────────────────────────────────────────────────────────────────
# NOW SAFE TO IMPORT MODULES THAT DEPEND ON SCHEMA
# ────────────────────────────────────────────────────────────────────────────────────
from data_manager import data_manager, cleanup_old_bars
from position_manager import position_manager
from ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
from scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)

# Breakout detector integration
from signal_generator import (
    check_and_alert,
    monitor_signals,
    print_active_signals,
    signal_generator
)

# Adaptive watchlist funnel
from watchlist_funnel import (
    get_current_watchlist,
    get_watchlist_with_metadata,
    get_funnel
)

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 2A: ANALYTICS & EOD REPORTING
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from signal_analytics import signal_tracker
    ANALYTICS_ENABLED = True
    print("[SCANNER] ✅ Signal analytics enabled")
except ImportError:
    ANALYTICS_ENABLED = False
    signal_tracker = None
    print("[SCANNER] ⚠️  signal_analytics not available — analytics disabled")

try:
    from pnl_digest import send_pnl_digest
    PNL_DIGEST_ENABLED = True
    print("[SCANNER] ✅ PnL digest enabled")
except ImportError:
    PNL_DIGEST_ENABLED = False
    print("[SCANNER] ⚠️  pnl_digest not available — using basic EOD report")

# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 2B: DAILY BIAS ENGINE (ICT Top-Down Analysis)
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from daily_bias_engine import bias_engine, reset_bias as _reset_bias_engine
    BIAS_ENGINE_ENABLED = True
    print("[SCANNER] ✅ Daily bias engine enabled (ICT top-down analysis)")
except ImportError:
    BIAS_ENGINE_ENABLED = False
    bias_engine = None
    _reset_bias_engine = None
    print("[SCANNER] ⚠️  daily_bias_engine not available — bias filtering disabled")

# ────────────────────────────────────────────────────────────────────────────────────
# OPTIONS INTELLIGENCE LAYER
# ────────────────────────────────────────────────────────────────────────────────────
try:
    from options_data_manager import options_dm
    OPTIONS_LAYER_ENABLED = True
    print("[SCANNER] ✅ Options intelligence layer enabled")
except ImportError:
    options_dm = None
    OPTIONS_LAYER_ENABLED = False
    print("[SCANNER] ⚠️  options_data_manager not available — options layer disabled")

API_KEY = os.getenv("EODHD_API_KEY", "")

# Minimal fallback (only used if funnel completely fails)
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]

# Key market proxies always included in bias analysis
BIAS_TICKERS = ["SPY", "QQQ"]  # Market-wide bias anchors


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


# ────────────────────────────────────────────────────────────────────────────────────
# PHASE 2B: PRE-MARKET BIAS ANALYSIS
# ────────────────────────────────────────────────────────────────────────────────────

def _run_premarket_bias_analysis(watchlist: list) -> None:
    """
    Run ICT top-down bias analysis before market open.
    Calculates BULL/BEAR/NEUTRAL bias for SPY, QQQ, and top watchlist tickers.
    Broadcasts results to console and Discord.

    Called once per session during pre-market watchlist build.
    """
    if not BIAS_ENGINE_ENABLED or bias_engine is None:
        return

    from discord_helpers import send_simple_message

    # Always analyze market proxies first, then top watchlist tickers
    key_tickers = list(dict.fromkeys(
        BIAS_TICKERS + [t for t in watchlist if t not in BIAS_TICKERS][:3]
    ))

    bias_lines    = []  # For Discord
    console_lines = []  # For terminal

    for ticker in key_tickers:
        try:
            bias_data  = bias_engine.calculate_daily_bias(ticker, force_refresh=True)
            bias       = bias_data['bias']
            confidence = bias_data['confidence']
            levels     = bias_data.get('key_levels', {}).get(ticker, {})

            # Emoji encoding
            emoji = {'BULL': '🟢', 'BEAR': '🔴', 'NEUTRAL': '⚪'}.get(bias, '⚪')

            level_str = ""
            if levels:
                level_str = f" | PDH: ${levels['PDH']:.2f}  PDL: ${levels['PDL']:.2f}"

            bias_lines.append(
                f"{emoji} **{ticker}**: {bias} ({confidence*100:.0f}% conf){level_str}"
            )
            console_lines.append(
                f"  [{bias:<7}] {ticker:<6} {confidence*100:.0f}% conf{level_str}"
            )

        except Exception as e:
            print(f"[BIAS] Error calculating bias for {ticker}: {e}")

    if not bias_lines:
        return

    # ── Console output ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊  PRE-MARKET DAILY BIAS ANALYSIS  (ICT Top-Down)")
    print("=" * 70)
    for line in console_lines:
        print(line)

    # Print SPY reasons
    spy_data = bias_engine._get_bias_dict()
    if spy_data.get('reasons'):
        print("\nSPY Analysis:")
        for reason in spy_data['reasons']:
            print(f"  • {reason}")
    print("=" * 70 + "\n")

    # ── Discord alert ─────────────────────────────────────────────────────────
    now_str = _now_et().strftime('%I:%M %p ET')
    discord_msg = (
        f"📊 **PRE-MARKET BIAS ANALYSIS** — {now_str}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for line in bias_lines:
        discord_msg += f"{line}\n"

    # Add SPY structural reasons
    if spy_data.get('reasons'):
        discord_msg += "\n📋 **SPY Structure:**\n"
        for reason in spy_data['reasons'][:3]:
            discord_msg += f"  • {reason}\n"

    # Add filter warning if strong directional bias
    spy_bias       = spy_data.get('bias', 'NEUTRAL')
    spy_confidence = spy_data.get('confidence', 0.0)
    if spy_confidence >= 0.7 and spy_bias != 'NEUTRAL':
        counter = 'SELL' if spy_bias == 'BULL' else 'BUY'
        discord_msg += (
            f"\n⚠️ **Filter Active:** {counter} signals suppressed "
            f"(counter-trend to {spy_bias} bias)\n"
        )

    discord_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    try:
        send_simple_message(discord_msg)
        print("[BIAS] Pre-market bias alert sent to Discord ✅")
    except Exception as e:
        print(f"[BIAS] Discord error: {e}")


# ────────────────────────────────────────────────────────────────────────────────────
# OPTIONS INTELLIGENCE HELPERS
# ────────────────────────────────────────────────────────────────────────────────────

def enhance_watchlist_with_options(watchlist: list) -> list:
    """
    Sort watchlist by options quality using CACHED scores only.
    Makes ZERO new API calls — safe to call every scan cycle.
    """
    if not OPTIONS_LAYER_ENABLED or options_dm is None:
        return watchlist

    try:
        scored   = []
        unscored = []

        with options_dm._lock:
            for ticker in watchlist:
                cached = options_dm._score_cache.get(ticker)
                if cached:
                    score     = cached['data'].get('score', 0)
                    tradeable = cached['data'].get('tradeable', True)
                    scored.append((ticker, score, tradeable))
                else:
                    unscored.append(ticker)

        scored.sort(key=lambda x: (x[2], x[1]), reverse=True)
        enhanced = [t for t, _, _ in scored] + unscored

        if scored:
            tradeable_count = sum(1 for _, _, t in scored if t)
            top3 = ', '.join(f"{t}({s:.0f})" for t, s, _ in scored[:3])
            print(
                f"[OPTIONS] Watchlist enhanced — "
                f"{tradeable_count}/{len(scored)} cached tradeable | "
                f"Top: {top3} | {len(unscored)} uncached"
            )

        return enhanced

    except Exception as e:
        print(f"[OPTIONS] enhance_watchlist error (non-fatal): {e}")
        return watchlist


def prefetch_options_scores(watchlist: list, top_n: int = 20) -> None:
    """Background async prefetch of options scores for the top N tickers."""
    if not OPTIONS_LAYER_ENABLED or options_dm is None:
        return

    tickers_to_fetch = watchlist[:top_n]

    def _do_prefetch():
        fetched = 0
        errors  = 0
        for ticker in tickers_to_fetch:
            try:
                import time as _time
                with options_dm._lock:
                    cached = options_dm._score_cache.get(ticker)
                if cached:
                    age = _time.time() - cached['timestamp']
                    if age < options_dm.cache_ttl:
                        continue
                options_dm.get_options_score(ticker)
                fetched += 1
            except Exception:
                errors += 1
                continue

        if fetched > 0:
            print(f"[OPTIONS] Background prefetch — {fetched} fetched, {errors} errors")

    thread      = threading.Thread(target=_do_prefetch, daemon=True)
    thread.name = "options-prefetch"
    thread.start()


def _log_options_context(watchlist: list) -> None:
    """Print one-line options environment summary for the current cycle."""
    if not OPTIONS_LAYER_ENABLED or options_dm is None:
        return

    try:
        stats        = options_dm.get_cache_stats()
        cached_count = stats['scores_cached']

        if cached_count == 0:
            print("[OPTIONS] No cached scores yet — prefetch in progress")
            return

        scores = []
        with options_dm._lock:
            for ticker in watchlist:
                c = options_dm._score_cache.get(ticker)
                if c:
                    scores.append(c['data'].get('score', 0))

        if not scores:
            return

        avg_score = sum(scores) / len(scores)
        high_env  = sum(1 for s in scores if s >= 60)
        low_env   = sum(1 for s in scores if s < 30)

        print(
            f"[OPTIONS] Context — "
            f"{len(scores)}/{len(watchlist)} scored | "
            f"Avg: {avg_score:.0f} | High(≥60): {high_env} | Weak(<30): {low_env}"
        )

    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────────────────────
# EXISTING SCANNER FUNCTIONS
# ────────────────────────────────────────────────────────────────────────────────────

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
    from data_manager import data_manager
    from ws_feed import get_current_bar, is_connected
    open_positions = position_manager.get_open_positions()
    if not open_positions:
        return
    print(f"\n[MONITOR] Checking {len(open_positions)} open positions...")
    current_prices = {}
    for pos in open_positions:
        ticker = pos["ticker"]
        bar = get_current_bar(ticker) if is_connected() else None
        if bar is None:
            bars = data_manager.get_bars_from_memory(ticker, limit=1)
            bar  = bars[-1] if bars else None
        if bar:
            current_prices[ticker] = bar["close"]
    position_manager.check_exits(current_prices)


def start_scanner_loop():
    from sniper import process_ticker, clear_armed_signals, clear_watching_signals
    from discord_helpers import send_simple_message
    from ai_learning import learning_engine

    print(f"\n{'='*60}")
    print("WAR MACHINE - CFW6 SCANNER + BREAKOUT DETECTOR")
    print(f"{'='*60}")
    print(f"Market Hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
    print(f"Adaptive intervals + watchlist funnel + breakout signals active")
    if OPTIONS_LAYER_ENABLED:
        print(f"Options layer: ✅ ENABLED (cache-sort + background prefetch)")
    if ANALYTICS_ENABLED:
        print(f"Analytics:     ✅ ENABLED (quality scoring, Sharpe, expectancy)")
    if PNL_DIGEST_ENABLED:
        print(f"PnL Digest:    ✅ ENABLED (rich EOD Discord embeds)")
    if BIAS_ENGINE_ENABLED:
        print(f"Daily Bias:    ✅ ENABLED (ICT top-down, pivot+sweep analysis)")
    print(f"Candle Cache:  ✅ ENABLED (95%+ API reduction on redeploy)")
    print(f"{'='*60}\n")

    try:
        send_simple_message("🎯 WAR MACHINE ONLINE - CFW6 Scanner + Breakout Detector Started")
    except Exception as e:
        print(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist = []
    premarket_built     = False
    bias_calculated     = False   # New: track if bias has been run today
    cycle_count         = 0
    last_report_day     = None
    loss_streak_alerted = False

    # ── STARTUP SEQUENCE ──────────────────────────────────────────────────────
    startup_watchlist = list(EMERGENCY_FALLBACK)
    try:
        start_ws_feed(startup_watchlist)
        print(f"[WS] WebSocket feed started for {len(startup_watchlist)} tickers")
    except Exception as e:
        print(f"[WS] ERROR starting WebSocket feed: {e}")

    # CACHE-AWARE STARTUP: Loads from cache first, only fetches gaps
    from data_manager_cache_integration import startup_backfill_with_cache
    startup_backfill_with_cache(data_manager, startup_watchlist, days=30)
    data_manager.startup_intraday_backfill_today(startup_watchlist)
    set_backfill_complete()

    prefetch_options_scores(startup_watchlist, top_n=len(startup_watchlist))
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

                        print(
                            f"[WS] Subscribed premarket watchlist "
                            f"({len(premarket_watchlist)} tickers) to WS feed"
                        )

                        prefetch_options_scores(premarket_watchlist, top_n=20)

                        # ── BIAS: Run pre-market top-down analysis ────────────
                        if not bias_calculated:
                            _run_premarket_bias_analysis(premarket_watchlist)
                            bias_calculated = True
                        # ─────────────────────────────────────────────────────

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
                        enhanced_pm = enhance_watchlist_with_options(premarket_watchlist)
                        check_and_alert(enhanced_pm)

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

                            metadata = watchlist_data['metadata']
                            print(
                                f"[FUNNEL] Stage: {metadata['stage'].upper()} - "
                                f"{metadata['stage_description']}"
                            )
                            print(f"[FUNNEL] Top 3: {', '.join(metadata['top_3_tickers'])}\n")

                            prefetch_options_scores(premarket_watchlist, top_n=20)
                            enhanced_pm = enhance_watchlist_with_options(premarket_watchlist)

                            print(
                                f"[SIGNALS] Pre-market breakout scan on "
                                f"{len(enhanced_pm)} tickers..."
                            )
                            check_and_alert(enhanced_pm)
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

                prefetch_options_scores(watchlist, top_n=20)
                watchlist = enhance_watchlist_with_options(watchlist)
                _log_options_context(watchlist)

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

                    # 2. PNL DIGEST
                    if PNL_DIGEST_ENABLED:
                        try:
                            print("[EOD] Generating PnL digest for Discord...")
                            digest_success = send_pnl_digest()
                            if digest_success:
                                print("[EOD] ✅ PnL digest sent to Discord")
                            else:
                                print("[EOD] ⚠️  PnL digest generation returned False")
                        except Exception as e:
                            print(f"[EOD] PnL digest error: {e}")
                            import traceback
                            traceback.print_exc()
                            try:
                                daily_stats = position_manager.get_daily_stats()
                                send_simple_message(
                                    f"📊 **EOD Report {current_day}**\n"
                                    f"Trades: {daily_stats['trades']} | "
                                    f"WR: {daily_stats['win_rate']:.1f}% | "
                                    f"P&L: ${daily_stats['total_pnl']:+.2f}"
                                )
                            except Exception as e2:
                                print(f"[EOD] Basic report fallback failed: {e2}")
                    else:
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
                            print(f"[EOD] Basic EOD report error: {e}")

                    # 3. AI LEARNING
                    try:
                        learning_engine.optimize_confirmation_weights()
                        learning_engine.optimize_fvg_threshold()
                        print(learning_engine.generate_performance_report())
                    except Exception as e:
                        print(f"[AI] Optimization error: {e}")

                    # 4. DATABASE CLEANUP
                    try:
                        cleanup_old_bars(days_to_keep=60)
                    except Exception as e:
                        print(f"[CLEANUP] Error: {e}")

                    # 5. DAILY RESET — signals
                    signal_generator.reset_daily()
                    print("[SIGNALS] Daily reset complete")

                    # 6. DAILY RESET — bias engine
                    if BIAS_ENGINE_ENABLED and _reset_bias_engine:
                        try:
                            _reset_bias_engine()
                        except Exception as e:
                            print(f"[BIAS] Reset error: {e}")

                    # 7. OPTIONS CACHE CLEAR
                    if OPTIONS_LAYER_ENABLED and options_dm is not None:
                        try:
                            options_dm.clear_cache()
                            print("[OPTIONS] Cache cleared for new session")
                        except Exception as e:
                            print(f"[OPTIONS] Cache clear error: {e}")

                    # 8. STATE RESET
                    last_report_day     = current_day
                    premarket_watchlist = []
                    premarket_built     = False
                    bias_calculated     = False   # Allow new bias calc tomorrow
                    cycle_count         = 0
                    loss_streak_alerted = False

                    clear_armed_signals()
                    clear_watching_signals()

                    # 9. PDH/PDL CACHE CLEAR
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
    """Legacy screener function - kept for backwards compatibility."""
    import requests
    import json
    url    = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume",               ">=", 1000000],
            ["exchange",             "=",  "US"]
        ]),
        "limit": limit,
        "sort":  "volume.desc"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data    = response.json()
        tickers = []
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                code = item.get("code")
                if code:
                    tickers.append(code.replace(".US", ""))
        print(f"[SCREENER] Fetched {len(tickers)} tickers")
        return tickers[:limit]
    except Exception as e:
        print(f"[SCREENER] Error: {e}")
        return []


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_scanner_loop()
