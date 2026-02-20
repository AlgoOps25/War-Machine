"""
Scanner Module - Intelligent Watchlist Builder & Scanner Loop
INTEGRATED: Pre-Market Scanner, Position Monitoring, Database Cleanup
"""
import os
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import config
from premarket_scanner import build_premarket_watchlist
from data_manager import data_manager, cleanup_old_bars
from position_manager import position_manager
from ws_feed import start_ws_feed
from scanner_optimizer import (
    get_adaptive_scan_interval,
    should_scan_now,
    calculate_optimal_watchlist_size
)
from earnings_filter import bulk_prefetch_earnings, clear_earnings_cache
from db_connection import get_conn, dict_cursor, ph

API_KEY = os.getenv("EODHD_API_KEY", "")

# ── Module-level watchlist — single source of truth ──────────────────────────────
FALLBACK_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "AMD",  "NFLX", "ADBE",  "CRM",  "ORCL", "INTC", "CSCO",
    "JPM",  "BAC",  "GS",    "MS",   "WFC",
    "UNH",  "JNJ",  "PFE",   "ABBV", "MRK",
    "WMT",  "HD",   "COST",  "NKE",  "MCD",
    "SPY",  "QQQ",  "IWM",   "DIA",
]


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


def build_watchlist() -> list:
    return fallback_list()


def fallback_list() -> list:
    print(f"[SCANNER] Using fallback watchlist: {len(FALLBACK_WATCHLIST)} tickers")
    return list(FALLBACK_WATCHLIST)


def monitor_open_positions():
    from data_manager import data_manager
    open_positions = position_manager.get_open_positions()
    if not open_positions:
        return
    print(f"\n[MONITOR] Checking {len(open_positions)} open positions...")
    current_prices = {}
    for pos in open_positions:
        ticker = pos["ticker"]
        bars = data_manager.get_bars_from_memory(ticker, limit=1)
        if bars:
            current_prices[ticker] = bars[-1]["close"]
    position_manager.check_exits(current_prices)


def _has_loss_streak(max_consecutive_losses: int = 3) -> bool:
    """Return True if today's closed trades end with a losing streak >= N."""
    try:
        today = _now_et().date()
        conn = get_conn()
        cursor = dict_cursor(conn)
        p = ph()
        cursor.execute(
            f"""
            SELECT pnl
            FROM positions
            WHERE status = {p}
              AND DATE(exit_time) = {p}
            ORDER BY exit_time ASC
            """,
            ("CLOSED", today),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return False
        streak = 0
        for row in rows:
            pnl = row["pnl"] or 0.0
            if pnl <= 0:
                streak += 1
            else:
                streak = 0
        return streak >= max_consecutive_losses
    except Exception as e:
        print(f"[RISK] Loss-streak check error: {e}")
        return False


def start_scanner_loop():
    from sniper import process_ticker, clear_armed_signals, clear_watching_signals
    from discord_helpers import send_simple_message
    from ai_learning import learning_engine

    print(f"\n{'='*60}")
    print("WAR MACHINE - CFW6 SCANNER")
    print(f"{'='*60}")
    print(f"Market Hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
    print(f"Adaptive intervals active")
    print(f"{'='*60}\n")

    try:
        send_simple_message("WAR MACHINE ONLINE - CFW6 Scanner Started")
    except Exception as e:
        print(f"[SCANNER] Discord unavailable: {e}")

    premarket_watchlist = []
    premarket_built = False
    cycle_count = 0
    last_report_day = None

    # ── STARTUP SEQUENCE ────────────────────────────────────────────────────
    # 0. Start WebSocket feed so today's ticks are accumulating in DB.
    startup_watchlist = fallback_list()
    try:
        start_ws_feed(startup_watchlist)
        print(f"[WS] WebSocket feed started for {len(startup_watchlist)} tickers")
    except Exception as e:
        print(f"[WS] ERROR starting WebSocket feed: {e}")

    # 1. 30-day historical REST backfill (up to yesterday’s close)
    # 2. Best-effort today REST backfill (04:00 -> now) for mid-session restarts
    # 3. Earnings calendar prefetch
    data_manager.startup_backfill_today(startup_watchlist)
    data_manager.startup_intraday_backfill_today(startup_watchlist)
    bulk_prefetch_earnings(startup_watchlist)

    # ─────────────────────────────────────────────────────────────────────

    while True:
        try:
            now_et = _now_et()
            current_time_str = now_et.strftime('%I:%M:%S %p ET')
            current_day = now_et.strftime('%Y-%m-%d')

            if is_premarket():
                if not premarket_built:
                    print(f"[PRE-MARKET] {current_time_str} - Building Watchlist")
                    try:
                        premarket_watchlist = build_premarket_watchlist()
                        premarket_built = True
                        msg = f"Pre-Market Watchlist: {len(premarket_watchlist)} tickers - {', '.join(premarket_watchlist[:20])}"
                        send_simple_message(msg)
                    except Exception as e:
                        print(f"[PRE-MARKET] Error: {e}")
                        premarket_watchlist = fallback_list()
                        premarket_built = True
                else:
                    print(f"[PRE-MARKET] {current_time_str} - Waiting for 9:30 AM ET...")
                time.sleep(300)
                continue

            elif is_market_hours():
                if not should_scan_now():
                    print(f"[SCANNER] {current_time_str} - Opening Range forming, waiting...")
                    time.sleep(15)
                    continue

                # Daily loss circuit breaker: halt new scans after 3 consecutive losses.
                if _has_loss_streak(max_consecutive_losses=3):
                    print("[RISK] Daily loss streak reached (3 consecutive losses) — halting new scans.")
                    monitor_open_positions()
                    time.sleep(60)
                    continue

                cycle_count += 1
                print(f"\n{'='*60}")
                print(f"[SCANNER] CYCLE #{cycle_count} - {current_time_str}")
                print(f"{'='*60}")

                watchlist = premarket_watchlist if premarket_watchlist else build_watchlist()
                optimal_size = calculate_optimal_watchlist_size()
                watchlist = watchlist[:optimal_size]
                print(f"[SCANNER] {len(watchlist)} tickers | {', '.join(watchlist[:10])}...\n")

                monitor_open_positions()

                daily_stats = position_manager.get_daily_stats()
                print(f"[TODAY] Trades: {daily_stats['trades']} W/L: {daily_stats['wins']}/{daily_stats['losses']} WR: {daily_stats['win_rate']:.1f}% P&L: ${daily_stats['total_pnl']:+.2f}\n")

                try:
                    updated = data_manager.bulk_update_live_bars(watchlist)
                    print(f"[LIVE] Snapshot: {updated} tickers")
                except Exception as e:
                    print(f"[LIVE] Bulk update error: {e}")

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
                    print(f"[EOD] Market Closed - Generating Reports")

                    open_positions = position_manager.get_open_positions()
                    if open_positions:
                        print(f"[EOD] {len(open_positions)} positions still open")

                    daily_stats = position_manager.get_daily_stats()
                    eod_report = f"EOD Report {current_day} | Trades: {daily_stats['trades']} | WR: {daily_stats['win_rate']:.1f}% | P&L: ${daily_stats['total_pnl']:+.2f}"

                    try:
                        win_rate_report = position_manager.generate_report()
                        eod_report += f"\n{win_rate_report}"
                    except Exception as e:
                        print(f"[EOD] Report error: {e}")

                    send_simple_message(eod_report)

                    try:
                        learning_engine.optimize_confirmation_weights()
                        learning_engine.optimize_fvg_threshold()
                        print(learning_engine.generate_performance_report())
                    except Exception as e:
                        print(f"[AI] Optimization error: {e}")

                    try:
                        cleanup_old_bars(days_to_keep=60)
                    except Exception as e:
                        print(f"[CLEANUP] Error: {e}")

                    last_report_day = current_day
                    premarket_watchlist = []
                    premarket_built = False
                    cycle_count = 0

                    # Reset all intraday signal state for the new day
                    clear_armed_signals()
                    clear_watching_signals()
                    clear_earnings_cache()   # ← NEW: fresh earnings data next session

                print(f"[AFTER-HOURS] {current_time_str} - Market closed")
                time.sleep(600)

        except KeyboardInterrupt:
            print("\nScanner stopped by user")
            position_manager.print_summary()
            break

        except Exception as e:
            print(f"[SCANNER] Critical error: {e}")
            import traceback
            traceback.print_exc()
            try:
                send_simple_message(f"Scanner Error: {str(e)}")
            except Exception:
                pass
            time.sleep(30)


def get_screener_tickers(min_market_cap: int = 1_000_000_000, limit: int = 50) -> list:
    import requests
    import json
    url = "https://eodhd.com/api/screener"
    params = {
        "api_token": config.EODHD_API_KEY,
        "filters": json.dumps([
            ["market_capitalization", ">=", min_market_cap],
            ["volume", ">=", 1000000],
            ["exchange", "=", "US"]
        ]),
        "limit": limit,
        "sort": "volume.desc"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
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
