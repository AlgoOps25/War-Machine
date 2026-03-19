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

REST Failover (get_current_bar_with_fallback):
  - When WS is disconnected, falls back to EODHD REST intraday API.
  - 3-tier priority: WS bar → REST API bar → None (caller falls back to DB).
  - REST results cached per-ticker for REST_CACHE_TTL seconds to avoid
    hammering the API during the 5s reconnect window.
  - 'source' key added to bar dict: 'ws' or 'rest'.
  - get_failover_stats() returns session-level REST usage for monitoring.

Log behaviour (Phase 1.17 — log batching):
  - _flush_open() is ALWAYS quiet. Open-bar upserts fire every FLUSH_INTERVAL
    seconds per ticker (e.g. 20 tickers x 6/min = 120 lines/min). These are
    in-flight bars that the scanner reads directly from _open_bars; the DB
    write is just for durability. A single heartbeat '.' prints every 60s.
  - _flush_pending() prints ONE summary line per cycle for all closed bars:
      [WS] Closed: NVDA×2, AAPL×1, SPY×3  (6 bars, 14:05:01 ET)
    If no bars closed that cycle, nothing is printed.
  - startup_backfill / update_ticker calls still print normally (quiet=False
    default in store_bars).

Usage:
    from app.data.ws_feed import (
        start_ws_feed, subscribe_tickers, set_backfill_complete,
        get_current_bar, get_current_bar_with_fallback, get_failover_stats
    )
    start_ws_feed(fallback_watchlist)           # once, before scanner loop
    subscribe_tickers(premarket_watchlist)      # after premarket build
    set_backfill_complete()                     # after both backfills finish
    bar = get_current_bar_with_fallback(ticker) # preferred over get_current_bar()
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

# How often (seconds) to print a heartbeat '.' when open-bar flushes are quiet
HEARTBEAT_INTERVAL = 60

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

# ── Shared state ──────────────────────────────────────────────────────────────────────────────────────
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

# Guard against double-start
_started            = False

# Backfill suppression (kept for backwards compat, no longer used in flush logic)
_backfill_active    = True

# Heartbeat state
_last_heartbeat: float = 0.0


def set_backfill_complete():
    """Call after startup_backfill_today() + startup_intraday_backfill_today() finish."""
    global _backfill_active
    _backfill_active = False


# ── Public read API ─────────────────────────────────────────────────────────────────────────────

def is_connected() -> bool:
    """Return True if the WebSocket is currently connected and subscribed."""
    return _connected


def get_current_bar(ticker: str):
    """Return a copy of the currently-open 1m bar for a ticker (thread-safe)."""
    with _lock:
        bar = _open_bars.get(ticker)
        return dict(bar) if bar else None


# ── Tick aggregation ───────────────────────────────────────────────────────────────────────────────────

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
      2. Dark pool filter — reject off-exchange trades (dp: true)
      3. Trade condition filter — reject invalid condition codes
      4. Market status filter (optional) — reject non-RTH ticks if ENFORCE_RTH_ONLY=True
      5. Spike filter — reject ticks that move > SPIKE_THRESHOLD from current close
    """
    # Gate 1: basic bounds (fast path, no lock needed)
    if price <= 0 or volume < 0 or price > 100_000:
        print(f"[WS] ⚠️ Bad tick rejected: {ticker} p={price} v={volume}")
        return

    if msg:
        # Gate 2: Dark pool filter
        if msg.get("dp", False):
            return

        # Gate 3: Trade condition filter
        condition = msg.get("c", 0)
        if isinstance(condition, list):
            if any(c in INVALID_TRADE_CONDITIONS for c in condition):
                return
            condition = condition[0] if condition else 0
        if condition in INVALID_TRADE_CONDITIONS:
            return

        # Gate 4: Market status filter (optional RTH enforcement)
        if ENFORCE_RTH_ONLY:
            market_status = msg.get("ms", "")
            if market_status != MARKET_STATUS_RTH:
                return

    bar_dt = _minute_floor(epoch_ms)

    with _lock:
        cur = _open_bars.get(ticker)

        # Gate 5: spike filter
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


# ── DB flush helpers ─────────────────────────────────────────────────────────────────────────────────

def _flush_pending():
    """
    Persist all completed 1m bars to DB.

    Phase 1.17 — batched log:
      Prints ONE summary line for the entire flush cycle:
        [WS] Closed: NVDA×2, AAPL×1, SPY×3  (6 bars, 14:05:01 ET)
      Nothing is printed if no bars closed this cycle.
    """
    from app.data.data_manager import data_manager  # late import avoids circular dep

    with _lock:
        snapshot = {t: list(bars) for t, bars in _pending.items() if bars}
        for t in snapshot:
            _pending[t].clear()

    if not snapshot:
        return

    stored_counts = {}   # ticker -> bars actually stored
    for ticker, bars in snapshot.items():
        count = data_manager.store_bars(ticker, bars, quiet=True)  # suppress per-ticker line
        data_manager.materialize_5m_bars(ticker)
        if count:
            stored_counts[ticker] = count

    if stored_counts:
        total = sum(stored_counts.values())
        parts = ", ".join(f"{t}\u00d7{n}" for t, n in stored_counts.items())
        ts    = datetime.now(ET).strftime("%H:%M:%S")
        print(f"[WS] Closed: {parts}  ({total} bars, {ts} ET)")


def _flush_open():
    """
    Upsert each open bar so the scanner sees live price on every poll.

    Phase 1.17 — always quiet:
      Open-bar upserts fire every FLUSH_INTERVAL seconds per ticker.
      With 20 tickers at FLUSH_INTERVAL=10s that is 120 log lines/min.
      The scanner reads price directly from _open_bars (in-memory); the
      DB write is just for durability. No log output here.
      A single heartbeat '[WS] ♥ live' prints every HEARTBEAT_INTERVAL
      seconds so the console shows the feed is still active.
    """
    global _last_heartbeat
    from app.data.data_manager import data_manager

    today_et = datetime.now(ET).date()
    with _lock:
        snapshot = {t: dict(b) for t, b in _open_bars.items()}

    for ticker, bar in snapshot.items():
        if bar["datetime"].date() == today_et:
            data_manager.store_bars(ticker, [bar], quiet=True)  # always quiet

    # Heartbeat: one line per HEARTBEAT_INTERVAL so console shows WS is alive
    now = time.monotonic()
    if now - _last_heartbeat >= HEARTBEAT_INTERVAL:
        ts = datetime.now(ET).strftime("%H:%M:%S")
        active = len(snapshot)
        print(f"[WS] ♥ live | {active} tickers | {ts} ET")
        _last_heartbeat = now


def _flush_loop():
    """Background thread — runs every FLUSH_INTERVAL seconds."""
    while True:
        time.sleep(FLUSH_INTERVAL)
        try:
            _flush_pending()
            _flush_open()
        except Exception as exc:
            print(f"[WS] Flush error: {exc}")


# ── Dynamic subscription (async, runs inside WS event loop) ────────────────────

async def _do_subscribe(ws, tickers: list):
    """
    Send subscribe messages for any tickers not already in _subscribed.
    Sends in chunks of SUBSCRIBE_CHUNK to respect EODHD's per-message limit.
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
    """
    global _all_tickers
    with _sub_lock:
        new = [t for t in tickers if t not in _all_tickers]
        if new:
            _all_tickers.extend(new)

    if not new:
        return

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


# ── WebSocket coroutine ───────────────────────────────────────────────────────────────────────────────────

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

                with _sub_lock:
                    _subscribed.clear()

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

                        if "status_code" in msg or "status" in msg:
                            print(f"[WS] Server msg: {msg}")
                            continue

                        ticker = msg.get("s", "")
                        price  = msg.get("p")
                        volume = int(msg.get("v", 0))
                        ts_ms  = msg.get("t")

                        if ticker and price and ts_ms:
                            _on_tick(ticker, float(price), volume, int(ts_ms), msg=msg)
                    except Exception as exc:
                        print(f"[WS] Tick error: {exc}")

                _connected     = False
                _ws_connection = None

        except Exception as exc:
            _connected     = False
            _ws_connection = None
            print(f"[WS] Disconnected ({exc}) — reconnecting in {RECONNECT_DELAY}s")
            await asyncio.sleep(RECONNECT_DELAY)


# ── Public API ────────────────────────────────────────────────────────────────────────────────

def start_ws_feed(tickers: list):
    """
    Launch the WebSocket feed and flush loop as background daemon threads.
    Call once from scanner.py before the scan loop.
    Use subscribe_tickers() afterwards to add premarket or dynamic tickers.

    Args:
        tickers: list of plain ticker symbols (no .US suffix), e.g. ['AAPL','MSFT']

    If called a second time (e.g. from both main.py and scanner.py), the guard
    below merges any new tickers via subscribe_tickers() and returns immediately.
    """
    global _event_loop, _all_tickers, _started

    if not _HAS_WEBSOCKETS:
        print("[WS] WARNING: 'websockets' package missing — "
              "install with: pip install 'websockets>=12.0'")
        return

    if _started:
        subscribe_tickers(tickers)
        print(f"[WS] Already running — merged {len(tickers)} tickers into active session")
        return
    _started = True

    with _sub_lock:
        for t in tickers:
            if t not in _all_tickers:
                _all_tickers.append(t)

    def _event_loop_thread():
        global _event_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _event_loop = loop
        loop.run_until_complete(_ws_run())

    threading.Thread(target=_event_loop_thread, name="ws-feed",  daemon=True).start()
    threading.Thread(target=_flush_loop,         name="ws-flush", daemon=True).start()
    print(f"[WS] Feed initializing | {len(tickers)} seed tickers | "
          f"DB flush every {FLUSH_INTERVAL}s")


# ── REST Failover ─────────────────────────────────────────────────────────────────────────────────────
#
# When the WebSocket is disconnected, get_current_bar_with_fallback() fetches
# the latest 1m bar via EODHD REST intraday API instead of returning None.
#
# 3-tier fallback chain (transparent to scanner/sniper):
#   Tier 1: WS live bar       — always preferred, in-memory, zero latency
#   Tier 2: REST intraday API — only when _connected=False, 5s timeout
#   Tier 3: None              — caller falls back to DB last bar (unchanged)
#
# REST results are cached per-ticker for REST_CACHE_TTL seconds so a
# 5-second reconnect window generates at most 1 REST call per ticker.
#
# 'source' key added to returned bar dict:
#   bar['source'] == 'ws'   → live WS data
#   bar['source'] == 'rest' → REST failover (WS was disconnected)
# ──────────────────────────────────────────────────────────────────────────────────────

REST_CACHE_TTL = 15      # seconds — REST results cached to avoid API hammering
_rest_lock     = threading.Lock()
_rest_cache    = {}      # ticker -> {"bar": dict|None, "fetched_at": float}
_rest_hits     = 0       # total REST failover fetches this session (for monitoring)


def _fetch_bar_rest(ticker: str) -> dict | None:
    """
    Fetch the most recent 1m bar via EODHD REST intraday API.
    Returns a bar dict matching get_current_bar() format + 'source':'rest'.
    Only called when WS is disconnected. Hard timeout: 5s.
    """
    import requests  # lazy import — only needed during WS outages
    global _rest_hits

    url    = f"https://eodhd.com/api/intraday/{ticker}.US"
    params = {
        "interval":  "1m",
        "api_token": config.EODHD_API_KEY,
        "fmt":       "json",
        "limit":     2,
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code != 200:
            print(f"[WS-FAILOVER] REST HTTP {resp.status_code} for {ticker}")
            return None
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        row = data[-1]
        _rest_hits += 1
        return {
            "datetime": datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S"),
            "open":     float(row["open"]),
            "high":     float(row["high"]),
            "low":      float(row["low"]),
            "close":    float(row["close"]),
            "volume":   int(row["volume"]),
            "source":   "rest",
        }
    except Exception as exc:
        print(f"[WS-FAILOVER] REST fetch failed for {ticker}: {exc}")
        return None


def get_current_bar_with_fallback(ticker: str) -> dict | None:
    """
    Get the current 1m bar for a ticker with automatic REST failover.

    Priority:
      1. Live WS bar  — if WebSocket is up and a bar exists (zero latency)
      2. REST API bar — if WS is disconnected, cached for REST_CACHE_TTL seconds
      3. None         — if both fail (caller should fall back to DB last bar)
    """
    bar = get_current_bar(ticker)
    if bar is not None:
        bar["source"] = "ws"
        return bar

    if _connected:
        return None

    now = time.monotonic()
    with _rest_lock:
        cached = _rest_cache.get(ticker)
        if cached is not None and (now - cached["fetched_at"]) < REST_CACHE_TTL:
            return cached["bar"]

    print(
        f"[WS-FAILOVER] WS down — fetching {ticker} via REST "
        f"(session fetches so far: {_rest_hits + 1})"
    )
    bar = _fetch_bar_rest(ticker)
    with _rest_lock:
        _rest_cache[ticker] = {"bar": bar, "fetched_at": now}
    return bar


def get_failover_stats() -> dict:
    """Return REST failover statistics for monitoring / EOD reporting."""
    now = time.monotonic()
    with _rest_lock:
        cache_active = sum(
            1 for c in _rest_cache.values()
            if c["bar"] is not None
            and (now - c["fetched_at"]) < REST_CACHE_TTL
        )
    return {
        "rest_hits":    _rest_hits,
        "cache_active": cache_active,
        "ws_connected": _connected,
    }
