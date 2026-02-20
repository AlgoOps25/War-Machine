"""
BOS + FVG Engine — 0DTE Intraday Signal Detection
Break of Structure → Fair Value Gap → Entry/Exit for same-session 0DTE options
"""
from datetime import datetime, time
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────
# CONSTANTS — 0DTE SPECIFIC
# ─────────────────────────────────────────────────────────────

LOOKBACK_SWING   = 10     # bars to identify swing highs/lows
FVG_MIN_PCT      = 0.001  # 0.1% minimum FVG size
HARD_CLOSE_TIME  = time(15, 45)  # No new entries after this
FORCE_CLOSE_TIME = time(15, 55)  # All positions force-closed by this
MIN_BARS_SESSION = 20     # Need at least 20 bars before scanning


# ─────────────────────────────────────────────────────────────
# TIME FILTERS
# ─────────────────────────────────────────────────────────────

def _bar_time(bar: Dict):
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def is_valid_entry_time(bar: Dict) -> bool:
    """No new entries before 9:40 AM or after 3:45 PM ET."""
    bt = _bar_time(bar)
    if bt is None:
        return False
    return time(9, 40) <= bt <= HARD_CLOSE_TIME


def is_force_close_time(bar: Dict) -> bool:
    """Force close all 0DTE positions at 3:55 PM ET."""
    bt = _bar_time(bar)
    if bt is None:
        return False
    return bt >= FORCE_CLOSE_TIME


# ─────────────────────────────────────────────────────────────
# STRUCTURE DETECTION — Swing Highs / Swing Lows
# ─────────────────────────────────────────────────────────────

def find_swing_points(bars: List[Dict], lookback: int = LOOKBACK_SWING) -> Dict:
    """
    Find the most recent significant swing high and swing low.
    A valid swing high: bar[i].high is the highest in a window of
    `lookback` bars on each side.
    """
    half = lookback // 2
    swing_high = swing_high_idx = None
    swing_low  = swing_low_idx  = None

    # Search from most recent backwards so we get the latest swing
    search_range = range(len(bars) - 1 - half, half, -1)

    for i in search_range:
        window = bars[i - half: i + half + 1]
        bar    = bars[i]

        if bar["high"] >= max(b["high"] for b in window):
            if swing_high is None:
                swing_high     = bar["high"]
                swing_high_idx = i

        if bar["low"] <= min(b["low"] for b in window):
            if swing_low is None:
                swing_low     = bar["low"]
                swing_low_idx = i

        # Stop once we have both
        if swing_high is not None and swing_low is not None:
            break

    return {
        "swing_high":     swing_high,
        "swing_high_idx": swing_high_idx,
        "swing_low":      swing_low,
        "swing_low_idx":  swing_low_idx
    }


# ─────────────────────────────────────────────────────────────
# BOS DETECTION
# ─────────────────────────────────────────────────────────────

def detect_bos(bars: List[Dict]) -> Optional[Dict]:
    """
    Detect a Break of Structure on the most recent bar.

    BULL BOS: latest close > prior swing high  (market breaking up)
    BEAR BOS: latest close < prior swing low   (market breaking down)

    Uses bars[:-1] to build structure so the latest bar is the trigger.
    """
    if len(bars) < LOOKBACK_SWING * 2 + 1:
        return None

    # Build structure WITHOUT the latest bar
    structure  = find_swing_points(bars[:-1])
    latest_bar = bars[-1]

    swing_high = structure["swing_high"]
    swing_low  = structure["swing_low"]

    if swing_high and latest_bar["close"] > swing_high:
        strength = (latest_bar["close"] - swing_high) / swing_high
        print(f"[BOS] BULL — broke ${swing_high:.2f} | "
              f"close=${latest_bar['close']:.2f} | strength={strength*100:.3f}%")
        return {
            "direction":   "bull",
            "bos_price":   swing_high,
            "break_price": latest_bar["close"],
            "bos_bar":     latest_bar,
            "bos_idx":     len(bars) - 1,
            "strength":    strength
        }

    if swing_low and latest_bar["close"] < swing_low:
        strength = (swing_low - latest_bar["close"]) / swing_low
        print(f"[BOS] BEAR — broke ${swing_low:.2f} | "
              f"close=${latest_bar['close']:.2f} | strength={strength*100:.3f}%")
        return {
            "direction":   "bear",
            "bos_price":   swing_low,
            "break_price": latest_bar["close"],
            "bos_bar":     latest_bar,
            "bos_idx":     len(bars) - 1,
            "strength":    strength
        }

    return None


# ─────────────────────────────────────────────────────────────
# FVG DETECTION — After BOS
# ─────────────────────────────────────────────────────────────

def find_fvg_after_bos(bars: List[Dict], bos_idx: int,
                        direction: str) -> Optional[Dict]:
    """
    Scan bars around the BOS for the nearest valid FVG.
    Looks back 5 bars before the BOS and forward to end of bars.

    FVG = 3-candle pattern:
      Bull: c0.high < c2.low  (gap above c0, below c2)
      Bear: c0.low  > c2.high (gap below c0, above c2)

    Entry will be triggered when price retraces INTO this gap.
    """
    search_start = max(0, bos_idx - 5)
    search_bars  = bars[search_start:]

    for i in range(2, len(search_bars)):
        c0 = search_bars[i - 2]
        c2 = search_bars[i]

        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= FVG_MIN_PCT:
                print(f"[FVG] BULL gap ${c0['high']:.2f} — ${c2['low']:.2f} "
                      f"({gap / c0['high'] * 100:.3f}%)")
                return {
                    "fvg_high":     c2["low"],
                    "fvg_low":      c0["high"],
                    "fvg_mid":      (c2["low"] + c0["high"]) / 2,
                    "fvg_size":     gap,
                    "fvg_size_pct": round(gap / c0["high"] * 100, 3),
                    "fvg_bar_idx":  search_start + i,
                    "direction":    "bull"
                }

        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= FVG_MIN_PCT:
                print(f"[FVG] BEAR gap ${c2['high']:.2f} — ${c0['low']:.2f} "
                      f"({gap / c0['low'] * 100:.3f}%)")
                return {
                    "fvg_high":     c0["low"],
                    "fvg_low":      c2["high"],
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
    Entry price = FVG midpoint (50% retracement of the gap).

    Bull: bar dips into [fvg_low, fvg_high] but closes above fvg_low
          → buy the retest of the gap
    Bear: bar rallies into [fvg_low, fvg_high] but closes below fvg_high
          → sell the retest of the gap
    """
    direction = fvg["direction"]
    fvg_low   = fvg["fvg_low"]
    fvg_high  = fvg["fvg_high"]
    fvg_mid   = fvg["fvg_mid"]

    if direction == "bull":
        if current_bar["low"] <= fvg_high and current_bar["close"] >= fvg_low:
            return {
                "entry_price": fvg_mid,
                "entry_type":  "FVG_FILL_BULL",
                "entry_bar":   current_bar,
                "fvg_low":     fvg_low,
                "fvg_high":    fvg_high
            }

    elif direction == "bear":
        if current_bar["high"] >= fvg_low and current_bar["close"] <= fvg_high:
            return {
                "entry_price": fvg_mid,
                "entry_type":  "FVG_FILL_BEAR",
                "entry_bar":   current_bar,
                "fvg_low":     fvg_low,
                "fvg_high":    fvg_high
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
    0DTE-specific stop and target logic.

    Stop:  Just beyond the FVG extreme + 20% of FVG size as buffer
           (tight — never ATR-based for 0DTE)
    T1:    1.5R — close 50% of position here immediately
    T2:    2.5R — runner, hard-closed at 3:55 PM regardless

    Risk/Reward:
      T1 = 1.5:1  (scale out fast)
      T2 = 2.5:1  (let the runner breathe)
    """
    fvg_size = fvg["fvg_high"] - fvg["fvg_low"]
    buffer   = fvg_size * 0.20

    if direction == "bull":
        stop = fvg["fvg_low"] - buffer
        risk = entry_price - stop
        t1   = entry_price + risk * 1.5
        t2   = entry_price + risk * 2.5
    else:
        stop = fvg["fvg_high"] + buffer
        risk = stop - entry_price
        t1   = entry_price - risk * 1.5
        t2   = entry_price - risk * 2.5

    print(f"[0DTE LEVELS] Entry: ${entry_price:.2f} | "
          f"Stop: ${stop:.2f} | Risk: ${risk:.2f} | "
          f"T1: ${t1:.2f} (1.5R) | T2: ${t2:.2f} (2.5R)")

    return {
        "stop": round(stop, 2),
        "t1":   round(t1,   2),
        "t2":   round(t2,   2),
        "risk": round(risk, 2),
        "rr_t1": 1.5,
        "rr_t2": 2.5
    }


# ─────────────────────────────────────────────────────────────
# MAIN SCAN FUNCTION — called from sniper.py
# ─────────────────────────────────────────────────────────────

def scan_bos_fvg(ticker: str, bars: List[Dict]) -> Optional[Dict]:
    """
    Full BOS + FVG scan on the latest session bars.
    Returns a complete signal dict or None.
    Called every 1-minute scan cycle from sniper.process_ticker().

    Pipeline:
      1. Time filter (9:40 AM – 3:45 PM ET only)
      2. BOS detection on latest bar vs prior swing structure
      3. FVG detection around the BOS
      4. Entry trigger: price retracing INTO the FVG
      5. 0DTE stops and targets
    """
    if len(bars) < MIN_BARS_SESSION:
        return None

    latest_bar = bars[-1]

    # Time filter
    if not is_valid_entry_time(latest_bar):
        return None

    # Step 1: BOS
    bos = detect_bos(bars)
    if not bos:
        return None

    # Step 2: FVG near the BOS
    fvg = find_fvg_after_bos(bars, bos["bos_idx"], bos["direction"])
    if not fvg:
        print(f"[{ticker}] BOS confirmed but no FVG found")
        return None

    # Step 3: Entry trigger
    entry_trigger = check_fvg_entry(latest_bar, fvg)
    if not entry_trigger:
        return None

    # Step 4: 0DTE levels
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
        "entry_type":   entry_trigger["entry_type"],
        "signal_time":  latest_bar["datetime"],
        "dte":          0
    }
