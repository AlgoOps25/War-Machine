# Sniper Module - CFW6 Strategy Implementation
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers
# TWO-PATH SCANNING: OR-Anchored + Intraday BOS+FVG fallback
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
from bos_fvg_engine import scan_bos_fvg, is_force_close_time

# Global dictionary to track armed signals (reset at EOD by clear_armed_signals)
armed_signals = {}

# Minimum grade required for intraday (no-OR) signals — stricter than OR mode
INTRADAY_MIN_GRADES = {"A+", "A"}

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
        print(f"[TRACKER] Logged proposed {direction} {signal_type} signal for {ticker}")
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
# INTRADAY BOS DETECTION (Path B — no OR required)
# ─────────────────────────────────────────────────────────────

def detect_intraday_bos(bars: list, lookback: int = 40) -> tuple:
    """
    Detect Intraday Break of Structure without Opening Range.

    Uses a rolling lookback window to define swing structure (high/low),
    then checks if the most recent 1-2 bars have closed outside that
    structure — signaling a BOS (Break of Structure / MSB).

    Logic:
      - Reference window: bars[-(lookback+2):-2]  (established structure)
      - Active bars:      bars[-2:]                (recent price action)
      - BOS bull: active close > struct_high * (1 + ORB_BREAK_THRESHOLD)
      - BOS bear: active close < struct_low  * (1 - ORB_BREAK_THRESHOLD)

    Time filter: only scans between 10:00 AM and 3:30 PM ET to avoid
    OR overlap on the open and avoid late-session noise near the close.

    Returns: (direction, bos_idx, struct_high, struct_low)
         or  (None, None, None, None) if no BOS detected.
    """
    if len(bars) < lookback + 3:
        return None, None, None, None

    # Reference window: established structure BEFORE the last 2 active bars
    ref_bars = bars[-(lookback + 2):-2]
    if len(ref_bars) < 10:
        return None, None, None, None

    struct_high = max(b["high"] for b in ref_bars)
    struct_low  = min(b["low"]  for b in ref_bars)

    # Check the last 2 bars (bars[-2] first, then bars[-1]) for a fresh BOS
    for offset in [2, 1]:
        i   = len(bars) - offset
        bar = bars[i]
        bt  = _bar_time(bar)

        # Time filter: 10:00 AM – 3:30 PM ET only
        if bt is None or not (time(10, 0) <= bt <= time(15, 30)):
            continue

        if bar["close"] > struct_high * (1 + config.ORB_BREAK_THRESHOLD):
            print(f"[INTRADAY BOS] BULL at idx {i} ({bt}): "
                  f"${bar['close']:.2f} > struct H ${struct_high:.2f}")
            return "bull", i, struct_high, struct_low

        if bar["close"] < struct_low * (1 - config.ORB_BREAK_THRESHOLD):
            print(f"[INTRADAY BOS] BEAR at idx {i} ({bt}): "
                  f"${bar['close']:.2f} < struct L ${struct_low:.2f}")
            return "bear", i, struct_high, struct_low

    return None, None, None, None

# ─────────────────────────────────────────────────────────────
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade,
               options_rec=None, signal_type="CFW6_OR"):
    """Arms a ticker after signal confirmation and sends Discord alert."""

    MIN_STOP_PCT  = 0.002
    min_stop_dist = entry_price * MIN_STOP_PCT
    actual_stop_dist = abs(entry_price - stop_price)
    if actual_stop_dist < min_stop_dist:
        print(f"[ARM] ⚠️ {ticker} stop distance ${actual_stop_dist:.3f} "
              f"below minimum ${min_stop_dist:.3f} — skipping")
        return

    mode_label = " [INTRADAY]" if signal_type == "CFW6_INTRADAY" else " [OR]"
    print(f"✅ {ticker} ARMED{mode_label}: {direction.upper()} | "
          f"Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"  Zone: ${zone_low:.2f}-${zone_high:.2f} | "
          f"Struct/OR: ${or_low:.2f}-${or_high:.2f}")
    print(f"  Targets: T1=${t1:.2f} T2=${t2:.2f} | "
          f"Confidence: {confidence*100:.1f}% ({grade})")

    log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade)

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
        "options_rec":   options_rec,
        "signal_type":   signal_type
    }
    print(f"[ARMED] {ticker} position opened (ID: {position_id}) | Type: {signal_type}")

def clear_armed_signals():
    """Reset armed signals dict at EOD."""
    armed_signals.clear()
    print("[ARMED] Cleared all armed signals for new trading day")

# ─────────────────────────────────────────────────────────────
# MAIN PROCESS TICKER
# ─────────────────────────────────────────────────────────────

def process_ticker(ticker: str):
    """
    Main CFW6 strategy processor — two-path scanning.

    PATH A — OR-Anchored (full CFW6):
      Requires 9:30-9:40 OR bars. Detects ORB breakout then FVG.
      Allows grades: A+, A, A-

    PATH B — Intraday BOS+FVG (fallback):
      Activates when PATH A produces no complete signal (no OR data,
      no ORB, or no FVG after ORB). Uses a 40-bar rolling swing
      structure as the BOS reference level.
      Allows grades: A+, A only (stricter — no OR context)
      Applies 5% confidence decay.
      Time filter: 10:00 AM – 3:30 PM ET.

    PATH A is always attempted first. PATH B fires only when PATH A
    does not produce a full OR → Breakout → FVG signal chain.

    CFW6 Steps (shared by both paths after structure is set):
      1.  Re-arm guard
      2.  Incremental DB fetch
      3.  Load today's session bars
      3b. Force-close check (3:55 PM EOD rule)
      4.  Determine scan mode (OR-Anchored vs Intraday BOS)
      5.  Detect breakout / BOS
      6.  Detect FVG after breakout
      7.  Wait for CFW6 confirmation candle
      8.  Multi-factor confirmation layers (VWAP, Prev Day, Inst. Vol, Options)
      9.  Compute stops & targets
      10. Get options recommendation
      11. Compute confidence score (AI + MTF boost)
      12. Arm ticker & open position
    """
    try:
        # STEP 1 — Re-arm guard: one signal per ticker per session
        if ticker in armed_signals:
            return

        # STEP 2 — Incremental fetch: pull only new bars since last stored bar.
        data_manager.update_ticker(ticker)

        # STEP 3 — Load today's session bars from DB.
        bars_session = data_manager.get_today_session_bars(ticker)

        if not bars_session:
            print(f"[{ticker}] ⚠️  No bars for today's session yet — skipping")
            return

        print(f"[{ticker}] Scanning TODAY {_now_et().date()} "
              f"({len(bars_session)} bars)")
        t_first = _bar_time(bars_session[0])
        t_last  = _bar_time(bars_session[-1])
        print(f"[{ticker}] Bar window: {t_first} → {t_last}")

        # STEP 3b — Force close check: hard-close all positions at 3:55 PM ET
        if is_force_close_time(bars_session[-1]):
            prices = {ticker: bars_session[-1]["close"]}
            position_manager.close_all_eod(prices)
            return

        # ── STEP 4: DETERMINE SCAN MODE ──────────────────────────────────────
        #
        # Try PATH A first (OR-Anchored). If OR bars exist and produce a
        # full Breakout → FVG signal chain, use it. Otherwise fall through
        # to PATH B (Intraday BOS+FVG).
        # ─────────────────────────────────────────────────────────────────────

        direction    = None
        breakout_idx = None
        zone_low     = None
        zone_high    = None
        or_high_ref  = None
        or_low_ref   = None
        scan_mode    = None

        # ── PATH A: OR-ANCHORED ───────────────────────────────────────────────
        or_high, or_low = compute_opening_range_from_bars(bars_session)
        has_or = (or_high is not None and or_low is not None)

        if has_or:
            print(f"[{ticker}] OR available: ${or_low:.2f} - ${or_high:.2f} | "
                  f"Attempting OR-Anchored scan...")
            direction, breakout_idx = detect_breakout_after_or(
                bars_session, or_high, or_low
            )
            if direction is not None:
                zone_low, zone_high = detect_fvg_after_break(
                    bars_session, breakout_idx, direction
                )
                if zone_low is not None and zone_high is not None:
                    scan_mode   = "OR_ANCHORED"
                    or_high_ref = or_high
                    or_low_ref  = or_low
                    print(f"[{ticker}] ✅ PATH A: OR-Anchored signal found")
                else:
                    print(f"[{ticker}] ORB detected but no FVG — trying intraday scan")
                    direction = None  # reset for PATH B
            else:
                print(f"[{ticker}] No ORB breakout — trying intraday scan")
        else:
            print(f"[{ticker}] No OR bars (9:30-9:40) — going straight to intraday scan")

        # ── PATH B: INTRADAY BOS+FVG ──────────────────────────────────────────
        if scan_mode is None:
            if len(bars_session) < 30:
                print(f"[{ticker}] ⚠️  Insufficient bars for intraday scan "
                      f"({len(bars_session)} < 30) — skipping")
                return

            direction, breakout_idx, struct_high, struct_low = detect_intraday_bos(
                bars_session
            )
            if direction is None:
                print(f"[{ticker}] — No intraday BOS detected")
                return

            zone_low, zone_high = detect_fvg_after_break(
                bars_session, breakout_idx, direction
            )
            if zone_low is None or zone_high is None:
                print(f"[{ticker}] — No FVG found after intraday BOS")
                return

            # Use swing struct levels as OR proxy for stops/targets/position
            or_high_ref = struct_high
            or_low_ref  = struct_low
            scan_mode   = "INTRADAY_BOS"
            print(f"[{ticker}] ✅ PATH B: Intraday BOS signal found | "
                  f"Struct H: ${struct_high:.2f} L: ${struct_low:.2f}")

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        print(f"[{ticker}] Mode: {scan_mode} | "
              f"FVG zone: ${zone_low:.2f} - ${zone_high:.2f}")

        # ── STEPS 7-12: SHARED LOGIC (both paths) ────────────────────────────

        # STEP 7 — CFW6 CONFIRMATION CANDLE
        result = wait_for_confirmation(
            bars_session, direction, (zone_low, zone_high), breakout_idx + 1
        )
        found, entry_price, base_grade, confirm_idx, confirm_type = result
        if not found or base_grade == "reject":
            print(f"[{ticker}] — No confirmation candle "
                  f"(found={found}, grade={base_grade})")
            return

        # STEP 7b — Grade filter (stricter for intraday signals)
        if scan_mode == "INTRADAY_BOS" and base_grade not in INTRADAY_MIN_GRADES:
            print(f"[{ticker}] — Intraday signal requires A or A+ "
                  f"(got {base_grade}) — skipping")
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
            print(f"[{ticker}] — Signal rejected after confirmation layers "
                  f"(base={base_grade})")
            return

        # STEP 9 — CALCULATE STOPS & TARGETS
        stop_price, t1, t2 = compute_stop_and_targets(
            bars_session, direction, or_high_ref, or_low_ref, entry_price
        )

        # STEP 10 — OPTIONS RECOMMENDATION
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1
        )

        # STEP 11 — COMPUTE CONFIDENCE (AI learning + MTF boost)
        base_confidence   = compute_confidence(final_grade, "5m", ticker)
        ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)

        try:
            from timeframe_manager import calculate_mtf_convergence_boost
            mtf_boost = calculate_mtf_convergence_boost(ticker)
        except ImportError:
            mtf_boost = 0.0

        # 5% confidence decay for intraday signals (no OR context)
        mode_decay = 0.95 if scan_mode == "INTRADAY_BOS" else 1.0

        final_confidence = min(
            (base_confidence * ticker_multiplier * mode_decay) + mtf_boost, 1.0
        )
        print(f"[CONFIDENCE] Base: {base_confidence:.2f} × Ticker: "
              f"{ticker_multiplier:.2f} × Mode: {mode_decay:.2f} "
              f"+ MTF: {mtf_boost:.2f} = {final_confidence:.2f}")

        # STEP 12 — ARM TICKER & OPEN POSITION
        arm_ticker(
            ticker, direction, zone_low, zone_high,
            or_low_ref, or_high_ref,
            entry_price, stop_price, t1, t2,
            final_confidence, final_grade,
            options_rec,
            signal_type=signal_type
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
