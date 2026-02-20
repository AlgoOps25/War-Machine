# Sniper Module - BOS+FVG 0DTE Strategy
# INTEGRATED: Position Manager, AI Learning, Confirmation Layers
import traceback
from datetime import datetime, time
from zoneinfo import ZoneInfo
from discord_helpers import send_options_signal_alert
from options_filter import get_options_recommendation
from ai_learning import learning_engine
from cfw6_confirmation import grade_signal_with_confirmations
from data_manager import data_manager
from position_manager import position_manager
from learning_policy import compute_confidence
from bos_fvg_engine import scan_bos_fvg, is_force_close_time
import config

# Global dictionary to track armed signals (reset at EOD by clear_armed_signals)
armed_signals = {}

# ─────────────────────────────────────────────────────────────
class AlgoOps25:
    pass
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
# ARM
# ─────────────────────────────────────────────────────────────

def arm_ticker(ticker, direction, zone_low, zone_high,
               entry_price, stop_price, t1, t2,
               confidence, grade, options_rec=None):
    """Arms a ticker after BOS+FVG signal and sends Discord alert."""

    MIN_STOP_PCT     = 0.002
    min_stop_dist    = entry_price * MIN_STOP_PCT
    actual_stop_dist = abs(entry_price - stop_price)
    if actual_stop_dist < min_stop_dist:
        print(f"[ARM] {ticker} stop distance ${actual_stop_dist:.3f} "
              f"below minimum ${min_stop_dist:.3f} — skipping")
        return

    print(f"{ticker} ARMED: {direction.upper()} | "
          f"Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f}")
    print(f"  FVG Zone: ${zone_low:.2f}-${zone_high:.2f}")
    print(f"  Targets: T1=${t1:.2f} T2=${t2:.2f} | "
          f"Confidence: {confidence*100:.1f}% ({grade}) | DTE: 0")

    log_proposed_trade(ticker, "BOS+FVG", direction, entry_price, confidence, grade)

    send_options_signal_alert(
        ticker=ticker,
        direction=direction,
        entry=entry_price,
        stop=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        timeframe="1m",
        grade=grade,
        options_data=options_rec
    )

    position_id = position_manager.open_position(
        ticker=ticker,
        direction=direction,
        zone_low=zone_low,
        zone_high=zone_high,
        or_low=zone_low,    # FVG zone used as reference
        or_high=zone_high,
        entry_price=entry_price,
        stop_price=stop_price,
        t1=t1,
        t2=t2,
        confidence=confidence,
        grade=grade,
        options_rec=options_rec
    )

    armed_signals[ticker] = {
        "position_id": position_id,
        "direction":   direction,
        "zone_low":    zone_low,
        "zone_high":   zone_high,
        "entry_price": entry_price,
        "stop_price":  stop_price,
        "t1":          t1,
        "t2":          t2,
        "confidence":  confidence,
        "grade":       grade,
        "options_rec": options_rec,
        "dte":         0
    }
    print(f"[ARMED] {ticker} position opened (ID: {position_id}) | 0DTE")


def clear_armed_signals():
    """Reset armed signals dict at EOD."""
    armed_signals.clear()
    print("[ARMED] Cleared all armed signals for new trading day")


# ─────────────────────────────────────────────────────────────
# MAIN PROCESS TICKER
# ─────────────────────────────────────────────────────────────

def process_ticker(ticker: str):
    """
    BOS+FVG 0DTE strategy processor.

    Flow:
      1. Re-arm guard (one signal per ticker per session)
      2. Incremental bar fetch
      3. Force-close check at 3:55 PM ET
      4. BOS+FVG scan via bos_fvg_engine
      5. Confirmation layer grading
      6. Options recommendation
      7. Confidence calculation
      8. Arm ticker + open position
    """
    try:
        # STEP 1 — one signal per ticker per session
        if ticker in armed_signals:
            return

        # STEP 2 — incremental fetch
        data_manager.update_ticker(ticker)

        # STEP 3 — load today's session bars
        bars_session = data_manager.get_today_session_bars(ticker)
        if not bars_session:
            print(f"[{ticker}] No bars for today's session yet — skipping")
            return

        print(f"[{ticker}] Scanning TODAY {_now_et().date()} "
              f"({len(bars_session)} bars)")

        t_first = _bar_time(bars_session[0])
        t_last  = _bar_time(bars_session[-1])
        print(f"[{ticker}] Bar window: {t_first} -> {t_last}")

        # STEP 4 — 0DTE hard close at 3:55 PM
        if is_force_close_time(bars_session[-1]):
            current_price = bars_session[-1]["close"]
            position_manager.close_all_eod({ticker: current_price})
            return

        # STEP 5 — BOS + FVG scan
        signal = scan_bos_fvg(ticker, bars_session)
        if not signal:
            # scan_bos_fvg prints its own reason internally
            return

        direction   = signal["direction"]
        entry_price = signal["entry"]
        zone_low    = signal["fvg_low"]
        zone_high   = signal["fvg_high"]
        stop_price  = signal["stop"]
        t1          = signal["t1"]
        t2          = signal["t2"]

        print(f"[{ticker}] BOS+FVG ✔ {direction.upper()} | "
              f"BOS @ ${signal['bos_price']:.2f} | "
              f"FVG {signal['fvg_size_pct']:.3f}% | "
              f"Entry: ${entry_price:.2f}")

        # STEP 6 — confirmation layer grading (VWAP, Prev Day, Institutional, Options Flow)
        confirmation_result = grade_signal_with_confirmations(
            ticker=ticker,
            direction=direction,
            bars=bars_session,
            current_price=entry_price,
            breakout_idx=len(bars_session) - 1,
            base_grade="A"
        )
        final_grade = confirmation_result["final_grade"]
        if final_grade == "reject":
            print(f"[{ticker}] Signal rejected after confirmation layers")
            return

        # STEP 7 — options recommendation (0DTE)
        options_rec = get_options_recommendation(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            target_price=t1
        )

        # STEP 8 — confidence score
        base_confidence   = compute_confidence(final_grade, "1m", ticker)
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

        # STEP 9 — arm + open position
        arm_ticker(
            ticker, direction, zone_low, zone_high,
            entry_price, stop_price, t1, t2,
            final_confidence, final_grade,
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
