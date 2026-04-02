"""
app/futures/futures_orb_scanner.py — NQ/MNQ ORB Signal Generator

Integration contract (ZERO touch to existing systems):
  - Reads candle data via tradier_futures_feed.get_todays_bars() only.
  - Reuses opening_range.py DETECTION FUNCTIONS (stateless) — does NOT
    instantiate OpeningRangeDetector, which caches equity-ticker state.
  - Writes armed signals to armed_signals_persist with
    signal_type = 'FUTURES_ORB'   <- equity queries use ≠ this value
    AND to the separate futures_signals table (migration 006).
  - Also writes a Discord alert via the existing discord_helpers —
    same channel, separate embed colour (orange = futures).
  - Does NOT call:
      app.options.*           (options/greeks system)
      app.validation.*        (equity CFW6 confirmation)
      app.risk.position_manager  (no auto-execution until Tradier confirmed)
      app.screening.*         (equity watchlist funnel)

Signal gate order (mirrors sniper_pipeline.py structure for consistency):
  1. SESSION gate   — 09:30–11:00 ET only
  2. BAR COUNT gate — need >= 10 bars to form a valid OR
  3. OR FORMATION   — first 10 bars (09:30–09:40) define OR high/low
  4. BOS / ORB      — detect_breakout_after_or() from opening_range.py
  5. FVG entry      — detect_fvg_after_break() from opening_range.py
  6. MOMENTUM fallback — detect_momentum_continuation() if no FVG
  7. ATR STOP       — 1× intraday ATR below/above entry
  8. CONFIDENCE     — simple scoring (OR classification + entry type)
  9. PERSIST        — armed_signals_persist + futures_signals
 10. DISCORD        — orange embed alert
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ── Session constants ─────────────────────────────────────────────────────────
_SESSION_START  = time(9, 30)
_SESSION_CUTOFF = time(11, 0)  # Same as sniper_pipeline TIME gate
_OR_END         = time(9, 40)  # First 10 minutes form the OR

# ── Risk constants ────────────────────────────────────────────────────────────
_POINT_VALUE = {"NQ": 20.0, "MNQ": 2.0}  # USD per point per contract
_CONTRACTS   = 1                           # Fixed at 1 until live trading confirmed
_MIN_CONFIDENCE = 55  # % — below this the signal is skipped (not logged to DB)

# R:R ratios — T1=2R (conservative), T2=3.5R (mentor annotation range 3.31–4.1)
_RR_T1 = 2.0
_RR_T2 = 3.5


class FuturesORBScanner:
    """
    Stateless scanner — call .scan() once per loop iteration.
    Maintains a simple per-session 'already_fired' flag to avoid
    duplicate signals for the same direction on the same day.
    """

    def __init__(self, symbol: str = "MNQ"):
        self.symbol         = symbol
        self._fired_today:  set[str] = set()   # {"bull", "bear"} — resets at EOD
        self._or_high:      Optional[float] = None
        self._or_low:       Optional[float] = None
        self._or_locked:    bool = False

    # ── Public ────────────────────────────────────────────────────────────────

    def scan(self, current_time: Optional[datetime] = None) -> Optional[dict]:
        """
        Run one scan cycle. Returns the armed signal dict if a signal was
        generated and persisted, or None if no signal.

        Safe to call every 30–60s without side effects if no setup exists.
        """
        if current_time is None:
            current_time = datetime.now(ET)

        now = current_time.time()

        # Gate 1 — session
        if not (_SESSION_START <= now <= _SESSION_CUTOFF):
            return None

        # Fetch bars
        from app.futures.tradier_futures_feed import get_todays_bars
        bars = get_todays_bars(self.symbol)

        # Gate 2 — minimum bars
        if not bars or len(bars) < 10:
            logger.debug(f"[FUTURES-ORB] {self.symbol}: only {len(bars) if bars else 0} bars — waiting for OR formation")
            return None

        # Gate 3 — lock OR after 09:40
        if not self._or_locked:
            or_bars = [b for b in bars if b["datetime"].astimezone(ET).time() < _OR_END]
            if len(or_bars) >= 10 or now >= _OR_END:
                self._or_high = max(b["high"] for b in or_bars)
                self._or_low  = min(b["low"]  for b in or_bars)
                self._or_locked = True
                logger.info(
                    f"[FUTURES-ORB] OR locked: {self.symbol} "
                    f"H={self._or_high:.2f} L={self._or_low:.2f}"
                )

        if not self._or_locked:
            return None  # still building the OR

        or_high = self._or_high
        or_low  = self._or_low
        atr     = self._compute_atr(bars)

        # Gate 4 — BOS / ORB breakout
        from app.signals.opening_range import (
            detect_breakout_after_or,
            detect_fvg_after_break,
            detect_momentum_continuation,
        )
        direction, bk_idx = detect_breakout_after_or(bars, or_high, or_low)
        if direction is None:
            return None

        # Duplicate guard — only one signal per direction per session
        if direction in self._fired_today:
            return None

        # Gate 5/6 — FVG entry or momentum fallback
        entry, entry_type = self._resolve_entry(
            bars, bk_idx, direction, or_high, or_low,
            detect_fvg_after_break, detect_momentum_continuation
        )
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

    def _compute_atr(self, bars: list[dict], window: int = 10) -> float:
        """Simple intraday ATR: mean of (high-low) over last `window` bars."""
        if not bars:
            return 1.0
        recent = bars[-window:] if len(bars) >= window else bars
        ranges = [b["high"] - b["low"] for b in recent if b["high"] > b["low"]]
        return sum(ranges) / len(ranges) if ranges else 1.0

    def _resolve_entry(
        self, bars, bk_idx, direction, or_high, or_low,
        detect_fvg_fn, detect_momentum_fn
    ) -> Tuple[Optional[float], str]:
        """Resolve FVG entry first, then momentum fallback."""
        fvg_low, fvg_high = detect_fvg_fn(bars, bk_idx, direction)
        if fvg_low is not None:
            entry = fvg_high if direction == "bull" else fvg_low
            return entry, "FVG"

        mom = detect_momentum_fn(bars, bk_idx, direction, ticker=self.symbol)
        if mom is not None:
            entry = mom.get("entry_high") if direction == "bull" else mom.get("entry_low")
            if entry is not None:
                return entry, "MOMENTUM_CONTINUATION"

        logger.debug(
            f"[FUTURES-ORB] {self.symbol} {direction}: BOS confirmed but "
            f"no FVG / momentum entry — waiting"
        )
        return None, ""

    @staticmethod
    def _compute_levels(
        entry: float, direction: str, atr: float
    ) -> Tuple[float, float, float]:
        """Compute stop, T1 (2R), T2 (3.5R) from entry and ATR."""
        risk = atr  # 1R = 1 ATR
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
        """Simple confidence score (0–100).  No dependency on signal_scorecard."""
        score = 50  # base

        # Entry type bonus
        if entry_type == "FVG":
            score += 15
        elif entry_type == "MOMENTUM_CONTINUATION":
            score += 8

        # Clean breakout candle (close well beyond OR)
        if bars and bk_idx < len(bars):
            bk_bar = bars[bk_idx]
            or_range = or_high - or_low
            if or_range > 0:
                penetration = abs(bk_bar["close"] - (or_high if direction == "bull" else or_low))
                if penetration > or_range * 0.3:
                    score += 10

        # OR range quality (not too wide, not too narrow)
        or_range = or_high - or_low
        if 5 <= or_range <= 50:   # reasonable MNQ point range
            score += 10
        elif or_range > 50:
            score -= 5  # very wide OR = lower quality setup

        # Volume on breakout candle (if available)
        if bars and bk_idx < len(bars):
            bk_vol = bars[bk_idx].get("volume", 0)
            avg_vol = sum(b.get("volume", 0) for b in bars[:bk_idx]) / max(bk_idx, 1)
            if avg_vol > 0 and bk_vol > avg_vol * 1.5:
                score += 10

        return min(score, 100)

    def _build_signal(self, direction, entry, stop, t1, t2,
                      confidence, entry_type, or_high, or_low, atr) -> dict:
        point_value  = _POINT_VALUE.get(self.symbol, 2.0)
        risk_pts     = abs(entry - stop)
        dollar_risk  = round(risk_pts * point_value * _CONTRACTS, 2)
        return {
            # ── armed_signals_persist columns ─────────────────────────────
            "ticker":        self.symbol,
            "direction":     direction.upper(),
            "entry_price":   round(entry, 4),
            "stop_price":    round(stop, 4),
            "t1":            t1,
            "t2":            t2,
            "confidence":    round(confidence / 100, 4),  # stored as 0.0–1.0
            "grade":         "A" if confidence >= 75 else ("B" if confidence >= 60 else "C"),
            "signal_type":   "FUTURES_ORB",
            # ── validation_data JSONB payload ──────────────────────────────
            "validation_data": {
                "or_high":       or_high,
                "or_low":        or_low,
                "or_range":      round(or_high - or_low, 4),
                "entry_type":    entry_type,
                "atr":           round(atr, 4),
                "risk_pts":      round(risk_pts, 4),
                "rr_t1":         _RR_T1,
                "rr_t2":         _RR_T2,
                "contracts":     _CONTRACTS,
                "point_value":   point_value,
                "dollar_risk":   dollar_risk,
                "tradier_live":  os.getenv("TRADIER_FUTURES_ENABLED", "false"),
            },
        }

    @staticmethod
    def _persist(signal: dict) -> None:
        """
        Write to:
          1. armed_signals_persist  (existing table, signal_type='FUTURES_ORB')
          2. futures_signals        (new table from migration 006)
        Options/equity queries filter on signal_type != 'FUTURES_ORB' or
        simply ignore rows where the ticker is a futures symbol — no conflict.
        """
        try:
            from app.core.armed_signal_store import _persist_armed_signal
            # armed_signal_store expects position_id — futures don't open a
            # position_manager position yet (no auto-execution until Tradier live)
            signal_with_pos = {**signal, "position_id": None}
            _persist_armed_signal(signal["ticker"], signal_with_pos)
            logger.info(f"[FUTURES-ORB] Persisted to armed_signals_persist: {signal['ticker']} {signal['direction']}")
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] armed_signals_persist write failed (non-fatal): {e}")

        # Write to dedicated futures_signals table
        try:
            from app.data.db_connection import get_connection
            import json
            conn = get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO futures_signals
                            (symbol, direction, entry_price, stop_price, t1, t2,
                             confidence, grade, signal_type, entry_type, validation_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        )
                    )
                conn.commit()
                logger.info(f"[FUTURES-ORB] Persisted to futures_signals table")
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] futures_signals write failed (non-fatal): {e}")

    @staticmethod
    def _discord_alert(signal: dict) -> None:
        """Fire Discord alert using existing send_simple_message.
        Uses orange colour prefix to visually distinguish from equity signals."""
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
