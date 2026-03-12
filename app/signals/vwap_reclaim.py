# app/signals/vwap_reclaim.py
# D1: VWAP Reclaim Signal
# Detects when price loses VWAP then reclaims it with a confirming close.
# This is a standalone signal that feeds into _run_signal_pipeline via
# process_ticker as a third scan path (after OR and intraday BOS).
#
# Signal criteria:
#   1. At least one bar closed BELOW vwap (loss)
#   2. Current bar closes ABOVE vwap (reclaim)
#   3. Reclaim candle body >= RECLAIM_BODY_MIN_PCT
#   4. Volume on reclaim bar >= RECLAIM_RVOL_MIN * avg volume
#   5. Only valid between 9:45 AM – 3:00 PM ET

from datetime import time

RECLAIM_BODY_MIN_PCT  = 0.0010   # reclaim candle body >= 0.10%
RECLAIM_RVOL_MIN      = 1.2      # reclaim bar volume >= 1.2x avg
RECLAIM_LOOKBACK      = 10       # bars to look back for the VWAP loss
RECLAIM_AVG_VOL_BARS  = 20       # bars used to compute avg volume


def _compute_vwap(bars: list) -> list[float]:
    """Returns per-bar cumulative VWAP values."""
    vwaps = []
    cum_tpv = 0.0
    cum_vol = 0.0
    for bar in bars:
        tp = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        v  = bar.get("volume", 0)
        cum_tpv += tp * v
        cum_vol += v
        vwaps.append(cum_tpv / cum_vol if cum_vol > 0 else 0.0)
    return vwaps


def _avg_volume(bars: list, lookback: int) -> float:
    vols = [b.get("volume", 0) for b in bars[-lookback:]]
    return sum(vols) / len(vols) if vols else 1.0


def _bar_time(bar: dict):
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def detect_vwap_reclaim(bars: list) -> dict | None:
    """
    Scans bars for a VWAP reclaim signal.

    Returns dict with keys:
        direction, reclaim_bar_idx, vwap_at_reclaim,
        entry_price, signal_type
    or None.
    """
    if not bars or len(bars) < RECLAIM_LOOKBACK + 3:
        return None

    vwaps = _compute_vwap(bars)
    avg_vol = _avg_volume(bars, RECLAIM_AVG_VOL_BARS)

    # Only scan during valid session hours
    for i in range(len(bars) - 1, max(len(bars) - RECLAIM_LOOKBACK, 3) - 1, -1):
        bar     = bars[i]
        bt      = _bar_time(bar)
        if bt is None:
            continue
        if not (time(9, 45) <= bt <= time(15, 0)):
            continue

        vwap_now  = vwaps[i]
        if vwap_now == 0:
            continue

        body = abs(bar["close"] - bar["open"])
        body_pct = body / bar["open"] if bar["open"] > 0 else 0

        # ── Bull reclaim: prior bar below VWAP, current bar closes above ──
        if (bar["close"] > vwap_now
                and bars[i - 1]["close"] < vwaps[i - 1]
                and body_pct >= RECLAIM_BODY_MIN_PCT
                and bar.get("volume", 0) >= avg_vol * RECLAIM_RVOL_MIN):
            return {
                "direction":        "bull",
                "reclaim_bar_idx":  i,
                "vwap_at_reclaim":  vwap_now,
                "entry_price":      bar["close"],
                "signal_type":      "VWAP_RECLAIM",
            }

        # ── Bear reclaim: prior bar above VWAP, current bar closes below ──
        if (bar["close"] < vwap_now
                and bars[i - 1]["close"] > vwaps[i - 1]
                and body_pct >= RECLAIM_BODY_MIN_PCT
                and bar.get("volume", 0) >= avg_vol * RECLAIM_RVOL_MIN):
            return {
                "direction":        "bear",
                "reclaim_bar_idx":  i,
                "vwap_at_reclaim":  vwap_now,
                "entry_price":      bar["close"],
                "signal_type":      "VWAP_RECLAIM",
            }

    return None
