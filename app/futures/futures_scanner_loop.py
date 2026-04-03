"""
app/futures/futures_scanner_loop.py — Independent Futures Scan Thread

Called from scanner.py's start_scanner_loop() when FUTURES_ENABLED=true.
Runs in a separate daemon thread so it is completely independent of the
equity scan loop — a crash here cannot affect the equity/options system.

Thread safety:
  - FuturesORBScanner maintains its own state (_fired_today, OR levels).
  - No shared mutable state with the equity scanner.
  - Thread is daemon=True — exits automatically when main process exits.

Scan interval:
  - 09:30–09:40 (OR formation): 5s  ← same as equity OR window
  - 09:40–11:00 (signal window): 30s ← Tradier REST poll minimum interval
  - Outside session: 300s (5 min idle)

MON-FUT-1 (2026-04-03):
  - start_futures_loop() now also starts the FuturesPositionMonitor daemon
    thread via futures_position_monitor.start_monitor_loop().
  - After scanner.scan() returns a signal, the monitor is armed automatically
    so stop/T1/T2 Discord exit alerts fire without any manual intervention.
"""
from __future__ import annotations
import logging
import threading
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_futures_thread: threading.Thread | None = None


def _get_scan_interval(now_time: dtime) -> int:
    if dtime(9, 30) <= now_time < dtime(9, 40):
        return 5
    elif dtime(9, 40) <= now_time < dtime(11, 0):
        return 30
    return 300


def _futures_loop(symbol: str) -> None:
    """Target function for the futures scan thread."""
    from app.futures.futures_orb_scanner import FuturesORBScanner
    from app.futures.tradier_futures_feed import clear_bar_cache
    from app.futures.futures_position_monitor import get_monitor

    logger.info(f"[FUTURES-LOOP] Thread started for {symbol}")
    scanner = FuturesORBScanner(symbol=symbol)
    monitor = get_monitor(symbol)
    last_reset_day = None

    while True:
        try:
            now = datetime.now(ET)
            today = now.strftime("%Y-%m-%d")

            # Daily reset
            if last_reset_day != today:
                scanner.reset_daily()
                monitor.disarm()
                clear_bar_cache(symbol)
                last_reset_day = today
                logger.info(f"[FUTURES-LOOP] Daily reset complete for {symbol}")

            # Run scan — arm monitor if a signal fires
            signal = scanner.scan(current_time=now)
            if signal is not None:
                monitor.arm(signal)

        except Exception as e:
            logger.error(f"[FUTURES-LOOP] Unhandled error: {e}")
            logger.exception(e)

        interval = _get_scan_interval(datetime.now(ET).time())
        time.sleep(interval)


def start_futures_loop(symbol: str = "MNQ") -> threading.Thread:
    """
    Launch the futures scan loop and position monitor in daemon threads.
    Safe to call multiple times — only starts one of each per process.
    Returns the scan thread object (useful for testing / health checks).
    """
    global _futures_thread

    # MON-FUT-1: start position monitor alongside the scanner
    from app.futures.futures_position_monitor import start_monitor_loop
    start_monitor_loop(symbol)

    if _futures_thread is not None and _futures_thread.is_alive():
        logger.info("[FUTURES-LOOP] Thread already running — skipping duplicate start")
        return _futures_thread

    _futures_thread = threading.Thread(
        target=_futures_loop,
        args=(symbol,),
        daemon=True,
        name=f"futures_orb_{symbol}",
    )
    _futures_thread.start()
    logger.info(f"[FUTURES-LOOP] ✅ Started futures ORB thread for {symbol}")
    return _futures_thread
