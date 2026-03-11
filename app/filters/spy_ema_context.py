# app/filters/spy_ema_context.py
# SPY EMA Regime Context — 5-minute bars, 3-layer EMA system (9/21/50)
# Computed ONCE per scan cycle and cached for TTL seconds.
# Provides: label (STRONG_BULL / BULL / NEUTRAL_BULL / NEUTRAL / BEAR / STRONG_BEAR)
#            score_adj (int, applied to final_confidence in _run_signal_pipeline)
#            slope_bull (bool) — EMA50 slope direction
#            ema9, ema21, ema50, price (float)
#
# Integration: imported by app/core/sniper.py
# Cache TTL: 90s — covers one full scan cycle without redundant recomputes per ticker

from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# ── Module-level cache ───────────────────────────────────────────────────────
_spy_regime_cache: dict = {}
_CACHE_TTL_SECONDS = 90  # stale after 90s


# ── EMA computation ──────────────────────────────────────────────────────────
def _compute_ema(bars: list, period: int) -> float:
    """Standard EMA over bar close prices. Returns 0.0 if insufficient bars."""
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < period:
        return 0.0
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period  # seed SMA
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 4)


# ── Regime labelling ─────────────────────────────────────────────────────────
def _label_regime(price: float, ema9: float, ema21: float, ema50: float,
                  slope_bull: bool) -> tuple:
    """
    Returns (label: str, score_adj: int, reason: str)

    score_adj range: -15 to +15
    Applied as a fractional confidence adjustment in sniper._run_signal_pipeline():
        bull signals: +abs(score_adj)/100
        bear signals: +abs(neg_score_adj)/100
    Hard blocks:
        BEAR / STRONG_BEAR  → longs suppressed
        STRONG_BULL         → shorts suppressed
    """
    if ema9 == 0.0 or ema21 == 0.0 or ema50 == 0.0:
        return "UNKNOWN", 0, "Insufficient SPY bars for EMA calculation"

    # STRONG_BULL: full stack aligned bullish + slope rising
    if price > ema9 > ema21 > ema50 and slope_bull:
        return (
            "STRONG_BULL", 15,
            f"SPY full bull stack (P={price:.2f} > E9={ema9:.2f} > E21={ema21:.2f} > E50={ema50:.2f}) slope↑"
        )

    # BULL: price above mid and macro EMA
    if price > ema21 > ema50:
        return (
            "BULL", 8,
            f"SPY bull (P={price:.2f} > E21={ema21:.2f} > E50={ema50:.2f})"
        )

    # NEUTRAL_BULL: above macro EMA but short-term weakening
    if price > ema50 and ema9 <= ema21:
        return (
            "NEUTRAL_BULL", 3,
            f"SPY above E50={ema50:.2f} but E9({ema9:.2f}) <= E21({ema21:.2f}) — cautious bull"
        )

    # STRONG_BEAR: full stack inverted + slope falling
    if price < ema9 < ema21 < ema50 and not slope_bull:
        return (
            "STRONG_BEAR", -15,
            f"SPY full bear stack (P={price:.2f} < E9={ema9:.2f} < E21={ema21:.2f} < E50={ema50:.2f}) slope↓"
        )

    # BEAR: price below macro EMA
    if price < ema50:
        return (
            "BEAR", -8,
            f"SPY below E50={ema50:.2f} — suppress longs"
        )

    return "NEUTRAL", 0, "SPY indeterminate regime"


# ── Public API ───────────────────────────────────────────────────────────────
def get_spy_ema_regime(force_refresh: bool = False) -> dict:
    """
    Returns the cached SPY EMA regime dict. Refreshes if stale or forced.
    SPY is a seed ticker subscribed at startup, so bars are always available.

    Return keys:
        label (str), score_adj (int), ema9 (float), ema21 (float),
        ema50 (float), slope_bull (bool), reason (str), price (float), ts (datetime)
    """
    global _spy_regime_cache

    now = datetime.now(_ET)

    # Return cache if still fresh
    if not force_refresh and _spy_regime_cache:
        age = (now - _spy_regime_cache.get("ts", now)).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            return _spy_regime_cache

    try:
        from app.data.data_manager import data_manager

        # Attempt 5-minute compression first
        bars_5m = None
        try:
            from app.mtf.mtf_compression import compress_to_timeframe
            bars_1m = data_manager.get_today_session_bars("SPY")
            if bars_1m and len(bars_1m) >= 10:
                bars_5m = compress_to_timeframe(bars_1m, "5m")
        except Exception:
            pass

        # Fallback: use 1-minute bars directly
        if not bars_5m or len(bars_5m) < 10:
            bars_5m = data_manager.get_today_session_bars("SPY")

        if not bars_5m or len(bars_5m) < 10:
            _spy_regime_cache = {
                "label": "UNKNOWN", "score_adj": 0,
                "ema9": 0.0, "ema21": 0.0, "ema50": 0.0,
                "slope_bull": True, "reason": "SPY bars unavailable",
                "price": 0.0, "ts": now
            }
            return _spy_regime_cache

        ema9  = _compute_ema(bars_5m, 9)
        ema21 = _compute_ema(bars_5m, 21)
        ema50 = _compute_ema(bars_5m, 50)

        # EMA50 slope: compare current to prior bar
        slope_bull = True
        if len(bars_5m) >= 51:
            ema50_prev = _compute_ema(bars_5m[:-1], 50)
            slope_bull = ema50 >= ema50_prev

        current_price = bars_5m[-1]["close"]
        label, score_adj, reason = _label_regime(current_price, ema9, ema21, ema50, slope_bull)

        _spy_regime_cache = {
            "label":      label,
            "score_adj":  score_adj,
            "ema9":       ema9,
            "ema21":      ema21,
            "ema50":      ema50,
            "slope_bull": slope_bull,
            "reason":     reason,
            "price":      current_price,
            "ts":         now
        }

    except Exception as e:
        _spy_regime_cache = {
            "label": "UNKNOWN", "score_adj": 0,
            "ema9": 0.0, "ema21": 0.0, "ema50": 0.0,
            "slope_bull": True,
            "reason": f"SPY EMA error: {e}",
            "price": 0.0, "ts": now
        }

    return _spy_regime_cache


def is_long_allowed(regime: dict) -> bool:
    """Hard-suppress longs in BEAR and STRONG_BEAR regimes."""
    return regime.get("label") not in ("BEAR", "STRONG_BEAR")


def is_short_allowed(regime: dict) -> bool:
    """Hard-suppress shorts in STRONG_BULL regime."""
    return regime.get("label") not in ("STRONG_BULL",)


def print_spy_regime(regime: dict, ticker: str = ""):
    """Structured log line for SPY EMA regime — printed per ticker in process_ticker."""
    EMOJI = {
        "STRONG_BULL":  "🟢🟢",
        "BULL":         "🟢",
        "NEUTRAL_BULL": "🟡",
        "NEUTRAL":      "⚪",
        "BEAR":         "🔴",
        "STRONG_BEAR":  "🔴🔴",
        "UNKNOWN":      "❓",
    }
    label     = regime.get("label", "UNKNOWN")
    score_adj = regime.get("score_adj", 0)
    reason    = regime.get("reason", "")
    ema9      = regime.get("ema9", 0.0)
    ema21     = regime.get("ema21", 0.0)
    ema50     = regime.get("ema50", 0.0)
    price     = regime.get("price", 0.0)
    slope     = "↑" if regime.get("slope_bull") else "↓"
    prefix    = f"[{ticker}] " if ticker else ""
    emoji     = EMOJI.get(label, "❓")
    adj_str   = f"+{score_adj}" if score_adj >= 0 else str(score_adj)

    print(
        f"{prefix}{emoji} SPY-EMA [{label}] adj={adj_str} | "
        f"P={price:.2f} E9={ema9:.2f} E21={ema21:.2f} E50={ema50:.2f} slope={slope} | "
        f"{reason}"
    )
