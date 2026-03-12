"""
BOS + FVG Engine — 0DTE Intraday Signal Detection
Break of Structure → Fair Value Gap → Entry/Exit for same-session options

UPDATED: Proper confirmation-wait-then-enter-next-bar logic
Based on Nitro Trades video transcript (lines 1238-1255)
"""
from datetime import datetime, time, timedelta
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from utils import config
FORCE_CLOSE_TIME = config.FORCE_CLOSE_TIME


ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────
# CONSTANTS — 0DTE SPECIFIC
# ─────────────────────────────────────────────────────────────

LOOKBACK_SWING   = 10     # bars to look back for swing high/low
FVG_MIN_PCT      = 0.001  # 0.1% minimum FVG size (tighter for 0DTE) — default
HARD_CLOSE_TIME  = time(15, 45)  # No new entries after this
MIN_BARS_SESSION = 5      # Need at least 5 bars before scanning


# ─────────────────────────────────────────────────────────────
# STRUCTURE DETECTION — Swing Highs / Swing Lows
# ─────────────────────────────────────────────────────────────

def find_swing_points(bars: List[Dict], lookback: int = LOOKBACK_SWING) -> Dict:
    """
    Identify the most recent swing high and swing low.
    Uses a 3x lookback window so early-session BOS bars that fall
    just outside a 2x window are still reachable.

    A swing high = bar[i].high > all bars within ±lookback/2
    A swing low  = bar[i].low  < all bars within ±lookback/2
    """
    if len(bars) < lookback * 2:
        return {"swing_high": None, "swing_high_idx": None,
                "swing_low":  None, "swing_low_idx":  None}

    # 3x lookback gives more scan positions than 2x, critical for
    # short early-session bar counts (20-30 bars).
    recent = bars[-(lookback * 3):]

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
# 3-TIER CANDLE CONFIRMATION — Nitro Trades Quality Model
# ─────────────────────────────────────────────────────────────

def classify_confirmation_candle(bar: Dict, fvg: Dict) -> Dict:
    """
    Classify the FVG retest candle into 3 quality tiers based on
    Nitro Trades confirmation logic:

    A+ (Grade 1): Strong directional candle with minimal/no wicks
                  - Bull: green candle, small lower wick (<20% of body)
                  - Bear: red candle, small upper wick (<20% of body)

    A  (Grade 2): Candle opens counter-trend, then flips back
                  - Bull: red initially → closes green with strong lower wick
                  - Bear: green initially → closes red with strong upper wick

    A- (Grade 3): Large rejection wick but doesn't fully flip
                  - Bull: red candle but large lower wick (>50% of range)
                  - Bear: red candle but large upper wick (>50% of range)

    Returns: {
        "grade":       "A+", "A", "A-", or None,
        "score":       100, 85, 70, or 0,
        "candle_type": description string
    }
    """
    direction = fvg["direction"]
    o = bar["open"]
    h = bar["high"]
    l = bar["low"]
    c = bar["close"]

    body = abs(c - o)
    total_range = h - l

    # Avoid division by zero
    if total_range == 0:
        return {"grade": None, "score": 0, "candle_type": "Doji (no range)"}

    if direction == "bull":
        lower_wick = o - l if c >= o else c - l
        upper_wick = h - c if c >= o else h - o
        is_green = c > o
        is_red = c < o

        # A+ : Strong green candle with minimal lower wick
        if is_green and (lower_wick / total_range) < 0.20:
            return {
                "grade": "A+",
                "score": 100,
                "candle_type": "Strong bull push (no wick)"
            }

        # A : Opens red initially, flips to green (strong lower wick)
        if is_green and (lower_wick / total_range) >= 0.30:
            return {
                "grade": "A",
                "score": 85,
                "candle_type": "Bull flip (red→green with wick)"
            }

        # A- : Red candle but large lower wick rejection
        if is_red and (lower_wick / total_range) >= 0.50:
            return {
                "grade": "A-",
                "score": 70,
                "candle_type": "Bull rejection wick (stayed red)"
            }

    elif direction == "bear":
        upper_wick = h - o if c <= o else h - c
        lower_wick = c - l if c <= o else o - l
        is_red = c < o
        is_green = c > o

        # A+ : Strong red candle with minimal upper wick
        if is_red and (upper_wick / total_range) < 0.20:
            return {
                "grade": "A+",
                "score": 100,
                "candle_type": "Strong bear push (no wick)"
            }

        # A : Opens green initially, flips to red (strong upper wick)
        if is_red and (upper_wick / total_range) >= 0.30:
            return {
                "grade": "A",
                "score": 85,
                "candle_type": "Bear flip (green→red with wick)"
            }

        # A- : Green candle but large upper wick rejection
        if is_green and (upper_wick / total_range) >= 0.50:
            return {
                "grade": "A-",
                "score": 70,
                "candle_type": "Bear rejection wick (stayed green)"
            }

    # No valid confirmation pattern
    return {
        "grade": None,
        "score": 0,
        "candle_type": "No confirmation"
    }


# ─────────────────────────────────────────────────────────────
# ENTRY TRIGGER — Proper Confirmation-Wait-Then-Enter Logic
# ─────────────────────────────────────────────────────────────

def check_fvg_entry(bars: List[Dict], fvg: Dict,
                   require_confirmation: bool = True) -> Optional[Dict]:
    """
    CRITICAL FIX: Proper confirmation-wait-then-enter-next-bar logic.

    Based on Nitro Trades video transcript (lines 1238-1255):
    1. Price retests FVG (pullback into the gap)
    2. Wait for that candle to CLOSE
    3. Grade the CLOSED candle (A+/A/A-)
    4. Enter on NEXT bar open if valid confirmation

    This checks the PREVIOUS bar (bars[-2]) for FVG retest + confirmation,
    then triggers entry on the CURRENT bar (bars[-1]) open.

    FVG BOUNCE CHECK (v1.23a fix):
    A valid retest requires the candle to have BOUNCED off the FVG —
    meaning it entered the gap AND closed back in the direction of the trade.
    - Bull: close must be >= fvg_mid (bounced back up)
    - Bear: close must be <= fvg_mid (bounced back down)
    A candle that blows straight through the FVG is a zone failure, not a
    confirmation, and must be rejected even if candle shape looks valid.

    If require_confirmation=True (default), only A+, A, or A- candles
    trigger entries. Set to False to allow all FVG touches (not recommended).

    Returns:
        Dict with entry details if confirmed, None otherwise
    """
    if len(bars) < 2:
        return None  # Need at least 2 bars (previous + current)

    # PREVIOUS bar = the one that just CLOSED (potential confirmation candle)
    prev_bar = bars[-2]
    # CURRENT bar = the one that's forming NOW (entry bar)
    current_bar = bars[-1]

    direction = fvg["direction"]
    fvg_low   = fvg["fvg_low"]
    fvg_high  = fvg["fvg_high"]
    fvg_mid   = fvg["fvg_mid"]

    # ── Step 1: Did the PREVIOUS bar retest AND bounce off the FVG? ───
    # Wick must have touched the FVG zone AND close must confirm bounce.
    # This rejects candles that blow through the FVG without bouncing.
    price_in_fvg = False

    if direction == "bull":
        # Wick touched into FVG from above AND closed back above fvg_mid
        if prev_bar["low"] <= fvg_high and prev_bar["close"] >= fvg_mid:
            price_in_fvg = True

    elif direction == "bear":
        # Wick touched into FVG from below AND closed back below fvg_mid
        if prev_bar["high"] >= fvg_low and prev_bar["close"] <= fvg_mid:
            price_in_fvg = True

    if not price_in_fvg:
        return None  # No valid FVG bounce — keep scanning

    # ── Step 2: Grade the CLOSED confirmation candle ─────────────────
    confirmation = classify_confirmation_candle(prev_bar, fvg)

    # Require valid confirmation grade (A+, A, or A-)
    if require_confirmation and confirmation["grade"] is None:
        return None  # Candle touched FVG but didn't confirm, keep waiting

    # ── Step 3: Trigger entry on NEXT bar open (current bar) ─────────
    # Entry price = current bar's OPEN (the bar AFTER confirmation closed)
    entry_price = current_bar["open"]

    return {
        "entry_price":      entry_price,
        "entry_type":       "FVG_FILL",
        "entry_bar":        current_bar,
        "confirmation_bar": prev_bar,  # The bar that confirmed
        "confirmed_at":     prev_bar["datetime"],  # When confirmation closed
        "entry_at":         current_bar["datetime"],  # When we entered
        "fvg_low":          fvg_low,
        "fvg_high":         fvg_high,
        "confirmation":     confirmation["grade"],
        "conf_score":       confirmation["score"],
        "candle_type":      confirmation["candle_type"]
    }


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
    """
    Allow BOS+FVG scanning from 9:30 AM ET.
    Candles are watched from 9:30; first signal fires at 9:40 bar open
    once confirmation-wait-then-enter-next-bar logic in check_fvg_entry()
    resolves on the 9:39 closed candle.
    No new entries after 3:45 PM ET.
    """
    bt = bar.get("datetime")
    if bt is None:
        return False
    bar_time = bt.time() if hasattr(bt, "time") else bt
    return time(9, 30) <= bar_time <= HARD_CLOSE_TIME


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
                fvg_min_pct: float = FVG_MIN_PCT,
                require_confirmation: bool = True) -> Optional[Dict]:
    """
    Full BOS+FVG scan with proper confirmation-wait-then-enter logic.

    CRITICAL UPDATE: Now checks PREVIOUS bar for FVG retest + confirmation,
    then enters on NEXT bar open. This fixes premature entries during pullback.

    fvg_min_pct: minimum FVG gap size as a fraction of price.
                 Pass the adaptive threshold from trade_calculator
                 .get_adaptive_fvg_threshold() for volatility-adjusted
                 filtering. Defaults to FVG_MIN_PCT (0.1%).

    require_confirmation: If True (default), only A+, A, or A- candles
                         trigger entries. Set False to allow all FVG touches.

    Returns:
        Complete signal dict with entry details, or None if no valid setup

    Called every scan cycle from sniper.py process_ticker().
    """
    if len(bars) < MIN_BARS_SESSION:
        return None

    latest_bar = bars[-1]

    # Time filter — watch candles from 9:30 AM; no new signals after 3:45 PM ET
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

    # ── Step 3: Check if PREVIOUS bar retested FVG + confirmed ────
    #    Then enter on CURRENT bar open
    entry_trigger = check_fvg_entry(bars, fvg,
                                    require_confirmation=require_confirmation)
    if not entry_trigger:
        return None  # Either no retest yet, or no valid confirmation

    # ── Step 4: Compute 0DTE stops and targets ──────────────────
    levels = compute_0dte_stops_and_targets(
        entry_trigger["entry_price"], bos["direction"], fvg
    )

    return {
        "ticker":          ticker,
        "direction":       bos["direction"],
        "bos_idx":         bos["bos_idx"],
        "entry":           entry_trigger["entry_price"],
        "stop":            levels["stop"],
        "t1":              levels["t1"],
        "t2":              levels["t2"],
        "risk":            levels["risk"],
        "fvg_low":         fvg["fvg_low"],
        "fvg_high":        fvg["fvg_high"],
        "fvg_size_pct":    fvg["fvg_size_pct"],
        "bos_price":       bos["bos_price"],
        "bos_strength":    round(bos["strength"] * 100, 3),
        "entry_type":      "BOS+FVG",
        "signal_time":     latest_bar["datetime"],
        "confirmed_at":    entry_trigger["confirmed_at"],
        "entry_at":        entry_trigger["entry_at"],
        "dte":             0,
        "confirmation":    entry_trigger["confirmation"],
        "conf_score":      entry_trigger["conf_score"],
        "candle_type":     entry_trigger["candle_type"]
    }
