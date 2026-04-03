"""
app/futures/futures_position_monitor.py — Futures Position Monitor

MON-FUT-1 (2026-04-03): Added to support manual-execution workflow.

Goal
----
After FuturesORBScanner fires an entry signal, this monitor:
  1. Arms itself with the signal’s stop / T1 / T2 / entry levels.
  2. Polls live price from the last 1-min bar close every 15 seconds.
  3. Fires a Discord exit alert automatically when price touches:
       - Stop    → reason = "STOP_HIT"    (red embed)
       - T1      → reason = "T1_HIT"      (green embed) + move-to-BE note
       - T2      → reason = "T2_HIT"      (green embed, full runner)
  4. Disarms itself after T2 or stop. T1 leaves the position open at BE.

Manual use
----------
You can also arm / disarm the monitor manually from a Railway shell:

    from app.futures.futures_position_monitor import get_monitor
    m = get_monitor("MNQ")
    m.arm(signal)                             # arm from a signal dict
    m.arm_manual("MNQ", "BULL", 19410, 19392.75, 19444.50, 19470.38)
    m.disarm()                                # clear all state
    m.trail_stop(19430.0)                     # update stop to BE / trail
    m.get_status()                            # print current state

Design notes
------------
  - Thread-safe: all mutable state lives in a threading.Lock.
  - Non-blocking: poll loop is a daemon thread started by futures_scanner_loop.
  - No broker integration: this is purely a Discord notification helper.
  - Price source: last closed 1-min bar close from get_todays_bars().
    On gap-open or illiquid minutes the last bar close may lag price by up
    to 1 minute — acceptable for a manual-execution workflow.
  - One monitor instance per symbol via module-level registry (_monitors).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_POLL_INTERVAL = 15   # seconds between price checks
_SESSION_END   = (16, 0)   # (hour, minute) ET — force EOD disarm

# Module-level registry: one monitor per symbol
_monitors: dict[str, "FuturesPositionMonitor"] = {}


def get_monitor(symbol: str = "MNQ") -> "FuturesPositionMonitor":
    """Return (or create) the singleton monitor for a given symbol."""
    if symbol not in _monitors:
        _monitors[symbol] = FuturesPositionMonitor(symbol)
    return _monitors[symbol]


class FuturesPositionMonitor:
    """
    Singleton monitor for one futures symbol.  Arm it after an entry
    signal fires, then let it auto-fire exit Discord alerts.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._lock  = threading.Lock()
        self._reset_state()

    # ── Public API ────────────────────────────────────────────────────────────────

    def arm(self, signal: dict) -> None:
        """
        Arm the monitor from a signal dict produced by FuturesORBScanner.
        Called automatically in futures_scanner_loop after scan() fires.
        """
        with self._lock:
            self._armed     = True
            self._direction = signal.get("direction", "BULL")
            self._entry     = float(signal.get("entry_price", 0))
            self._stop      = float(signal.get("stop_price", 0))
            self._t1        = float(signal.get("t1", 0))
            self._t2        = float(signal.get("t2", 0))
            self._t1_hit    = False
            self._t2_hit    = False
            self._stop_hit  = False
            logger.info(
                f"[FUTURES-MON] ✅ ARMED {self.symbol} {self._direction} "
                f"entry={self._entry} stop={self._stop} "
                f"T1={self._t1} T2={self._t2}"
            )

    def arm_manual(
        self,
        symbol: str,
        direction: str,
        entry: float,
        stop: float,
        t1: float,
        t2: float,
    ) -> None:
        """Arm manually from a Railway shell without a signal dict."""
        self.arm({
            "direction":   direction.upper(),
            "entry_price": entry,
            "stop_price":  stop,
            "t1":          t1,
            "t2":          t2,
        })

    def disarm(self) -> None:
        """Clear all state. Call after T2, stop, or manual close."""
        with self._lock:
            self._reset_state()
        logger.info(f"[FUTURES-MON] {self.symbol} disarmed")

    def trail_stop(self, new_stop: float) -> None:
        """Update the stop price (move to BE or trail after T1)."""
        with self._lock:
            if not self._armed:
                logger.warning("[FUTURES-MON] trail_stop called but monitor not armed")
                return
            old = self._stop
            self._stop = new_stop
        logger.info(f"[FUTURES-MON] {self.symbol} stop trailed {old} → {new_stop}")

    def get_status(self) -> dict:
        """Return current monitor state as a dict."""
        with self._lock:
            return {
                "symbol":    self.symbol,
                "armed":     self._armed,
                "direction": self._direction,
                "entry":     self._entry,
                "stop":      self._stop,
                "t1":        self._t1,
                "t2":        self._t2,
                "t1_hit":    self._t1_hit,
                "t2_hit":    self._t2_hit,
                "stop_hit":  self._stop_hit,
            }

    # ── Poll loop ────────────────────────────────────────────────────────────────────

    def tick(self) -> None:
        """
        Single poll cycle. Called by _monitor_loop() every 15 seconds.
        Safe to call manually for debugging.
        """
        with self._lock:
            if not self._armed:
                return
            direction = self._direction
            entry     = self._entry
            stop      = self._stop
            t1        = self._t1
            t2        = self._t2
            t1_hit    = self._t1_hit
            t2_hit    = self._t2_hit

        price = self._get_live_price()
        if price is None:
            return

        logger.debug(
            f"[FUTURES-MON] {self.symbol} {direction} price={price:.2f} "
            f"stop={stop:.2f} T1={t1:.2f} T2={t2:.2f}"
        )

        now_et = datetime.now(ET)

        # EOD force-close
        if (now_et.hour, now_et.minute) >= _SESSION_END:
            pnl = self._calc_pnl(price, entry, direction)
            self._fire_exit(direction, price, "EOD_CLOSE", entry, pnl)
            self.disarm()
            return

        if direction == "BULL":
            # Stop
            if price <= stop and not t1_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "STOP_HIT", entry, pnl)
                self.disarm()
                return
            # T2 (full runner close)
            if price >= t2 and not t2_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "T2_HIT", entry, pnl)
                with self._lock:
                    self._t2_hit = True
                self.disarm()
                return
            # T1 (partial — alert only, keep armed, suggest move-to-BE)
            if price >= t1 and not t1_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "T1_HIT", entry, pnl)
                with self._lock:
                    self._t1_hit = True
                    self._stop = entry  # auto-trail to breakeven
                logger.info(
                    f"[FUTURES-MON] {self.symbol} T1 hit — stop auto-trailed to BE ({entry})"
                )
                return

        else:  # BEAR
            # Stop
            if price >= stop and not t1_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "STOP_HIT", entry, pnl)
                self.disarm()
                return
            # T2
            if price <= t2 and not t2_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "T2_HIT", entry, pnl)
                with self._lock:
                    self._t2_hit = True
                self.disarm()
                return
            # T1
            if price <= t1 and not t1_hit:
                pnl = self._calc_pnl(price, entry, direction)
                self._fire_exit(direction, price, "T1_HIT", entry, pnl)
                with self._lock:
                    self._t1_hit = True
                    self._stop = entry  # auto-trail to breakeven
                logger.info(
                    f"[FUTURES-MON] {self.symbol} T1 hit — stop auto-trailed to BE ({entry})"
                )
                return

    # ── Private helpers ────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        """Must be called inside _lock or before thread starts."""
        self._armed:     bool          = False
        self._direction: str           = "BULL"
        self._entry:     float         = 0.0
        self._stop:      float         = 0.0
        self._t1:        float         = 0.0
        self._t2:        float         = 0.0
        self._t1_hit:    bool          = False
        self._t2_hit:    bool          = False
        self._stop_hit:  bool          = False

    def _get_live_price(self) -> Optional[float]:
        """
        Derive live price from the last 1-min bar close.
        Max lag: 1 minute. Adequate for a manual-execution workflow.
        """
        try:
            from app.futures.tradier_futures_feed import get_todays_bars
            bars = get_todays_bars(self.symbol)
            if bars:
                return float(bars[-1]["close"])
        except Exception as e:
            logger.debug(f"[FUTURES-MON] _get_live_price error: {e}")
        return None

    @staticmethod
    def _calc_pnl(price: float, entry: float, direction: str) -> float:
        """Return PnL in points (positive = profit)."""
        if direction == "BULL":
            return round(price - entry, 2)
        return round(entry - price, 2)

    def _fire_exit(
        self,
        direction: str,
        exit_price: float,
        reason: str,
        entry_price: float,
        pnl_pts: float,
    ) -> None:
        """Send the Discord exit alert. Non-fatal on failure."""
        try:
            from app.notifications.discord_helpers import send_futures_exit_alert
            from app.futures.futures_orb_scanner import _POINT_VALUE, _CONTRACTS
            pv = _POINT_VALUE.get(self.symbol, 2.0)
            send_futures_exit_alert(
                symbol=self.symbol,
                direction=direction,
                exit_price=exit_price,
                reason=reason,
                entry_price=entry_price,
                pnl_pts=pnl_pts,
                contracts=_CONTRACTS,
                point_value=pv,
            )
            logger.info(
                f"[FUTURES-MON] Exit alert sent: {self.symbol} {direction} "
                f"{reason} @ {exit_price:.2f} PnL={pnl_pts:+.2f} pts"
            )
        except Exception as e:
            logger.warning(f"[FUTURES-MON] Exit alert failed (non-fatal): {e}")


# ── Module-level daemon thread ──────────────────────────────────────────────────────────

_monitor_thread: threading.Thread | None = None


def _monitor_loop(symbol: str) -> None:
    """Daemon thread target: calls monitor.tick() every _POLL_INTERVAL seconds."""
    monitor = get_monitor(symbol)
    logger.info(f"[FUTURES-MON] Monitor thread started for {symbol}")
    while True:
        try:
            monitor.tick()
        except Exception as e:
            logger.error(f"[FUTURES-MON] Unhandled tick error: {e}")
        time.sleep(_POLL_INTERVAL)


def start_monitor_loop(symbol: str = "MNQ") -> threading.Thread:
    """
    Start the position monitor daemon thread.
    Safe to call multiple times — only starts one thread.
    Called from futures_scanner_loop.start_futures_loop().
    """
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        logger.info("[FUTURES-MON] Thread already running — skipping duplicate start")
        return _monitor_thread
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(symbol,),
        daemon=True,
        name=f"futures_monitor_{symbol}",
    )
    _monitor_thread.start()
    logger.info(f"[FUTURES-MON] ✅ Monitor thread started for {symbol}")
    return _monitor_thread
