"""
Sniper Module - CFW6 Strategy Implementation
INTEGRATED: Position Tracker, AI Learning, Confirmation Layers
"""

import traceback
from datetime import datetime, time
from scanner_helpers import get_recent_bars_from_memory
from discord_helpers import send_options_signal_alert
from options_filter import get_options_recommendation
from ai_learning import learning_engine

from cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from trade_calculator import compute_stop_and_targets, apply_confidence_decay, calculate_atr
from data_manager import data_manager, update_ticker, cleanup_old_bars
from position_manager import position_manager

# Global dictionary to track armed signals
armed_signals = {}


def compute_opening_range_from_bars(bars: list) -> tuple:
    """Compute Opening Range high/low from 9:30-9:40 AM EST."""
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
    """Compute pre-market high/low from 4:00-9:30 AM EST."""
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
    """Detect breakout of Opening Range."""
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
    """Detect Fair Value Gap after breakout."""
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
    """Arms a ticker after signal confirmation and sends Discord alert."""
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
    
    # Open position in tracker
    position_id = position_tracker.open_position(
        ticker=ticker,
        direction=direction,
        entry=entry_price,
        stop=stop_price,
        t1=t1,
        t2=t2,
        contracts=1,
        grade=grade,
        confidence=confidence
    )
    
    # Store armed signal
    armed_signals[ticker] = {
        "position_id": position_id,
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
    
    print(f"[ARMED] {ticker} position opened (ID: {position_id})")


def process_ticker(ticker: str):
    """
    Main CFW6 strategy processor with full integration:
    1. Get bars from memory DB
    2. Compute Opening Range (9:30-9:40)
    3. Detect breakout
    4. Detect FVG after breakout
    5. Wait for CFW6 confirmation candle
    6. Apply confirmation layers (VWAP, prev day, institutional, options flow)
    7. Calculate stops/targets
    8. Get options recommendation
    9. ARM and send alert
    10. Open position in tracker
    """
    try:
        # STEP 1 — Update memory DB
        incremental_fetch.update_ticker(ticker)

        # STEP 2 — Get bars from memory
        bars = get_recent_bars_from_memory(ticker, limit=300)

        if not bars or len(bars) < 50:
            return

        # STEP 3 — OPENING RANGE (9:30-9:40)
        or_high, or_low = compute_opening_range_from_bars(bars)
        if or_high is None:
            return

        # STEP 4 — BREAKOUT DETECTION
        direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
        if not direction:
            return

        # STEP 5 — FVG DETECTION
        fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
        if not fvg_low:
            return

        zone_low, zone_high = min(fvg_low, fvg_high), max(fvg_low, fvg_high)

        # STEP 6 — CFW6 CONFIRMATION CANDLE
        found, entry_price, base_grade, confirm_idx = wait_for_confirmation(
            bars, direction, (zone_low, zone_high), breakout_idx + 1
        )
        
        if not found or base_grade == "reject":
            return

        # STEP 7 — APPLY ADDITIONAL CONFIRMATION LAYERS
        confirmation_result = grade_signal_with_confirmations(
            ticker=ticker,
            direction=direction,
            bars=bars,
            current_price=entry_price,
            breakout_idx=breakout_idx,
            base_grade=base_grade
        )
        
        final_grade = confirmation_result["final_grade"]
        
        if final_grade == "reject":
            print(f"{ticker}: Signal rejected after confirmation layers")
            return

        # STEP 8 — CALCULATE STOPS & TARGETS
        stop_price, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price
        )

        # STEP 9 — OPTIONS RECOMMENDATION
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1
        )

        # STEP 10 — COMPUTE CONFIDENCE (with AI learning boost)
        base_confidence = compute_confidence(final_grade, "5m", ticker)
        
        # Apply AI learning ticker multiplier
        ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
        final_confidence = min(base_confidence * ticker_multiplier, 1.0)
        
        print(f"[CONFIDENCE] Base: {base_confidence:.2f} × Ticker: {ticker_multiplier:.2f} = {final_confidence:.2f}")

        # STEP 11 — ARM TICKER & OPEN POSITION
        arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
                   entry_price, stop_price, t1, t2, final_confidence, final_grade, options_rec)

    except Exception as e:
        print(f"process_ticker error for {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    """Simple discord message sender (for backwards compatibility)."""
    try:
        import requests
        import config
        payload = {"content": message}
        requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
