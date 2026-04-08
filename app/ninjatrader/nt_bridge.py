"""
app/ninjatrader/nt_bridge.py

NinjaTrader → War Machine bridge.

Architecture:
    NinjaScript strategy (NT8) streams JSON bar payloads over TCP.
    NTBridge listens on a configurable port, deserializes each payload
    into NTBarData, passes it through SignalEngine, and puts the
    resulting NTSignal onto a thread-safe queue for downstream
    War Machine consumers.

Expected JSON payload from NinjaScript (one per bar close):
    {
        "symbol":       "NQ JUN26",
        "timestamp":    "2026-04-08T09:35:00",
        "open":         18200.25,
        "high":         18215.50,
        "low":          18195.00,
        "close":        18210.75,
        "volume":       1842,
        "cum_delta":    312.0,
        "vwap":         18205.10,
        "poc":          18200.00,
        "vah":          18220.00,
        "val":          18185.00
    }

Usage:
    bridge = NTBridge(host="0.0.0.0", port=5570)
    bridge.start()                          # non-blocking background thread
    signal = bridge.signal_queue.get()      # blocks until next signal arrives
    bridge.stop()

Fix BUG-NT-1 (2026-04-08):
    SignalEngine._prev_bar is now reset when NT disconnects so that the
    first bar of a new connection is never compared against a stale bar
    from a previous session, preventing false delta-divergence signals.
"""

import json
import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5570
RECONNECT_DELAY_SEC = 5
MAX_RECONNECT_ATTEMPTS = 10
SOCKET_TIMEOUT_SEC = 30
BUFFER_SIZE = 4096


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Direction(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"   # no tradeable edge


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NTBarData:
    """Normalized bar payload received from NinjaTrader."""
    symbol:    str
    timestamp: datetime
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    int
    cum_delta: float          # net aggressive buy − sell volume this bar
    vwap:      float          # session VWAP
    poc:       float          # Volume Profile Point of Control
    vah:       float          # Value Area High
    val:       float          # Value Area Low

    # Rolling delta history populated by SignalEngine — not sent over wire
    prev_cum_delta: Optional[float] = field(default=None, repr=False)
    prev_close:     Optional[float] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "NTBarData":
        return cls(
            symbol    = data["symbol"],
            timestamp = datetime.fromisoformat(data["timestamp"]),
            open      = float(data["open"]),
            high      = float(data["high"]),
            low       = float(data["low"]),
            close     = float(data["close"]),
            volume    = int(data["volume"]),
            cum_delta = float(data["cum_delta"]),
            vwap      = float(data["vwap"]),
            poc       = float(data["poc"]),
            vah       = float(data["vah"]),
            val       = float(data["val"]),
        )


@dataclass
class NTSignal:
    """Output signal produced by SignalEngine for War Machine."""
    direction:  Direction
    confidence: float          # 0.0 – 1.0
    reason:     str            # human-readable explanation
    bar:        NTBarData
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def is_actionable(self) -> bool:
        return self.direction != Direction.FLAT


# ---------------------------------------------------------------------------
# Signal Engine
# ---------------------------------------------------------------------------

class SignalEngine:
    """
    Applies three-layer filter to produce a directional signal:

        Layer 1 — VWAP Bias
            close > vwap  → bullish bias
            close < vwap  → bearish bias

        Layer 2 — Volume Profile POC Filter
            price above POC → only accept longs
            price below POC → only accept shorts
            price inside VA → reduce confidence (mean-reversion zone)

        Layer 3 — Cumulative Delta Divergence
            price up  + delta down → bearish divergence → SELL
            price down + delta up  → bullish divergence → BUY
            agreement              → trend continuation, follow VWAP bias
    """

    def __init__(self):
        self._prev_bar: Optional[NTBarData] = None

    def reset(self) -> None:
        """Clear carry-over state between NT sessions.

        Must be called whenever the TCP connection is lost so that the first
        bar received on the next connection is not compared against a stale
        bar from a previous session (BUG-NT-1).
        """
        if self._prev_bar is not None:
            logger.info(
                "[SignalEngine] State reset — discarding prev_bar from %s",
                self._prev_bar.timestamp,
            )
        self._prev_bar = None

    def evaluate(self, bar: NTBarData) -> NTSignal:
        prev = self._prev_bar
        self._prev_bar = bar

        if prev is None:
            return NTSignal(
                direction=Direction.FLAT,
                confidence=0.0,
                reason="Initializing — awaiting second bar for delta comparison",
                bar=bar,
            )

        bar.prev_cum_delta = prev.cum_delta
        bar.prev_close     = prev.close

        # ── Layer 1: VWAP bias ──────────────────────────────────────────────
        vwap_bullish = bar.close > bar.vwap
        vwap_label   = "above VWAP" if vwap_bullish else "below VWAP"

        # ── Layer 2: POC position ───────────────────────────────────────────
        above_poc     = bar.close > bar.poc
        inside_va     = bar.val <= bar.close <= bar.vah
        va_confidence = 0.6 if inside_va else 1.0  # reduce inside Value Area

        # ── Layer 3: Cumulative delta divergence ────────────────────────────
        price_up    = bar.close > prev.close
        price_down  = bar.close < prev.close
        delta_up    = bar.cum_delta > prev.cum_delta
        delta_down  = bar.cum_delta < prev.cum_delta

        bearish_div = price_up  and delta_down   # new price high, delta failing
        bullish_div = price_down and delta_up    # new price low, delta holding
        agreement   = (price_up and delta_up) or (price_down and delta_down)

        # ── Combine layers ──────────────────────────────────────────────────
        if bearish_div and not above_poc and not vwap_bullish:
            return NTSignal(
                direction=Direction.SELL,
                confidence=round(0.85 * va_confidence, 2),
                reason=f"Bearish delta divergence | {vwap_label} | price below POC",
                bar=bar,
            )

        if bullish_div and above_poc and vwap_bullish:
            return NTSignal(
                direction=Direction.BUY,
                confidence=round(0.85 * va_confidence, 2),
                reason=f"Bullish delta divergence | {vwap_label} | price above POC",
                bar=bar,
            )

        if agreement and vwap_bullish and above_poc:
            return NTSignal(
                direction=Direction.BUY,
                confidence=round(0.70 * va_confidence, 2),
                reason=f"Delta/price agreement | {vwap_label} | price above POC",
                bar=bar,
            )

        if agreement and not vwap_bullish and not above_poc:
            return NTSignal(
                direction=Direction.SELL,
                confidence=round(0.70 * va_confidence, 2),
                reason=f"Delta/price agreement | {vwap_label} | price below POC",
                bar=bar,
            )

        return NTSignal(
            direction=Direction.FLAT,
            confidence=0.0,
            reason="Conflicting layers — no edge",
            bar=bar,
        )


# ---------------------------------------------------------------------------
# TCP Bridge
# ---------------------------------------------------------------------------

class NTBridge:
    """
    Listens for NinjaTrader bar payloads over TCP, evaluates each bar
    through SignalEngine, and pushes NTSignal objects onto signal_queue.

    Thread model:
        _listen_thread  — accepts connections, reads newline-delimited JSON
        All other War Machine threads consume from signal_queue safely.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        max_queue_size: int = 100,
    ):
        self.host           = host
        self.port           = port
        self.signal_queue:  queue.Queue[NTSignal] = queue.Queue(maxsize=max_queue_size)
        self._engine        = SignalEngine()
        self._stop_event    = threading.Event()
        self._listen_thread = threading.Thread(
            target=self._listen_loop,
            name="NTBridge-Listener",
            daemon=True,
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background listener thread (non-blocking)."""
        logger.info("NTBridge starting on %s:%d", self.host, self.port)
        self._listen_thread.start()

    def stop(self) -> None:
        """Signal the listener to stop and wait for clean shutdown."""
        logger.info("NTBridge stopping...")
        self._stop_event.set()
        self._listen_thread.join(timeout=5)
        logger.info("NTBridge stopped.")

    @property
    def is_running(self) -> bool:
        return self._listen_thread.is_alive()

    # ── Internal ────────────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        attempts = 0
        while not self._stop_event.is_set():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
                    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    srv.settimeout(SOCKET_TIMEOUT_SEC)
                    srv.bind((self.host, self.port))
                    srv.listen(1)
                    logger.info("NTBridge listening on %s:%d", self.host, self.port)
                    attempts = 0  # reset on successful bind

                    conn, addr = srv.accept()
                    logger.info("NinjaTrader connected from %s", addr)
                    self._handle_connection(conn)

            except socket.timeout:
                logger.debug("NTBridge: no connection yet, retrying...")
                continue

            except OSError as exc:
                attempts += 1
                logger.warning(
                    "NTBridge socket error (attempt %d/%d): %s",
                    attempts, MAX_RECONNECT_ATTEMPTS, exc,
                )
                if attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("NTBridge: max reconnect attempts reached. Stopping.")
                    break
                time.sleep(RECONNECT_DELAY_SEC)

    def _handle_connection(self, conn: socket.socket) -> None:
        buffer = ""
        with conn:
            conn.settimeout(SOCKET_TIMEOUT_SEC)
            while not self._stop_event.is_set():
                try:
                    chunk = conn.recv(BUFFER_SIZE).decode("utf-8")
                    if not chunk:
                        logger.info("NinjaTrader disconnected.")
                        break
                    buffer += chunk
                    # NinjaScript sends newline-delimited JSON
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            self._process_line(line)

                except socket.timeout:
                    logger.debug("NTBridge: waiting for data...")
                    continue

                except (ConnectionResetError, BrokenPipeError):
                    logger.warning("NTBridge: connection lost.")
                    break

        # BUG-NT-1: Reset SignalEngine state when connection drops so the first
        # bar of the next session is never compared against a stale prior bar.
        self._engine.reset()

    def _process_line(self, line: str) -> None:
        try:
            data   = json.loads(line)
            bar    = NTBarData.from_dict(data)
            signal = self._engine.evaluate(bar)

            if signal.is_actionable():
                logger.info(
                    "[%s] %s | confidence=%.2f | %s",
                    bar.symbol, signal.direction.value,
                    signal.confidence, signal.reason,
                )

            try:
                self.signal_queue.put_nowait(signal)
            except queue.Full:
                logger.warning("NTBridge signal queue full — dropping oldest signal")
                try:
                    self.signal_queue.get_nowait()
                except queue.Empty:
                    pass
                self.signal_queue.put_nowait(signal)

        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            logger.error("NTBridge: failed to parse bar payload: %s | raw: %s", exc, line)
