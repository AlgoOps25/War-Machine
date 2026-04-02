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

500 / entitlement handling (v4):
  - Consecutive 500s are counted. First one logs normally. Subsequent ones are
    suppressed (log every 10th) to prevent log spam.
  - After SERVER_500_BACKOFF_THRESHOLD consecutive 500s (default 3), the feed
    backs off hard. Backoff duration grows exponentially:
      attempt 1: 300s, attempt 2: 600s, attempt 3: 1200s, … capped at 3600s.
  - CRITICAL FIX (v4): The hard-backoff attempt counter now lives OUTSIDE the
    TCP connect block and is only reset on a confirmed 200 auth from the server.
    Previously it was reset on every TCP connect success, which meant the
    counter always stayed at 1 (300s) even during prolonged EODHD outages where
    the server accepted TCP but immediately returned 500s at the application layer.
  - If the server sends a non-200 status_code that is NOT 500 (e.g. 401/403),
    the feed logs a permanent entitlement warning and stops retrying — no
    point hammering an auth-rejected endpoint.

BUG-WQF-1/2 fix (DATA-4 audit):
  - bid/ask field parsing changed from `msg.get("b") or msg.get("bb")` to
    an explicit `is not None` check. The `or` form treats 0.0 as falsy and
    would silently fall through to the alternate field name on a valid zero
    price, returning a wrong value. The corrected form uses the primary field
    when it is explicitly present (even if 0.0), and falls back to the
    alternate only when the primary key is absent from the message.

Primary consumers:
  - sniper.py: is_spread_acceptable(ticker) before arming/entering signals
  - analytics: get_spread_summary() for logging during market hours
  - target_discovery: spread data fed into target modeling

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
        logger.info(f"[SPREAD] AAPL blocked: {spread:.3f}% > threshold")
        return
"""
import asyncio
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
logger = logging.getLogger(__name__)

try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

from utils import config

ET                  = ZoneInfo("America/New_York")
QUOTE_WS_BASE_URL   = "wss://ws.eodhistoricaldata.com/ws/us-quote"
RECONNECT_DELAY_MIN = 2      # seconds — base for exponential backoff
RECONNECT_DELAY_MAX = 60     # seconds — cap on normal reconnect backoff
SUBSCRIBE_CHUNK     = 50     # max tickers per subscribe message (EODHD limit)
SPREAD_HISTORY_LEN  = 20     # rolling window for spread% averaging

# 500 flood control:
#   After this many consecutive 500s, back off hard before retrying.
SERVER_500_BACKOFF_THRESHOLD = 3
#   Base hard-backoff duration (seconds). Actual wait = min(BASE * 2^(attempt-1), MAX).
#   attempt 1 → 300s, attempt 2 → 600s, attempt 3 → 1200s, … capped at 3600s.
SERVER_500_HARD_BACKOFF_BASE = 300
SERVER_500_HARD_BACKOFF_MAX  = 3600  # 1 hour ceiling

# Spread gate: block entries when spread_pct exceeds this threshold.
# Configurable via config.MAX_SPREAD_PCT; default 0.15% (15 bps).
# Fail-open: if no quote data, returns 0.0 (entry allowed).
MAX_SPREAD_PCT = getattr(config, "MAX_SPREAD_PCT", 0.15)

# ── Shared state ──────────────────────────────────────────────────────────────────────────────────
lock              = threading.Lock()
_quotes            = {}          # ticker → {bid, ask, spread, spread_pct, mid, ...}
_spread_history    = defaultdict(lambda: deque(maxlen=SPREAD_HISTORY_LEN))
_connected         = False

_sub_lock          = threading.Lock()
_all_tickers: list = []
_subscribed: set   = set()
_event_loop        = None
_ws_connection     = None
_started           = False


# ── Public read API ──────────────────────────────────────────────────────────────────────────────────────

def is_quote_connected() -> bool:
    """Return True if the quote WebSocket is currently connected."""
    return _connected


def get_quote(ticker: str) -> dict | None:
    """
    Return the latest bid/ask quote dict for a ticker, or None if not yet received.

    Keys: bid, ask, spread, spread_pct, mid, bid_size, ask_size, timestamp
    """
    with lock:
        q = _quotes.get(ticker)
        return dict(q) if q else None


def get_spread_pct(ticker: str) -> float:
    """
    Return the current instantaneous spread percentage for a ticker.
    Returns 0.0 (fail-open) if no quote has been received yet.
    """
    with lock:
        q = _quotes.get(ticker)
        return q["spread_pct"] if q else 0.0


def get_avg_spread_pct(ticker: str) -> float:
    """
    Return the rolling average spread% over the last SPREAD_HISTORY_LEN quotes.
    More stable than instantaneous spread for threshold decisions.
    Returns 0.0 if no history yet.
    """
    with lock:
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
    """Return spread snapshot for all tracked tickers."""
    with lock:
        return {
            ticker: {
                "spread_pct": q["spread_pct"],
                "mid":        q["mid"],
                "bid":        q["bid"],
                "ask":        q["ask"],
            }
            for ticker, q in _quotes.items()
        }


# ── Quote update handler ────────────────────────────────────────────────────────────────────────────

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

    with lock:
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


# ── Dynamic subscription ─────────────────────────────────────────────────────────────────────────────────

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
        logger.info(f"[QUOTE] +{len(chunk)} tickers subscribed: {preview}")


def subscribe_quote_tickers(tickers: list):
    """
    Subscribe additional tickers to the quote feed (thread-safe).
    Call from scanner after premarket watchlist is built.
    """
    global _all_tickers
    with _sub_lock:
        new = [t for t in tickers if t not in _all_tickers]
        if new:
            _all_tickers.extend(new)

    if not new:
        return

    if _event_loop is None or _ws_connection is None:
        logger.info(
            f"[QUOTE] subscribe_quote_tickers: WS not ready — "
            f"{len(new)} ticker(s) queued for next connect"
        )
        return

    try:
        asyncio.run_coroutine_threadsafe(
            _do_subscribe(_ws_connection, new), _event_loop
        )
    except Exception as e:
        logger.info(f"[QUOTE] subscribe_quote_tickers error: {e}")


# ── Server message handler ─────────────────────────────────────────────────────────────────────────

def _handle_server_msg(msg: dict, consecutive_500s: list) -> str:
    """
    Handle EODHD server status messages received inside the WS message loop.

    Returns an action string:
        'ok'           — 200 auth, continue normally
        'count_500'    — 500 error, caller should increment counter + maybe hard-backoff
        'fatal'        — non-200/non-500 (e.g. 401/403) — stop retrying
        'ignore'       — informational, no action needed
    """
    code = msg.get("status_code") or msg.get("status")
    text = msg.get("message", "")

    if code == 200:
        logger.info(f"[QUOTE] Server msg: {msg}")
        return "ok"

    if code == 500:
        count = consecutive_500s[0] + 1
        consecutive_500s[0] = count
        # Log first occurrence and every 10th after that to suppress spam
        if count == 1:
            logger.warning(
                f"[QUOTE] \u26a0\ufe0f  Server 500 (#{count}): {text} — will back off after "
                f"{SERVER_500_BACKOFF_THRESHOLD} consecutive errors"
            )
        elif count % 10 == 0:
            logger.info(f"[QUOTE] \u26a0\ufe0f  Server 500 (#{count}, suppressed repeats): {text}")
        return "count_500"

    # Any other non-200 code (401 Unauthorized, 403 Forbidden, 429 rate-limit, etc.)
    logger.warning(
        f"[QUOTE] \U0001f6ab Server returned status {code}: {text} — "
        f"quote feed disabled (check EODHD us-quote entitlement)"
    )
    return "fatal"


# ── WebSocket coroutine ──────────────────────────────────────────────────────────────────────────────────────────

async def _ws_run():
    """
    Quote WebSocket coroutine. Runs in a dedicated asyncio event loop thread.

    Reconnect strategy:
      Normal disconnect → exponential backoff: min(2^attempt, 60s), resets on clean connect.
      500 flood (>= SERVER_500_BACKOFF_THRESHOLD consecutive) → exponential hard backoff:
        min(SERVER_500_HARD_BACKOFF_BASE * 2^(attempt-1), SERVER_500_HARD_BACKOFF_MAX)
        i.e. 300s → 600s → 1200s → … capped at 3600s.
      Fatal auth error (401/403) → stops retrying entirely.

    FIX v4 changes vs v3:
      - hard_backoff_attempt counter moved OUTSIDE the TCP connect block.
        Previously it lived inside `async with websockets.connect()` and was
        reset to 0 on every TCP connect, so the 300→600→1200 ladder never
        accumulated during EODHD application-layer 500 storms (TCP accepts
        the connection fine, but immediately returns 500 status messages).
      - hard_backoff_attempt now only resets to 0 on a confirmed 200 auth
        message from EODHD — the only real signal that the server is healthy.

    FIX v3 changes vs v2:
      - Hard backoff is now exponential (300 * 2^(attempt-1), max 3600s) instead of
        a flat 300s. This prevents the reconnect storm where the flat timeout expired
        and attempt reset to 1, causing the feed to hammer EODHD every 5 minutes
        during a prolonged outage.

    FIX v2 changes vs v1:
      - _handle_server_msg() deduplicates 500 log spam (log 1st + every 10th).
      - consecutive_500s counter tracked per-connection; triggers hard backoff
        when threshold is hit instead of immediately reconnecting.
      - Fatal non-200/non-500 codes (401/403) disable the feed permanently.
      - attempt counter incremented on 500-triggered hard backoff.

    BUG-WQF-1/2 fix (DATA-4 audit):
      - bid/ask parsed with explicit `is not None` checks so a 0.0 price from
        the primary field name is not silently discarded.
    """
    global _connected, _ws_connection, _subscribed

    url                  = f"{QUOTE_WS_BASE_URL}?api_token={config.EODHD_API_KEY}"
    reconnect_attempt    = 0   # normal TCP reconnect backoff counter
    hard_backoff_attempt = 0   # 500-flood backoff counter — persists across TCP connects
                               # only resets on confirmed 200 auth from EODHD

    while True:
        try:
            logger.info(
                f"[QUOTE] Connecting -> {QUOTE_WS_BASE_URL}"
                + (f" (attempt {reconnect_attempt + 1})" if reconnect_attempt > 0 else "")
            )

            async with websockets.connect(
                url, ping_interval=20, ping_timeout=10, close_timeout=5
            ) as ws:
                _ws_connection     = ws
                reconnect_attempt  = 0  # clean TCP connect — reset normal backoff only
                # NOTE: hard_backoff_attempt is intentionally NOT reset here.
                # It only resets on a confirmed 200 auth message below.

                with _sub_lock:
                    _subscribed.clear()

                # Allow EODHD auth handshake to complete before sending subscribe.
                # Without this, subscribe messages race ahead of auth and trigger
                # 422 'Symbols limit reached' errors.
                await asyncio.sleep(0.5)

                with _sub_lock:
                    master = list(_all_tickers)
                await _do_subscribe(ws, master)

                _connected = True
                logger.info(
                    f"[QUOTE] Live | {len(_subscribed)} tickers | "
                    f"spread gate: {MAX_SPREAD_PCT:.2f}% max"
                )

                # Per-connection 500 counter — reset to [0] on each new connection
                consecutive_500s       = [0]
                hard_backoff_triggered = False

                async for raw in ws:
                    try:
                        msg = json.loads(raw)

                        if "status_code" in msg or "status" in msg:
                            action = _handle_server_msg(msg, consecutive_500s)

                            if action == "fatal":
                                # Auth/entitlement failure — no point retrying
                                _connected     = False
                                _ws_connection = None
                                logger.warning(
                                    "[QUOTE] Feed permanently disabled — "
                                    "verify EODHD us-quote WebSocket entitlement."
                                )
                                return  # exits _ws_run entirely

                            if action == "count_500":
                                if consecutive_500s[0] >= SERVER_500_BACKOFF_THRESHOLD:
                                    hard_backoff_triggered = True
                                    break
                            elif action == "ok":
                                # Confirmed 200 auth — server is healthy, reset both counters
                                consecutive_500s[0]  = 0
                                hard_backoff_attempt = 0
                            else:
                                consecutive_500s[0] = 0

                            continue

                        # Reset 500 counter on any valid quote tick
                        consecutive_500s[0] = 0

                        # Quote tick — handle both known EODHD field name variants:
                        #   ask: "a" or "ab"   |   bid: "b" or "bb"
                        #
                        # BUG-WQF-1/2: use explicit `is not None` checks so that a
                        # legitimate 0.0 price from the primary field is never
                        # discarded by Python's falsy `or` short-circuit evaluation.
                        ticker   = msg.get("s", "")
                        _ask_a   = msg.get("a")
                        ask      = _ask_a if _ask_a is not None else msg.get("ab")
                        _bid_b   = msg.get("b")
                        bid      = _bid_b if _bid_b is not None else msg.get("bb")
                        ask_size = int(msg.get("av", 0))
                        bid_size = int(msg.get("bv", 0))
                        ts_ms    = msg.get("t")

                        if ticker and bid is not None and ask is not None and ts_ms:
                            _on_quote(ticker, float(bid), float(ask),
                                      bid_size, ask_size, int(ts_ms))

                    except Exception as exc:
                        logger.info(f"[QUOTE] Tick error: {exc}")

                _connected     = False
                _ws_connection = None

                if hard_backoff_triggered:
                    hard_backoff_attempt += 1
                    backoff = min(
                        SERVER_500_HARD_BACKOFF_BASE * (2 ** (hard_backoff_attempt - 1)),
                        SERVER_500_HARD_BACKOFF_MAX
                    )
                    logger.warning(
                        f"[QUOTE] \U0001f534 {consecutive_500s[0]} consecutive 500s — "
                        f"hard backoff {backoff}s before retry (attempt {hard_backoff_attempt})"
                    )
                    await asyncio.sleep(backoff)

        except Exception as exc:
            _connected     = False
            _ws_connection = None

            delay              = min(2 ** reconnect_attempt, RECONNECT_DELAY_MAX)
            reconnect_attempt += 1
            logger.info(
                f"[QUOTE] Disconnected ({exc}) — reconnecting in {delay}s "
                f"(attempt {reconnect_attempt})"
            )
            await asyncio.sleep(delay)


# ── Public API ─────────────────────────────────────────────────────────────────────────────────────────

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
        logger.warning(
            "[QUOTE] WARNING: 'websockets' package missing — "
            "install with: pip install 'websockets>=12.0'"
        )
        return

    if _started:
        subscribe_quote_tickers(tickers)
        logger.info(f"[QUOTE] Already running — merged {len(tickers)} tickers into active session")
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
    logger.info(
        f"[QUOTE] Feed initializing | {len(tickers)} seed tickers | "
        f"spread gate: {MAX_SPREAD_PCT:.2f}% max"
    )


# ── Module self-test ────────────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("QUOTE FEED - Connection Test")
    logger.info("=" * 60)

    test_tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
    start_quote_feed(test_tickers)

    logger.info(f"\nMonitoring spreads for: {test_tickers}")
    logger.info(f"Max spread threshold:   {MAX_SPREAD_PCT:.2f}%")
    logger.info("\nPress Ctrl+C to stop\n")

    try:
        while True:
            time.sleep(5)
            logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Spread snapshot:")

            if not is_quote_connected():
                logger.info("  Waiting for connection...")
                continue

            for ticker in test_tickers:
                q = get_quote(ticker)
                if q:
                    ok, spread = is_spread_acceptable(ticker)
                    avg        = get_avg_spread_pct(ticker)
                    status     = "\u2705 OK" if ok else "\U0001f6ab WIDE"
                    logger.info(
                        f"  {ticker:6s}  bid={q['bid']:.2f}  ask={q['ask']:.2f}  "
                        f"spread={q['spread_pct']:.3f}%  avg={avg:.3f}%  {status}"
                    )
                else:
                    logger.info(f"  {ticker:6s}  waiting for quote...")

    except KeyboardInterrupt:
        logger.info("\n[QUOTE] Test stopped")
        summary = get_spread_summary()
        if summary:
            logger.info("\nFinal spread snapshot:")
            for ticker, data in sorted(summary.items()):
                logger.info(
                    f"  {ticker:6s}  {data['spread_pct']:.3f}%  "
                    f"mid={data['mid']:.2f}"
                )
