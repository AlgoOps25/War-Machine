"""
ws_feed.py — EODHD WebSocket Real-Time Bar Builder

Connects to wss://ws.eodhistoricaldata.com/ws/us?api_token=KEY and aggregates
live trade ticks into 1m OHLCV bars persisted to the DB via data_manager.store_bars().

EODHD WebSocket protocol:
  - API key goes in the connection URL as ?api_token=KEY  (no JSON auth message)
  - Subscribe:  {"action": "subscribe", "symbols": "AAPL,MSFT,NVDA"}
  - Tick:       {"s": "AAPL", "p": 227.31, "v": 100, "t": 1725198451165}
                 s = plain ticker (no .US suffix)
                 p = last trade price
                 v = trade size (shares)
                 t = epoch milliseconds
  - Docs:       https://eodhd.com/financial-apis/new-real-time-data-api-websockets
  - Plan req:   EOD+Intraday (All World Extended) or All-In-One

Design:
  - Runs in a background daemon thread with its own asyncio event loop.
  - Completed bars (minute closed) are flushed to DB immediately.
  - Current open bar flushed every FLUSH_INTERVAL seconds so scanner
    always sees live price without waiting for the minute to close.
  - Auto-reconnects after RECONNECT_DELAY seconds on any disconnect;
    ALL known tickers (startup + any added via subscribe_tickers) are
    re-subscribed on every reconnect automatically.
  - subscribe_tickers() is thread-safe: callable from the main scanner
    thread at any time, including before the WS connection is established.
    New tickers are merged into the master list and sent live if connected.
  - _on_tick() rejects bad prints (price <= 0, volume < 0, price > 100k) and
    intra-bar spikes > 10% from the current close before touching bar state.
  - NEW: Filters dark pool trades (dp: true) and invalid condition codes
    (Form T, odd lots, derivative pricing) to improve bar quality.
  - NEW: Optional market status (ms) filtering to enforce RTH-only bar building.
  - Gracefully skips startup if 'websockets' package is not installed.
  - _started guard prevents double thread creation if start_ws_feed() is
    called more than once (e.g. from both main.py and scanner.py).

Log behaviour:
  - Single-bar WS flushes are suppressed at DEBUG level during the startup
    backfill window (_backfill_active = True) to keep the console clean.
  - Once backfill completes, all store_bars() calls log normally.
  - Set _backfill_active = False via set_backfill_complete() after both
    startup_backfill_today() and startup_intraday_backfill_today() finish.

Usage:
    from ws_feed import start_ws_feed, subscribe_tickers, set_backfill_complete
    start_ws_feed(fallback_watchlist)       # once, before scanner loop
    subscribe_tickers(premarket_watchlist)  # after premarket build
    set_backfill_complete()                 # after both backfills finish
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

from utils import config

ET              = ZoneInfo("America/New_York")
WS_BASE_URL     = "wss://ws.eodhistoricaldata.com/ws/us"
RECONNECT_DELAY = 5     # seconds between reconnect attempts
FLUSH_INTERVAL  = 10    # seconds between open-bar DB flushes
SUBSCRIBE_CHUNK = 50    # max tickers per subscribe message (EODHD limit)
SPIKE_THRESHOLD = 0.10  # reject ticks that move > 10% from current bar close

# Trade condition codes to reject (EODHD WebSocket feed)
# Reference: https://eodhd.com/financial-apis/new-real-time-data-api-websockets
INVALID_TRADE_CONDITIONS = {
    12,  # Form T - Late report (dark pool/off-exchange)
    37,  # Odd lot (< 100 shares) - illiquid, not representative
    52,  # Derivative priced
    53,  # Re-opening trade
    80,  # Sold out of sequence
    81,  # Sold (out of sequence, reg NMS exempt)
}

# Market status filtering (optional RTH enforcement)
MARKET_STATUS_RTH = "open"  # Regular trading hours (9:30 AM - 4:00 PM ET)
ENFORCE_RTH_ONLY = False     # Set True to reject pre/post-market ticks
                             # Set False to allow all ticks (default)
                             # NOTE: Your RTH filter in scanner.py will still
                             # block signals outside RTH - this is a data-level filter

# ── Shared state ────────────────────────────────────────────────────────────────────────────────
_lock               = threading.Lock()
_open_bars          = {}                 # ticker -> current open bar dict
_pending            = defaultdict(list)  # ticker -> completed bars not yet in DB
_connected          = False

# Dynamic subscription state (thread-safe via _sub_lock)
_sub_lock           = threading.Lock()
_all_tickers: list  = []                 # master list — startup + premarket additions
_subscribed: set    = set()              # tickers currently subscribed on active WS
_event_loop         = None               # background asyncio loop (set before connect)
_ws_connection      = None               # active websockets connection object

# FIX #3: guard against double-start when main.py and scanner.py both call start_ws_feed()
_started            = False

# Backfill log suppression: while True, single-bar WS stores are silent (DEBUG-level).
# Set to False via set_backfill_complete() once both backfills finish.
_backfill_active    = True


def set_backfill_complete():
    """Call after startup_backfill_today() + startup_intraday_backfill_today() finish.
    Restores normal INFO-level logging for WS bar stores."""
    global _backfill_active
    _backfill_active = False


# ── Public read API ────────────────────────────────────────────────────────────────────────────

def is_connected() -> bool:
    """Return True if the WebSocket is currently connected and subscribed."""
    return _connected


def get_current_bar(ticker: str):
    """Return a copy of the currently-open 1m bar for a ticker (thread-safe)."""
    with _lock:
        bar = _open_bars.get(ticker)
        return dict(bar) if bar else None


# ── Tick aggregation ───────────────────────────────────────────────────────────────────────────

def _minute_floor(epoch_ms: int) -> datetime:
    """Convert ms epoch -> ET-naive datetime floored to the minute."""
    return (
        datetime.fromtimestamp(epoch_ms / 1000, tz=ET)
        .replace(tzinfo=None, second=0, microsecond=0)
    )


def _on_tick(ticker: str, price: float, volume: int, epoch_ms: int, msg: dict = None):
    """
    Merge one trade tick into the current open bar; close bar on minute rollover.

    Sanity gates (applied before any bar state is touched):
      1. Basic bounds — price must be > 0 and <= 100,000; volume must be >= 0.
         Catches zero-price fills, negative volumes, and obviously corrupt ticks.
      2. Dark pool filter — reject off-exchange trades (dp: true)
      3. Trade condition filter — reject invalid condition codes
      4. Market status filter (optional) — reject non-RTH ticks if ENFORCE_RTH_ONLY=True
      5. Spike filter — if a bar already exists for this ticker, reject any tick
         that moves more than SPIKE_THRESHOLD (10%) from the current close.
         Protects against bad prints that would generate false breakout signals.
         Applied inside the lock so the reference close is the exact same value
         the bar logic would use.
    """
    # Gate 1: basic bounds (fast path, no lock needed)
    if price <= 0 or volume < 0 or price > 100_000:
        print(f"[WS] ⚠️ Bad tick rejected: {ticker} p={price} v={volume}")
        return
    
    # NEW Gates 2-4: Message-based filters (if msg dict provided)
    if msg:
        # Gate 2: Dark pool filter
        if msg.get("dp", False):
            # Silent reject - dark pools are common, don't spam logs
            # Uncomment for debugging: print(f"[WS] 🚫 Dark pool: {ticker} p={price:.2f} v={volume}")
            return
        
        # Gate 3: Trade condition filter
        condition = msg.get("c", 0)
        if condition in INVALID_TRADE_CONDITIONS:
            print(f"[WS] 🚫 Condition {condition}: {ticker} p={price:.2f} v={volume}")
            return
        
        # Gate 4: Market status filter (optional RTH enforcement)
        if ENFORCE_RTH_ONLY:
            market_status = msg.get("ms", "")
            if market_status != MARKET_STATUS_RTH:
                # Silent reject - extended hours ticks are common
                # Uncomment for debugging: print(f"[WS] 🚫 Non-RTH: {ticker} ms={market_status}")
                return

    bar_dt = _minute_floor(epoch_ms)

    with _lock:
        cur = _open_bars.get(ticker)

        # Gate 5: spike filter (inside lock — cur['close'] is the authoritative reference)
        if cur is not None:
            deviation = abs(price - cur["close"]) / cur["close"]
            if deviation > SPIKE_THRESHOLD:
                print(
                    f"[WS] ⚠️ Spike rejected: {ticker} "
                    f"p={price:.2f} vs close={cur['close']:.2f} "
                    f"({deviation:.1%} > {SPIKE_THRESHOLD:.0%})"
                )
                return

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


# ── DB flush helpers ───────────────────────────────────────────────────────────────────────────

def _flush_pending():
    """Persist all completed 1m bars to DB and clear the queue."""
    from app.data.data_manager import data_manager  # late import avoids circular dep
    with _lock:
        snapshot = {t: list(bars) for t, bars in _pending.items() if bars}
        for t in snapshot:
            _pending[t].clear()
    for ticker, bars in snapshot.items():
        data_manager.store_bars(ticker, bars)
        data_manager.materialize_5m_bars(ticker)


def _flush_open():
    """Upsert each open bar so the scanner sees live price on every poll."""
    from app.data.data_manager import data_manager
    today_et = datetime.now(ET).date()
    with _lock:
        snapshot = {t: dict(b) for t, b in _open_bars.items()}
    for ticker, bar in snapshot.items():
        if bar["datetime"].date() == today_et:
            # Suppress log noise during backfill for single-bar open-bar flushes
            data_manager.store_bars(ticker, [bar], quiet=_backfill_active)


def _flush_loop():
    """Background thread — runs every FLUSH_INTERVAL seconds."""
    while True:
        time.sleep(FLUSH_INTERVAL)
        try:
            _flush_pending()
            _flush_open()
        except Exception as exc:
            print(f"[WS] Flush error: {exc}")


# ── Dynamic subscription (async, runs inside WS event loop) ──────────────────

async def _do_subscribe(ws, tickers: list):
    """
    Send subscribe messages for any tickers not already in _subscribed.
    Sends in chunks of SUBSCRIBE_CHUNK to respect EODHD's per-message limit.
    Must be called from within the WS event loop (use asyncio.run_coroutine_threadsafe
    when calling from the main thread).
    """
    global _subscribed
    with _sub_lock:
        new = [t for t in tickers if t not in _subscribed]
    if not new:
        return
    for i in range(0, len(new), SUBSCRIBE_CHUNK):
        chunk = new[i:i + SUBSCRIBE_CHUNK]
        await ws.send(json.dumps({"action": "subscribe", "symbols": ",".join(chunk)}))
        with _sub_lock:
            _subscribed.update(chunk)
        preview = ", ".join(chunk[:8]) + ("..." if len(chunk) > 8 else "")
        print(f"[WS] +{len(chunk)} tickers subscribed: {preview}")


def subscribe_tickers(tickers: list):
    """
    Subscribe additional tickers to the running WS session (thread-safe).
    Safe to call from the main scanner thread at any point after start_ws_feed().

    - New tickers are merged into _all_tickers (master list) so they are
      automatically re-subscribed on any future reconnect.
    - If the WS is already connected, the subscribe message is sent immediately
      via asyncio.run_coroutine_threadsafe.
    - If the WS is not yet connected, the tickers sit in _all_tickers and will
      be sent when _ws_run establishes the first connection.
    """
    global _all_tickers
    with _sub_lock:
        new = [t for t in tickers if t not in _all_tickers]
        if new:
            _all_tickers.extend(new)

    if not new:
        return  # nothing novel to subscribe

    if _event_loop is None or _ws_connection is None:
        print(f"[WS] subscribe_tickers: WS not ready — "
              f"{len(new)} ticker(s) queued for next connect")
        return

    try:
        asyncio.run_coroutine_threadsafe(
            _do_subscribe(_ws_connection, new), _event_loop
        )
    except Exception as e:
        print(f"[WS] subscribe_tickers error: {e}")


# ── WebSocket coroutine ────────────────────────────────────────────────────────────────────────

async def _ws_run():
    """Main WebSocket coroutine. Runs in a dedicated asyncio event loop thread."""
    global _connected, _ws_connection, _subscribed

    url = f"{WS_BASE_URL}?api_token={config.EODHD_API_KEY}"

    while True:
        try:
            print(f"[WS] Connecting -> {WS_BASE_URL}")
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=10, close_timeout=5
            ) as ws:
                _ws_connection = ws

                # Clear subscribed set so _do_subscribe re-sends everything
                # (covers both initial connect and reconnect after drop).
                with _sub_lock:
                    _subscribed.clear()

                # Subscribe to full master list (startup + any added tickers)
                with _sub_lock:
                    master = list(_all_tickers)
                await _do_subscribe(ws, master)

                _connected = True
                rth_status = "RTH-only" if ENFORCE_RTH_ONLY else "all-hours"
                print(f"[WS] Live | {len(_subscribed)} tickers subscribed | "
                      f"{rth_status} | waiting for ticks...")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)

                        # Status / confirmation messages (not ticks)
                        if "status_code" in msg or "status" in msg:
                            print(f"[WS] Server msg: {msg}")
                            continue

                        # Trade tick: {"s":"AAPL","p":227.31,"v":100,"t":1725198451165,"c":0,"dp":false,"ms":"open"}
                        ticker = msg.get("s", "")
                        price  = msg.get("p")
                        volume = int(msg.get("v", 0))
                        ts_ms  = msg.get("t")

                        if ticker and price and ts_ms:
                            # MODIFIED: Pass full msg dict for condition filtering
                            _on_tick(ticker, float(price), volume, int(ts_ms), msg=msg)
                    except Exception as exc:
                        print(f"[WS] Tick error: {exc}")

                # Clean server-side close — reset state before next reconnect attempt.
                _connected     = False
                _ws_connection = None

        except Exception as exc:
            _connected     = False
            _ws_connection = None
            print(f"[WS] Disconnected ({exc}) — reconnecting in {RECONNECT_DELAY}s")
            await asyncio.sleep(RECONNECT_DELAY)


# ── Public API ─────────────────────────────────────────────────────────────────────────────────

def start_ws_feed(tickers: list):
    """
    Launch the WebSocket feed and flush loop as background daemon threads.
    Call once from scanner.py before the scan loop.
    Use subscribe_tickers() afterwards to add premarket or dynamic tickers.

    Args:
        tickers: list of plain ticker symbols (no .US suffix), e.g. ['AAPL','MSFT']

    If called a second time (e.g. from both main.py and scanner.py), the guard
    below merges any new tickers via subscribe_tickers() and returns immediately
    — no duplicate threads are created.
    """
    global _event_loop, _all_tickers, _started

    if not _HAS_WEBSOCKETS:
        print("[WS] WARNING: 'websockets' package missing — "
              "install with: pip install 'websockets>=12.0'")
        return

    # FIX #3: guard — already running; just subscribe any new tickers and exit
    if _started:
        subscribe_tickers(tickers)
        print(f"[WS] Already running — merged {len(tickers)} tickers into active session")
        return
    _started = True

    # Seed master list before thread starts so reconnects work immediately
    with _sub_lock:
        for t in tickers:
            if t not in _all_tickers:
                _all_tickers.append(t)

    def _event_loop_thread():
        global _event_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _event_loop = loop   # expose before run_until_complete so subscribe_tickers works
        loop.run_until_complete(_ws_run())

    threading.Thread(target=_event_loop_thread, name="ws-feed",  daemon=True).start()
    threading.Thread(target=_flush_loop,         name="ws-flush", daemon=True).start()
    print(f"[WS] Feed initializing | {len(tickers)} seed tickers | "
          f"DB flush every {FLUSH_INTERVAL}s")
