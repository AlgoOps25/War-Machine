"""
ws_quote_feed.py — EODHD WebSocket Real-Time Quote (Bid/Ask) Feed

Connects to wss://ws.eodhistoricaldata.com/ws/us-quote?api_token=KEY
Maintains per-ticker bid/ask/spread state for entry quality filtering.

EODHD us-quote WebSocket protocol:
  - URL:       wss://ws.eodhistoricaldata.com/ws/us-quote?api_token=KEY
  - Subscribe: {"action": "subscribe", "symbols": "AAPL,MSFT,NVDA"}
  - Quote tick (known field variants):
      {"s":"AAPL", "a":150.01, "b":149.99, "av":200, "bv":500, "t":1725198451165}
      {"s":"AAPL", "ab":150.01,"b":149.99, "av":200, "bv":500, "t":1725198451165}
       s  = ticker
       a / ab = ask price (both variants handled)
       b / bb = bid price (both variants handled)
       av = ask size
       bv = bid size
       t  = epoch milliseconds
  - Docs: https://eodhd.com/financial-apis/new-real-time-data-api-websockets

Design:
  - Mirrors ws_feed.py architecture exactly:
    daemon thread, own asyncio loop, auto-reconnect, chunked subscriptions.
  - Stores latest quote per ticker in _quotes dict (thread-safe via _lock).
  - Rolling spread history (SPREAD_HISTORY_LEN quotes) per ticker.
  - Fail-open: if no quote data exists for a ticker, get_spread_pct() returns 0.0
    so entries are NEVER blocked by missing quote data.
  - Separate _started guard prevents duplicate threads.
  - Exponential backoff on reconnect: 2^attempt seconds, capped at 60s.
    Resets to 0 on a clean successful connection so normal brief disconnects
    recover quickly while repeated 500s from EODHD don't cause a reconnect storm.

Primary consumers:
  - sniper.py: is_spread_acceptable(ticker) before arming/entering signals
  - analytics: get_spread_summary() for logging during market hours (Day 4 testing)
  - target_discovery: spread data fed into target modeling (Day 5)

Spread threshold guide (0DTE equity underlying):
  SPY/QQQ:     typical 0.002-0.010%  |  wide > 0.05%
  AAPL/MSFT:   typical 0.005-0.020%  |  wide > 0.10%
  Mid-caps:    typical 0.020-0.100%  |  wide > 0.20%
  Default cap: 0.15% (15 bps) blocks clearly illiquid entries

Usage:
    from app.data.ws_quote_feed import (
        start_quote_feed, subscribe_quote_tickers,
        get_quote, get_spread_pct, is_spread_acceptable, is_quote_connected
    )
    start_quote_feed(watchlist)              # once, alongside start_ws_feed()
    subscribe_quote_tickers(new_tickers)     # after premarket watchlist builds

    # In sniper before entry:
    ok, spread = is_spread_acceptable("AAPL")
    if not ok:
        print(f"[SPREAD] AAPL blocked: {spread:.3f}% > threshold")
        return
"""
import asyncio
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

from utils import config

ET                  = ZoneInfo("America/New_York")
QUOTE_WS_BASE_URL   = "wss://ws.eodhistoricaldata.com/ws/us-quote"
RECONNECT_DELAY_MIN = 2      # seconds — base for exponential backoff (2^0 = 1 → floored to 2)
RECONNECT_DELAY_MAX = 60     # seconds — cap so we never wait more than a minute
SUBSCRIBE_CHUNK     = 50     # max tickers per subscribe message (EODHD limit)
SPREAD_HISTORY_LEN  = 20     # rolling window for spread% averaging

# Spread gate: block entries when spread_pct exceeds this threshold.
# Configurable via config.MAX_SPREAD_PCT; default 0.15% (15 bps).
# Fail-open: if no quote data, returns 0.0 (entry allowed).
MAX_SPREAD_PCT = getattr(config, "MAX_SPREAD_PCT", 0.15)

# ── Shared state ─────────────────────────────────────────────────────────────────────
_lock              = threading.Lock()
_quotes            = {}          # ticker → {bid, ask, spread, spread_pct, mid, ...}
_spread_history    = defaultdict(lambda: deque(maxlen=SPREAD_HISTORY_LEN))
_connected         = False

_sub_lock          = threading.Lock()
_all_tickers: list = []
_subscribed: set   = set()
_event_loop        = None
_ws_connection     = None
_started           = False


# ── Public read API ───────────────────────────────────────────────────────────────────────

def is_quote_connected() -> bool:
    """Return True if the quote WebSocket is currently connected."""
    return _connected


def get_quote(ticker: str) -> dict | None:
    """
    Return the latest bid/ask quote dict for a ticker, or None if not yet received.

    Keys: bid, ask, spread, spread_pct, mid, bid_size, ask_size, timestamp
    """
    with _lock:
        q = _quotes.get(ticker)
        return dict(q) if q else None


def get_spread_pct(ticker: str) -> float:
    """
    Return the current instantaneous spread percentage for a ticker.
    Returns 0.0 (fail-open) if no quote has been received yet.
    """
    with _lock:
        q = _quotes.get(ticker)
        return q["spread_pct"] if q else 0.0


def get_avg_spread_pct(ticker: str) -> float:
    """
    Return the rolling average spread% over the last SPREAD_HISTORY_LEN quotes.
    More stable than instantaneous spread for threshold decisions.
    Returns 0.0 if no history yet.
    """
    with _lock:
        history = list(_spread_history[ticker])
    return (sum(history) / len(history)) if history else 0.0


def is_spread_acceptable(ticker: str, max_spread_pct: float = None) -> tuple:
    """
    Check if the current spread is within acceptable range for entry.
    Uses the instantaneous spread (most conservative check).

    Returns:
        (is_acceptable: bool, current_spread_pct: float)

    Fail-open: returns (True, 0.0) when no quote data exists so entries
    are never blocked purely due to missing quote feed data.
    """
    threshold = max_spread_pct if max_spread_pct is not None else MAX_SPREAD_PCT
    spread    = get_spread_pct(ticker)
    if spread == 0.0:
        return True, 0.0  # no data → fail-open
    return spread <= threshold, spread


def get_spread_summary() -> dict:
    """
    Return spread snapshot for all tracked tickers.
    Use during Day 4 testing to monitor spreads live.
    """
    with _lock:
        return {
            ticker: {
                "spread_pct": q["spread_pct"],
                "mid":        q["mid"],
                "bid":        q["bid"],
                "ask":        q["ask"],
            }
            for ticker, q in _quotes.items()
        }


# ── Quote update handler ──────────────────────────────────────────────────────────────

def _on_quote(ticker: str, bid: float, ask: float,
             bid_size: int, ask_size: int, epoch_ms: int):
    """
    Process a bid/ask quote update. Rejects malformed quotes:
      - bid <= 0, ask <= 0
      - bid > ask (crossed market — data error)
      - ask > 100,000 (obviously corrupt)
    """
    if bid <= 0 or ask <= 0 or bid > ask or ask > 100_000:
        return

    spread     = round(ask - bid, 4)
    mid        = round((bid + ask) / 2, 4)
    spread_pct = round((spread / mid) * 100, 4) if mid > 0 else 0.0
    ts         = datetime.fromtimestamp(epoch_ms / 1000, tz=ET).replace(tzinfo=None)

    with _lock:
        _quotes[ticker] = {
            "bid":        bid,
            "ask":        ask,
            "spread":     spread,
            "spread_pct": spread_pct,
            "mid":        mid,
            "bid_size":   bid_size,
            "ask_size":   ask_size,
            "timestamp":  ts,
        }
        _spread_history[ticker].append(spread_pct)


# ── Dynamic subscription ──────────────────────────────────────────────────────────────

async def _do_subscribe(ws, tickers: list):
    """Send subscribe messages for new tickers. Must be called from WS event loop."""
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
        print(f"[QUOTE] +{len(chunk)} tickers subscribed: {preview}")


def subscribe_quote_tickers(tickers: list):
    """
    Subscribe additional tickers to the quote feed (thread-safe).
    Call from scanner after premarket watchlist is built — mirrors subscribe_tickers().
    """
    global _all_tickers
    with _sub_lock:
        new = [t for t in tickers if t not in _all_tickers]
        if new:
            _all_tickers.extend(new)

    if not new:
        return

    if _event_loop is None or _ws_connection is None:
        print(f"[QUOTE] subscribe_quote_tickers: WS not ready — "
              f"{len(new)} ticker(s) queued for next connect")
        return

    try:
        asyncio.run_coroutine_threadsafe(
            _do_subscribe(_ws_connection, new), _event_loop
        )
    except Exception as e:
        print(f"[QUOTE] subscribe_quote_tickers error: {e}")


# ── WebSocket coroutine ───────────────────────────────────────────────────────────────────

async def _ws_run():
    """
    Quote WebSocket coroutine. Runs in a dedicated asyncio event loop thread.

    Reconnect strategy — exponential backoff:
      delay = min(2 ** attempt, RECONNECT_DELAY_MAX)
      attempt resets to 0 after a clean successful connection.
    This prevents a tight reconnect storm when EODHD throws repeated 500s
    on subscription while still recovering quickly from normal brief drops.

    FIX: 0.5s sleep after connect before subscribing allows EODHD auth
    handshake to complete. Without this, subscribe messages race ahead of
    the auth response and trigger 422 'Symbols limit reached' errors.
    """
    global _connected, _ws_connection, _subscribed

    url     = f"{QUOTE_WS_BASE_URL}?api_token={config.EODHD_API_KEY}"
    attempt = 0  # tracks consecutive failed connect/run cycles

    while True:
        try:
            print(f"[QUOTE] Connecting -> {QUOTE_WS_BASE_URL}"
                  + (f" (attempt {attempt + 1})" if attempt > 0 else ""))
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=10, close_timeout=5
            ) as ws:
                _ws_connection = ws
                attempt = 0  # clean connect — reset backoff counter

                with _sub_lock:
                    _subscribed.clear()

                # Wait for EODHD auth handshake to complete before subscribing.
                # Without this delay, subscribe messages race ahead of the auth
                # response and trigger 422 'Symbols limit reached' errors.
                await asyncio.sleep(0.5)

                with _sub_lock:
                    master = list(_all_tickers)
                await _do_subscribe(ws, master)

                _connected = True
                print(f"[QUOTE] Live | {len(_subscribed)} tickers | "
                      f"spread gate: {MAX_SPREAD_PCT:.2f}% max")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)

                        if "status_code" in msg or "status" in msg:
                            print(f"[QUOTE] Server msg: {msg}")
                            continue

                        # Quote tick — handle both known EODHD field name variants:
                        #   ask: "a" or "ab"   |   bid: "b" or "bb"
                        ticker   = msg.get("s", "")
                        ask      = msg.get("a") or msg.get("ab")    # ask price
                        bid      = msg.get("b") or msg.get("bb")    # bid price
                        ask_size = int(msg.get("av", 0))
                        bid_size = int(msg.get("bv", 0))
                        ts_ms    = msg.get("t")

                        if ticker and bid is not None and ask is not None and ts_ms:
                            _on_quote(ticker, float(bid), float(ask),
                                      bid_size, ask_size, int(ts_ms))
                    except Exception as exc:
                        print(f"[QUOTE] Tick error: {exc}")

                _connected     = False
                _ws_connection = None

        except Exception as exc:
            _connected     = False
            _ws_connection = None

            # Exponential backoff: 2^attempt seconds, capped at RECONNECT_DELAY_MAX
            delay = min(2 ** attempt, RECONNECT_DELAY_MAX)
            attempt += 1
            print(f"[QUOTE] Disconnected ({exc}) — reconnecting in {delay}s "
                  f"(attempt {attempt})")
            await asyncio.sleep(delay)


# ── Public API ───────────────────────────────────────────────────────────────────────────

def start_quote_feed(tickers: list):
    """
    Launch the quote WebSocket feed as a background daemon thread.
    Call once from scanner.py immediately after start_ws_feed().
    Use subscribe_quote_tickers() afterwards to add premarket tickers.

    Args:
        tickers: list of plain ticker symbols (no .US suffix), e.g. ['AAPL','MSFT']

    Second-call guard: if already running, merges new tickers and returns immediately.
    """
    global _event_loop, _all_tickers, _started

    if not _HAS_WEBSOCKETS:
        print("[QUOTE] WARNING: 'websockets' package missing — "
              "install with: pip install 'websockets>=12.0'")
        return

    if _started:
        subscribe_quote_tickers(tickers)
        print(f"[QUOTE] Already running — merged {len(tickers)} tickers into active session")
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

    threading.Thread(
        target=_event_loop_thread, name="quote-feed", daemon=True
    ).start()
    print(f"[QUOTE] Feed initializing | {len(tickers)} seed tickers | "
          f"spread gate: {MAX_SPREAD_PCT:.2f}% max")


# ── Module self-test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("QUOTE FEED - Connection Test")
    print("=" * 60)

    test_tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
    start_quote_feed(test_tickers)

    print(f"\nMonitoring spreads for: {test_tickers}")
    print(f"Max spread threshold:   {MAX_SPREAD_PCT:.2f}%")
    print("\nPress Ctrl+C to stop\n")

    try:
        while True:
            time.sleep(5)
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Spread snapshot:")

            if not is_quote_connected():
                print("  Waiting for connection...")
                continue

            for ticker in test_tickers:
                q = get_quote(ticker)
                if q:
                    ok, spread = is_spread_acceptable(ticker)
                    avg        = get_avg_spread_pct(ticker)
                    status     = "✅ OK" if ok else "🚫 WIDE"
                    print(f"  {ticker:6s}  bid={q['bid']:.2f}  ask={q['ask']:.2f}  "
                          f"spread={q['spread_pct']:.3f}%  avg={avg:.3f}%  {status}")
                else:
                    print(f"  {ticker:6s}  waiting for quote...")

    except KeyboardInterrupt:
        print("\n[QUOTE] Test stopped")
        summary = get_spread_summary()
        if summary:
            print("\nFinal spread snapshot:")
            for ticker, data in sorted(summary.items()):
                print(f"  {ticker:6s}  {data['spread_pct']:.3f}%  "
                      f"mid={data['mid']:.2f}")
