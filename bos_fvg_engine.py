"""
BOS + FVG Engine — 0DTE Intraday Signal Detection
Break of Structure → Fair Value Gap → Entry/Exit for same-session options
"""
from datetime import datetime, time, timedelta
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────
# CONSTANTS — 0DTE SPECIFIC
# ─────────────────────────────────────────────────────────────

LOOKBACK_SWING   = 10     # bars to look back for swing high/low
FVG_MIN_PCT      = 0.001  # 0.1% minimum FVG size (tighter for 0DTE) — default
HARD_CLOSE_TIME  = time(15, 45)  # No new entries after this
FORCE_CLOSE_TIME = time(15, 55)  # All positions closed by this time
MIN_BARS_SESSION = 5      # Need at least 5 bars before scanning


# ─────────────────────────────────────────────────────────────
# STRUCTURE DETECTION — Swing Highs / Swing Lows
# ─────────────────────────────────────────────────────────────

def find_swing_points(bars: List[Dict], lookback: int = LOOKBACK_SWING) -> Dict:
    """
    Identify the most recent swing high and swing low
    in the last `lookback` bars.
    A swing high = bar[i].high > all bars within ±lookback/2
    """
    if len(bars) < lookback * 2:
        return {"swing_high": None, "swing_high_idx": None,
                "swing_low":  None, "swing_low_idx":  None}

    recent = bars[-(lookback * 2):]

    swing_high = swing_high_idx = None
    swing_low  = swing_low_idx  = None

    for i in range(lookback // 2, len(recent) - lookback // 2):
        window = recent[i - lookback // 2 : i + lookback // 2 + 1]
        bar    = recent[i]

        if bar["high"] == max(b["high"] for b in window):
            if swing_high is None or bar["high"] > swing_high:
                swing_high     = bar["high"]
                swing_high_idx = i

        if bar["low"] == min(b["low"] for b in window):
            if swing_low is None or bar["low"] < swing_low:
                swing_low     = bar["low"]
                swing_low_idx = i

    return {
        "swing_high":     swing_high,
        "swing_high_idx": swing_high_idx,
        "swing_low":      swing_low,
        "swing_low_idx":  swing_low_idx
    }


# ─────────────────────────────────────────────────────────────
# BOS DETECTION — Break of Structure
# ─────────────────────────────────────────────────────────────

def detect_bos(bars: List[Dict]) -> Optional[Dict]:
    """
    Detect a Break of Structure on the most recent bar.

    BULL BOS: current close > previous swing high  → market breaking up
    BEAR BOS: current close < previous swing low   → market breaking down

    Returns BOS dict or None if no BOS on the latest bar.
    """
    if len(bars) < LOOKBACK_SWING * 2 + 1:
        return None

    # Compute structure on all bars EXCEPT the last one
    structure  = find_swing_points(bars[:-1])
    latest_bar = bars[-1]

    swing_high = structure["swing_high"]
    swing_low  = structure["swing_low"]

    if swing_high and latest_bar["close"] > swing_high:
        return {
            "direction":   "bull",
            "bos_price":   swing_high,
            "break_price": latest_bar["close"],
            "bos_bar":     latest_bar,
            "bos_idx":     len(bars) - 1,
            "strength":    (latest_bar["close"] - swing_high) / swing_high
        }

    if swing_low and latest_bar["close"] < swing_low:
        return {
            "direction":   "bear",
            "bos_price":   swing_low,
            "break_price": latest_bar["close"],
            "bos_bar":     latest_bar,
            "bos_idx":     len(bars) - 1,
            "strength":    (swing_low - latest_bar["close"]) / swing_low
        }

    return None


# ─────────────────────────────────────────────────────────────
# FVG DETECTION — After BOS
# ─────────────────────────────────────────────────────────────

def find_fvg_after_bos(bars: List[Dict], bos_idx: int,
                       direction: str,
                       min_pct: float = FVG_MIN_PCT) -> Optional[Dict]:
    """
    Scan forward from BOS for the first valid FVG.
    FVG = 3-candle pattern where candle[0].high < candle[2].low (bull)
                                or candle[0].low  > candle[2].high (bear)

    The FVG zone is the gap between candle[0] and candle[2].
    Entry is triggered when price RETRACES INTO the FVG zone.

    min_pct: minimum gap size as a fraction of price.
             Pass the adaptive threshold from trade_calculator
             .get_adaptive_fvg_threshold() for volatility-adjusted filtering.
             Defaults to FVG_MIN_PCT (0.1%).
    """
    search_start = max(0, bos_idx - 5)  # Look back a few bars too
    search_bars  = bars[search_start:]

    for i in range(2, len(search_bars)):
        c0 = search_bars[i - 2]
        c1 = search_bars[i - 1]  # middle candle (not used directly)
        c2 = search_bars[i]

        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= min_pct:
                return {
                    "fvg_high":     c2["low"],   # Top of gap
                    "fvg_low":      c0["high"],  # Bottom of gap
                    "fvg_mid":      (c2["low"] + c0["high"]) / 2,
                    "fvg_size":     gap,
                    "fvg_size_pct": round(gap / c0["high"] * 100, 3),
                    "fvg_bar_idx":  search_start + i,
                    "direction":    "bull"
                }

        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= min_pct:
                return {
                    "fvg_high":     c0["low"],   # Top of gap
                    "fvg_low":      c2["high"],  # Bottom of gap
                    "fvg_mid":      (c0["low"] + c2["high"]) / 2,
                    "fvg_size":     gap,
                    "fvg_size_pct": round(gap / c0["low"] * 100, 3),
                    "fvg_bar_idx":  search_start + i,
                    "direction":    "bear"
                }

    return None


# ─────────────────────────────────────────────────────────────
# ENTRY TRIGGER — Price Retrace Into FVG
# ─────────────────────────────────────────────────────────────

def check_fvg_entry(current_bar: Dict, fvg: Dict) -> Optional[Dict]:
    """
    Entry fires when the current bar trades INTO the FVG zone.
    Entry price = FVG midpoint (50% of the gap).

    Bull: price dips into [fvg_low, fvg_high] → buy the dip into gap
    Bear: price rallies into [fvg_low, fvg_high] → sell the rip into gap
    """
    direction = fvg["direction"]
    fvg_low   = fvg["fvg_low"]
    fvg_high  = fvg["fvg_high"]
    fvg_mid   = fvg["fvg_mid"]

    if direction == "bull":
        # Price must touch or enter the FVG from above
        if current_bar["low"] <= fvg_high and current_bar["close"] >= fvg_low:
            return {
                "entry_price": fvg_mid,
                "entry_type":  "FVG_FILL",
                "entry_bar":   current_bar,
                "fvg_low":     fvg_low,
                "fvg_high":    fvg_high,
            }

    elif direction == "bear":
        # Price must touch or enter the FVG from below
        if current_bar["high"] >= fvg_low and current_bar["close"] <= fvg_high:
            return {
                "entry_price": fvg_mid,
                "entry_type":  "FVG_FILL",
                "entry_bar":   current_bar,
                "fvg_low":     fvg_low,
                "fvg_high":    fvg_high,
            }

    return None


# ─────────────────────────────────────────────────────────────
# 0DTE STOPS & TARGETS
# ─────────────────────────────────────────────────────────────

def compute_0dte_stops_and_targets(
    entry_price: float,
    direction:   str,
    fvg:         Dict
) -> Dict:
    """
    0DTE-specific stop/target logic.

    Stop:  Just beyond the FVG extreme (not ATR-based — too wide for 0DTE)
    T1:    1.5R — take 50% off fast
    T2:    2.5R — runner, close by FORCE_CLOSE_TIME regardless

    Stop buffer = 20% of FVG size (tight but not a tick stop)
    """
    fvg_size = fvg["fvg_high"] - fvg["fvg_low"]
    buffer   = fvg_size * 0.20   # 20% of gap as buffer

    if direction == "bull":
        stop = fvg["fvg_low"] - buffer
        risk = entry_price - stop
        t1   = entry_price + risk * 1.5
        t2   = entry_price + risk * 2.5

    else:  # bear
        stop = fvg["fvg_high"] + buffer
        risk = stop - entry_price
        t1   = entry_price - risk * 1.5
        t2   = entry_price - risk * 2.5

    return {
        "stop":  round(stop, 2),
        "t1":    round(t1,   2),
        "t2":    round(t2,   2),
        "risk":  round(risk, 2),
        "rr_t1": 1.5,
        "rr_t2": 2.5
    }


# ─────────────────────────────────────────────────────────────
# TIME FILTERS — 0DTE RULES
# ─────────────────────────────────────────────────────────────

def is_valid_entry_time(bar: Dict) -> bool:
    """No new entries after 3:45 PM ET on 0DTE."""
    bt = bar.get("datetime")
    if bt is None:
        return False
    bar_time = bt.time() if hasattr(bt, "time") else bt
    return time(9, 40) <= bar_time <= HARD_CLOSE_TIME


def is_force_close_time(bar: Dict) -> bool:
    """Force close all positions at 3:55 PM ET."""
    bt = bar.get("datetime")
    if bt is None:
        return False
    bar_time = bt.time() if hasattr(bt, "time") else bt
    return bar_time >= FORCE_CLOSE_TIME


# ─────────────────────────────────────────────────────────────
# MAIN SIGNAL FUNCTION — called from sniper.py
# ─────────────────────────────────────────────────────────────

def scan_bos_fvg(ticker: str, bars: List[Dict],
                fvg_min_pct: float = FVG_MIN_PCT) -> Optional[Dict]:
    """
    Full BOS+FVG scan on latest bars.
    Returns a complete signal dict or None.

    fvg_min_pct: minimum FVG gap size as a fraction of price.
                 Pass the adaptive threshold from trade_calculator
                 .get_adaptive_fvg_threshold() for volatility-adjusted
                 filtering. Defaults to FVG_MIN_PCT (0.1%).

    Called every scan cycle from sniper.py process_ticker().
    """
    if len(bars) < MIN_BARS_SESSION:
        return None

    latest_bar = bars[-1]

    # Time filter — no new signals after 3:45 PM ET
    if not is_valid_entry_time(latest_bar):
        return None

    # ── Step 1: Detect BOS ───────────────────────────────────────
    bos = detect_bos(bars)
    if not bos:
        return None

    # ── Step 2: Find FVG after BOS (with adaptive threshold) ───────
    fvg = find_fvg_after_bos(bars, bos["bos_idx"], bos["direction"],
                              min_pct=fvg_min_pct)
    if not fvg:
        return None

    # ── Step 3: Check if current bar is entering the FVG ─────────
    entry_trigger = check_fvg_entry(latest_bar, fvg)
    if not entry_trigger:
        return None

    # ── Step 4: Compute 0DTE stops and targets ──────────────────
    levels = compute_0dte_stops_and_targets(
        entry_trigger["entry_price"], bos["direction"], fvg
    )

    return {
        "ticker":       ticker,
        "direction":    bos["direction"],
        "entry":        entry_trigger["entry_price"],
        "stop":         levels["stop"],
        "t1":           levels["t1"],
        "t2":           levels["t2"],
        "risk":         levels["risk"],
        "fvg_low":      fvg["fvg_low"],
        "fvg_high":     fvg["fvg_high"],
        "fvg_size_pct": fvg["fvg_size_pct"],
        "bos_price":    bos["bos_price"],
        "bos_strength": round(bos["strength"] * 100, 3),
        "entry_type":   "BOS+FVG",
        "signal_time":  latest_bar["datetime"],
        "dte":          0
    }
