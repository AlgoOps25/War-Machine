# app/filters/market_regime_context.py
# SPY + QQQ Market Regime Context — 5-minute bars, EMA 9/21/50
#
# DESIGN (Phase 1.25):
#   - Computes EMA 9/21/50 for BOTH SPY and QQQ on 5m compressed bars
#   - Combines into a single conviction label + score_adj
#   - score_adj is a PASSIVE confidence nudge only (no hard blocks)
#   - Hard is_long_allowed / is_short_allowed removed — regime never kills signals
#   - send_regime_discord() posts a visual update to a dedicated Discord channel
#     every REGIME_DISCORD_INTERVAL_MINUTES (default 5 min)
#   - Cache TTL: 90s
#
# Conviction labels (SPY + QQQ combined):
#   STRONG_BULL  (+15) — both full bull stack, slopes rising
#   BULL         (+8)  — both above EMA21 > EMA50
#   NEUTRAL_BULL (+3)  — mixed but leaning bull
#   NEUTRAL       (0)  — no clear edge
#   NEUTRAL_BEAR (-3)  — mixed but leaning bear
#   BEAR         (-8)  — both below EMA50
#   STRONG_BEAR  (-15) — both full bear stack, slopes falling
#   UNKNOWN       (0)  — insufficient bars
#
# FIXED (Phase 1.26):
#   _get_5m_bars() now has a 3-tier fallback:
#     1. data_manager memory (WS bars) — fastest, zero-cost
#     2. data_manager.get_today_session_bars() — DB intraday rows
#     3. EODHD intraday REST API — guarantees bars even if SPY/QQQ were
#        never subscribed to the WS (e.g. mid-session redeploys before
#        Phase 1.26 scanner.py is deployed). Result is cached per-symbol
#        for EODHD_CACHE_SECONDS to avoid hammering the API.

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

_CACHE_TTL_SECONDS               = 90
REGIME_DISCORD_INTERVAL_MINUTES  = 5
EODHD_CACHE_SECONDS              = 60   # how long to reuse an EODHD-fetched bar list

_regime_cache: dict      = {}
_last_discord_post: datetime = datetime.min.replace(tzinfo=_ET)
_eodhd_bar_cache: dict   = {}  # symbol -> {"bars": [...], "ts": datetime}

EMOJI_MAP = {
    "STRONG_BULL":  "🟢🟢",
    "BULL":         "🟢",
    "NEUTRAL_BULL": "🟡",
    "NEUTRAL":      "⚪",
    "NEUTRAL_BEAR": "🟠",
    "BEAR":         "🔴",
    "STRONG_BEAR":  "🔴🔴",
    "UNKNOWN":      "❓",
}


# ── EMA helpers ──────────────────────────────────────────────────────────────────────
def _compute_ema(bars: list, period: int) -> float:
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < period:
        return 0.0
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 4)


def _get_slope_bull(bars: list, period: int) -> bool:
    if len(bars) < period + 1:
        return True
    current  = _compute_ema(bars,      period)
    previous = _compute_ema(bars[:-1], period)
    return current >= previous


def _fetch_eodhd_intraday(symbol: str, interval: str = "5m", limit: int = 60) -> list:
    """
    Fetch today’s intraday bars from EODHD as a last-resort fallback.
    Returns a list of {open, high, low, close, volume} dicts, or [].
    Result is cached in _eodhd_bar_cache for EODHD_CACHE_SECONDS.
    """
    global _eodhd_bar_cache
    now = datetime.now(_ET)

    cached = _eodhd_bar_cache.get(symbol)
    if cached:
        age = (now - cached["ts"]).total_seconds()
        if age < EODHD_CACHE_SECONDS and cached["bars"]:
            return cached["bars"]

    api_key = os.getenv("EODHD_API_KEY", "")
    if not api_key:
        return []

    try:
        import requests
        today_str = now.strftime("%Y-%m-%d")
        url = (
            f"https://eodhd.com/api/intraday/{symbol}.US"
            f"?api_token={api_key}&interval={interval}"
            f"&from={today_str}&fmt=json"
        )
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list) or not data:
            return []
        bars = [
            {
                "open":   float(row.get("open",   0)),
                "high":   float(row.get("high",   0)),
                "low":    float(row.get("low",    0)),
                "close":  float(row.get("close",  0)),
                "volume": int(row.get("volume",   0)),
            }
            for row in data
            if row.get("close")
        ]
        bars = bars[-limit:]
        _eodhd_bar_cache[symbol] = {"bars": bars, "ts": now}
        print(f"[REGIME] ✅ EODHD fallback: {symbol} {len(bars)} bars fetched")
        return bars
    except Exception as e:
        print(f"[REGIME] EODHD fallback error for {symbol}: {e}")
        return []


def _get_5m_bars(symbol: str):
    """
    Return 5-minute compressed bars for symbol.

    Tier 1: data_manager memory (WS feed) — zero latency
    Tier 2: data_manager.get_today_session_bars() — DB intraday rows
    Tier 3: EODHD intraday REST API — fallback when SPY/QQQ not in WS
    """
    from app.data.data_manager import data_manager

    # Tier 1: WS memory bars
    try:
        bars_1m = data_manager.get_bars_from_memory(symbol, limit=390)
        if bars_1m and len(bars_1m) >= 10:
            try:
                from app.mtf.mtf_compression import compress_to_timeframe
                bars_5m = compress_to_timeframe(bars_1m, "5m")
                if bars_5m and len(bars_5m) >= 10:
                    return bars_5m
            except Exception:
                pass
            return bars_1m  # return 1m if compression fails
    except Exception:
        pass

    # Tier 2: DB session bars
    try:
        bars_1m = data_manager.get_today_session_bars(symbol)
        if bars_1m and len(bars_1m) >= 10:
            try:
                from app.mtf.mtf_compression import compress_to_timeframe
                bars_5m = compress_to_timeframe(bars_1m, "5m")
                if bars_5m and len(bars_5m) >= 10:
                    return bars_5m
            except Exception:
                pass
            return bars_1m
    except Exception:
        pass

    # Tier 3: EODHD REST fallback
    bars = _fetch_eodhd_intraday(symbol, interval="5m", limit=60)
    return bars


# ── Per-instrument regime score ──────────────────────────────────────────────────
def _score_instrument(symbol: str) -> dict:
    """
    Returns a dict with keys:
        label, score, ema9, ema21, ema50, slope_bull, price, reason
    score range: -15 to +15
    """
    bars = _get_5m_bars(symbol)
    if len(bars) < 10:
        return {
            "label": "UNKNOWN", "score": 0,
            "ema9": 0.0, "ema21": 0.0, "ema50": 0.0,
            "slope_bull": True, "price": 0.0,
            "reason": f"{symbol} bars unavailable"
        }

    ema9       = _compute_ema(bars, 9)
    ema21      = _compute_ema(bars, 21)
    ema50      = _compute_ema(bars, 50)
    slope_bull = _get_slope_bull(bars, 50)
    price      = bars[-1]["close"]

    if ema9 == 0.0 or ema21 == 0.0 or ema50 == 0.0:
        return {
            "label": "UNKNOWN", "score": 0,
            "ema9": ema9, "ema21": ema21, "ema50": ema50,
            "slope_bull": slope_bull, "price": price,
            "reason": f"{symbol} insufficient bars for all EMAs"
        }

    if price > ema9 > ema21 > ema50 and slope_bull:
        label, score = "STRONG_BULL", 15
        reason = f"{symbol} full bull stack slope↑"
    elif price > ema21 > ema50:
        label, score = "BULL", 8
        reason = f"{symbol} P>{ema21:.2f}>E50{ema50:.2f}"
    elif price > ema50 and ema9 <= ema21:
        label, score = "NEUTRAL_BULL", 3
        reason = f"{symbol} above E50 but E9≤E21 — cautious"
    elif price < ema9 < ema21 < ema50 and not slope_bull:
        label, score = "STRONG_BEAR", -15
        reason = f"{symbol} full bear stack slope↓"
    elif price < ema50:
        label, score = "BEAR", -8
        reason = f"{symbol} below E50{ema50:.2f}"
    else:
        label, score = "NEUTRAL", 0
        reason = f"{symbol} indeterminate"

    return {
        "label": label, "score": score,
        "ema9": ema9, "ema21": ema21, "ema50": ema50,
        "slope_bull": slope_bull, "price": price, "reason": reason
    }


# ── Combined conviction label ───────────────────────────────────────────────────
def _combine(spy: dict, qqq: dict) -> tuple:
    """
    Average SPY + QQQ scores → single conviction label + score_adj.
    Returns (label: str, score_adj: int, reason: str)
    """
    if spy["label"] == "UNKNOWN" and qqq["label"] == "UNKNOWN":
        return "UNKNOWN", 0, "Both SPY and QQQ data unavailable"

    # If one is unknown, use the other at half weight
    spy_score = spy["score"] if spy["label"] != "UNKNOWN" else 0
    qqq_score = qqq["score"] if qqq["label"] != "UNKNOWN" else 0
    avg = (spy_score + qqq_score) / 2.0

    if avg >= 12:
        label, score_adj = "STRONG_BULL", 15
    elif avg >= 5:
        label, score_adj = "BULL", 8
    elif avg >= 1:
        label, score_adj = "NEUTRAL_BULL", 3
    elif avg <= -12:
        label, score_adj = "STRONG_BEAR", -15
    elif avg <= -5:
        label, score_adj = "BEAR", -8
    elif avg <= -1:
        label, score_adj = "NEUTRAL_BEAR", -3
    else:
        label, score_adj = "NEUTRAL", 0

    # Agreement boosts conviction description
    if spy["label"] == qqq["label"]:
        agreement = "SPY+QQQ agree"
    else:
        agreement = f"SPY={spy['label']} QQQ={qqq['label']}"

    reason = f"{agreement} | avg_score={avg:+.1f}"
    return label, score_adj, reason


# ── Public API ──────────────────────────────────────────────────────────────────────
def get_market_regime(force_refresh: bool = False) -> dict:
    """
    Returns the combined SPY+QQQ regime dict (cached 90s).

    Keys:
        label (str), score_adj (int), reason (str),
        spy (dict), qqq (dict), ts (datetime)

    score_adj is a PASSIVE confidence nudge — it does NOT block signals.
    """
    global _regime_cache
    now = datetime.now(_ET)

    if not force_refresh and _regime_cache:
        age = (now - _regime_cache.get("ts", now)).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            return _regime_cache

    try:
        spy = _score_instrument("SPY")
        qqq = _score_instrument("QQQ")
        label, score_adj, reason = _combine(spy, qqq)

        _regime_cache = {
            "label":     label,
            "score_adj": score_adj,
            "reason":    reason,
            "spy":       spy,
            "qqq":       qqq,
            "ts":        now,
        }
    except Exception as e:
        _regime_cache = {
            "label": "UNKNOWN", "score_adj": 0,
            "reason": f"Regime compute error: {e}",
            "spy": {}, "qqq": {}, "ts": now,
        }

    return _regime_cache


def print_market_regime(regime: dict, ticker: str = ""):
    """Single structured log line — printed once per cycle in process_ticker."""
    label     = regime.get("label", "UNKNOWN")
    score_adj = regime.get("score_adj", 0)
    reason    = regime.get("reason", "")
    spy       = regime.get("spy", {})
    qqq       = regime.get("qqq", {})
    emoji     = EMOJI_MAP.get(label, "❓")
    adj_str   = f"+{score_adj}" if score_adj >= 0 else str(score_adj)
    prefix    = f"[{ticker}] " if ticker else ""

    spy_line = (
        f"SPY P={spy.get('price', 0):.2f} "
        f"E9={spy.get('ema9', 0):.2f} E21={spy.get('ema21', 0):.2f} E50={spy.get('ema50', 0):.2f} "
        f"{'\u2191' if spy.get('slope_bull') else '\u2193'}"
    ) if spy else "SPY N/A"

    qqq_line = (
        f"QQQ P={qqq.get('price', 0):.2f} "
        f"E9={qqq.get('ema9', 0):.2f} E21={qqq.get('ema21', 0):.2f} E50={qqq.get('ema50', 0):.2f} "
        f"{'\u2191' if qqq.get('slope_bull') else '\u2193'}"
    ) if qqq else "QQQ N/A"

    print(
        f"{prefix}{emoji} REGIME [{label}] adj={adj_str} | "
        f"{spy_line} | {qqq_line} | {reason}"
    )


def send_regime_discord(regime: dict = None, force: bool = False):
    """
    Posts a visual regime update to REGIME_WEBHOOK_URL.
    Rate-limited to REGIME_DISCORD_INTERVAL_MINUTES to avoid spam.
    Call this once per scan cycle from scanner.py — completely non-blocking
    (catches all exceptions internally).
    """
    global _last_discord_post

    webhook_url = os.getenv("REGIME_WEBHOOK_URL", "")
    if not webhook_url:
        return  # channel not configured — silently skip

    now = datetime.now(_ET)
    minutes_since = (now - _last_discord_post).total_seconds() / 60
    if not force and minutes_since < REGIME_DISCORD_INTERVAL_MINUTES:
        return

    try:
        if regime is None:
            regime = get_market_regime()

        label     = regime.get("label", "UNKNOWN")
        score_adj = regime.get("score_adj", 0)
        reason    = regime.get("reason", "")
        spy       = regime.get("spy", {})
        qqq       = regime.get("qqq", {})
        emoji     = EMOJI_MAP.get(label, "❓")
        adj_str   = f"+{score_adj}" if score_adj >= 0 else str(score_adj)
        ts_str    = now.strftime("%I:%M %p ET")

        # Conviction bar (visual)
        bar_steps  = 10
        filled     = int(round((score_adj + 15) / 30 * bar_steps))
        filled     = max(0, min(bar_steps, filled))
        conv_bar   = "█" * filled + "░" * (bar_steps - filled)

        def _fmt(d: dict, sym: str) -> str:
            if not d or d.get("label") == "UNKNOWN":
                return f"**{sym}** — no data"
            lbl   = d.get("label", "?")
            p     = d.get("price", 0)
            e9    = d.get("ema9",  0)
            e21   = d.get("ema21", 0)
            e50   = d.get("ema50", 0)
            slope = "↑" if d.get("slope_bull") else "↓"
            em    = EMOJI_MAP.get(lbl, "❓")
            return (
                f"{em} **{sym}** `{lbl}` | "
                f"P={p:.2f}  E9={e9:.2f}  E21={e21:.2f}  E50={e50:.2f}  {slope}"
            )

        msg = (
            f"## {emoji} Market Regime — `{label}` ({adj_str})\n"
            f"`[{conv_bar}]` conviction\n\n"
            f"{_fmt(spy, 'SPY')}\n"
            f"{_fmt(qqq, 'QQQ')}\n\n"
            f"📋 {reason}\n"
            f"🕐 {ts_str} | passive nudge only — no signals blocked"
        )

        import requests
        requests.post(webhook_url, json={"content": msg}, timeout=5)
        _last_discord_post = now

    except Exception:
        pass  # never crash the scan loop over a Discord post
