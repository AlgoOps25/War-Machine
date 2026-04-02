"""
app/futures/tradier_futures_feed.py — Tradier REST feed for NQ/MNQ 1-min bars

Design notes:
  - Pure REST polling (no WebSocket) — Tradier's streaming API requires
    a separate futures data subscription; REST is sufficient for 1-min bars.
  - Symbol format: Tradier futures use the front-month contract notation,
    e.g. /MNQ:XCME or MNQ/M6:XCME.  We normalise at call time.
  - No dependency on EODHD, data_manager, or ws_feed. This feed is 100%
    self-contained so the existing EODHD-based equity pipeline is untouched.
  - Falls back to QQQ 1-min bars via EODHD when TRADIER_FUTURES_ENABLED=false
    or when Tradier returns a non-200. This lets you develop / backtest before
    your Tradier futures account is approved.

Environment variables consumed (all optional at import time):
    TRADIER_API_TOKEN          — sandbox or production bearer token
    TRADIER_BASE_URL           — defaults to https://api.tradier.com (production)
                                 set to https://sandbox.tradier.com for paper
    TRADIER_FUTURES_ENABLED    — "true" / "false" (default false until account confirmed)
    EODHD_API_KEY              — used for QQQ fallback only
"""
from __future__ import annotations
import os
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TRADIER_TOKEN           = os.getenv("TRADIER_API_TOKEN", "")
TRADIER_BASE_URL        = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_FUTURES_ENABLED = os.getenv("TRADIER_FUTURES_ENABLED", "false").lower() == "true"
EODHD_API_KEY           = os.getenv("EODHD_API_KEY", "")

ET = ZoneInfo("America/New_York")

# Tradier rate limit: 120 req/min on sandbox, 500 req/min on production.
# We poll at most once per 30s so we stay well under both limits.
_MIN_POLL_INTERVAL = 30  # seconds
_last_poll_time: dict[str, float] = {}

# In-memory bar cache — keyed by symbol.  Holds today's completed 1-min bars.
_bar_cache: dict[str, list[dict]] = {}


def _tradier_headers() -> dict:
    return {
        "Authorization": f"Bearer {TRADIER_TOKEN}",
        "Accept": "application/json",
    }


def _today_date_str() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def _rth_unix_window() -> tuple[int, int]:
    """
    Return (from_unix, to_unix) for today's RTH window (09:30–16:00 ET)
    as integer Unix epoch seconds.

    Using Unix integers instead of ISO strings avoids EODHD's 422
    'Unprocessable Content' rejection of timezone-naive ISO timestamps.
    """
    today = datetime.now(ET).date()
    from_dt = datetime(today.year, today.month, today.day, 9, 30, 0, tzinfo=ET)
    to_dt   = datetime(today.year, today.month, today.day, 16, 0, 0, tzinfo=ET)
    return int(from_dt.timestamp()), int(to_dt.timestamp())


def _is_rth_or_past_open() -> bool:
    """
    Return True if the current ET time is at or after 09:30.
    Prevents requesting a future window before the market opens, which
    would also produce a 422 from EODHD.
    """
    now_et = datetime.now(ET)
    return (now_et.hour, now_et.minute) >= (9, 30)


def _fetch_tradier_1m_bars(symbol: str) -> list[dict]:
    """
    Fetch 1-min OHLCV bars for today from Tradier.
    Returns list of dicts with keys: datetime, open, high, low, close, volume.
    Returns [] on any error.
    """
    if not TRADIER_TOKEN:
        logger.warning("[FUTURES-FEED] TRADIER_API_TOKEN not set")
        return []

    today = _today_date_str()
    url   = f"{TRADIER_BASE_URL}/v1/markets/timesales"
    params = {
        "symbol":   symbol,
        "interval": "1min",
        "start":    f"{today} 09:30",
        "end":      f"{today} 16:00",
        "session_filter": "open",
    }
    try:
        resp = requests.get(url, headers=_tradier_headers(), params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        series = data.get("series", {}) or {}
        if not series or series == "null":
            logger.info(f"[FUTURES-FEED] No bar data for {symbol} yet")
            return []
        raw = series.get("data", [])
        if isinstance(raw, dict):
            raw = [raw]  # single-bar edge case
        bars = []
        for item in raw:
            try:
                bars.append({
                    "datetime": datetime.fromisoformat(item["time"]).replace(tzinfo=timezone.utc),
                    "open":     float(item["open"]),
                    "high":     float(item["high"]),
                    "low":      float(item["low"]),
                    "close":    float(item["close"]),
                    "volume":   int(item.get("volume", 0)),
                })
            except (KeyError, ValueError) as parse_err:
                logger.debug(f"[FUTURES-FEED] Bar parse error: {parse_err} on {item}")
                continue
        logger.debug(f"[FUTURES-FEED] {symbol}: {len(bars)} bars fetched from Tradier")
        return bars
    except requests.exceptions.RequestException as e:
        logger.warning(f"[FUTURES-FEED] Tradier request failed for {symbol}: {e}")
        return []


def _fetch_eodhd_qqq_fallback() -> list[dict]:
    """
    Fallback: fetch QQQ 1-min bars from EODHD as a NQ proxy.
    Used when TRADIER_FUTURES_ENABLED=false or Tradier returns no data.

    FIX (2026-04-02): switched `from`/`to` params from ISO 8601 strings
    (e.g. "2026-04-02T09:30:00") to integer Unix epoch seconds.
    EODHD's intraday endpoint rejects timezone-naive ISO strings with
    HTTP 422 Unprocessable Content; Unix integers are accepted unconditionally.

    Also guards against calling before 09:30 ET to avoid requesting a
    future window (which also triggers 422).
    """
    if not EODHD_API_KEY:
        return []

    if not _is_rth_or_past_open():
        logger.debug("[FUTURES-FEED] QQQ fallback skipped — market not yet open (before 09:30 ET)")
        return []

    from_unix, to_unix = _rth_unix_window()
    url = (
        f"https://eodhd.com/api/intraday/QQQ.US"
        f"?interval=1m&from={from_unix}&to={to_unix}"
        f"&api_token={EODHD_API_KEY}&fmt=json"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        if not raw or not isinstance(raw, list):
            return []
        bars = []
        for item in raw:
            try:
                bars.append({
                    "datetime": datetime.fromtimestamp(item["timestamp"], tz=timezone.utc),
                    "open":     float(item["open"]),
                    "high":     float(item["high"]),
                    "low":      float(item["low"]),
                    "close":    float(item["close"]),
                    "volume":   int(item.get("volume", 0)),
                })
            except (KeyError, ValueError):
                continue
        logger.debug(f"[FUTURES-FEED] QQQ fallback: {len(bars)} bars")
        return bars
    except Exception as e:
        logger.warning(f"[FUTURES-FEED] EODHD QQQ fallback failed: {e}")
        return []


def get_todays_bars(symbol: str = "MNQ") -> list[dict]:
    """
    Public API — returns today's 1-min bars for the given futures symbol.
    Respects a 30s minimum poll interval to avoid hammering Tradier.
    Falls back to QQQ (EODHD) when Tradier futures not yet enabled.

    Args:
        symbol: e.g. "MNQ", "NQ"  (Tradier format without /)

    Returns:
        list of bar dicts sorted ascending by datetime.
        Empty list if no data available.
    """
    now = time.monotonic()
    last = _last_poll_time.get(symbol, 0)
    if now - last < _MIN_POLL_INTERVAL and symbol in _bar_cache:
        return _bar_cache[symbol]

    _last_poll_time[symbol] = now

    if TRADIER_FUTURES_ENABLED:
        bars = _fetch_tradier_1m_bars(symbol)
        if not bars:
            logger.info(f"[FUTURES-FEED] Tradier returned empty for {symbol} — trying QQQ fallback")
            bars = _fetch_eodhd_qqq_fallback()
    else:
        logger.debug("[FUTURES-FEED] TRADIER_FUTURES_ENABLED=false — using QQQ proxy")
        bars = _fetch_eodhd_qqq_fallback()

    bars.sort(key=lambda b: b["datetime"])
    _bar_cache[symbol] = bars
    return bars


def clear_bar_cache(symbol: Optional[str] = None) -> None:
    """Clear intraday cache at EOD reset. Called by futures_scanner_loop."""
    if symbol:
        _bar_cache.pop(symbol, None)
        _last_poll_time.pop(symbol, None)
    else:
        _bar_cache.clear()
        _last_poll_time.clear()
