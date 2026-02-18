"""
Sniper Module - CFW6 Strategy Implementation
Opening Range Breakout + Fair Value Gap + Candle Confirmation
"""

import traceback
from datetime import datetime, time
from scanner_helpers import get_recent_bars_from_memory
import incremental_fetch
from discord_helpers import send_options_signal_alert
from options_filter import get_options_recommendation
from targets import compute_stop_and_targets
from learning_policy import compute_confidence
from candle_confirmation import wait_for_confirmation

# Global dictionary to track armed signals
armed_signals = {}


def compute_opening_range_from_bars(bars: list) -> tuple:
    """
    Compute Opening Range high/low from 9:30-9:40 AM EST.
    Returns (or_high, or_low) or (None, None) if not formed yet.
    """
    or_bars = []
    for bar in bars:
        bar_time = bar.get("datetime")
        if bar_time:
            if time(9, 30) <= bar_time.time() < time(9, 40):
                or_bars.append(bar)
    
    if len(or_bars) < 2:
        return None, None
    
    or_high = max(b["high"] for b in or_bars)
    or_low = min(b["low"] for b in or_bars)
    
    return or_high, or_low


def compute_premarket_range(bars: list) -> tuple:
    """
    Compute pre-market high/low from 4:00-9:30 AM EST.
    Returns (pm_high, pm_low) or (None, None) if not available.
    """
    pm_bars = []
    for bar in bars:
        bar_time = bar.get("datetime")
        if bar_time:
            if time(4, 0) <= bar_time.time() < time(9, 30):
                pm_bars.append(bar)
    
    if len(pm_bars) < 10:
        return None, None
    
    pm_high = max(b["high"] for b in pm_bars)
    pm_low = min(b["low"] for b in pm_bars)
    
    return pm_high, pm_low


def detect_breakout_after_or(bars: list, or_high: float, or_low: float) -> tuple:
    """
    Detect breakout of Opening Range.
    Returns (direction, breakout_idx) or (None, None).
    """
    import config
    
    for i, bar in enumerate(bars):
        bar_time = bar.get("datetime")
        if not bar_time or bar_time.time() < time(9, 40):
            continue
        
        # Bull breakout
        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BULL at idx {i}, price ${bar['close']:.2f}")
            return "bull", i
        
        # Bear breakout
        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BEAR at idx {i}, price ${bar['close']:.2f}")
            return "bear", i
    
    return None, None


def detect_fvg_after_break(bars: list, breakout_idx: int, direction: str) -> tuple:
    """
    Detect Fair Value Gap after breakout.
    Returns (fvg_low, fvg_high) or (None, None).
    """
    import config
    
    for i in range(breakout_idx + 3, len(bars)):
        if i < 2:
            continue
        
        c0 = bars[i - 2]
        c1 = bars[i - 1]
        c2 = bars[i]
        
        if direction == "bull":
            gap_size = c2["low"] - c0["high"]
            if gap_size > 0:
                gap_pct = gap_size / c0["high"]
                if gap_pct >= config.FVG_MIN_SIZE_PCT:
                    fvg_low = c0["high"]
                    fvg_high = c2["low"]
                    print(f"[FVG] BULL FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                    return fvg_low, fvg_high
        
        elif direction == "bear":
            gap_size = c0["low"] - c2["high"]
            if gap_size > 0:
                gap_pct = gap_size / c0["low"]
                if gap_pct >= config.FVG_MIN_SIZE_PCT:
                    fvg_low = c2["high"]
                    fvg_high = c0["low"]
                    print(f"[FVG] BEAR FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                    return fvg_low, fvg_high
    
    return None, None

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high, 
               entry_price, stop_price, t1, t2, confidence, grade, options_rec=None):
    """
    Arms a ticker after signal confirmation and sends Discord alert.
    """
    print(f"✅ {ticker} ARMED: {direction.upper()} | Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"   Zone: ${zone_low:.2f}-${zone_high:.2f} | OR: ${or_low:.2f}-${or_high:.2f}")
    print(f"   Targets: T1=${t1:.2f} T2=${t2:.2f} | Confidence: {confidence*100:.1f}% ({grade})")
    
    # Send Discord alert with options data
    send_options_signal_alert(
        ticker=ticker,
        direction=direction,
        entry=entry_price,
        stop=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        timeframe="5m",
        options_data=options_rec
    )
    
    # Store armed signal for tracking
    armed_signals[ticker] = {
        "direction": direction,
        "entry": entry_price,
        "stop": stop_price,
        "t1": t1,
        "t2": t2,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "or_low": or_low,
        "or_high": or_high,
        "armed_time": datetime.now().isoformat(),
        "confidence": confidence,
        "grade": grade,
        "options": options_rec
    }
    
    print(f"[ARMED] {ticker} added to tracking")


def process_ticker(ticker: str):
    """
    Main CFW6 strategy processor:
    1. Get bars from memory DB
    2. Compute Opening Range (9:30-9:40)
    3. Detect breakout
    4. Detect FVG after breakout
    5. Wait for CFW6 confirmation candle
    6. Calculate stops/targets
    7. Get options recommendation
    8. ARM and send alert
    """
    try:
        # STEP 1 — update memory DB
        incremental_fetch.update_ticker(ticker)

        # STEP 2 — use memory DB
        bars = get_recent_bars_from_memory(ticker, limit=300)

        if not bars or len(bars) < 50:
            print(f"{ticker}: not enough memory bars")
            return

        print(f"📊 {ticker} using MEMORY bars: {len(bars)}")

        # STEP 3 — OPENING RANGE (9:30-9:40)
        or_high, or_low = compute_opening_range_from_bars(bars)
        if or_high is None:
            print(f"{ticker}: OR not formed yet")
            return

        print(f"[OR] {ticker} OR: High=${or_high:.2f} Low=${or_low:.2f}")

        # STEP 4 — BREAKOUT DETECTION
        direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
        if not direction:
            # No breakout yet
            return

        print(f"[BREAKOUT] {ticker} {direction.upper()} breakout detected")

        # STEP 5 — FVG DETECTION (after breakout)
        fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
        if not fvg_low:
            print(f"{ticker}: Breakout occurred but no FVG formed yet")
            return

        zone_low, zone_high = min(fvg_low, fvg_high), max(fvg_low, fvg_high)
        print(f"[FVG] {ticker} FVG zone: ${zone_low:.2f} - ${zone_high:.2f}")

        # STEP 6 — CFW6 CONFIRMATION CANDLE
        found, entry_price, grade, confirm_idx = wait_for_confirmation(
            bars, direction, (zone_low, zone_high), breakout_idx + 1
        )
        
        if not found:
            print(f"{ticker}: FVG formed but no valid CFW6 confirmation candle")
            return
        
        print(f"✅ {ticker}: {grade} CFW6 confirmation at ${entry_price:.2f}")

        # STEP 7 — CALCULATE STOPS & TARGETS
        stop_price, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price
        )

        # STEP 8 — OPTIONS RECOMMENDATION
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1
        )

        # STEP 9 — COMPUTE CONFIDENCE (with dark pool integration)
        confidence = compute_confidence(grade, "5m", ticker)

        # STEP 10 — ARM TICKER & SEND ALERT
        arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
                   entry_price, stop_price, t1, t2, confidence, grade, options_rec)

    except Exception as e:
        print(f"process_ticker error for {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    """Simple discord message sender (for backwards compatibility)"""
    try:
        import requests
        import config
        payload = {"content": message}
        requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")