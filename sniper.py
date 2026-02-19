#Sniper Module - CFW6 Strategy Implementation#
#INTEGRATED: Position Manager, AI Learning, Confirmation Layers#
import traceback
from datetime import datetime, time
from zoneinfo import ZoneInfo
from discord_helpers import send_options_signal_alert
from options_filter import get_options_recommendation
from ai_learning import learning_engine
from cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from trade_calculator import compute_stop_and_targets, apply_confidence_decay, calculate_atr
from data_manager import data_manager
from position_manager import position_manager
from learning_policy import compute_confidence
import config

# Global dictionary to track armed signals (reset at EOD by clear_armed_signals)
armed_signals = {}

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _now_et():
    return datetime.now(ZoneInfo("America/New_York"))

def _bar_time(bar):
    """Safely extract time from a bar's ET-naive datetime."""
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt

def log_proposed_trade(ticker, signal_type, direction, price, confidence, grade):
    """Log a proposed trade for win-rate tracking."""
    try:
        from db_connection import get_conn, ph
        conn = get_conn()
        cursor = conn.cursor()
        p = ph()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS proposed_trades (
                id SERIAL PRIMARY KEY,
                ticker TEXT,
                signal_type TEXT,
                direction TEXT,
                price REAL,
                confidence REAL,
                grade TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(f"""
            INSERT INTO proposed_trades (ticker, signal_type, direction, price, confidence, grade)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
        """, (ticker, signal_type, direction, price, confidence, grade))
        conn.commit()
        conn.close()
        print(f"[TRACKER] Logged proposed {direction} signal for {ticker}")
    except Exception as e:
        print(f"[TRACKER] Error logging proposed trade: {e}")

# ─────────────────────────────────────────────────────────────
# OPENING RANGE
# ─────────────────────────────────────────────────────────────

def compute_opening_range_from_bars(bars: list) -> tuple:
    """Compute Opening Range high/low from 9:30-9:40 AM ET."""
    or_bars = []
    for bar in bars:
        bt = _bar_time(bar)
        if bt and time(9, 30) <= bt < time(9, 40):
            or_bars.append(bar)

    if len(or_bars) < 2:
        return None, None

    or_high = max(b["high"] for b in or_bars)
    or_low  = min(b["low"]  for b in or_bars)
    return or_high, or_low

def compute_premarket_range(bars: list) -> tuple:
    """Compute pre-market high/low from 4:00-9:30 AM ET."""
    pm_bars = []
    for bar in bars:
        bt = _bar_time(bar)
        if bt and time(4, 0) <= bt < time(9, 30):
            pm_bars.append(bar)

    if len(pm_bars) < 10:
        return None, None

    pm_high = max(b["high"] for b in pm_bars)
    pm_low  = min(b["low"]  for b in pm_bars)
    return pm_high, pm_low

# ─────────────────────────────────────────────────────────────
# BREAKOUT & FVG DETECTION
# ─────────────────────────────────────────────────────────────

def detect_breakout_after_or(bars: list, or_high: float, or_low: float) -> tuple:
    """Detect breakout of Opening Range (only after 9:40 ET)."""
    for i, bar in enumerate(bars):
        bt = _bar_time(bar)
        if bt is None or bt < time(9, 40):
            continue

        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BULL at idx {i}, price ${bar['close']:.2f}")
            return "bull", i

        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            print(f"[BREAKOUT] BEAR at idx {i}, price ${bar['close']:.2f}")
            return "bear", i

    return None, None

def detect_fvg_after_break(bars: list, breakout_idx: int, direction: str) -> tuple:
    """Detect Fair Value Gap after breakout."""
    for i in range(breakout_idx + 3, len(bars)):
        if i < 2:
            continue
        c0 = bars[i-2]
        c1 = bars[i-1]  # noqa: F841
        c2 = bars[i]

        if direction == "bull":
            gap_size = c2["low"] - c0["high"]
            if gap_size > 0:
                gap_pct = gap_size / c0["high"]
                if gap_pct >= config.FVG_MIN_SIZE_PCT:
                    fvg_low  = c0["high"]
                    fvg_high = c2["low"]
                    print(f"[FVG] BULL FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                    return fvg_low, fvg_high

        elif direction == "bear":
            gap_size = c0["low"] - c2["high"]
            if gap_size > 0:
                gap_pct = gap_size / c0["low"]
                if gap_pct >= config.FVG_MIN_SIZE_PCT:
                    fvg_low  = c2["high"]
                    fvg_high = c0["low"]
                    print(f"[FVG] BEAR FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                    return fvg_low, fvg_high

    return None, None

# ─────────────────────────────────────────────────────────────
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade, options_rec=None):
    """Arms a ticker after signal confirmation and sends Discord alert."""
    print(f"\u2705 {ticker} ARMED: {direction.upper()} | Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"  Zone: ${zone_low:.2f}-${zone_high:.2f} | OR: ${or_low:.2f}-${or_high:.2f}")
    print(f"  Targets: T1=${t1:.2f} T2=${t2:.2f} | Confidence: {confidence*100:.1f}% ({grade})")

    log_proposed_trade(ticker, "CFW6", direction, entry_price, confidence, grade)

    send_options_signal_alert(
        ticker=ticker,
        direction=direction,
        entry=entry_price,
        stop=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        timeframe="5m",
        grade=grade,
        options_data=options_rec
    )

    position_id = position_manager.open_position(
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

    armed_signals[ticker] = {
        "position_id": position_id,
        "direction":   direction,
        "entry":       entry_price,
        "stop":        stop_price,
        "t1":          t1,
        "t2":          t2,
        "zone_low":    zone_low,
        "zone_high":   zone_high,
        "or_low":      or_low,
        "or_high":     or_high,
        "armed_time":  _now_et().isoformat(),
        "confidence":  confidence,
        "grade":       grade,
        "options":     options_rec
    }

    print(f"[ARMED] {ticker} position opened (ID: {position_id})")

def clear_armed_signals():
    """Reset armed signals dict at EOD."""
    armed_signals.clear()
    print("[ARMED] Cleared all armed signals for new trading day")

# ─────────────────────────────────────────────────────────────
# MAIN PROCESS TICKER
# ─────────────────────────────────────────────────────────────

def process_ticker(ticker: str):
    """
    Main CFW6 strategy processor:
    1. Guard: skip if already armed today
    2. Update memory DB via data_manager
    3. Get bars from memory, filter to TODAY only
    4. Compute Opening Range (9:30-9:40 ET)
    5. Detect ORB breakout
    6. Detect FVG after breakout
    7. CFW6 candle confirmation (A+/A/A-)
    8. Multi-factor confirmation layers
    9. Calculate stops & targets
    10. Get options recommendation
    11. Compute final confidence (AI + MTF boost)
    12. ARM ticker & open position
    """
    try:
        # STEP 1 — Re-arm guard: one signal per ticker per day
        if ticker in armed_signals:
            return

        # STEP 2 — Update memory DB
        data_manager.update_ticker(ticker)

        # STEP 3 — Get bars from memory (multi-day pool)
        bars = data_manager.get_bars_from_memory(ticker, limit=300)
        if not bars or len(bars) < 50:
            return

        # STEP 3b — Filter to TODAY only (prevents stale breakouts from prior sessions)
        today = _now_et().date()
        bars_today = [b for b in bars if b["datetime"].date() == today]
        if len(bars_today) < 20:
            print(f"[{ticker}] Only {len(bars_today)} bars today — skipping")
            return

        # STEP 4 — OPENING RANGE (9:30-9:40 ET)
        or_high, or_low = compute_opening_range_from_bars(bars_today)
        if or_high is None:
            return

        # STEP 5 — BREAKOUT DETECTION
        direction, breakout_idx = detect_breakout_after_or(bars_today, or_high, or_low)
        if not direction:
            return

        # STEP 6 — FVG DETECTION
        fvg_low, fvg_high = detect_fvg_after_break(bars_today, breakout_idx, direction)
        if not fvg_low:
            return
        zone_low  = min(fvg_low, fvg_high)
        zone_high = max(fvg_low, fvg_high)

        # STEP 7 — CFW6 CONFIRMATION CANDLE
        result = wait_for_confirmation(
            bars_today, direction, (zone_low, zone_high), breakout_idx + 1
        )
        found, entry_price, base_grade, confirm_idx, confirm_type = result
        if not found or base_grade == "reject":
            return

        # STEP 8 — MULTI-FACTOR CONFIRMATION LAYERS
        confirmation_result = grade_signal_with_confirmations(
            ticker=ticker,
            direction=direction,
            bars=bars_today,
            current_price=entry_price,
            breakout_idx=breakout_idx,
            base_grade=base_grade
        )
        final_grade = confirmation_result["final_grade"]
        if final_grade == "reject":
            print(f"{ticker}: Signal rejected after confirmation layers")
            return

        # STEP 9 — CALCULATE STOPS & TARGETS
        stop_price, t1, t2 = compute_stop_and_targets(
            bars_today, direction, or_high, or_low, entry_price
        )

        # STEP 10 — OPTIONS RECOMMENDATION
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1
        )

        # STEP 11 — COMPUTE CONFIDENCE (AI learning + MTF convergence boost)
        base_confidence   = compute_confidence(final_grade, "5m", ticker)
        ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)

        try:
            from timeframe_manager import calculate_mtf_convergence_boost
            mtf_boost = calculate_mtf_convergence_boost(ticker)
        except ImportError:
            mtf_boost = 0.0

        final_confidence = min((base_confidence * ticker_multiplier) + mtf_boost, 1.0)
        print(f"[CONFIDENCE] Base: {base_confidence:.2f} x Ticker: {ticker_multiplier:.2f} + MTF: {mtf_boost:.2f} = {final_confidence:.2f}")

        # STEP 12 — ARM TICKER & OPEN POSITION
        arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
                   entry_price, stop_price, t1, t2, final_confidence, final_grade, options_rec)

    except Exception as e:
        print(f"process_ticker error for {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    """Simple discord message sender (backward compatibility)."""
    try:
        import requests
        payload = {"content": message}
        requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
