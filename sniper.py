# Sniper Module - CFW6 Strategy Implementation
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers
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
            INSERT INTO proposed_trades
                (ticker, signal_type, direction, price, confidence, grade)
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
    or_bars = [
        b for b in bars
        if _bar_time(b) and time(9, 30) <= _bar_time(b) < time(9, 40)
    ]
    if len(or_bars) < 2:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)

def compute_premarket_range(bars: list) -> tuple:
    """Compute pre-market high/low from 4:00-9:30 AM ET."""
    pm_bars = [
        b for b in bars
        if _bar_time(b) and time(4, 0) <= _bar_time(b) < time(9, 30)
    ]
    if len(pm_bars) < 10:
        return None, None
    return max(b["high"] for b in pm_bars), min(b["low"] for b in pm_bars)

# ─────────────────────────────────────────────────────────────
# BREAKOUT & FVG DETECTION
# ─────────────────────────────────────────────────────────────

def detect_breakout_after_or(bars: list, or_high: float, or_low: float) -> tuple:
    """Detect breakout of Opening Range (only candles after 9:40 ET)."""
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
        c2 = bars[i]

        if direction == "bull":
            gap_size = c2["low"] - c0["high"]
            if gap_size > 0 and (gap_size / c0["high"]) >= config.FVG_MIN_SIZE_PCT:
                fvg_low, fvg_high = c0["high"], c2["low"]
                print(f"[FVG] BULL FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                return fvg_low, fvg_high

        elif direction == "bear":
            gap_size = c0["low"] - c2["high"]
            if gap_size > 0 and (gap_size / c0["low"]) >= config.FVG_MIN_SIZE_PCT:
                fvg_low, fvg_high = c2["high"], c0["low"]
                print(f"[FVG] BEAR FVG: ${fvg_low:.2f} - ${fvg_high:.2f}")
                return fvg_low, fvg_high

    return None, None

# ─────────────────────────────────────────────────────────────
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade, options_rec=None):
    """Arms a ticker after signal confirmation and sends Discord alert."""

    MIN_STOP_PCT  = 0.002
    min_stop_dist = entry_price * MIN_STOP_PCT
    actual_stop_dist = abs(entry_price - stop_price)
    if actual_stop_dist < min_stop_dist:
        print(f"[ARM] {ticker} stop distance ${actual_stop_dist:.3f} "
              f"below minimum ${min_stop_dist:.3f} — skipping")
        return

    print(f"{ticker} ARMED: {direction.upper()} | "
          f"Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"  Zone: ${zone_low:.2f}-${zone_high:.2f} | "
          f"OR: ${or_low:.2f}-${or_high:.2f}")
    print(f"  Targets: T1=${t1:.2f} T2=${t2:.2f} | "
          f"Confidence: {confidence*100:.1f}% ({grade})")

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
        zone_low=zone_low,
        zone_high=zone_high,
        or_low=or_low,
        or_high=or_high,
        entry_price=entry_price,
        stop_price=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        grade=grade,
        options_rec=options_rec
    )

    armed_signals[ticker] = {
        "position_id":   position_id,
        "direction":     direction,
        "zone_low":      zone_low,
        "zone_high":     zone_high,
        "or_low":        or_low,
        "or_high":       or_high,
        "entry_price":   entry_price,
        "stop_price":    stop_price,
        "t1":            t1,
        "t2":            t2,
        "confidence":    confidence,
        "grade":         grade,
        "options_rec":   options_rec
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
    Main CFW6 strategy processor.

    Data source: Postgres intraday_bars — today's ET session only.
    startup_backfill_today() (called once in scanner.py before the loop)
    guarantees 9:30-9:40 OR bars are present even after a midday restart.

    Rules:
      - Only today's real bars are used. No fallback to yesterday.
      - No synthetic OR. No made-up ranges.
      - If today's OR bars are missing, the ticker is skipped with a clear log.
      - Signals can be found at any point in the session (9:40 AM through close),
        not just at the open.
    """
    try:
        # STEP 1 — Re-arm guard: one signal per ticker per session
        if ticker in armed_signals:
            return

        # STEP 2 — Incremental fetch: pull only new bars since last stored bar.
        # Fast (~1-5 bars per call during market hours). Handles today catch-up
        # automatically if last_bar_time is from a prior day.
        data_manager.update_ticker(ticker)

        # STEP 3 — Load today's session bars from DB.
        # get_today_session_bars() queries strictly by today's ET date.
        # Returns [] if no bars exist — never returns yesterday's data.
        bars_session = data_manager.get_today_session_bars(ticker)

        if not bars_session:
            print(f"[{ticker}] No bars for today's session yet — skipping")
            return

        print(f"[{ticker}] Scanning TODAY {_now_et().date()} "
              f"({len(bars_session)} bars)")

        # Debug: confirm bar window covers the opening range
        t_first = _bar_time(bars_session[0])
        t_last  = _bar_time(bars_session[-1])
        print(f"[{ticker}] Bar window: {t_first} -> {t_last}")

        # STEP 4 — OPENING RANGE (9:30-9:40 ET)
        or_high, or_low = compute_opening_range_from_bars(bars_session)
        if or_high is None:
            or_count = sum(
                1 for b in bars_session
                if _bar_time(b) and time(9, 30) <= _bar_time(b) < time(9, 40)
            )
            print(f"[{ticker}] No OR: only {or_count} bars in 9:30-9:40 window "
                  f"(need >=2) — skipping, NOT falling back to yesterday")
            return
        print(f"[{ticker}] OR: low=${or_low:.2f} high=${or_high:.2f} "
              f"range=${or_high - or_low:.3f}")

        # STEP 5 — BREAKOUT DETECTION (first candle after 9:40 that closes
        # outside the OR — could happen at 9:41 or 1:30 PM, doesn't matter)
        direction, breakout_idx = detect_breakout_after_or(
            bars_session, or_high, or_low
        )
        if not direction:
            print(f"[{ticker}] No ORB breakout "
                  f"(threshold {config.ORB_BREAK_THRESHOLD*100:.2f}%)")
            return

        # STEP 6 — FVG DETECTION
        fvg_low, fvg_high = detect_fvg_after_break(
            bars_session, breakout_idx, direction
        )
        if not fvg_low:
            print(f"[{ticker}] No FVG after {direction.upper()} breakout "
                  f"(min size {config.FVG_MIN_SIZE_PCT*100:.2f}%)")
            return
        zone_low  = min(fvg_low, fvg_high)
        zone_high = max(fvg_low, fvg_high)

        # STEP 7 — CFW6 CONFIRMATION CANDLE
        result = wait_for_confirmation(
            bars_session, direction, (zone_low, zone_high), breakout_idx + 1
        )
        found, entry_price, base_grade, confirm_idx, confirm_type = result
        if not found or base_grade == "reject":
            print(f"[{ticker}] No confirmation candle "
                  f"(found={found}, grade={base_grade})")
            return

        # STEP 8 — MULTI-FACTOR CONFIRMATION LAYERS
        confirmation_result = grade_signal_with_confirmations(
            ticker=ticker,
            direction=direction,
            bars=bars_session,
            current_price=entry_price,
            breakout_idx=breakout_idx,
            base_grade=base_grade
        )
        final_grade = confirmation_result["final_grade"]
        if final_grade == "reject":
            print(f"[{ticker}] Signal rejected after confirmation layers "
                  f"(base={base_grade})")
            return

        # STEP 9 — CALCULATE STOPS & TARGETS
        stop_price, t1, t2 = compute_stop_and_targets(
            bars_session, direction, or_high, or_low, entry_price
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

        final_confidence = min(
            (base_confidence * ticker_multiplier) + mtf_boost, 1.0
        )
        print(f"[CONFIDENCE] Base: {base_confidence:.2f} x Ticker: "
              f"{ticker_multiplier:.2f} + MTF: {mtf_boost:.2f} "
              f"= {final_confidence:.2f}")

        # STEP 12 — ARM TICKER & OPEN POSITION
        arm_ticker(
            ticker, direction, zone_low, zone_high, or_low, or_high,
            entry_price, stop_price, t1, t2, final_confidence, final_grade,
            options_rec
        )

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
