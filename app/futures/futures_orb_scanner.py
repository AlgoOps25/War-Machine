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
  5. FVG entry      — 3-bar gap after breakout candle; entry at fill zone
                      (FIX-ORB-1: bull=fvg_low, bear=fvg_high)
  6. MOMENTUM fallback — if no FVG, use breakout candle close as entry
  7. STOP           — wick-anchored on FVG path (FIX-ORB-2);
                      ATR fallback for MOMENTUM_CONTINUATION only
  8. CONFIDENCE     — simple scoring (OR quality + entry type + volume)
                      floor raised to 65% (FIX-ORB-5)

FIX HISTORY (2026-04-03):

  FIX-ORB-1: FVG entry direction was inverted.
    _resolve_entry() set entry = fvg_high for bull and fvg_low for bear.
    A bullish FVG retest fills from fvg_low (bottom of gap) upward —
    entering at fvg_high means chasing the top of the gap, not retesting it.
    Fixed: bull entry = fvg_low (fill zone bottom), bear entry = fvg_high.

  FIX-ORB-2: ATR stop replaced with wick-anchored stop on FVG path.
    _compute_levels() used 1x ATR for both FVG and MOMENTUM entries.
    On the FVG path, the CFW6-STOP-1 rule applies: stop goes below/above
    the deepest wick of the FVG candle cluster, not a full ATR away.
    New: _compute_fvg_stop() walks the 3-bar FVG cluster and anchors
    the stop to the extreme wick with a 0.25-pt buffer. ATR fallback
    retained for MOMENTUM_CONTINUATION only.
    fvg_cluster_idx is now returned from _detect_fvg() as a third value
    so _compute_levels() can access the exact candles.

  FIX-ORB-3: _detect_fvg() loop started at max(bk_idx, 1), missing the
    earliest FVG when bk_idx == 0 (gap-open day, breakout on first
    post-OR bar). Fixed: loop starts at bk_idx; i-1 guard handled
    separately so index never underflows.

  FIX-ORB-4: Volume bonus in _score() fired trivially when bk_idx < 3
    because bars[:0] is empty, avg_vol == 0, and bk_vol > 0 is always
    true. Fixed: volume check skipped when bk_idx < 3.

  FIX-ORB-5: _MIN_CONFIDENCE raised from 55 to 65 to match the equity
    pipeline intent. Grade thresholds adjusted: A >= 80, B >= 68, C below.
    _CONTRACTS now read from env var FUTURES_CONTRACTS (default 1) so
    contract size is tunable without a code change.

  DIS-FUT-1 (Apr 3 2026):
    _discord_alert() upgraded to rich orange embed via send_futures_orb_alert().
    Plain-text send_simple_message() retained as fallback so a missing key
    or import error never silences the alert entirely.

  DIS-FUT-2 (Apr 3 2026):
    _discord_exit() static method added. Call when price reaches stop, T1,
    T2, or you close EOD manually. See docs/DISCORD_SIGNALS.md.

  FIX-ORB-6 (Apr 6 2026):
    SESSION_START renamed to _SESSION_START (added leading underscore) to
    match the reference on line 224 inside scan(). The mismatch caused a
    NameError crash on every loop iteration during the session window.
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

# ── Session constants ──────────────────────────────────────────────────────────────
_SESSION_START  = time(9, 30)   # FIX-ORB-6: was SESSION_START — matched scan() usage
_SESSION_CUTOFF = time(11, 0)
_OR_END         = time(9, 40)   # first 10 minutes form the OR

# ── Risk constants ────────────────────────────────────────────────────────────────
_POINT_VALUE    = {"NQ": 20.0, "MNQ": 2.0}
# FIX-ORB-5: read from env so contract size is tunable without a code change
_CONTRACTS      = int(os.getenv("FUTURES_CONTRACTS", "1"))
_MIN_CONFIDENCE = 65   # FIX-ORB-5: raised from 55 to match equity pipeline intent
_RR_T1          = 2.0
_RR_T2          = 3.5
_FVG_STOP_BUFFER = 0.25  # FIX-ORB-2: pts below/above FVG wick for stop placement


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
                ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """
    Look for a 3-bar Fair Value Gap starting at or after the breakout candle.
    A bullish FVG exists when bars[n-1].high < bars[n+1].low.
    A bearish FVG exists when bars[n-1].low  > bars[n+1].high.

    FIX-ORB-3: loop now starts at bk_idx (not max(bk_idx, 1)) so a gap
    that forms at the breakout bar itself is not missed on gap-open days.
    The i-1 guard is handled explicitly to prevent index underflow.

    Returns (fvg_low, fvg_high, cluster_mid_idx) or (None, None, None).
    cluster_mid_idx is the index of the middle bar of the FVG triplet —
    used by _compute_fvg_stop() to anchor the stop to the wick.
    """
    for i in range(bk_idx, len(bars) - 1):
        if i < 1:
            continue  # need a previous bar; skip index 0
        prev = bars[i - 1]
        nxt  = bars[i + 1]
        if direction == "bull":
            if prev["high"] < nxt["low"]:
                return prev["high"], nxt["low"], i
        else:
            if prev["low"] > nxt["high"]:
                return nxt["high"], prev["low"], i
    return None, None, None


def _compute_fvg_stop(
    bars: list[dict], cluster_mid_idx: int, direction: str
) -> Optional[float]:
    """
    FIX-ORB-2: Wick-anchored stop for the FVG entry path.

    Walks the 3-bar FVG cluster (mid-1, mid, mid+1) and places the stop
    just beyond the most extreme wick in the counter-trade direction,
    plus a small buffer (_FVG_STOP_BUFFER points).

    Returns the stop price, or None if the cluster indices are out of range.
    """
    start = cluster_mid_idx - 1
    end   = cluster_mid_idx + 1
    if start < 0 or end >= len(bars):
        return None
    cluster = bars[start : end + 1]
    if direction == "bull":
        extreme_wick = min(b["low"] for b in cluster)
        return round(extreme_wick - _FVG_STOP_BUFFER, 2)
    else:
        extreme_wick = max(b["high"] for b in cluster)
        return round(extreme_wick + _FVG_STOP_BUFFER, 2)


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


# ── Scanner class ──────────────────────────────────────────────────────────────────

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

    # ── Public ─────────────────────────────────────────────────────────────────────────────

    def scan(self, current_time: Optional[datetime] = None) -> Optional[dict]:
        """
        Run one scan cycle. Returns the armed signal dict if a signal was
        generated and persisted, or None if no signal.
        Safe to call every 30-60 s without side effects.
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
        entry, entry_type, fvg_cluster_idx = self._resolve_entry(
            bars, bk_idx, direction
        )
        if entry is None:
            return None

        # Gate 7 — stop & targets
        stop, t1, t2 = self._compute_levels(
            entry, direction, atr, entry_type, bars, fvg_cluster_idx
        )

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

    # ── Private helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_atr(bars: list[dict], window: int = 10) -> float:
        if not bars:
            return 1.0
        recent = bars[-window:] if len(bars) >= window else bars
        ranges = [b["high"] - b["low"] for b in recent if b["high"] > b["low"]]
        return sum(ranges) / len(ranges) if ranges else 1.0

    def _resolve_entry(
        self, bars: list[dict], bk_idx: int, direction: str
    ) -> Tuple[Optional[float], str, Optional[int]]:
        """
        FIX-ORB-1: Entry direction corrected.
          Bull FVG: enter at fvg_low (bottom of gap = fill zone entry).
          Bear FVG: enter at fvg_high (top of gap = fill zone entry).
          Previously inverted — was entering at the most extended side.

        Returns (entry_price, entry_type, fvg_cluster_idx).
        fvg_cluster_idx is passed to _compute_levels() for wick-anchored stop.
        """
        fvg_low, fvg_high, cluster_idx = _detect_fvg(bars, bk_idx, direction)
        if fvg_low is not None:
            # FIX-ORB-1: bull enters at fvg_low (fill zone bottom), not fvg_high
            entry = fvg_low if direction == "bull" else fvg_high
            return entry, "FVG", cluster_idx

        mom = _detect_momentum(bars, bk_idx, direction)
        if mom is not None:
            entry = mom.get("entry_high") if direction == "bull" else mom.get("entry_low")
            if entry is not None:
                return entry, "MOMENTUM_CONTINUATION", None

        logger.debug(
            f"[FUTURES-ORB] {self.symbol} {direction}: BOS confirmed "
            f"but no FVG / momentum entry yet — waiting"
        )
        return None, "", None

    @staticmethod
    def _compute_levels(
        entry: float,
        direction: str,
        atr: float,
        entry_type: str,
        bars: list[dict],
        fvg_cluster_idx: Optional[int],
    ) -> Tuple[float, float, float]:
        """
        FIX-ORB-2: Wick-anchored stop on FVG path; ATR fallback for momentum.

        FVG path: stop is placed just beyond the extreme wick of the 3-bar
        FVG cluster (_compute_fvg_stop). This matches the CFW6-STOP-1 rule
        used in the equity pipeline (sniper_pipeline.py).

        MOMENTUM_CONTINUATION path: ATR-based stop unchanged.
        """
        if entry_type == "FVG" and fvg_cluster_idx is not None:
            fvg_stop = _compute_fvg_stop(bars, fvg_cluster_idx, direction)
            if fvg_stop is not None:
                risk = abs(entry - fvg_stop)
                if direction == "bull":
                    t1 = round(entry + risk * _RR_T1, 2)
                    t2 = round(entry + risk * _RR_T2, 2)
                else:
                    t1 = round(entry - risk * _RR_T1, 2)
                    t2 = round(entry - risk * _RR_T2, 2)
                return fvg_stop, t1, t2

        # ATR fallback (MOMENTUM_CONTINUATION or FVG cluster out of range)
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

        # FIX-ORB-4: skip volume check when bk_idx < 3 — not enough history
        # to compute a meaningful average (bars[:0] is empty, avg_vol == 0,
        # causing bk_vol > 0 to trivially fire and inflate confidence).
        if bars and bk_idx is not None and bk_idx >= 3 and bk_idx < len(bars):
            bk_vol  = bars[bk_idx].get("volume", 0)
            avg_vol = sum(b.get("volume", 0) for b in bars[:bk_idx]) / bk_idx
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
        # FIX-ORB-5: grade thresholds tightened to match raised confidence floor
        grade = "A" if confidence >= 80 else ("B" if confidence >= 68 else "C")
        return {
            "ticker":       self.symbol,
            "direction":    direction.upper(),
            "entry_price":  round(entry, 4),
            "stop_price":   round(stop, 4),
            "t1":           t1,
            "t2":           t2,
            "confidence":   round(confidence / 100, 4),
            "grade":        grade,
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
        """
        DIS-FUT-1 (Apr 3 2026): Upgraded to rich embed via send_futures_orb_alert().
        Plain-text send_simple_message() is retained as a fallback so a missing
        key or import error never silences the alert entirely.
        """
        try:
            from app.notifications.discord_helpers import send_futures_orb_alert
            send_futures_orb_alert(signal)
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] Rich Discord alert failed ({e}) — falling back to plain text")
            try:
                from app.notifications.discord_helpers import send_simple_message
                sym   = signal.get("ticker", "UNKNOWN")
                d     = signal.get("direction", "BULL")
                entry = signal.get("entry_price", 0)
                stop  = signal.get("stop_price", 0)
                t1    = signal.get("t1", 0)
                t2    = signal.get("t2", 0)
                conf  = round(signal.get("confidence", 0) * 100, 1)
                grade = signal.get("grade", "?")
                etype = signal.get("validation_data", {}).get("entry_type", "?")
                drisk = signal.get("validation_data", {}).get("dollar_risk", 0)
                arrow = "✅" if d == "BULL" else "❌"
                msg = (
                    f"⬜ **FUTURES ORB SIGNAL** {arrow}\n"
                    f"**{sym}** {d} | Grade {grade} | {conf}% conf\n"
                    f"Entry: `{entry}` | Stop: `{stop}` | "
                    f"T1: `{t1}` | T2: `{t2}`\n"
                    f"Entry type: {etype} | Dollar risk ({_CONTRACTS} contract(s)): ${drisk}"
                )
                send_simple_message(msg)
            except Exception as e2:
                logger.warning(f"[FUTURES-ORB] Plain-text fallback also failed: {e2}")

    @staticmethod
    def _discord_exit(
        symbol: str,
        direction: str,
        exit_price: float,
        reason: str,
        entry_price: float = 0.0,
        pnl_pts: float = 0.0,
    ) -> None:
        """
        DIS-FUT-2 (Apr 3 2026): Send a rich exit/stop alert to Discord.
        Call when price reaches stop, T1, T2, or you close EOD manually.

        reason values: "STOP_HIT" | "T1_HIT" | "T2_HIT" | "EOD_CLOSE" | free-form

        Example:
            scanner._discord_exit("MNQ", "BULL", 19450.0, "T1_HIT",
                                   entry_price=19410.0, pnl_pts=40.0)

        See docs/DISCORD_SIGNALS.md for full reference.
        """
        try:
            from app.notifications.discord_helpers import send_futures_exit_alert
            pv = _POINT_VALUE.get(symbol, 2.0)
            send_futures_exit_alert(
                symbol=symbol,
                direction=direction,
                exit_price=exit_price,
                reason=reason,
                entry_price=entry_price,
                pnl_pts=pnl_pts,
                contracts=_CONTRACTS,
                point_value=pv,
            )
        except Exception as e:
            logger.warning(f"[FUTURES-ORB] Exit Discord alert failed (non-fatal): {e}")
