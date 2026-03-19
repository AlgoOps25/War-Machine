# app/data/intraday_atr.py
# Sprint 1 — 47.P6-2: Intraday ATR
#
# PURPOSE:
#   Replace the stale daily ATR (config.ATR_VALUE, a fixed constant) with a
#   true Wilder ATR computed on the current session's 1-minute bars.  This
#   makes breakout thresholds adaptive to today's actual volatility instead
#   of yesterday's close-to-close range.
#
# KEY FUNCTIONS:
#   compute_intraday_atr(bars, period=14) -> float
#       True Wilder ATR on session 1m bars.  Falls back to a high-low
#       range proxy if fewer than period+1 bars are available.
#
#   get_atr_for_breakout(bars, ticker="") -> (float, str)
#       Returns (atr_value, source_label) for use in dynamic_thresholds.
#       source_label is one of: "INTRADAY" | "DAILY_PROXY" | "FALLBACK"
#
# INTEGRATION (app/risk/dynamic_thresholds.py):
#   from app.data.intraday_atr import get_atr_for_breakout
#   atr, atr_source = get_atr_for_breakout(bars_session, ticker)
#   # Use atr instead of config.ATR_VALUE when computing OR breakout threshold
#
# FALLBACK CHAIN:
#   1. Wilder ATR on session 1m bars (period=14) — primary
#   2. Mean of (high - low) for available bars — if < period+1 bars
#   3. config.ATR_VALUE (daily constant) — if bars is empty or all zeros

import logging
logger = logging.getLogger(__name__)

DEFAULT_ATR_PERIOD = 14


def compute_intraday_atr(bars: list, period: int = DEFAULT_ATR_PERIOD) -> float:
    """
    Compute Wilder's ATR on 1-minute session bars.

    True Range for each bar:
        TR = max(high - low, |high - prev_close|, |low - prev_close|)
    Wilder smoothing:
        ATR_0 = mean(TR[0:period])
        ATR_n = (ATR_{n-1} * (period-1) + TR_n) / period

    Falls back to simple mean(high-low) if fewer than period+1 bars.
    Returns 0.0 on empty input.
    """
    if not bars:
        return 0.0

    closes = [b["close"] for b in bars]
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]

    # Fallback: not enough bars for Wilder ATR
    if len(bars) < period + 1:
        hl_ranges = [h - l for h, l in zip(highs, lows) if h > 0 and l > 0]
        if not hl_ranges:
            return 0.0
        return round(sum(hl_ranges) / len(hl_ranges), 4)

    # True Range series
    trs = [highs[0] - lows[0]]  # first bar: no prev close
    for i in range(1, len(bars)):
        prev_c = closes[i - 1]
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - prev_c),
            abs(lows[i]  - prev_c),
        )
        trs.append(tr)

    # Wilder smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return round(atr, 4)


def get_atr_for_breakout(bars: list, ticker: str = "") -> tuple:
    """
    Returns (atr_value: float, source_label: str).

    source_label:
        "INTRADAY"     — Wilder ATR on >= 15 session bars
        "DAILY_PROXY"  — mean(high-low) on < 15 bars
        "FALLBACK"     — config.ATR_VALUE (static daily constant)
    """
    try:
        if bars and len(bars) >= DEFAULT_ATR_PERIOD + 1:
            atr = compute_intraday_atr(bars, DEFAULT_ATR_PERIOD)
            if atr > 0:
                logger.info(f"[ATR] {ticker} INTRADAY ATR={atr:.4f} ({len(bars)} bars)")
                return atr, "INTRADAY"

        if bars and len(bars) > 0:
            atr = compute_intraday_atr(bars, DEFAULT_ATR_PERIOD)  # triggers hl_range fallback
            if atr > 0:
                logger.info(f"[ATR] {ticker} DAILY_PROXY ATR={atr:.4f} ({len(bars)} bars)")
                return atr, "DAILY_PROXY"
    except Exception as e:
        logger.info(f"[ATR] compute error for {ticker} (non-fatal): {e}")

    # Static fallback
    try:
        from utils import config
        fallback = getattr(config, "ATR_VALUE", 0.5)
    except Exception:
        fallback = 0.5
    logger.info(f"[ATR] {ticker} FALLBACK ATR={fallback} (no bars)")
    return fallback, "FALLBACK"
