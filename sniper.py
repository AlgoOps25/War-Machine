# Sniper Module - CFW6 Strategy Implementation
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers
# TWO-PATH SCANNING: OR-Anchored + Intraday BOS+FVG fallback
# TWO-PHASE ALERTS: Watch Alert (BOS detected) + Confirmed Signal (FVG+confirm)
# EARNINGS GUARD: Skips tickers with earnings within 2 days (IV crush protection)
import traceback
import requests
from datetime import datetime, time
from zoneinfo import ZoneInfo
from discord_helpers import send_options_signal_alert, send_simple_message
from options_filter import get_options_recommendation
from ai_learning import learning_engine
from cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from trade_calculator import compute_stop_and_targets, apply_confidence_decay, calculate_atr
from data_manager import data_manager
from position_manager import position_manager
from learning_policy import compute_confidence
from earnings_filter import has_earnings_soon
import config
from bos_fvg_engine import scan_bos_fvg, is_force_close_time

# ── Global State ─────────────────────────────────────────────────────────────
# armed_signals   : ticker → signal data  (one confirmed signal per ticker/day)
# watching_signals: ticker → BOS context  (watching for FVG to form)
armed_signals    = {}
watching_signals = {}

# How many bars after BOS to keep watching before expiring the watch state.
# At 1m bars this equals ~30 minutes of continued monitoring.
MAX_WATCH_BARS = 30

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
# PHASE 1 — WATCH ALERT
# ─────────────────────────────────────────────────────────────

def send_bos_watch_alert(ticker: str, direction: str, bos_price: float,
                          struct_high: float, struct_low: float,
                          signal_type: str = "CFW6_INTRADAY"):
    """
    Phase 1 Discord heads-up: BOS detected, waiting for FVG to form.

    Sent once per BOS event when a ticker enters watching_signals.
    No position is opened at this stage — this is purely informational.
    """
    arrow    = "🟢" if direction == "bull" else "🔴"
    d_label  = direction.upper()
    level    = f"${struct_high:.2f}" if direction == "bull" else f"${struct_low:.2f}"
    mode_tag = "[OR]" if signal_type == "CFW6_OR" else "[INTRADAY]"
    now_str  = _now_et().strftime("%I:%M %p ET")

    msg = (
        f"📡 **BOS ALERT {mode_tag}: {ticker}** — {arrow} {d_label}\n"
        f"Break Price : **${bos_price:.2f}**\n"
        f"Struct Level: {level}\n"
        f"⏳ Watching for FVG pullback to form (up to {MAX_WATCH_BARS} min)\n"
        f"🕐 {now_str}"
    )
    try:
        send_simple_message(msg)
        print(f"[WATCH] 📡 Alert sent for {ticker} {d_label} BOS @ ${bos_price:.2f}")
    except Exception as e:
        print(f"[WATCH] Discord alert error for {ticker}: {e}")


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
        c0 = bars[i - 2]
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
    OR overlap on the open and late-session noise near the close.

    Returns: (direction, bos_idx, struct_high, struct_low)
         or  (None, None, None, None) if no BOS detected.
    """
    if len(bars) < lookback + 3:
        return None, None, None, None

    ref_bars = bars[-(lookback + 2):-2]
    if len(ref_bars) < 10:
        return None, None, None, None

    struct_high = max(b["high"] for b in ref_bars)
    struct_low  = min(b["low"]  for b in ref_bars)

    for offset in [2, 1]:
        i   = len(bars) - offset
        bar = bars[i]
        bt  = _bar_time(bar)

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
# PHASE 2 — SIGNAL PIPELINE (Steps 7-12, shared by both paths)
# ─────────────────────────────────────────────────────────────

def _run_signal_pipeline(ticker: str, direction: str,
                          zone_low: float, zone_high: float,
                          or_high_ref: float, or_low_ref: float,
                          signal_type: str, bars_session: list,
                          breakout_idx: int) -> bool:
    """
    Steps 7-12: confirmation, sizing, and arming.

    Called from process_ticker() for both OR-Anchored and Intraday BOS
    paths, as well as when a watching ticker's FVG finally forms.

    Returns True if the ticker was successfully armed, False otherwise.
    """
    # STEP 7 — CFW6 CONFIRMATION CANDLE
    result = wait_for_confirmation(
        bars_session, direction, (zone_low, zone_high), breakout_idx + 1
    )
    found, entry_price, base_grade, confirm_idx, confirm_type = result
    if not found or base_grade == "reject":
        print(f"[{ticker}] — No confirmation candle "
              f"(found={found}, grade={base_grade})")
        return False

    # STEP 7b — Grade filter (stricter for intraday signals)
    if signal_type == "CFW6_INTRADAY" and base_grade not in INTRADAY_MIN_GRADES:
        print(f"[{ticker}] — Intraday signal requires A or A+ "
              f"(got {base_grade}) — skipping")
        return False

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
        return False

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

    mode_decay = 0.95 if signal_type == "CFW6_INTRADAY" else 1.0
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
    return True


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


def clear_watching_signals():
    """Reset watching signals dict at EOD."""
    watching_signals.clear()
    print("[WATCHING] Cleared all watching signals for new trading day")


# ─────────────────────────────────────────────────────────────
# MAIN PROCESS TICKER
# ─────────────────────────────────────────────────────────────

def process_ticker(ticker: str):
    """
    Main CFW6 strategy processor — two-path scanning, two-phase alerts.

    Guard order (fast-exit before any expensive work):
      1.  Re-arm guard       — one confirmed signal per ticker per session
      2.  Incremental fetch  — pull only new bars
      3.  Session bars check — ensure data is available
      3b. Force-close check  — EOD 3:55 PM hard stop
      3c. Earnings guard     — skip if earnings within EARNINGS_WINDOW_DAYS
      4.  Watching check     — resume FVG scan for previously-alerted BOS
      5+. Fresh scan         — PATH A (OR-Anchored) or PATH B (Intraday BOS)
    """
    try:
        # STEP 1 — Re-arm guard: one confirmed signal per ticker per session
        if ticker in armed_signals:
            return

        # STEP 2 — Incremental fetch
        data_manager.update_ticker(ticker)

        # STEP 3 — Load today's session bars
        bars_session = data_manager.get_today_session_bars(ticker)
        if not bars_session:
            print(f"[{ticker}] ⚠️  No bars for today's session yet — skipping")
            return

        print(f"[{ticker}] Scanning TODAY {_now_et().date()} "
              f"({len(bars_session)} bars)")
        t_first = _bar_time(bars_session[0])
        t_last  = _bar_time(bars_session[-1])
        print(f"[{ticker}] Bar window: {t_first} → {t_last}")

        # STEP 3b — Force close check
        if is_force_close_time(bars_session[-1]):
            prices = {ticker: bars_session[-1]["close"]}
            position_manager.close_all_eod(prices)
            return

        # STEP 3c — EARNINGS GUARD
        # Skip tickers with earnings today or tomorrow to avoid IV crush and
        # erratic pre-earnings price action on options buys.
        has_earns, earns_date = has_earnings_soon(ticker)
        if has_earns:
            print(f"[{ticker}] ❌ Earnings on {earns_date} — skipping "
                  f"(IV crush / pre-earnings noise risk)")
            return

        # ── STEP 4: WATCHING STATE CHECK ──────────────────────────────────────
        if ticker in watching_signals:
            watch        = watching_signals[ticker]
            breakout_idx = watch["breakout_idx"]
            direction    = watch["direction"]
            or_high_ref  = watch["or_high"]
            or_low_ref   = watch["or_low"]
            signal_type  = watch["signal_type"]
            bars_since   = len(bars_session) - breakout_idx

            if bars_since > MAX_WATCH_BARS:
                print(f"[{ticker}] ⏰ Watch expired: {bars_since} bars since "
                      f"{direction.upper()} BOS (max {MAX_WATCH_BARS}) — clearing")
                del watching_signals[ticker]
            else:
                print(f"[{ticker}] 👁️  WATCHING [{bars_since}/{MAX_WATCH_BARS}] "
                      f"{direction.upper()} | Scanning for FVG...")
                zone_low, zone_high = detect_fvg_after_break(
                    bars_session, breakout_idx, direction
                )
                if zone_low is None or zone_high is None:
                    print(f"[{ticker}] — FVG not yet formed, holding watch state")
                    return

                print(f"[{ticker}] ✅ FVG formed: ${zone_low:.2f} – ${zone_high:.2f} "
                      f"| Running confirmation pipeline...")
                _run_signal_pipeline(
                    ticker, direction, zone_low, zone_high,
                    or_high_ref, or_low_ref, signal_type,
                    bars_session, breakout_idx
                )
                del watching_signals[ticker]
                return

        # ── STEP 5: FRESH SCAN ───────────────────────────────────────────────
        direction    = None
        breakout_idx = None
        zone_low     = None
        zone_high    = None
        or_high_ref  = None
        or_low_ref   = None
        scan_mode    = None

        # ── PATH A: OR-ANCHORED ─────────────────────────────────────────────
        or_high, or_low = compute_opening_range_from_bars(bars_session)
        has_or = (or_high is not None and or_low is not None)

        if has_or:
            print(f"[{ticker}] OR: ${or_low:.2f} – ${or_high:.2f} | "
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
                    print(f"[{ticker}] 📡 ORB detected — watching for FVG to form")
                    if ticker not in watching_signals:
                        watching_signals[ticker] = {
                            "direction":    direction,
                            "breakout_idx": breakout_idx,
                            "or_high":      or_high,
                            "or_low":       or_low,
                            "signal_type":  "CFW6_OR"
                        }
                        send_bos_watch_alert(
                            ticker, direction,
                            bars_session[breakout_idx]["close"],
                            or_high, or_low,
                            signal_type="CFW6_OR"
                        )
                    return
            else:
                print(f"[{ticker}] No ORB breakout — trying intraday scan")
        else:
            print(f"[{ticker}] No OR bars (9:30–9:40) — going to intraday scan")

        # ── PATH B: INTRADAY BOS+FVG ─────────────────────────────────────────
        if scan_mode is None:
            if len(bars_session) < 30:
                print(f"[{ticker}] ⚠️  Insufficient bars ({len(bars_session)}) — skipping")
                return

            direction, breakout_idx, struct_high, struct_low = detect_intraday_bos(
                bars_session
            )
            if direction is None:
                print(f"[{ticker}] — No intraday BOS detected")
                return

            or_high_ref = struct_high
            or_low_ref  = struct_low

            zone_low, zone_high = detect_fvg_after_break(
                bars_session, breakout_idx, direction
            )

            if zone_low is None or zone_high is None:
                print(f"[{ticker}] 📡 Intraday BOS — watching for FVG to form")
                if ticker not in watching_signals:
                    watching_signals[ticker] = {
                        "direction":    direction,
                        "breakout_idx": breakout_idx,
                        "or_high":      struct_high,
                        "or_low":       struct_low,
                        "signal_type":  "CFW6_INTRADAY"
                    }
                    send_bos_watch_alert(
                        ticker, direction,
                        bars_session[breakout_idx]["close"],
                        struct_high, struct_low,
                        signal_type="CFW6_INTRADAY"
                    )
                return

            scan_mode = "INTRADAY_BOS"
            print(f"[{ticker}] ✅ PATH B: Intraday BOS+FVG | "
                  f"Struct H: ${struct_high:.2f} L: ${struct_low:.2f}")

        signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
        print(f"[{ticker}] Mode: {scan_mode} | "
              f"FVG zone: ${zone_low:.2f} – ${zone_high:.2f}")

        # ── STEPS 7-12: CONFIRMATION PIPELINE ─────────────────────────────
        _run_signal_pipeline(
            ticker, direction, zone_low, zone_high,
            or_high_ref, or_low_ref, signal_type,
            bars_session, breakout_idx
        )

    except Exception as e:
        print(f"process_ticker error for {ticker}:", e)
        traceback.print_exc()


def send_discord(message: str):
    """Simple discord message sender (backward compatibility)."""
    try:
        payload = {"content": message}
        requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
