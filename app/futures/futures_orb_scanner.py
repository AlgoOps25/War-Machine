"""
app/futures/futures_orb_scanner.py — NQ/MNQ ORB Signal Generator

Fully self-contained — no imports from app.signals.opening_range or
any other module that does not exist. All ORB detection logic is
implemented inline below.

Integration contract (ZERO touch to existing systems):
  - Reads candle data via tradier_futures_feed.get_todays_bars() only.
  - Writes armed signals to armed_signals_persist with
    signal_type = 'FUTURES_ORB'   <- equity queries ignore this value
    AND to the separate futures_signals table (migration 006).
  - Also writes a Discord alert via the existing discord_helpers —
    same channel, separate embed colour (orange = futures).
  - Does NOT call:
      app.options.*           (options/greeks system)
      app.validation.*        (equity CFW6 confirmation)
      app.risk.position_manager  (no auto-execution until Tradier confirmed)
      app.screening.*         (equity watchlist funnel)
      app.signals.opening_range  (does not exist)

Signal gate order:
  1. SESSION gate   — 09:30–11:00 ET only
  2. BAR COUNT gate — need >= 10 bars to form a valid OR
  3. OR FORMATION   — first 10 min (09:30–09:40) define OR high/low
  4. BOS / ORB      — price closes beyond OR high or low
  5. FVG entry      — 3-bar gap after breakout candle
  6. MOMENTUM fallback — if no FVG, use breakout candle close as entry
  7. ATR STOP       — 1× intraday ATR below/above entry
  8. CONFIDENCE     — simple scoring (OR quality + entry type + volume)
  9. PERSIST        — armed_signals_persist + futures_signals
 10. DISCORD        — orange embed alert
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ── Session constants ─────────────────────────────────────────────────────────
_SESSION_START  = time(9, 30)
_SESSION_CUTOFF = time(11, 0)
_OR_END         = time(9, 40)   # first 10 minutes form the OR

# ── Risk constants ────────────────────────────────────────────────────────────
_POINT_VALUE    = {"NQ": 20.0, "MNQ": 2.0}
_CONTRACTS      = 1
_MIN_CONFIDENCE = 55   # % — below this skip (do not log to DB)
_RR_T1          = 2.0
_RR_T2          = 3.5


# ── Inline ORB detection helpers (no external dependency) ────────────────────

def _detect_breakout(bars: list[dict], or_high: float, or_low: float
                     ) -> Tuple[Optional[str], Optional[int]]:
    """
    Walk bars after the OR window and return the first bar whose CLOSE
    is beyond the OR boundary.

    Returns:
        ("bull", index)  — bullish breakout
        ("bear", index)  — bearish breakout
        (None, None)     — no breakout yet
    """
    for i, bar in enumerate(bars):
        dt = bar["datetime"]
        if hasattr(dt, "astimezone"):
            dt = dt.astimezone(ET)
        if dt.time() < _OR_END:
            continue   # still inside OR formation window
        if bar["close"] > or_high:
            return "bull", i
        if bar["close"] < or_low:
            return "bear", i
    return None, None


def _detect_fvg(bars: list[dict], bk_idx: int, direction: str
                ) -> Tuple[Optional[float], Optional[float]]:
    """
    Look for a 3-bar Fair Value Gap starting at the breakout candle.
    A bullish FVG exists when bars[n-1].high < bars[n+1].low.
    A bearish FVG exists when bars[n-1].low  > bars[n+1].high.

    Returns (fvg_low, fvg_high) or (None, None) if no gap found.
    """
    for i in range(max(bk_idx, 1), len(bars) - 1):
        prev = bars[i - 1]
        curr = bars[i]      # noqa: F841 — kept for clarity
        nxt  = bars[i + 1]
        if direction == "bull":
            if prev["high"] < nxt["low"]:
                return prev["high"], nxt["low"]
        else:
            if prev["low"] > nxt["high"]:
                return nxt["high"], prev["low"]
    return None, None


def _detect_momentum(bars: list[dict], bk_idx: int, direction: str
                     ) -> Optional[dict]:
    """
    Fallback entry: use the breakout candle itself.
    Returns {"entry_high": float, "entry_low": float} or None.
    """
    if bk_idx is None or bk_idx >= len(bars):
        return None
    bar = bars[bk_idx]
    return {"entry_high": bar["high"], "entry_low": bar["low"]}


# ── Scanner class ─────────────────────────────────────────────────────────────

class FuturesORBScanner:
    """
    Stateless scanner — call .scan() once per loop iteration.
    Maintains a simple per-session 'already_fired' flag to avoid
    duplicate signals for the same direction on the same day.
    """

    def __init__(self, symbol: str = "MNQ"):
        self.symbol        = symbol
        self._fired_today: set[str] = set()
        self._or_high:     Optional[float] = None
        self._or_low:      Optional[float] = None
        self._or_locked:   bool = False

    # ── Public ────────────────────────────────────────────────────────────────

    def scan(self, current_time: Optional[datetime] = None) -> Optional[dict]:
        """
        Run one scan cycle. Returns the armed signal dict if a signal was
        generated and persisted, or None if no signal.
        Safe to call every 30–60 s without side effects.
        """
        if current_time is None:
            current_time = datetime.now(ET)

        now = current_time.time()

        # Gate 1 — session window
        if not (_SESSION_START <= now <= _SESSION_CUTOFF):
            return None

        # Fetch bars
        from app.futures.tradier_futures_feed import get_todays_bars
        bars = get_todays_bars(self.symbol)

        # Gate 2 — minimum bars
        if not bars or len(bars) < 10:
            logger.debug(
                f"[FUTURES-ORB] {self.symbol}: "
                f"{len(bars) if bars else 0} bars — waiting for OR"
            )
            return None

        # Gate 3 — lock OR after 09:40
        if not self._or_locked:
            or_bars = [
                b for b in bars
                if b["datetime"].astimezone(ET).time() < _OR_END
            ]
            if len(or_bars) >= 10 or now >= _OR_END:
                self._or_high   = max(b["high"] for b in or_bars)
                self._or_low    = min(b["low"]  for b in or_bars)
                self._or_locked = True
                logger.info(
                    f"[FUTURES-ORB] OR locked: {self.symbol} "
                    f"H={self._or_high:.2f} L={self._or_low:.2f}"
                )

        if not self._or_locked:
            return None

        or_high = self._or_high
        or_low  = self._or_low
        atr     = self._compute_atr(bars)

        # Gate 4 — BOS / ORB breakout
        direction, bk_idx = _detect_breakout(bars, or_high, or_low)
        if direction is None:
            return None

        # Duplicate guard
        if direction in self._fired_today:
            return None

        # Gate 5/6 — FVG entry or momentum fallback
        entry, entry_type = self._resolve_entry(bars, bk_idx, direction)
        if entry is None:
            return None

        # Gate 7 — stop & targets
        stop, t1, t2 = self._compute_levels(entry, direction, atr)

        # Gate 8 — confidence
        confidence = self._score(entry_type, direction, bars, bk_idx, or_high, or_low)
        if confidence < _MIN_CONFIDENCE:
            logger.info(
                f"[FUTURES-ORB] {self.symbol} confidence {confidence}% "
                f"< {_MIN_CONFIDENCE}% floor — skipped"
            )
            return None

        signal = self._build_signal(
            direction, entry, stop, t1, t2, confidence, entry_type,
            or_high, or_low, atr
        )

        # Gate 9 — persist
        self._persist(signal)

        # Gate 10 — Discord
        self._discord_alert(signal)

        self._fired_today.add(direction)
        logger.info(
            f"[FUTURES-ORB] ✅ SIGNAL FIRED: {self.symbol} {direction.upper()} "
            f"entry={entry:.2f} stop={stop:.2f} T1={t1:.2f} T2={t2:.2f} "
            f"conf={confidence}% type={entry_type}"
        )
        return signal

    def reset_daily(self) -> None:
        """Call at EOD reset (mirrors clear_armed_signals in scanner.py)."""
        self._fired_today.clear()
        self._or_high   = None
        self._or_low    = None
        self._or_locked = False
        logger.info(f"[FUTURES-ORB] Daily state reset for {self.symbol}")

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _compute_atr(bars: list[dict], window: int = 10) -> float:
        if not bars:
            return 1.0
        recent = bars[-window:] if len(bars) >= window else bars
        ranges = [b["high"] - b["low"] for b in recent if b["high"] > b["low"]]
        return sum(ranges) / len(ranges) if ranges else 1.0

    def _resolve_entry(
        self, bars: list[dict], bk_idx: int, direction: str
    ) -> Tuple[Optional[float], str]:
        fvg_low, fvg_high = _detect_fvg(bars, bk_idx, direction)
        if fvg_low is not None:
            entry = fvg_high if direction == "bull" else fvg_low
            return entry, "FVG"

        mom = _detect_momentum(bars, bk_idx, direction)
        if mom is not None:
            entry = mom.get("entry_high") if direction == "bull" else mom.get("entry_low")
            if entry is not None:
                return entry, "MOMENTUM_CONTINUATION"

        logger.debug(
            f"[FUTURES-ORB] {self.symbol} {direction}: BOS confirmed "
            f"but no FVG / momentum entry yet — waiting"
        )
        return None, ""

    @staticmethod
    def _compute_levels(
        entry: float, direction: str, atr: float
    ) -> Tuple[float, float, float]:
        risk = atr
        if direction == "bull":
            stop = round(entry - risk, 2)
            t1   = round(entry + risk * _RR_T1, 2)
            t2   = round(entry + risk * _RR_T2, 2)
        else:
            stop = round(entry + risk, 2)
            t1   = round(entry - risk * _RR_T1, 2)
            t2   = round(entry - risk * _RR_T2, 2)
        return stop, t1, t2

    @staticmethod
    def _score(
        entry_type: str, direction: str,
        bars: list[dict], bk_idx: int,
        or_high: float, or_low: float
    ) -> int:
        score = 50

        if entry_type == "FVG":
            score += 15
        elif entry_type == "MOMENTUM_CONTINUATION":
            score += 8

        if bars and bk_idx is not None and bk_idx < len(bars):
            bk_bar    = bars[bk_idx]
            or_range  = or_high - or_low
            if or_range > 0:
                penetration = abs(
                    bk_bar["close"] - (or_high if direction == "bull" else or_low)
                )
                if penetration > or_range * 0.3:
                    score += 10

        or_range = or_high - or_low
        if 5 <= or_range <= 50:
            score += 10
        elif or_range > 50:
            score -= 5

        if bars and bk_idx is not None and bk_idx < len(bars):
            bk_vol  = bars[bk_idx].get("volume", 0)
            avg_vol = sum(b.get("volume", 0) for b in bars[:bk_idx]) / max(bk_idx, 1)
            if avg_vol > 0 and bk_vol > avg_vol * 1.5:
                score += 10

        return min(score, 100)

    def _build_signal(
        self, direction, entry, stop, t1, t2,
        confidence, entry_type, or_high, or_low, atr
    ) -> dict:
        point_value = _POINT_VALUE.get(self.symbol, 2.0)
        risk_pts    = abs(entry - stop)
        dollar_risk = round(risk_pts * point_value * _CONTRACTS, 2)
        return {
            "ticker":       self.symbol,
            "direction":    direction.upper(),
            "entry_price":  round(entry, 4),
            "stop_price":   round(stop, 4),
            "t1":           t1,
            "t2":           t2,
            "confidence":   round(confidence / 100, 4),
            "grade":        "A" if confidence >= 75 else ("B" if confidence >= 60 else "C"),
            "signal_type":  "FUTURES_ORB",
            "validation_data": {
                "or_high":      or_high,
                "or_low":       or_low,
                "or_range":     round(or_high - or_low, 4),
                "entry_type":   entry_type,
                "atr":          round(atr, 4),
                "risk_pts":     round(risk_pts, 4),
                "rr_t1":        _RR_T1,
                "rr_t2":        _RR_T2,
                "contracts":    _CONTRACTS,
                "point_value":  point_value,
                "dollar_risk":  dollar_risk,
                "tradier_live": os.getenv("TRADIER_FUTURES_ENABLED", "false"),
            },
        }

    @staticmethod
    def _persist(signal: dict) -> None:
        try:
            from app.core.armed_signal_store import _persist_armed_signal
            _persist_armed_signal(signal["ticker"], {**signal, "position_id": None})
            logger.info(
                f"[FUTURES-ORB] Persisted to armed_signals_persist: "
                f"{signal['ticker']} {signal['direction']}"
            )
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] armed_signals_persist write failed (non-fatal): {e}")

        try:
            from app.data.db_connection import get_connection
            conn = get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO futures_signals
                            (symbol, direction, entry_price, stop_price, t1, t2,
                             confidence, grade, signal_type, entry_type, validation_data)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            signal["ticker"],
                            signal["direction"],
                            signal["entry_price"],
                            signal["stop_price"],
                            signal["t1"],
                            signal["t2"],
                            signal["confidence"],
                            signal["grade"],
                            signal["signal_type"],
                            signal["validation_data"]["entry_type"],
                            json.dumps(signal["validation_data"]),
                        ),
                    )
                conn.commit()
                logger.info("[FUTURES-ORB] Persisted to futures_signals table")
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] futures_signals write failed (non-fatal): {e}")

    @staticmethod
    def _discord_alert(signal: dict) -> None:
        try:
            from app.notifications.discord_helpers import send_simple_message
            sym   = signal["ticker"]
            d     = signal["direction"]
            entry = signal["entry_price"]
            stop  = signal["stop_price"]
            t1    = signal["t1"]
            t2    = signal["t2"]
            conf  = round(signal["confidence"] * 100, 1)
            etype = signal["validation_data"]["entry_type"]
            grade = signal["grade"]
            drisk = signal["validation_data"]["dollar_risk"]
            arrow = "🟢" if d == "BULL" else "🔴"
            msg = (
                f"🟠 **FUTURES ORB SIGNAL** {arrow}\n"
                f"**{sym}** {d} | Grade {grade} | {conf}% conf\n"
                f"Entry: `{entry}` | Stop: `{stop}` | "
                f"T1: `{t1}` | T2: `{t2}`\n"
                f"Entry type: {etype} | Dollar risk (1 contract): ${drisk}"
            )
            send_simple_message(msg)
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] Discord alert failed (non-fatal): {e}")
