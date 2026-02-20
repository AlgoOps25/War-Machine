"""
ws_feed.py — EODHD WebSocket Real-Time Bar Builder

Connects to wss://ws.eodhistoricaldata.com/ws/us and aggregates live trade
ticks into 1m OHLCV bars persisted to the DB via data_manager.store_bars().

Design:
  - Runs in a background daemon thread with its own asyncio event loop.
  - Completed bars (minute closed) are flushed to DB immediately.
  - The current open bar is flushed every FLUSH_INTERVAL seconds so the
    scanner always sees live price without waiting for the minute to close.
  - Auto-reconnects after RECONNECT_DELAY seconds on any disconnect.
  - Gracefully skips startup if 'websockets' package is not installed.

Usage (called once from main.py before the scanner loop):
    from ws_feed import start_ws_feed
    start_ws_feed(watchlist_tickers)

EODHD WebSocket protocol:
  Auth:      {"action":"auth","key":"<API_KEY>"}
  Subscribe: {"action":"subscribe","symbols":"AAPL.US,MSFT.US,..."}
  Tick:      {"s":"AAPL.US","p":"263.44","v":100,"t":1700000000000}
"""
import asyncio
import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

import config

ET              = ZoneInfo("America/New_York")
WS_URL          = "wss://ws.eodhistoricaldata.com/ws/us"
RECONNECT_DELAY = 5     # seconds between reconnect attempts
FLUSH_INTERVAL  = 10    # seconds between open-bar DB flushes

# ── Shared state ──────────────────────────────────────────────────────────────
_lock       = threading.Lock()
_open_bars  = {}                    # ticker -> current open bar dict
_pending    = defaultdict(list)     # ticker -> list of completed bars (not yet in DB)
_connected  = False


def is_connected() -> bool:
    """Return True if the WebSocket is currently authenticated and live."""
    return _connected


def get_current_bar(ticker: str):
    """Return a copy of the currently-open 1m bar for a ticker (thread-safe)."""
    with _lock:
        bar = _open_bars.get(ticker)
        return dict(bar) if bar else None


# ── Tick aggregation ──────────────────────────────────────────────────────────

def _minute_floor(epoch_ms: int) -> datetime:
    """Convert ms epoch -> ET-naive datetime floored to the minute."""
    return (
        datetime.fromtimestamp(epoch_ms / 1000, tz=ET)
        .replace(tzinfo=None, second=0, microsecond=0)
    )


def _on_tick(ticker: str, price: float, volume: int, epoch_ms: int):
    """Merge one trade tick into the current open bar; close bar on minute rollover."""
    bar_dt = _minute_floor(epoch_ms)
    with _lock:
        cur = _open_bars.get(ticker)
        if cur is None:
            _open_bars[ticker] = {
                "datetime": bar_dt, "open": price, "high": price,
                "low": price, "close": price, "volume": volume,
            }
            return

        if bar_dt > cur["datetime"]:
            # Minute rolled — close old bar, open new one
            _pending[ticker].append(dict(cur))
            _open_bars[ticker] = {
                "datetime": bar_dt, "open": price, "high": price,
                "low": price, "close": price, "volume": volume,
            }
        else:
            cur["high"]   = max(cur["high"], price)
            cur["low"]    = min(cur["low"],  price)
            cur["close"]  = price
            cur["volume"] += volume


# ── DB flush helpers ──────────────────────────────────────────────────────────

def _flush_pending():
    """Persist all completed 1m bars to DB and clear the queue."""
    from data_manager import data_manager  # late import avoids circular dep
    with _lock:
        snapshot = {t: list(bars) for t, bars in _pending.items() if bars}
        for t in snapshot:
            _pending[t].clear()
    for ticker, bars in snapshot.items():
        data_manager.store_bars(ticker, bars)
        data_manager.materialize_5m_bars(ticker)


def _flush_open():
    """Upsert each open bar so the scanner sees live price on every poll."""
    from data_manager import data_manager
    today_et = datetime.now(ET).date()
    with _lock:
        snapshot = {t: dict(b) for t, b in _open_bars.items()}
    for ticker, bar in snapshot.items():
        if bar["datetime"].date() == today_et:
            data_manager.store_bars(ticker, [bar])


def _flush_loop():
    """Background thread — runs every FLUSH_INTERVAL seconds."""
    while True:
        time.sleep(FLUSH_INTERVAL)
        try:
            _flush_pending()
            _flush_open()
        except Exception as exc:
            print(f"[WS] Flush error: {exc}")


# ── WebSocket coroutine ───────────────────────────────────────────────────────

async def _ws_run(tickers: list):
    global _connected
    symbols = ",".join(f"{t}.US" for t in tickers[:50])

    while True:
        try:
            print(f"[WS] Connecting -> {WS_URL}")
            async with websockets.connect(
                WS_URL, ping_interval=20, ping_timeout=10, close_timeout=5
            ) as ws:
                # Authenticate
                await ws.send(json.dumps({"action": "auth", "key": config.EODHD_API_KEY}))
                auth = json.loads(await ws.recv())
                if auth.get("status_code") != 200:
                    print(f"[WS] Auth failed: {auth} — retrying in {RECONNECT_DELAY}s")
                    _connected = False
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
                print("[WS] Authenticated OK")

                # Subscribe
                await ws.send(json.dumps({"action": "subscribe", "symbols": symbols}))
                print(f"[WS] Subscribed to {len(tickers[:50])} tickers OK")
                _connected = True

                async for raw in ws:
                    try:
                        msg    = json.loads(raw)
                        ticker = msg.get("s", "").replace(".US", "")
                        price  = msg.get("p")
                        volume = int(msg.get("v", 0))
                        ts_ms  = msg.get("t")
                        if ticker and price and ts_ms:
                            _on_tick(ticker, float(price), volume, int(ts_ms))
                    except Exception as exc:
                        print(f"[WS] Tick error: {exc}")

        except Exception as exc:
            _connected = False
            print(f"[WS] Disconnected ({exc}) — reconnecting in {RECONNECT_DELAY}s")
            await asyncio.sleep(RECONNECT_DELAY)


# ── Public API ────────────────────────────────────────────────────────────────

def start_ws_feed(tickers: list):
    """
    Launch the WebSocket feed and flush loop as background daemon threads.
    Call once from main.py before start_scanner_loop().

    Args:
        tickers: list of plain ticker symbols (no .US suffix), e.g. ['AAPL','MSFT']
    """
    if not _HAS_WEBSOCKETS:
        print("[WS] WARNING: 'websockets' package missing — "
              "install with: pip install 'websockets>=12.0'")
        return

    def _event_loop_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_ws_run(tickers))

    threading.Thread(target=_event_loop_thread, name="ws-feed", daemon=True).start()
    threading.Thread(target=_flush_loop, name="ws-flush", daemon=True).start()
    print(f"[WS] Feed initializing | {len(tickers)} tickers | DB flush every {FLUSH_INTERVAL}s")
