"""
Annotation Resolver
===================
Converts a human-posted R:R annotation from #chart-annotations into a live
futures signal and submits it to the War Machine position pipeline.

Pipeline:
  1. Pull the last N 1-min candles from PostgreSQL (same table the scanner
     already writes to).
  2. Calculate ATR-based entry, stop, T1, and T2 using the supplied R:R.
  3. Validate:
       a. Minimum R:R gate (config.MIN_RISK_REWARD_RATIO, default 1.5)
       b. BOS confirmation (last close broke above/below recent swing)
       c. RTH guard (delegates to position_manager.can_open_position)
  4. Call position_manager.open_position() with signal_type="DISCORD_ANNOTATION".
  5. Send a Discord confirmation via discord_helpers.send_signal_alert.

This module is intentionally synchronous so it can be called from both:
  - asyncio.to_thread() inside the annotation listener
  - unit tests without an event loop

CANDLE TABLE SCHEMA EXPECTED:
    candles (symbol TEXT, timestamp TIMESTAMP, open REAL, high REAL,
             low REAL, close REAL, volume INTEGER)
"""

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from utils import config
from app.data.db_connection import get_conn, return_conn, dict_cursor, ph
from app.risk.position_manager import PositionManager

logger = logging.getLogger(__name__)

_ET              = ZoneInfo("America/New_York")
_MIN_RR          = getattr(config, "MIN_RISK_REWARD_RATIO", 1.5)
_CANDLE_LOOKBACK = getattr(config, "ANNOTATION_CANDLE_LOOKBACK", 20)
_ATR_PERIOD      = getattr(config, "ANNOTATION_ATR_PERIOD", 14)
_SYMBOL_MULT     = getattr(config, "FUTURES_POINT_MULT", 20.0)   # NQ = $20/pt

# Shared PositionManager — reuses the same instance as the scanner when
# imported from the same process; each thread gets its own if run standalone.
_pm: Optional[PositionManager] = None


def _get_pm() -> PositionManager:
    global _pm
    if _pm is None:
        _pm = PositionManager()
    return _pm


# ── Candle fetch ──────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, limit: int) -> list:
    """Return the most recent `limit` 1-min candles for `symbol` from PostgreSQL."""
    conn = None
    try:
        p      = ph()
        conn   = get_conn()
        cursor = dict_cursor(conn)
        cursor.execute(
            f"""
            SELECT timestamp, open, high, low, close, volume
            FROM   candles
            WHERE  symbol = {p}
            ORDER  BY timestamp DESC
            LIMIT  {p}
            """,
            (symbol, limit),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]  # index 0 = newest
    except Exception as exc:
        logger.error(f"[ANNOTATION] Candle fetch failed for {symbol}: {exc}")
        return []
    finally:
        if conn:
            return_conn(conn)


# ── Technical helpers ─────────────────────────────────────────────────────────

def _true_range(candle: dict, prev_close: float) -> float:
    h, l, pc = candle["high"], candle["low"], prev_close
    return max(h - l, abs(h - pc), abs(l - pc))


def _atr(candles: list, period: int) -> float:
    """Wilder ATR from the most recent `period` candles (index 0 = newest)."""
    if len(candles) < period + 1:
        # Fallback: simple H-L average
        return sum(c["high"] - c["low"] for c in candles[:period]) / max(len(candles), 1)
    tr_values = [
        _true_range(candles[i], candles[i + 1]["close"])
        for i in range(period)
    ]
    return sum(tr_values) / period


def _detect_bos(candles: list, direction: str) -> bool:
    """
    Simple BOS check:
      bull — latest close > highest high of candles[1:6]
      bear — latest close < lowest low  of candles[1:6]
    Candles are newest-first (index 0 = latest closed bar).
    """
    if len(candles) < 6:
        return False
    latest_close = candles[0]["close"]
    if direction == "bull":
        swing_high = max(c["high"] for c in candles[1:6])
        return latest_close > swing_high
    else:
        swing_low = min(c["low"] for c in candles[1:6])
        return latest_close < swing_low


def _infer_direction(candles: list) -> str:
    """Fallback: bullish if price is above the midpoint of the lookback range."""
    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    mid   = (max(highs) + min(lows)) / 2
    return "bull" if candles[0]["close"] > mid else "bear"


# ── Main resolver ─────────────────────────────────────────────────────────────

def resolve_annotation(
    rr_ratio:       float,
    direction_hint: Optional[str],
    symbol:         str,
    posted_at:      datetime,
) -> None:
    """
    Core resolver.  Synchronous — safe to call from any thread.

    Args:
        rr_ratio:       Annotated R:R from Discord (e.g. 3.31).
        direction_hint: "bull", "bear", or None (auto-detect).
        symbol:         Futures contract symbol (e.g. "NQM25").
        posted_at:      UTC datetime of the Discord message.
    """
    tag = f"[ANNOTATION {symbol} R:{rr_ratio}]"

    # ── 1. Gate: minimum R:R ──────────────────────────────────────────────────
    if rr_ratio < _MIN_RR:
        logger.info(f"{tag} Skipped — R:R {rr_ratio} < min {_MIN_RR}")
        return

    # ── 2. Fetch candles ──────────────────────────────────────────────────────
    candles = _fetch_candles(symbol, _CANDLE_LOOKBACK + 5)
    if len(candles) < 5:
        logger.warning(f"{tag} Skipped — insufficient candles ({len(candles)})")
        return

    # ── 3. Direction ──────────────────────────────────────────────────────────
    direction = direction_hint or _infer_direction(candles)

    # ── 4. BOS gate ───────────────────────────────────────────────────────────
    if not _detect_bos(candles, direction):
        logger.info(f"{tag} Skipped — BOS not confirmed (direction={direction})")
        return

    # ── 5. Build levels ───────────────────────────────────────────────────────
    atr          = _atr(candles, _ATR_PERIOD)
    entry        = candles[0]["close"]
    stop_dist    = atr                    # 1 ATR = 1R
    t1_dist      = atr * (rr_ratio / 2)  # scale-out at half target
    t2_dist      = atr * rr_ratio        # full R:R target

    if direction == "bull":
        stop = entry - stop_dist
        t1   = entry + t1_dist
        t2   = entry + t2_dist
    else:
        stop = entry + stop_dist
        t1   = entry - t1_dist
        t2   = entry - t2_dist

    # Dummy OR levels (not applicable for direct futures signals)
    or_low  = min(c["low"]  for c in candles[:5])
    or_high = max(c["high"] for c in candles[:5])

    logger.info(
        f"{tag} {direction.upper()} | entry={entry:.2f}  stop={stop:.2f}  "
        f"T1={t1:.2f}  T2={t2:.2f}  ATR={atr:.2f}"
    )

    # ── 6. Submit to position pipeline ───────────────────────────────────────
    pm = _get_pm()
    pos_id = pm.open_position(
        ticker        = symbol,
        direction     = direction,
        zone_low      = or_low,
        zone_high     = or_high,
        or_low        = or_low,
        or_high       = or_high,
        entry_price   = entry,
        stop_price    = stop,
        t1            = t1,
        t2            = t2,
        confidence    = 0.70,          # human-validated = treat as standard
        grade         = "A",
        signal_type   = "DISCORD_ANNOTATION",
    )

    if pos_id and pos_id > 0:
        logger.info(f"{tag} Position opened — ID {pos_id}")
        _notify(symbol, direction, entry, stop, t1, t2, rr_ratio, pos_id)
    else:
        logger.info(f"{tag} open_position rejected (risk gate or duplicate)")


# ── Discord notification ──────────────────────────────────────────────────────

def _notify(
    symbol: str, direction: str,
    entry: float, stop: float, t1: float, t2: float,
    rr: float, pos_id: int,
) -> None:
    """Best-effort Discord alert — mirrors the style of send_signal_alert."""
    try:
        from app.notifications.discord_helpers import send_discord_message
        arrow = "\U0001f7e2 LONG" if direction == "bull" else "\U0001f534 SHORT"
        msg = (
            f"**{arrow} {symbol}** (Annotation Signal | R:R {rr}:1)\n"
            f"Entry: `{entry:.2f}` | Stop: `{stop:.2f}`\n"
            f"T1: `{t1:.2f}` | T2: `{t2:.2f}`\n"
            f"Position ID: `{pos_id}`"
        )
        send_discord_message(msg)
    except Exception as exc:
        logger.warning(f"[ANNOTATION] Discord notify failed (non-fatal): {exc}")
